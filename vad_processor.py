# -*- coding: utf-8 -*-
"""
VAD 处理器：自适应能量阈值 VAD（唯一版本）

说明：
- 本文件为唯一 VAD 实现，基于自适应能量阈值 + 语速感知的静音断句。
- 历史上曾尝试引入 Silero 神经网络 VAD 作为升级，但因：
    1) torch.jit.load 在 Windows 中文路径下 errno 2 失败
    2) Silero 的「即时返回多段 timestamps」语义与 server.py 的
       「流式累积缓冲区取单段」架构不匹配，强行加累积补丁会碎片化
    3) Silero 缺乏 legacy 的「自适应语速」和「反向搜索静音点」能力
  最终回滚为仅保留 legacy 版本，删除所有 Silero 相关代码与依赖。
"""

import numpy as np


class VADProcessor:
    """
    自适应能量阈值 VAD：根据说话语速动态调整静音断句阈值。

    核心特性：
    - 自适应语速：统计 speech_gaps，快说快切（0.8s）、慢说慢切（1.2s）
    - 反向搜索静音点：强制切分时回扫 1.5s 找低能量帧，避免词中间断
    - 三级兜底：quick_cut（2.5s+0.8s 静音）→ 正常切分 → force_cut（回扫静音点）→ desperate（硬切）
    """

    def __init__(self, vad_silence_threshold=1.0, vad_force_cut=True, vad_force_cut_sec=6.0,
                 min_speech_duration=0.12):
        """
        Args:
            vad_silence_threshold: 判定一句话结束的静音时长（秒）。
            vad_force_cut: 是否开启长句强制切分。
            vad_force_cut_sec: 长句强制切分阈值（秒）。
            min_speech_duration: 最小有效语音时长（秒）。
        """
        self.vad_silence_threshold = vad_silence_threshold
        self.vad_force_cut = vad_force_cut
        self.vad_force_cut_sec = vad_force_cut_sec
        self.min_speech_duration = min_speech_duration

        # 自适应 VAD 内部状态
        self.speech_gaps = []
        self.adaptive_threshold = 1.0

    def _reset_adaptive(self):
        """清空自适应历史数据"""
        self.speech_gaps = []
        self.adaptive_threshold = 1.0

    def reset(self):
        """重置会话状态：清空自适应历史数据"""
        self._reset_adaptive()

    def cut(self, audio_data, sr):
        """
        切分完整语音段。

        返回 (语音段, 剩余缓冲区, VAD信息字典)
        - 语音段: numpy array 或 None（无完整语音段）
        - 剩余缓冲区: numpy array 或 None（无需更新时为 None）
        - VAD信息字典: 包含 silence / forced / chunk_dur / engine 等字段
        """
        frame_len = int(sr * 0.03)
        hop_len = int(sr * 0.01)
        n_frames = (len(audio_data) - frame_len) // hop_len + 1

        vad_info = {'silence': self.vad_silence_threshold, 'adaptive_coeff': 1.0,
                    'forced': False, 'overlap': 1.3, 'chunk_dur': 0, 'engine': 'legacy'}

        min_dur_frames = int(self.min_speech_duration / 0.03)
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
        fc = self.vad_force_cut_sec
        force_cut_sec = fc + 0.5
        force_cut_size = fc
        desperate_sec = fc + 1.5

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
        # 基础阈值 = vad_silence_threshold（默认 1.0s）
        # 快速说话（间隙小）→ 0.8s，快速断句
        # 慢速说话（间隙大）→ 1.2s，耐心等待
        if len(self.speech_gaps) >= 5:
            median_gap = np.median(self.speech_gaps)
            # 自适应系数：间隙 < 0.8s → 0.8x; 间隙 > 1.2s → 1.2x
            self.adaptive_threshold = np.clip(median_gap / 0.8, 0.8, 1.2)
        else:
            self.adaptive_threshold = 1.0  # 样本不足时使用基础阈值

        adaptive_silence = self.vad_silence_threshold * self.adaptive_threshold
        # 限制自适应范围：0.8s ~ 1.2s，防止极端值
        adaptive_silence = max(0.8, min(adaptive_silence, 1.2))
        min_silence_frames = int(adaptive_silence / 0.01)

        vad_info['silence'] = round(adaptive_silence, 2)
        vad_info['adaptive_coeff'] = round(self.adaptive_threshold, 2)

        min_speech_frames = max(1, int(self.min_speech_duration / 0.01))

        # === 找到完整语音段（末尾有足够静音）===
        if np.any(is_speech):
            last_speech_frame = np.where(is_speech)[0][-1]
            silence_after = n_frames - last_speech_frame
            first_speech_frame = np.where(is_speech)[0][0]
            speech_duration = (last_speech_frame - first_speech_frame + 1) * 0.01

            # 连续说话快速切分（提高语速/时长阈值，减少误切）
            quick_cut_dur = 2.5
            quick_cut_silence = int(0.8 / 0.01)
            if self.vad_force_cut and speech_duration > quick_cut_dur and silence_after >= quick_cut_silence:
                cut_point = (last_speech_frame + 1) * hop_len
                speech_segment = audio_data[:cut_point]
                remaining = audio_data[cut_point:]
                self._reset_adaptive()
                vad_info['chunk_dur'] = len(speech_segment) / sr
                vad_info['forced'] = False
                return speech_segment, remaining, vad_info

            if silence_after >= min_silence_frames:
                cut_point = (last_speech_frame + 1) * hop_len
                speech_segment = audio_data[:cut_point]
                speech_duration = len(speech_segment) / sr

                # 不跳过静音区，保留全部音频给下一段，避免丢失句首
                remaining = audio_data[cut_point:]

                # 重置间隙统计
                self._reset_adaptive()

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
