# -*- coding: utf-8 -*-
"""
共享工具模块 — 消除多文件间的重复实现

包含：
- StdoutRedirect:       把 stdout/stderr 重定向到回调（app.py / local_processor.py 复用）
- resample_audio:       任意采样率重采样（server.py / realtime_panel.py 复用）
- SPEAKER_MODEL_MAP / STRICTNESS_THRESHOLDS:  说话人模型与严格度映射
- load_speaker_pipeline:说话人识别 pipeline 加载（实时/本地/批处理共用）
"""

import numpy as np


# 说话人识别模型 ID 与本地缓存目录名映射
SPEAKER_MODEL_MAP = {
    "cam++": {
        "id": "iic/speech_campplus_sv_zh-cn_16k-common",
        "dir": "speech_campplus_sv_zh-cn_16k-common",
        "label": "CAM++",
    },
    "eres2netv2": {
        "id": "iic/speech_eres2netv2_sv_zh-cn_16k-common",
        "dir": "speech_eres2netv2_sv_zh-cn_16k-common",
        "label": "ERes2NetV2",
    },
    "eres2net": {
        "id": "iic/speech_eres2net_base_sv_zh-cn_3dspeaker_16k",
        "dir": "speech_eres2net_base_sv_zh-cn_3dspeaker_16k",
        "label": "ERes2Net base",
    },
}

# 说话人严格度 → 声纹相似度阈值（宽松=0.50 合并，标准=0.55，严格=0.62）
STRICTNESS_THRESHOLDS = {"loose": 0.50, "standard": 0.55, "strict": 0.62}


class StdoutRedirect:
    """把 stdout/stderr 重定向到回调函数。

    逐行缓冲，遇换行才回调，避免把半行文本塞进日志。
    回调或底层 writer 抛异常时静默降级，绝不中断主流程。
    用法（配对恢复）：
        _so, _se = sys.stdout, sys.stderr
        sys.stdout = StdoutRedirect(cb)
        sys.stderr = StdoutRedirect(cb)
        try: ...
        finally: sys.stdout, sys.stderr = _so, _se
    """

    def __init__(self, callback, fallback=None):
        self._cb = callback
        self._fb = fallback
        self._b = ""

    def write(self, s):
        if not s:
            return
        try:
            self._b += s
            if "\n" in self._b:
                ls = self._b.split("\n")
                self._b = ls.pop()
                for l in ls:
                    if l.strip():
                        self._cb(l + "\n")
                    elif self._fb is not None:
                        try:
                            self._fb.write(l + "\n")
                        except Exception:
                            pass
        except Exception:
            pass

    def flush(self):
        try:
            if self._b.strip():
                self._cb(self._b + "\n")
                self._b = ""
            elif self._fb is not None:
                try:
                    self._fb.flush()
                except Exception:
                    pass
        except Exception:
            pass


def resample_audio(audio_data, from_rate, to_rate):
    """把音频从 from_rate 重采样到 to_rate。

    优先 scipy.signal.resample_poly（抗混叠）；无 scipy 时回退为
    线性插值（支持任意上/下采样比例）。
    """
    if from_rate == to_rate:
        return audio_data
    try:
        from scipy import signal
        return signal.resample_poly(audio_data.astype(np.float64), to_rate, from_rate).astype(np.float32)
    except ImportError:
        n_out = max(1, int(len(audio_data) * to_rate / from_rate))
        src_idx = np.arange(len(audio_data))
        out_idx = np.clip(np.arange(n_out) * (from_rate / to_rate),
                          0, max(0, len(audio_data) - 1))
        return np.interp(out_idx, src_idx, audio_data.astype(np.float64)).astype(np.float32)


def load_speaker_pipeline(speaker_model_key="cam++"):
    """加载说话人识别 pipeline（CAM++ / ERes2NetV2 / ERes2Net base）。

    优先使用项目 models/ 目录下的本地缓存，否则从 ModelScope 下载。
    失败时返回 None（ASR 主流程不受影响，说话人统一标记 Speaker0）。
    """
    from core import MODELS_DIR, silence_noisy_loggers
    silence_noisy_loggers()
    model_info = SPEAKER_MODEL_MAP.get(speaker_model_key, SPEAKER_MODEL_MAP["cam++"])
    try:
        from modelscope.pipelines import pipeline
        from modelscope.utils.constant import Tasks

        sp_local = None
        for candidate in list(MODELS_DIR.glob(f'**/{model_info["dir"]}')):
            if candidate.is_dir() and '.___' not in str(candidate):
                sp_local = str(candidate)
                break

        if sp_local:
            print(f"[SPEAKER] {model_info['label']} from cache: {sp_local}", flush=True)
            return pipeline(task=Tasks.speaker_verification, model=sp_local)
        print(f"[SPEAKER] Downloading {model_info['label']} from ModelScope...", flush=True)
        return pipeline(
            task=Tasks.speaker_verification,
            model=model_info["id"],
            model_revision='v1.0.0',
        )
    except Exception as e:
        print(f"[SPEAKER] {model_info['label']} load failed: {e}", flush=True)
        return None
