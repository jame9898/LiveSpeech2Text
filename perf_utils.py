# -*- coding: utf-8 -*-
"""
性能检测模块 — 本地处理阶段计时 + GPU 工作状态采样

包含：
- PerfMonitor:  阶段计时器（VAD/ASR/说话人/报告 各阶段耗时与占比）
- gpu_info:     采样 GPU 名称/利用率/显存/温度（nvidia-smi 子进程，零新依赖）
- format_elapsed: 秒数格式化（自动切换 时:分:秒 / 分:秒.x / x.xs）
"""

import shutil
import subprocess
import time

# nvidia-smi 所在路径（Windows 下通常在 System32；Linux 下在 PATH）
_SMI_CANDIDATES = [
    shutil.which("nvidia-smi"),
    r"C:\Windows\System32\nvidia-smi.exe",
    "/usr/bin/nvidia-smi",
]
_SMI = next((c for c in _SMI_CANDIDATES if c), None)


def gpu_info():
    """返回 GPU 工作状态文本，如 'NVIDIA GeForce RTX 4070 SUPER | 利用率 68% | 显存 4.2/12.0GB | 温度 62°C'。

    CPU 环境或无 nvidia-smi 时返回 None（调用方自行处理）。
    失败（驱动/权限等）返回 None，绝不让采样异常影响主流程。
    """
    if not _SMI:
        return None
    try:
        result = subprocess.run(
            [_SMI, "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return None
        parts = [p.strip() for p in result.stdout.strip().split(",")]
        if len(parts) < 5:
            return None
        name, util, mem_used, mem_total, temp = parts[:5]
        return (f"{name} | 利用率 {util}% | 显存 "
                f"{float(mem_used) / 1024:.1f}/{float(mem_total) / 1024:.1f}GB | 温度 {temp}°C")
    except Exception:
        return None


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
