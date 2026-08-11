# -*- coding: utf-8 -*-
"""
VAD 处理器：自适应静音断句 + 音乐/噪声检测
从 RealtimeASRServer 中提取，独立为 VADProcessor 类

支持三种 VAD 引擎：
  1. energy（能量阈值法）：RMS 能量阈值，无需额外依赖，速度快但精度一般
  2. silero（Silero VAD）：基于 STFT 频谱的神经网络 VAD，精度高、多语言鲁棒
  3. fsmn（FSMN VAD）：达摩院 FunASR 框架的 VAD，中文优化、语义连贯性好

VAD 引擎选择通过配置项 model_settings.vad_engine 控制：
  - energy：能量阈值法，实时/本地模式均可用
  - silero：Silero 神经网络 VAD，精度高；实时模式用 SileroStreamingVAD（流式状态），
    本地/批处理用 silero_vad_segment（整段切分）
  - fsmn：FunASR FSMN VAD（中文优化），仅批处理切分可用；实时模式回退 energy
  （server.py 实时模式按 vad_engine 选择 VADProcessor / SileroStreamingVAD）
"""

import numpy as np

# ============================================================
# Silero VAD（神经网络语音活动检测）
# ============================================================

_SILERO_MODEL = None
_SILERO_UTILS = None
_SILERO_LOAD_LOCK = __import__('threading').Lock()


def load_silero_vad(models_dir=None):
    """加载 Silero VAD 模型（带本地缓存）。
    返回 (model, utils)，utils[0] = get_speech_timestamps。

    修复1：torch.hub.load 在 Windows 中文路径下会因混合分隔符（/ 和 \\）
    导致 PyTorch C++ 层 fopen 失败。改为先用 torch.hub 下载代码仓库，
    再手动用 os.path.normpath 规范化路径后加载 JIT 模型。

    修复2：GitHub zipball 中的 silero_vad.jit 是 Git LFS 指针（约 130 字节），
    解压后无法直接加载；且 torch.hub 解压后的目录名可能不固定。
    本函数在 jit 文件缺失或大小异常（LFS 指针）时，直接从 GitHub raw
    下载真实模型文件（2.3MB），并兼容目录名差异。
    """
    global _SILERO_MODEL, _SILERO_UTILS
    with _SILERO_LOAD_LOCK:
        if _SILERO_MODEL is not None:
            return _SILERO_MODEL, _SILERO_UTILS
        import os
        import torch
        from pathlib import Path

        if models_dir is None:
            models_dir = str(Path(__file__).parent / "models" / "silero-vad")
        os.makedirs(models_dir, exist_ok=True)
        torch.hub.set_dir(models_dir)

        # 本地缓存目录（torch.hub 下载后解压到此）
        repo_local_dir = os.path.join(models_dir, "snakers4_silero-vad_master")
        jit_model_path = os.path.join(repo_local_dir, "src", "silero_vad", "data", "silero_vad.jit")

        # 兼容目录名差异：GitHub zipball 解压后可能是 snakers4-silero-vad-master 等
        if not os.path.isfile(jit_model_path):
            repo_local_dir = _resolve_silero_repo_dir(models_dir, repo_local_dir)
            jit_model_path = os.path.join(repo_local_dir, "src", "silero_vad", "data", "silero_vad.jit")

        # 如果本地缓存不存在，先用 torch.hub.load 下载（允许它失败，只关心下载）
        if not os.path.isfile(jit_model_path):
            try:
                torch.hub.load(
                    repo_or_dir='snakers4/silero-vad',
                    model='silero_vad',
                    trust_repo=True,
                    onnx=False,
                )
            except Exception as e:
                print(f"[VAD] torch.hub 下载 Silero 仓库失败（尝试手动补全）: {e}", flush=True)

        # 目录名再次解析（torch.hub 解压后可能用不同命名）
        if not os.path.isfile(jit_model_path):
            repo_local_dir = _resolve_silero_repo_dir(models_dir, repo_local_dir)
            jit_model_path = os.path.join(repo_local_dir, "src", "silero_vad", "data", "silero_vad.jit")

        # zipball 中的 silero_vad.jit 是 Git LFS 指针（~130B），须下载真实文件（~2.3MB）
        if os.path.isfile(jit_model_path) and os.path.getsize(jit_model_path) < 1024:
            print("[VAD] 检测到 LFS 指针文件，下载真实 Silero VAD 模型...", flush=True)
            os.remove(jit_model_path)
        if not os.path.isfile(jit_model_path):
            try:
                _download_silero_jit(jit_model_path)
            except Exception as e:
                print(f"[VAD] 下载 Silero VAD 模型失败: {e}", flush=True)

        # 验证模型文件存在
        if not os.path.isfile(jit_model_path):
            raise FileNotFoundError(
                f"Silero VAD 模型文件未找到: {jit_model_path}\n"
                f"请检查网络连接，或手动从 https://github.com/snakers4/silero-vad 下载"
            )

        # 手动加载 JIT 模型
        # Windows 中文路径下，PyTorch C++ 层 fopen 无法处理 Unicode 路径
        # （如 "在线实时语音识别"），用 Python 打开文件对象再传给 torch.jit.load
        with open(jit_model_path, 'rb') as f:
            model = torch.jit.load(f, map_location='cpu')
        model.eval()

        # 手动导入 utils（不依赖 torch.hub 的路径处理）
        import sys
        src_dir = os.path.normpath(os.path.join(repo_local_dir, "src"))
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)
        from silero_vad.utils_vad import (
            get_speech_timestamps,
            save_audio,
            read_audio,
            VADIterator,
            collect_chunks,
        )
        utils = (get_speech_timestamps, save_audio, read_audio,
                 VADIterator, collect_chunks)

        _SILERO_MODEL = model
        _SILERO_UTILS = utils
        return _SILERO_MODEL, _SILERO_UTILS


def _resolve_silero_repo_dir(models_dir, expected_dir):
    """在 models_dir 下查找含 hubconf.py 的 Silero 仓库目录（兼容解压命名差异）。"""
    import os
    from pathlib import Path
    expected = os.path.normpath(expected_dir)
    for child in Path(models_dir).iterdir():
        if not child.is_dir():
            continue
        if (child / "hubconf.py").is_file():
            found = str(child)
            if os.path.normpath(found) != expected:
                try:
                    os.rename(found, expected)
                    print(f"[VAD] Silero 目录已重命名: {found} -> {expected}", flush=True)
                    return expected
                except OSError:
                    return found
            return found
    return expected_dir


def _download_silero_jit(jit_model_path):
    """从 GitHub raw 下载真实 Silero VAD JIT 模型（zipball 中仅为 LFS 指针）。

    官方文件: https://raw.githubusercontent.com/snakers4/silero-vad/master/src/silero_vad/data/silero_vad.jit
    LFS 文件经 raw 链接会重定向到真实内容（约 2.3MB），非 LFS 指针。
    """
    import os
    import urllib.request
    from pathlib import Path
    jit_path = Path(jit_model_path)
    jit_path.parent.mkdir(parents=True, exist_ok=True)
    url = "https://raw.githubusercontent.com/snakers4/silero-vad/master/src/silero_vad/data/silero_vad.jit"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(jit_path, "wb") as f:
        f.write(resp.read())
    size = jit_path.stat().st_size
    if size < 1024:
        raise RuntimeError(f"下载的 Silero VAD 模型异常（{size} 字节）: {url}")
    print(f"[VAD] Silero VAD 模型下载完成: {jit_path} ({size} 字节)", flush=True)


def silero_vad_segment(audio, sr, vad_silence_threshold=0.8,
                       min_speech_duration=0.12, force_cut_sec=6.0,
                       speech_prob_threshold=0.5, window_size_samples=None):
    """用 Silero VAD 做批量语音切分。

    参数:
        audio: numpy array (mono float32, 16kHz)
        sr: 采样率（固定 16000）
        vad_silence_threshold: 静音断句时长（秒）→ silero min_silence_duration_ms
        min_speech_duration: 最小语音段时长（秒）→ silero min_speech_duration_ms
        force_cut_sec: 最大语音段时长（秒）→ silero max_speech_duration_s
        speech_prob_threshold: 语音概率阈值（0~1），默认 0.5
        window_size_samples: Silero 前向窗口（512=32ms 精度最高；1536=96ms 快约 3 倍）。
            None = 自动：GPU 用 512，CPU 用 1536（切分边界粒度 96ms，对 ASR 段落影响可忽略）

    返回: [(seg_audio, seg_time, seg_dur, vad_info), ...]
    """
    import torch

    model, utils = load_silero_vad()
    get_speech_timestamps = utils[0]

    # numpy → torch tensor
    if isinstance(audio, np.ndarray):
        audio_t = torch.from_numpy(audio).float()
    else:
        audio_t = torch.as_tensor(audio, dtype=torch.float32)

    # Silero VAD 参数映射
    min_silence_ms = int(vad_silence_threshold * 1000)
    min_speech_ms = int(min_speech_duration * 1000)

    # CPU 上每 512 样本一次前向开销大（10 分钟音频约 2 万次），
    # 用 1536 窗口（官方支持 512/1024/1536 三档）前向次数降为 1/3
    if window_size_samples is None:
        window_size_samples = 512 if torch.cuda.is_available() else 1536

    timestamps = get_speech_timestamps(
        audio_t,
        model,
        threshold=speech_prob_threshold,
        min_speech_duration_ms=min_speech_ms,
        max_speech_duration_s=force_cut_sec,  # 新版 API：单位为秒
        min_silence_duration_ms=min_silence_ms,
        # 语音两端填充避免句首/句尾丢失，但需钳制在 min_silence 一半以内：
        # 相邻段间隔至少为 min_silence，pad 过大（如 min_silence<0.4s 时固定 200ms）
        # 会使相邻段区间重叠，导致下游 ASR 重复识别同一段音频
        speech_pad_ms=min(200, min_silence_ms // 2),
        sampling_rate=sr,
        return_seconds=False,
        visualize_probs=False,
        window_size_samples=window_size_samples,
    )

    segments = []
    for ts in timestamps:
        start = ts['start']
        end = ts['end']
        seg_audio = audio[start:end]
        seg_dur = len(seg_audio) / sr
        # seg_time 是该段在原始音频中的起始时间
        seg_time = start / sr
        # 超长段二次切分兜底：若 max_speech_duration_s 参数被旧版 silero 忽略，
        # 导致返回超长段，按 force_cut_sec 强制切分，避免下游 ASR OOM/截断
        if seg_dur > force_cut_sec:
            _chunk_samples = int(force_cut_sec * sr)
            # 不做 overlap：下游逐 chunk ASR 后直接拼接文本，无去重逻辑，
            # 重叠会导致切分边界处文本重复；改为从边界精确开始切分
            _step = _chunk_samples
            _offset = 0
            _forced_count = 0
            while _offset < len(seg_audio):
                _chunk = seg_audio[_offset:_offset + _chunk_samples]
                _chunk_dur = len(_chunk) / sr
                _chunk_time = seg_time + _offset / sr
                vad_info = {
                    'silence': vad_silence_threshold,
                    'adaptive_coeff': 1.0,
                    'forced': True,
                    'overlap': 0,
                    'chunk_dur': _chunk_dur,
                    'engine': 'silero',
                    'forced_split': True,
                    'forced_idx': _forced_count,
                }
                segments.append((_chunk, _chunk_time, _chunk_dur, vad_info))
                _offset += _step
                _forced_count += 1
        else:
            vad_info = {
                'silence': vad_silence_threshold,
                'adaptive_coeff': 1.0,
                'forced': False,
                'overlap': 0.2,  # speech_pad
                'chunk_dur': seg_dur,
                'engine': 'silero',
            }
            segments.append((seg_audio, seg_time, seg_dur, vad_info))

    return segments


class SileroStreamingVAD:
    """实时流式 Silero VAD（供 server.py 实时模式使用）。

    与 VADProcessor.cut(audio_data, sr) 保持相同接口：
      - 内部维护 Silero VADIterator（带状态），只对"新到的音频"做推理，
        避免每次对整段缓冲全量重算，CPU 上开销极小；
      - 段结束（句尾静音 >= min_silence）时返回完整语音段 + 剩余缓冲，
        语义与能量 VAD 一致，并带尾音保护（避免 ASR 漏掉句尾字词）。
    """

    def __init__(self, vad_silence_threshold=0.5, vad_force_cut=True, vad_force_cut_sec=6.0,
                 min_speech_duration=0.25, max_buffer_seconds=30, speech_prob_threshold=0.5,
                 models_dir=None):
        import torch
        import copy
        model, utils = load_silero_vad(models_dir)
        # 流式 VADIterator 持有跨调用状态（_state），而批处理 get_speech_timestamps
        # 会内部 reset 模型状态；两者共享同一实例会互踩。这里深拷贝一份给流式专用。
        model = copy.deepcopy(model)
        _VADIterator = utils[3]
        min_silence_ms = max(100, int(vad_silence_threshold * 1000))
        speech_pad_ms = min(200, min_silence_ms // 2)
        self._vad = _VADIterator(
            model,
            threshold=speech_prob_threshold,
            sampling_rate=16000,
            min_silence_duration_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
        )
        self._window = 512  # silero @16k 每次处理 512 样本
        self.vad_silence_threshold = vad_silence_threshold
        self.vad_force_cut = vad_force_cut
        self.vad_force_cut_sec = vad_force_cut_sec
        self.min_speech_duration = min_speech_duration
        self.max_buffer_seconds = max_buffer_seconds
        # 内部状态
        self._total = 0        # 已喂给 VAD 的样本数（相对当前缓冲起点）
        self._seg_start = None  # 当前语音段起点（VAD 坐标）
        self.reset()

    def reset(self):
        """重置会话状态（start/clear 时调用）"""
        self._vad.reset_states()
        self._total = 0
        self._seg_start = None

    def _mk_info(self, chunk_dur, forced=False, skipped=False):
        return {
            'silence': self.vad_silence_threshold,
            'adaptive_coeff': 1.0,
            'forced': forced,
            'overlap': 0.1,
            'chunk_dur': chunk_dur,
            'engine': 'silero',
            'skipped': skipped,
        }

    def cut(self, audio_data, sr):
        """喂入当前缓冲，返回 (语音段, 剩余缓冲, vad_info)。

        - audio_data 为"从段开始到现在的完整缓冲"（server 不断追加，
          切段后替换为 remaining）；
        - 本方法只对 _total 之后的新音频做 VAD 推理。
        """
        import torch

        # 缓冲被裁剪（overflow 兜底）或长度异常导致无法对齐：丢弃当前累积重新开始
        if len(audio_data) < self._total:
            self.reset()

        new = audio_data[self._total:]
        n = len(new)
        i = 0
        while i + self._window <= n:
            chunk = new[i:i + self._window]
            self._total += self._window
            x = torch.from_numpy(np.ascontiguousarray(chunk, dtype=np.float32)).unsqueeze(0)
            ev = self._vad(x)
            if ev:
                if 'start' in ev:
                    self._seg_start = ev['start']
                if 'end' in ev:
                    end = ev['end']
                    # 尾音保护：段尾多保留一段静音，避免 ASR 漏掉句尾发音
                    tail_pad = min(int(0.2 * sr), int(self.vad_silence_threshold * 0.5 * sr))
                    cut_point = min(len(audio_data), end + tail_pad)
                    seg_audio = audio_data[:cut_point]
                    seg_dur = len(seg_audio) / sr
                    speech_dur = (end - (self._seg_start if self._seg_start is not None else 0)) / sr
                    self.reset()
                    if speech_dur < self.min_speech_duration:
                        # 过短语音（噪声/呼吸）跳过，推进缓冲
                        return None, audio_data[cut_point:], self._mk_info(0, skipped=True)
                    return seg_audio, audio_data[cut_point:], self._mk_info(seg_dur)
            i += self._window

        # 连续说话无静音时的强制切分（受 vad_force_cut 开关控制）
        if self.vad_force_cut and self._seg_start is not None:
            speech_dur = (self._total - self._seg_start) / sr
            if speech_dur > self.vad_force_cut_sec:
                cut_point = min(len(audio_data), self._total)
                seg_audio = audio_data[:cut_point]
                seg_dur = len(seg_audio) / sr
                self.reset()
                return seg_audio, audio_data[cut_point:], self._mk_info(seg_dur, forced=True)

        # 无语音检测但缓冲区已积压：可能是轻声说话/连续背景音（音乐、白噪等），
        # silero 全程未触发 start。与能量 VAD 的 desperate 兜底一致，强制切分
        # （受 vad_force_cut 开关控制），避免缓冲无限增长直到 server 端 30s 溢出裁剪。
        if self.vad_force_cut and self._seg_start is None:
            buffer_dur = len(audio_data) / sr
            if buffer_dur > self.vad_force_cut_sec * 2.0:
                cut_point = min(len(audio_data), int(self.vad_force_cut_sec * sr))
                seg_audio = audio_data[:cut_point]
                seg_dur = len(seg_audio) / sr
                self.reset()
                return seg_audio, audio_data[cut_point:], self._mk_info(seg_dur, forced=True)

        return None, None, self._mk_info(0)


def batch_vad(audio, sr, vad):
    """模拟流式 VAD：逐块喂入音频，收集切出的语音段。
    返回 [(seg_audio, seg_time, seg_dur, vad_info), ...]
    """
    chunk_size = int(sr * 0.5)
    buf = np.array([], dtype=np.float32)
    segments = []
    cursor = 0.0
    min_flush_samples = int(sr * 0.3)

    for i in range(0, len(audio), chunk_size):
        chunk = audio[i:i + chunk_size]
        buf = np.concatenate([buf, chunk]) if len(buf) > 0 else chunk.copy()

        while True:
            seg, remaining, vad_info = vad.cut(buf, sr)
            if seg is not None and len(seg) > 0:
                seg_dur = len(seg) / sr
                segments.append((seg, cursor, seg_dur, vad_info))
                cursor += seg_dur
                if remaining is not None:
                    buf = remaining
                else:
                    buf = np.array([], dtype=np.float32)
                    break
            elif remaining is not None:
                # 短语音被跳过（cut 返回 None 段）：按 buf 原长与 remaining 差值
                # 补偿 cursor，否则后续段时间戳系统性偏早
                cursor += (len(buf) - len(remaining)) / sr
                buf = remaining
            else:
                break

    if len(buf) > min_flush_samples:
        seg_dur = len(buf) / sr
        vad_info = {'forced': True, 'silence': vad.vad_silence_threshold,
                    'adaptive_coeff': 1.0, 'overlap': 1.3, 'chunk_dur': seg_dur}
        segments.append((buf, cursor, seg_dur, vad_info))

    return segments


class VADProcessor:

    MUSIC_ENERGY_EPSILON = 1e-8

    def __init__(self, vad_silence_threshold=0.85, vad_force_cut=True, vad_force_cut_sec=6.0,
                 min_speech_duration=0.12,
                 max_buffer_seconds=30, adaptive=True):
        self.vad_silence_threshold = vad_silence_threshold
        self.vad_force_cut = vad_force_cut
        self.vad_force_cut_sec = vad_force_cut_sec
        self.min_speech_duration = min_speech_duration
        self.max_buffer_seconds = max_buffer_seconds
        # adaptive=True（实时模式）：根据说话语速动态调整阈值
        # adaptive=False（本地批处理）：直接使用用户设置的阈值，不自适应
        self.adaptive = adaptive

        # 自适应VAD内部状态
        self.speech_gaps = []
        self.adaptive_threshold = 1.35

    def reset(self):
        """重置会话状态：清空自适应历史数据"""
        self.speech_gaps = []
        self.adaptive_threshold = 1.35

    def cut(self, audio_data, sr):
        """
        自适应VAD：根据说话语速动态调整静音断句阈值
        - 说话快（间隙短）→ 阈值小（0.5s），快速断句
        - 说话慢（间隙长）→ 阈值大（1.3s），耐心等待不打断
        返回 (语音段, 剩余缓冲区, VAD信息字典)
        - 语音段: numpy array 或 None（无完整语音段）
        - 剩余缓冲区: numpy array 或 None（无需更新时为 None）
        - VAD信息字典
        """
        frame_len = int(sr * 0.03)
        hop_len = int(sr * 0.01)
        n_frames = (len(audio_data) - frame_len) // hop_len + 1

        vad_info = {'silence': self.vad_silence_threshold, 'adaptive_coeff': 1.0,
                    'forced': False, 'overlap': 1.3, 'chunk_dur': 0}

        min_dur_frames = max(1, int(self.min_speech_duration / 0.03))
        if n_frames < min_dur_frames:
            return None, None, vad_info

        energies = np.zeros(n_frames)
        for i in range(n_frames):
            start = i * hop_len
            frame = audio_data[start:start + frame_len]
            energies[i] = np.sqrt(np.mean(frame ** 2))

        threshold = np.median(energies) * 1.5 if np.median(energies) > 0 else 0.0005
        is_speech = energies > threshold

        # === 流式模式：使用配置的静音阈值和强制切分参数 ===
        # fc 是用户设置的强制切分时长。下面三个值的偏移用于：
        # - force_cut_sec: 达到此长度开始寻找切分点（略晚于 fc，给静音检测留余量）
        # - force_cut_size: 实际切分时的最小段长度（= fc，严格遵循用户设置）
        # - desperate_sec: 绝望切分长度，超过此值无论有无静音强制切（避免无限增长）
        # 偏移采用 fc 的 10% 而非固定秒数，使行为随用户设置按比例缩放
        fc = self.vad_force_cut_sec
        _margin = max(0.3, fc * 0.1)  # 至少 0.3s 余量，避免短段切分过早
        force_cut_sec = fc + _margin
        force_cut_size = fc
        desperate_sec = fc + _margin * 3

        # === 计算语音爆发间隙，更新自适应阈值 ===
        changes = np.diff(np.concatenate([[False], is_speech, [False]]).astype(int))
        starts = np.where(changes == 1)[0]   # 语音爆发开始帧
        ends = np.where(changes == -1)[0]     # 语音爆发结束帧
        ends = ends[:len(starts)]              # 对齐

        # 计算间隙（上一段结束到下一段开始）
        for i in range(1, len(starts)):
            gap = (starts[i] - ends[i-1]) * 0.01  # 转换为秒
            if 0.05 < gap < 10:  # 忽略太短和太长的异常间隙
                self.speech_gaps.append(gap)
                if len(self.speech_gaps) > 20:
                    self.speech_gaps.pop(0)

        # === 自适应静音阈值：根据说话间隙动态调整 ===
        # 基础阈值 = vad_silence_threshold（默认 0.85s）
        # adaptive=False（本地批处理）：直接用用户设置的阈值，不做自适应
        # adaptive=True（实时模式）：根据说话语速动态调整
        if not self.adaptive:
            adaptive_silence = self.vad_silence_threshold
            self.adaptive_threshold = 1.0
        elif len(self.speech_gaps) >= 5:
            median_gap = np.median(self.speech_gaps)
            self.adaptive_threshold = np.clip(median_gap / 0.8, 0.8, 1.5)
            adaptive_silence = self.vad_silence_threshold * self.adaptive_threshold
            # 上下界保护：确保下界不超过上界（避免大 vad_silence_threshold 时约束失效）
            _lower = self.vad_silence_threshold * 0.8
            _upper = max(1.5, _lower)
            adaptive_silence = max(_lower, min(adaptive_silence, _upper))
        else:
            self.adaptive_threshold = 1.0
            adaptive_silence = self.vad_silence_threshold

        min_silence_frames = int(adaptive_silence / 0.01)

        vad_info['silence'] = round(adaptive_silence, 2)
        vad_info['adaptive_coeff'] = round(self.adaptive_threshold, 2)

        min_speech_frames = max(1, int(self.min_speech_duration / 0.01))

        # === 尾音保护 ===
        # VAD 只标记高于能量阈值的帧，句尾的轻声/气声（如语气词"呢/啊/吧"
        # 的收尾、末尾辅音）往往低于阈值。若在最后一帧处硬切，ASR 看不到
        # 句尾发音 → 导致"结尾漏字/漏词"。
        # 把段尾向后多保留约 200ms（且不超过有效静音的一半），并补齐最后一帧
        # 的能量尾（frame_len - hop_len），让 ASR 看到完整的句尾，又不侵占下一句开头。
        _tail_pad = min(int(0.2 * sr), int(adaptive_silence * 0.5 * sr)) + (frame_len - hop_len)

        # === 找到完整语音段（末尾有足够静音）===
        if np.any(is_speech):
            last_speech_frame = np.where(is_speech)[0][-1]
            silence_after = n_frames - last_speech_frame
            first_speech_frame = np.where(is_speech)[0][0]
            speech_duration = (last_speech_frame - first_speech_frame + 1) * 0.01

            # 语音段太短且后面有足够静音：判定为噪声/呼吸声，跳过这段短语音
            # 返回 None（不切出段），但更新缓冲区跳过已处理的短语音
            if speech_duration < self.min_speech_duration and silence_after >= min_silence_frames:
                cut_point = (last_speech_frame + 1) * hop_len
                remaining = audio_data[cut_point:]
                vad_info['chunk_dur'] = 0
                vad_info['skipped'] = True
                return None, remaining, vad_info

            # 连续说话快速切分：使用用户配置的静音阈值（而非硬编码）
            quick_cut_dur = 2.5
            if self.vad_force_cut and speech_duration > quick_cut_dur and silence_after >= min_silence_frames:
                cut_point = min(len(audio_data), (last_speech_frame + 1) * hop_len + _tail_pad)
                speech_segment = audio_data[:cut_point]
                remaining = audio_data[cut_point:]
                self.speech_gaps = []
                self.adaptive_threshold = 1.35
                vad_info['chunk_dur'] = len(speech_segment) / sr
                vad_info['forced'] = False
                return speech_segment, remaining, vad_info

            if silence_after >= min_silence_frames:
                cut_point = min(len(audio_data), (last_speech_frame + 1) * hop_len + _tail_pad)
                speech_segment = audio_data[:cut_point]
                speech_duration = len(speech_segment) / sr

                # 不跳过静音区，保留全部音频给下一段，避免丢失句首
                remaining = audio_data[cut_point:]

                # 重置间隙统计
                self.speech_gaps = []
                self.adaptive_threshold = 1.35

                vad_info['chunk_dur'] = len(speech_segment) / sr
                vad_info['forced'] = False
                return speech_segment, remaining, vad_info

            # 缓冲区超过阈值且无静音间隙则强制切出（受 vad_force_cut 开关控制）
            buffer_dur = len(audio_data) / sr
            if self.vad_force_cut and buffer_dur > force_cut_sec:
                cut_samples = int(force_cut_size * sr)
                # Search backward up to 1.5s for a silence gap (increased from 0.5s)
                # to reduce mid-word splits during continuous speech
                search_back_sec = min(1.5, force_cut_size * 0.4)
                search_start = max(0, cut_samples - int(search_back_sec * sr))
                search_region = energies[search_start//hop_len:cut_samples//hop_len]
                if len(search_region) > 0:
                    # Find the last low-energy frame in the search region
                    silence_mask = search_region < threshold
                    if np.any(silence_mask):
                        last_silence_idx = np.where(silence_mask)[0][-1]
                        cut_samples = (search_start // hop_len + last_silence_idx + 1) * hop_len
                speech_segment = audio_data[:cut_samples]
                remaining = audio_data[cut_samples:]
                vad_info['forced'] = True
                vad_info['chunk_dur'] = len(speech_segment) / sr
                return speech_segment, remaining, vad_info

        # 无语音检测但缓冲区已积压：可能是轻声说话/连续背景音（受 vad_force_cut 开关控制）
        buffer_dur = len(audio_data) / sr
        if self.vad_force_cut and buffer_dur > desperate_sec:
            cut_samples = int(min(buffer_dur, fc) * sr)
            speech_segment = audio_data[:cut_samples]
            remaining = audio_data[cut_samples:]
            vad_info['forced'] = True
            vad_info['chunk_dur'] = len(speech_segment) / sr
            return speech_segment, remaining, vad_info

        return None, None, vad_info


# ============================================================
# FSMN VAD（达摩院 FunASR 框架，中文优化）
# ============================================================

_FSMN_MODEL = None
_FSMN_LOAD_LOCK = __import__('threading').Lock()


def load_fsmn_vad(models_dir=None):
    """加载 FSMN VAD 模型（通过 FunASR AutoModel）。
    返回 funasr AutoModel 实例。

    模型：iic/speech_fsmn_vad_zh-cn-16k-common-pytorch
    首次使用自动从 ModelScope 下载（~15MB），之后从本地缓存加载。
    需要安装 funasr：pip install funasr
    """
    global _FSMN_MODEL
    with _FSMN_LOAD_LOCK:
        if _FSMN_MODEL is not None:
            return _FSMN_MODEL
        import io
        import os
        import sys
        from pathlib import Path

        if models_dir is None:
            models_dir = str(Path(__file__).parent / "models" / "fsmn-vad")
        os.makedirs(models_dir, exist_ok=True)

        try:
            from funasr import AutoModel
        except ImportError as e:
            raise ImportError(
                "FSMN VAD 需要 funasr 库，请执行: pip install funasr\n"
                f"原始错误: {e}"
            )

        # FSMN VAD 模型（中文 16k 通用 PyTorch 版本）
        model_id = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"

        # AutoModel.__init__ 内部调用 logging.basicConfig(level=INFO)，
        # 会用当前 sys.stderr 创建 StreamHandler。
        # app.py 中 sys.stderr 被替换为 LR(log_cb) 对象，
        # LR 没有 fileno()/isatty() 等方法，可能导致 FunASR/tqdm/modelscope
        # 内部的 'NoneType' object has no attribute 'write' 错误。
        # 这里临时恢复 sys.stdout/sys.stderr 为真实文件对象。
        _orig_stdout, _orig_stderr = sys.stdout, sys.stderr
        _safe_stdout = sys.__stdout__ if sys.__stdout__ is not None else io.StringIO()
        _safe_stderr = sys.__stderr__ if sys.__stderr__ is not None else io.StringIO()
        sys.stdout = _safe_stdout
        sys.stderr = _safe_stderr
        try:
            _FSMN_MODEL = AutoModel(
                model=model_id,
                model_revision="v2.0.4",
                device="cpu",  # 强制 CPU 运行，避免与 ASR 模型竞争 GPU 显存导致 OOM
            )
        finally:
            sys.stdout = _orig_stdout
            sys.stderr = _orig_stderr
        return _FSMN_MODEL


def fsmn_vad_segment(audio, sr, vad_silence_threshold=0.8,
                     min_speech_duration=0.12, force_cut_sec=6.0,
                     speech_noise_threshold=0.6):
    """用 FSMN VAD 做批量语音切分。

    参数:
        audio: numpy array (mono float32, 16kHz)
        sr: 采样率（固定 16000）
        vad_silence_threshold: 静音断句时长（秒）→ fsmn max_end_silence_time
        min_speech_duration: 最小语音段时长（秒）→ fsmn min_speech_duration
        force_cut_sec: 最大语音段时长（秒），超过则强制切分
        speech_noise_threshold: 语音/噪声判别阈值（0~1，越高越严格）

    返回: [(seg_audio, seg_time, seg_dur, vad_info), ...]
    """
    import os
    import sys
    import tempfile
    import wave

    # funasr 内部 torchaudio.load 需要 torchcodec，缺失时回退到系统 ffmpeg。
    # 用户环境通常没装 torchcodec，且系统 PATH 也没有 ffmpeg（项目的在 models/ffmpeg/）。
    # 这里把项目 ffmpeg 目录加入 PATH，让 funasr 的 _load_audio_ffmpeg 能找到。
    try:
        from core import MODELS_DIR
        ffmpeg_dir = MODELS_DIR / "ffmpeg"
        if ffmpeg_dir.is_dir():
            ffmpeg_dir_str = str(ffmpeg_dir)
            if ffmpeg_dir_str not in os.environ.get("PATH", ""):
                os.environ["PATH"] = ffmpeg_dir_str + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass

    model = load_fsmn_vad()

    # FSMN VAD 需要文件输入，把 numpy array 写入临时 wav
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".wav", prefix="_fsmn_vad_")
    os.close(tmp_fd)  # 关闭 fd，只用文件路径
    try:
        tmp_path = os.path.normpath(tmp_path)
        with wave.open(tmp_path, 'wb') as wav_writer:
            wav_writer.setnchannels(1)
            wav_writer.setsampwidth(2)  # int16
            wav_writer.setframerate(sr)
            audio_int16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
            wav_writer.writeframes(audio_int16.tobytes())

        # 调用 FSMN VAD
        # 临时恢复 sys.stdout/sys.stderr 为真实文件对象，
        # 避免 app.py 中 LR 重定向对象导致 FunASR/tqdm 内部 'NoneType' object has no attribute 'write'
        import io
        _orig_stdout, _orig_stderr = sys.stdout, sys.stderr
        # sys.__stdout__ 在 GUI 应用（pythonw）中可能为 None，用 io.StringIO() 兜底
        _safe_stdout = sys.__stdout__ if sys.__stdout__ is not None else io.StringIO()
        _safe_stderr = sys.__stderr__ if sys.__stderr__ is not None else io.StringIO()
        sys.stdout = _safe_stdout
        sys.stderr = _safe_stderr
        try:
            res = model.generate(
                input=tmp_path,
                cache={},
                is_final=True,
                max_end_silence_time=int(vad_silence_threshold * 1000),
                min_speech_duration=int(min_speech_duration * 1000),
                speech_noise_threshold=speech_noise_threshold,
                disable_pbar=True,  # 禁用 tqdm 进度条，避免 sys.stderr 被替换时报错
            )
        finally:
            sys.stdout = _orig_stdout
            sys.stderr = _orig_stderr
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    # 解析 FSMN VAD 输出
    # res 格式: [{'key': '...', 'value': [[start_ms, end_ms], ...]}]
    # start/end 单位是毫秒
    if not res or not res[0].get('value'):
        return []

    timestamps = res[0]['value']
    segments = []
    for ts in timestamps:
        # FSMN VAD 输出是 [start_ms, end_ms] 列表
        if isinstance(ts, list):
            start_ms, end_ms = ts[0], ts[1]
        elif isinstance(ts, dict):
            start_ms = ts.get('start', 0)
            end_ms = ts.get('end', 0)
        else:
            continue

        start_sample = int(start_ms * sr / 1000)
        end_sample = int(end_ms * sr / 1000)

        start_sample = max(0, min(start_sample, len(audio)))
        end_sample = max(start_sample + 1, min(end_sample, len(audio)))

        seg_audio = audio[start_sample:end_sample]
        seg_dur = len(seg_audio) / sr
        seg_time = start_sample / sr

        # 超过 force_cut_sec 的段做二次切分（不做 overlap：下游逐 chunk ASR 后
        # 直接拼接文本且无去重逻辑，重叠会导致切分边界处文本重复）
        if seg_dur > force_cut_sec:
            chunk_samples = int(force_cut_sec * sr)
            step = chunk_samples
            i = 0
            while i < len(seg_audio):
                chunk = seg_audio[i:i + chunk_samples]
                chunk_dur = len(chunk) / sr
                chunk_time = seg_time + i / sr
                vad_info = {
                    'silence': vad_silence_threshold,
                    'adaptive_coeff': 1.0,
                    'forced': True,
                    'overlap': 0,
                    'chunk_dur': chunk_dur,
                    'engine': 'fsmn',
                }
                segments.append((chunk, chunk_time, chunk_dur, vad_info))
                i += step
        else:
            vad_info = {
                'silence': vad_silence_threshold,
                'adaptive_coeff': 1.0,
                'forced': False,
                'overlap': 0,
                'chunk_dur': seg_dur,
                'engine': 'fsmn',
            }
            segments.append((seg_audio, seg_time, seg_dur, vad_info))

    return segments


# ============================================================
# FireRedVAD（小红书面部 ASR 系 DFSMN VAD，FLEURS-102 语言 SOTA）
# 官方评测 F1 97.57 vs Silero 95.95，误报率 2.69% vs 9.41%
# 模型：xukaituo/FireRedVAD（VAD/Stream-VAD/AED 三个子模型，各 ~2.3MB）
# 来源：https://github.com/FireRedTeam/FireRedASR2S（Apache-2.0，代码已 vendor 至 vendor/fireredvad）
# 注意：官方仅声明 Linux 测试通过，Windows 下经本项目 POC 实测可用
# ============================================================

_FIRERED_VAD = None
_FIRERED_VAD_LOAD_LOCK = __import__('threading').Lock()
# FireRedVAD 帧长 16ms（DFSMN），用于参数换算
_FIRERED_FRAME_SEC = 0.016


def load_firered_vad(models_dir=None, use_gpu=False, vad_silence_threshold=0.5,
                     min_speech_duration=0.25, force_cut_sec=6.0, speech_threshold=0.4):
    """加载 FireRedVAD 模型（vendor 推理代码 + models/firered-vad/VAD 权重）。

    参数按帧（16ms）换算进后处理配置；模型极小（2.3MB，加载约 0.0s），每次按参数构建。
    模型缺失时给出 modelscope 下载命令提示。
    """
    from pathlib import Path
    if models_dir is None:
        models_dir = Path(__file__).parent / "models" / "firered-vad" / "VAD"
    models_dir = Path(models_dir)
    if not (models_dir / "model.pth.tar").is_file():
        raise FileNotFoundError(
            "FireRedVAD 模型不存在，请先下载（约 7MB）:\n"
            "  python -c \"from modelscope.hub.snapshot_download import snapshot_download; "
            "snapshot_download('xukaituo/FireRedVAD', cache_dir='models')\"\n"
            "  下载后把 models/xukaituo/FireRedVAD 复制为 models/firered-vad（含 VAD/Stream-VAD/AED）"
        )
    try:
        from vendor.fireredvad import FireRedVad, FireRedVadConfig
    except ImportError as e:
        raise ImportError(f"FireRedVAD 推理代码缺失（vendor/fireredvad）: {e}")
    _frame = _FIRERED_FRAME_SEC
    config = FireRedVadConfig(
        use_gpu=bool(use_gpu),
        smooth_window_size=5,
        speech_threshold=speech_threshold,
        min_speech_frame=max(1, int(min_speech_duration / _frame)),
        max_speech_frame=max(2, int(force_cut_sec / _frame)),
        min_silence_frame=max(1, int(vad_silence_threshold / _frame)),
        merge_silence_frame=0,
        extend_speech_frame=0,
        chunk_max_frame=30000,
    )
    return FireRedVad.from_pretrained(str(models_dir), config)


def firered_vad_segment(audio, sr, vad_silence_threshold=0.5,
                        min_speech_duration=0.25, force_cut_sec=6.0,
                        speech_threshold=0.4, use_gpu=False):
    """FireRedVAD 语音切分（DFSMN，多语言 SOTA，误报率低于 Silero 约 3.5 倍）。

    参数:
        audio: numpy array (mono float32, 16kHz)
        sr: 采样率（固定 16000）
        vad_silence_threshold: 静音断句时长（秒）→ min_silence_frame
        min_speech_duration: 最小语音段时长（秒）→ min_speech_frame
        force_cut_sec: 最大语音段时长（秒），超过则强制切分
        speech_threshold: 语音概率阈值（0~1，默认 0.4，官方默认）

    返回: [(seg_audio, seg_time, seg_dur, vad_info), ...]
    """
    import os
    import tempfile
    import uuid

    vad = load_firered_vad(
        use_gpu=use_gpu,
        vad_silence_threshold=vad_silence_threshold,
        min_speech_duration=min_speech_duration,
        force_cut_sec=force_cut_sec,
        speech_threshold=speech_threshold,
    )

    # FireRedVAD detect 只接受文件路径，把 numpy array 写入临时 wav
    tmp_path = os.path.join(
        tempfile.gettempdir(), f"_firered_vad_{uuid.uuid4().hex}.wav")
    try:
        import soundfile as sf
        sf.write(tmp_path, audio.astype(np.float32), sr)
        result, _probs = vad.detect(tmp_path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass

    timestamps = result.get('timestamps', []) if result else []
    segments = []
    for start_s, end_s in timestamps:
        start_sample = int(start_s * sr)
        end_sample = int(end_s * sr)
        start_sample = max(0, min(start_sample, len(audio)))
        end_sample = max(start_sample + 1, min(end_sample, len(audio)))

        seg_audio = audio[start_sample:end_sample]
        seg_dur = len(seg_audio) / sr
        seg_time = start_sample / sr

        # 超过 force_cut_sec 的段做二次切分（与 FSMN 引擎一致：无重叠）
        if seg_dur > force_cut_sec:
            chunk_samples = int(force_cut_sec * sr)
            step = chunk_samples
            i = 0
            while i < len(seg_audio):
                chunk = seg_audio[i:i + chunk_samples]
                chunk_dur = len(chunk) / sr
                chunk_time = seg_time + i / sr
                vad_info = {
                    'silence': vad_silence_threshold,
                    'adaptive_coeff': 1.0,
                    'forced': True,
                    'overlap': 0,
                    'chunk_dur': chunk_dur,
                    'engine': 'firered',
                }
                segments.append((chunk, chunk_time, chunk_dur, vad_info))
                i += step
        else:
            vad_info = {
                'silence': vad_silence_threshold,
                'adaptive_coeff': 1.0,
                'forced': False,
                'overlap': 0,
                'chunk_dur': seg_dur,
                'engine': 'firered',
            }
            segments.append((seg_audio, seg_time, seg_dur, vad_info))
    return segments