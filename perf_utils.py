# -*- coding: utf-8 -*-
"""
性能检测模块 — 本地处理阶段计时 + GPU/CPU 工作状态实时采样

包含：
- PerfMonitor:  阶段计时器（VAD/ASR/说话人/报告 各阶段耗时与占比）
- PerfSampler:  后台线程实时采样 GPU/CPU 利用率与显存/内存（均值/峰值统计）
- gpu_info:     单次采样 GPU 名称/利用率/显存/温度（nvidia-smi 子进程，零新依赖）
- format_elapsed: 秒数格式化（自动切换 时:分:秒 / 分:秒.x / x.xs）
"""

import shutil
import subprocess
import sys
import threading
import time

# nvidia-smi 所在路径（Windows 下通常在 System32；Linux 下在 PATH）
_SMI_CANDIDATES = [
    shutil.which("nvidia-smi"),
    r"C:\Windows\System32\nvidia-smi.exe",
    "/usr/bin/nvidia-smi",
]
_SMI = next((c for c in _SMI_CANDIDATES if c), None)

# Windows 下抑制子进程控制台窗口（否则每秒采样都会闪一个 cmd 窗口）
_IS_WINDOWS = sys.platform == "win32"
_CREATE_NO_WINDOW = 0x08000000 if _IS_WINDOWS else 0

# pynvml（nvidia-ml-py，NVIDIA 官方库）可选加速：直读驱动，无子进程、无窗口
try:
    import pynvml as _pynvml_mod
    _HAS_PYNVML = True
except Exception:
    _pynvml_mod = None
    _HAS_PYNVML = False

_NVML_READY = None   # None=未探测 False=不可用 True=可用
_NVML_HANDLE = None


def _nvml_ensure():
    """惰性初始化 pynvml。成功返回 device handle；无 pynvml/无驱动时返回 None（调用方回退 nvidia-smi）。"""
    global _NVML_READY, _NVML_HANDLE
    if _NVML_READY is not None:
        return _NVML_HANDLE if _NVML_READY else None
    if not _HAS_PYNVML:
        _NVML_READY = False
        return None
    try:
        _pynvml_mod.nvmlInit()
        _NVML_HANDLE = _pynvml_mod.nvmlDeviceGetHandleByIndex(0)
        _NVML_READY = True
        return _NVML_HANDLE
    except Exception:
        _NVML_READY = False
        return None


def _run_smi(query_args):
    """nvidia-smi 子进程采样（窗口已隐藏）。失败返回 None。"""
    if not _SMI:
        return None
    try:
        result = subprocess.run(
            [_SMI, "--query-gpu=" + ",".join(query_args),
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
            creationflags=_CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except Exception:
        return None


def gpu_info():
    """返回 GPU 工作状态文本，如 'NVIDIA GeForce RTX 4070 SUPER | 利用率 68% | 显存 4.2/12.0GB | 温度 62°C'。

    优先 pynvml 直读驱动（无子进程、无控制台窗口），失败回退 nvidia-smi（窗口已隐藏）。
    CPU 环境或无 nvidia-smi 时返回 None（调用方自行处理）。
    失败（驱动/权限等）返回 None，绝不让采样异常影响主流程。
    """
    handle = _nvml_ensure()
    if handle is not None:
        try:
            util = _pynvml_mod.nvmlDeviceGetUtilizationRates(handle)
            mem = _pynvml_mod.nvmlDeviceGetMemoryInfo(handle)
            temp = _pynvml_mod.nvmlDeviceGetTemperature(handle, 0)  # NVML_TEMPERATURE_GPU = 0
            name = _pynvml_mod.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="replace")
            return (f"{name} | 利用率 {util.gpu}% | 显存 "
                    f"{mem.used / 1024 ** 3:.1f}/{mem.total / 1024 ** 3:.1f}GB | 温度 {temp}°C")
        except Exception:
            pass  # 回退 nvidia-smi
    out = _run_smi(["name", "utilization.gpu", "memory.used", "memory.total", "temperature.gpu"])
    if not out:
        return None
    parts = [p.strip() for p in out.split(",")]
    if len(parts) < 5:
        return None
    name, util, mem_used, mem_total, temp = parts[:5]
    return (f"{name} | 利用率 {util}% | 显存 "
            f"{float(mem_used) / 1024:.1f}/{float(mem_total) / 1024:.1f}GB | 温度 {temp}°C")


def _gpu_snapshot():
    """低开销 GPU 采样：返回 (利用率%, 显存占用GB, 显存总量GB, 温度°C) 或 None。

    优先 pynvml 直读驱动（无子进程、无控制台窗口，秒级采样零开销），失败回退 nvidia-smi。
    """
    handle = _nvml_ensure()
    if handle is not None:
        try:
            util = _pynvml_mod.nvmlDeviceGetUtilizationRates(handle)
            mem = _pynvml_mod.nvmlDeviceGetMemoryInfo(handle)
            temp = _pynvml_mod.nvmlDeviceGetTemperature(handle, 0)
            return (float(util.gpu), mem.used / 1024 ** 3, mem.total / 1024 ** 3, float(temp))
        except Exception:
            pass  # 回退 nvidia-smi
    out = _run_smi(["utilization.gpu", "memory.used", "memory.total", "temperature.gpu"])
    if not out:
        return None
    parts = [p.strip() for p in out.split(",")]
    if len(parts) < 4:
        return None
    return (float(parts[0]), float(parts[1]) / 1024, float(parts[2]) / 1024, float(parts[3]))


def _cpu_usage():
    """Windows 下用 GetSystemTimes 计算 CPU 总利用率%（两次调用间隔采样）。
    返回 0~100 浮点；非 Windows 或失败返回 None。
    """
    try:
        import ctypes
        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]
        idle = FILETIME(); kern = FILETIME(); user = FILETIME()
        ok = ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
        if not ok:
            return None
        def _to64(ft):
            return (ft.dwHighDateTime << 32) | ft.dwLowDateTime
        idle1 = _to64(idle); kern1 = _to64(kern); user1 = _to64(user)
        time.sleep(0.5)
        ok = ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
        if not ok:
            return None
        idle2 = _to64(idle); kern2 = _to64(kern); user2 = _to64(user)
        d_idle = idle2 - idle1
        d_kern = kern2 - kern1
        d_user = user2 - user1
        total = d_kern + d_user
        if total <= 0:
            return None
        return max(0.0, min(100.0, (total - d_idle) * 100.0 / total))
    except Exception:
        return None


def _mem_usage():
    """Windows 下用 GlobalMemoryStatusEx 返回 (已用GB, 总量GB) 或 None"""
    try:
        import ctypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
                ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64),
            ]
        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        if not ok:
            return None
        used = (m.ullTotalPhys - m.ullAvailPhys) / (1024 ** 3)
        total = m.ullTotalPhys / (1024 ** 3)
        return (used, total)
    except Exception:
        return None


class PerfSampler:
    """后台线程实时采样 GPU/CPU 利用率与显存/内存，统计均值与峰值。

    用法：
        ps = PerfSampler(interval=1.0)
        ps.start()          # 开始后台采样
        ...                 # 处理中任意时刻 ps.status_line() 取实时状态
        ps.stop()           # 停止（输出汇总 summary()）
    """

    def __init__(self, interval=1.0):
        self._interval = max(0.2, interval)
        self._lock = threading.Lock()
        self._thread = None
        self._running = False
        self._latest = None        # 最近一次 status_line 文本
        self._latest_snap = None   # 最近一次结构化快照 (gpu, cpu, mem)
        self._n = 0
        self._gpu_utils = []
        self._gpu_mems = []
        self._cpu_utils = []
        self._mem_used = []
        self._t0 = None
        self._total = 0.0

    def start(self):
        if self._running:
            return
        self._running = True
        self._t0 = time.perf_counter()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="perf-sampler")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=self._interval + 1.0)
            self._thread = None
        if self._t0 is not None:
            self._total = time.perf_counter() - self._t0

    def _loop(self):
        while self._running:
            gpu = _gpu_snapshot()
            cpu = _cpu_usage()
            mem = _mem_usage()
            with self._lock:
                self._n += 1
                if gpu:
                    self._gpu_utils.append(gpu[0])
                    self._gpu_mems.append(gpu[1])
                if cpu is not None:
                    self._cpu_utils.append(cpu)
                if mem:
                    self._mem_used.append(mem[0])
                self._latest = self._compose(gpu, cpu, mem)
                self._latest_snap = (gpu, cpu, mem)
            time.sleep(self._interval)

    def _compose(self, gpu, cpu, mem):
        parts = []
        if gpu:
            parts.append(f"GPU 利用率 {gpu[0]:.0f}% | 显存 {gpu[1]:.1f}/{gpu[2]:.1f}GB | 温度 {gpu[3]:.0f}°C")
        if cpu is not None:
            parts.append(f"CPU 利用率 {cpu:.0f}%")
        if mem:
            parts.append(f"内存 {mem[0]:.1f}/{mem[1]:.1f}GB")
        return " | ".join(parts) if parts else "（无法采样）"

    def status_line(self):
        """实时状态行（处理中每 1s 刷新显示用）"""
        with self._lock:
            return self._latest or self._compose(_gpu_snapshot(), _cpu_usage(), _mem_usage())

    def snapshot(self):
        """实时结构化快照：{gpu_util, gpu_mem, gpu_mem_total, gpu_temp, cpu_util, mem_used, mem_total}（无则 None）"""
        with self._lock:
            return self._latest_snap

    def summary(self, label="PERF"):
        """处理结束后的汇总文本：均值/峰值 + 采样时长"""
        with self._lock:
            n = self._n
            gpu_avg = sum(self._gpu_utils) / len(self._gpu_utils) if self._gpu_utils else None
            gpu_max = max(self._gpu_utils) if self._gpu_utils else None
            gpu_mem_max = max(self._gpu_mems) if self._gpu_mems else None
            cpu_avg = sum(self._cpu_utils) / len(self._cpu_utils) if self._cpu_utils else None
            cpu_max = max(self._cpu_utils) if self._cpu_utils else None
        total = self._total if self._total > 0 else (time.perf_counter() - self._t0) if self._t0 else 0
        lines = [f"[{label}] 采样 {n} 次 / {format_elapsed(total)}"]
        if gpu_avg is not None:
            lines.append(f"[{label}] GPU 利用率 平均 {gpu_avg:.0f}% / 峰值 {gpu_max:.0f}% | 显存峰值 {gpu_mem_max:.1f}GB")
        if cpu_avg is not None:
            lines.append(f"[{label}] CPU 利用率 平均 {cpu_avg:.0f}% / 峰值 {cpu_max:.0f}%")
        return "\n".join(lines) if lines else f"[{label}] 无采样数据"


def format_elapsed(seconds):
    """把秒数格式化为可读字符串：<1s 显示 0.xxs；<1min 显示 x.xs；<1h 显示 m:ss.x；否则 h:mm:ss"""
    seconds = max(0.0, seconds)
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}:{s:02d}.{int((seconds % 1) * 10)}"
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def _git(cmd):
    """执行 git 子进程（隐藏控制台窗口），失败返回 None。"""
    try:
        result = subprocess.run(
            ["git", *cmd],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=5,
            creationflags=_CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return None
        out = result.stdout.strip()
        return out or None
    except Exception:
        return None


def version_info():
    """版本信息：分支 + 最近 commit（hash+摘要+日期）+ GitHub/Gitee 远程仓库。

    用于性能报告里标注当前运行版本，方便对照远端最新提交做测试/回退。
    无 git 环境或非 git 目录时返回 None（调用方自行处理）。
    """
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"])
    commit = _git(["rev-parse", "--short", "HEAD"])
    summary = _git(["log", "-1", "--pretty=%s"])
    date = _git(["log", "-1", "--pretty=%ad", "--date=short"])
    remotes = []
    for name in ("github", "gitee", "origin"):
        url = _git(["remote", "get-url", name])
        if url:
            remotes.append(f"{name} {url}")
    if not branch and not commit:
        return None
    parts = []
    ident = f"{branch or '?'} @ {commit or '?'}"
    if summary:
        ident += f"（{summary[:40]}）"
    if date:
        ident += f" [{date}]"
    parts.append(f"版本: {ident}")
    if remotes:
        parts.append("远端: " + " | ".join(remotes))
    return "\n".join(parts)


class PerfMonitor:
    """阶段计时器：记录命名阶段耗时，支持多阶段并行计时与跨阶段累加。

    用法：
        pm = PerfMonitor(log_cb)
        pm.start("VAD")
        ...
        pm.stop("VAD")
        print(pm.summary())  # 各阶段耗时 + 总耗时 + 占比
        print(pm.gpu_line()) # 采样 GPU 状态
    """

    def __init__(self, log_cb=None, label="PERF"):
        self._log = log_cb if log_cb is not None else lambda s: print(s, flush=True)
        self._label = label
        self._t0 = time.perf_counter()
        self._times = {}          # 阶段名 -> 累计秒
        self._active = {}         # 阶段名 -> 开始时间戳（并行计时，允许多个 active）

    def start(self, name):
        """开始计时阶段（同名再次 start 会重置该阶段起点，不覆盖已累计时长）"""
        self._active[name] = time.perf_counter()

    def stop(self, name):
        """停止计时阶段，累计进 _times"""
        t = self._active.pop(name, None)
        if t is None:
            return
        self._times[name] = self._times.get(name, 0.0) + (time.perf_counter() - t)

    def elapsed(self, name):
        """取某阶段累计秒数（尚未 stop 的返回 0）"""
        return self._times.get(name, 0.0)

    def total(self):
        """自创建以来的总耗时（秒）"""
        return time.perf_counter() - self._t0

    def gpu_line(self):
        """GPU 工作状态行（无 GPU 时返回 None）"""
        info = gpu_info()
        if not info:
            return None
        return f"[{self._label}] GPU: {info}"

    def summary(self, extra=None):
        """返回性能小结多行文本：总耗时 + 各阶段耗时与占比（按耗时降序）。

        extra: 可选 dict，额外展示的指标（如 {'实时率': '2.3x', '平均': '1.2s/段'}）。
        """
        total = self.total()
        lines = [f"[{self._label}] 总耗时: {format_elapsed(total)}"]
        if extra:
            lines.append(f"[{self._label}] " + " | ".join(f"{k}: {v}" for k, v in extra.items()))
        stages = sorted(self._times.items(), key=lambda kv: kv[1], reverse=True)
        if stages:
            lines.append(f"[{self._label}] 阶段耗时:")
            for name, sec in stages:
                pct = (sec / total * 100) if total > 0 else 0.0
                lines.append(f"[{self._label}]   {name:12s} {format_elapsed(sec):>10s}  ({pct:.0f}%)")
        gpu = self.gpu_line()
        if gpu:
            lines.append(gpu)
        return "\n".join(lines)
