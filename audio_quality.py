# -*- coding: utf-8 -*-
"""
语音质量评分模块（后训练数据集用）

评分维度：
  - snr:               信噪比估计（纯净度）。用分段能量法：高能量帧均值 / 低能量帧均值，
                       转为 dB 后归一化到 0.0~1.0。越高越干净。
  - rms:               音量电平（RMS, 0.0~1.0）。过低=太轻，过高=可能削波。
  - clipping:          削波比例（0.0~1.0）。统计接近 ±1.0 的样本占比。越低越好。
  - spectral_flatness: 频谱平坦度（0.0~1.0）。越低=语音特征明显，越高=白噪声/嗡嗡声。
  - overall:           综合评分（0.0~1.0）。加权组合，用于筛选优质片段。

设计原则：
  - 仅依赖 numpy + scipy（项目已有），无额外第三方库。
  - 纯函数式：score_audio(audio, sr) -> dict，便于在转录流程中直接调用。
  - 阈值基于 16kHz mono float32 语音片段经验值，可在需要时调整。
"""

import numpy as np
from scipy import signal as scipy_signal


# 评分权重（综合评分用）
_W_SNR = 0.35
_W_RMS = 0.25
_W_CLIPPING = 0.20
_W_FLATNESS = 0.20

# 帧参数（用于 SNR 分帧估计）
_FRAME_LEN = 1024       # 约 64ms @16kHz
_HOP_LEN = 512          # 50% overlap

# 削波判定阈值（|sample| >= CLIP_THR 视为削波）
_CLIP_THR = 0.99


def _to_mono_float32(audio):
    """统一为 mono float32 ndarray。"""
    arr = np.asarray(audio, dtype=np.float32)
    if arr.ndim > 1:
        arr = np.mean(arr, axis=1).astype(np.float32)
    return arr


def _estimate_snr(audio):
    """分段能量法估计 SNR（dB → 归一化到 0.0~1.0）。

    把音频按帧切分，计算每帧能量。高能量帧（top 30%）均值视为信号能量，
    低能量帧（bottom 30%）均值视为噪声能量。SNR_dB = 10*log10(signal/noise)。
    归一化：SNR_dB / 30dB（30dB 视为满分纯净），clamp 到 [0,1]。
    """
    if len(audio) < _FRAME_LEN:
        # 过短：用整体能量与极低参考比，返回保守值
        rms_all = float(np.sqrt(np.mean(audio ** 2)) + 1e-12)
        noise_ref = 1e-4
        snr_db = 10.0 * np.log10(max(rms_all ** 2, noise_ref) / noise_ref)
        return float(min(1.0, max(0.0, snr_db / 30.0)))

    # 分帧能量
    n_frames = 1 + (len(audio) - _FRAME_LEN) // _HOP_LEN
    if n_frames < 2:
        rms_all = float(np.sqrt(np.mean(audio ** 2)) + 1e-12)
        return float(min(1.0, max(0.0, (10.0 * np.log10(rms_all ** 2 / 1e-8)) / 30.0)))

    energies = np.empty(n_frames, dtype=np.float64)
    for i in range(n_frames):
        start = i * _HOP_LEN
        frame = audio[start:start + _FRAME_LEN]
        energies[i] = np.mean(frame ** 2) + 1e-12

    sorted_e = np.sort(energies)
    n = len(sorted_e)
    low_n = max(1, n // 3)
    high_n = max(1, n // 3)
    noise_e = float(np.mean(sorted_e[:low_n]))
    signal_e = float(np.mean(sorted_e[-high_n:]))

    if noise_e <= 0 or signal_e <= 0:
        return 0.0
    snr_db = 10.0 * np.log10(signal_e / noise_e)
    # 30dB 视为满分，-10dB 视为 0 分
    norm = (snr_db + 10.0) / 40.0
    return float(min(1.0, max(0.0, norm)))


def _estimate_rms(audio):
    """RMS 音量电平，归一化到 0.0~1.0。"""
    if len(audio) == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(audio ** 2)))
    return min(1.0, max(0.0, rms))


def _estimate_clipping(audio):
    """削波比例（0.0~1.0）。"""
    if len(audio) == 0:
        return 0.0
    clipped = np.sum(np.abs(audio) >= _CLIP_THR)
    return float(clipped / len(audio))


def _estimate_spectral_flatness(audio):
    """频谱平坦度（0.0~1.0）。

    geometric_mean / arithmetic_mean of power spectrum。
    语音信号有明显谐波结构 → 平坦度低；白噪声 → 平坦度接近 1。
    """
    if len(audio) < _FRAME_LEN:
        return 0.5  # 过短无法估计，返回中性值

    # 用 Hann 窗 + FFT 计算功率谱
    window = np.hanning(_FRAME_LEN)
    freqs, psd = scipy_signal.welch(audio, fs=16000, window=window,
                                    nperseg=_FRAME_LEN, noverlap=_HOP_LEN,
                                    scaling='density')

    psd = np.maximum(psd, 1e-12)  # 避免 log(0)
    # 对所有帧的平均功率谱做平坦度
    mean_psd = np.mean(psd, axis=0) if psd.ndim > 1 else psd
    mean_psd = np.maximum(mean_psd, 1e-12)

    log_mean = np.mean(np.log(mean_psd))
    geo_mean = np.exp(log_mean)
    arith_mean = np.mean(mean_psd)

    if arith_mean <= 0:
        return 0.5
    flatness = float(geo_mean / arith_mean)
    return min(1.0, max(0.0, flatness))


def _rms_to_score(rms):
    """RMS 映射到评分：0.02~0.3 区间为优质，过低/过高扣分。"""
    if rms < 0.005:
        return 0.1  # 几乎静音
    if rms < 0.02:
        return 0.3 + (rms - 0.005) / (0.02 - 0.005) * 0.4  # 0.3~0.7
    if rms <= 0.3:
        return 1.0  # 理想区间
    if rms <= 0.6:
        return 1.0 - (rms - 0.3) / (0.6 - 0.3) * 0.3  # 1.0~0.7
    return max(0.2, 0.7 - (rms - 0.6) * 1.0)  # 削波风险


def _clipping_to_score(clipping):
    """削波比例映射：0% 削波=1.0，>3% 削波=接近 0。"""
    if clipping <= 0.001:
        return 1.0
    if clipping <= 0.03:
        return 1.0 - (clipping - 0.001) / (0.03 - 0.001) * 0.3
    return max(0.0, 0.7 - (clipping - 0.03) * 20.0)


def _flatness_to_score(flatness):
    """平坦度映射：平坦度越低（语音特征明显）评分越高。

    语音段平坦度通常 0.05~0.3；白噪声接近 1.0。
    """
    if flatness <= 0.1:
        return 1.0
    if flatness <= 0.3:
        return 1.0 - (flatness - 0.1) / (0.3 - 0.1) * 0.2  # 1.0~0.8
    if flatness <= 0.6:
        return 0.8 - (flatness - 0.3) / (0.6 - 0.3) * 0.4  # 0.8~0.4
    return max(0.0, 0.4 - (flatness - 0.6) * 1.0)


def score_audio(audio, sr=16000):
    """对一段语音片段打分。

    参数:
        audio: numpy array (mono 或 multi-channel, float32)
        sr:    采样率（仅用于参考，本实现固定按 16kHz 调参）

    返回:
        dict:
            snr:               0.0~1.0
            rms:               0.0~1.0（原始 RMS，非评分）
            clipping:          0.0~1.0（原始削波比例，非评分）
            spectral_flatness: 0.0~1.0（原始平坦度，非评分）
            overall:           0.0~1.0（综合评分）
    """
    arr = _to_mono_float32(audio)
    if len(arr) == 0:
        return {
            "snr": 0.0, "rms": 0.0, "clipping": 0.0,
            "spectral_flatness": 0.0, "overall": 0.0,
        }

    snr = _estimate_snr(arr)
    rms = _estimate_rms(arr)
    clipping = _estimate_clipping(arr)
    flatness = _estimate_spectral_flatness(arr)

    snr_score = max(0.0, min(1.0, snr))
    rms_score = _rms_to_score(rms)
    clip_score = _clipping_to_score(clipping)
    flat_score = _flatness_to_score(flatness)

    overall = (
        _W_SNR * snr_score
        + _W_RMS * rms_score
        + _W_CLIPPING * clip_score
        + _W_FLATNESS * flat_score
    )
    overall = float(max(0.0, min(1.0, overall)))

    return {
        "snr": round(float(snr), 4),
        "rms": round(float(rms), 4),
        "clipping": round(float(clipping), 4),
        "spectral_flatness": round(float(flatness), 4),
        "overall": round(overall, 4),
    }


def is_high_quality(scores, threshold=0.6):
    """判断片段是否达到优质训练数据标准。

    默认阈值 0.6：综合评分 >= 0.6 且 削波 < 5% 且 平坦度 < 0.7。
    """
    if not scores:
        return False
    if scores.get("overall", 0.0) < threshold:
        return False
    if scores.get("clipping", 1.0) > 0.05:
        return False
    if scores.get("spectral_flatness", 1.0) > 0.7:
        return False
    return True
