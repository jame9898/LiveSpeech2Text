# -*- coding: utf-8 -*-
"""
VAD 处理器：自适应静音断句 + 音乐/噪声检测
从 RealtimeASRServer 中提取，独立为 VADProcessor 类
"""

import numpy as np


class VADProcessor:

    MUSIC_ENERGY_EPSILON = 1e-8

    def __init__(self, vad_silence_threshold=0.85, vad_force_cut=True, vad_force_cut_sec=6.0,
                 min_speech_duration=0.08,
                 max_buffer_seconds=30):
        self.vad_silence_threshold = vad_silence_threshold
        self.vad_force_cut = vad_force_cut
        self.vad_force_cut_sec = vad_force_cut_sec
        self.min_speech_duration = min_speech_duration
        self.max_buffer_seconds = max_buffer_seconds

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
        - 说话快（间隙短）→ 阈值小（1秒），快速断句
        - 说话慢（间隙长）→ 阈值大（2-4秒），耐心等待不打断
        返回 (语音段, 剩余缓冲区, VAD信息字典)
        - 语音段: numpy array 或 None（无完整语音段）
        - 剩余缓冲区: numpy array 或 None（无需更新时为 None）
        - VAD信息字典
        """
        frame_len = int(sr * 0.03)
        hop_len = int(sr * 0.01)
        n_frames = (len(audio_data) - frame_len) // hop_len + 1

        vad_info = {'silence': 1.3, 'forced': False, 'overlap': 1.3, 'chunk_dur': 0}

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
        min_silence_frames = int(self.vad_silence_threshold / 0.01)
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

        min_speech_frames = max(1, int(self.min_speech_duration / 0.01))

        # === 找到完整语音段（末尾有足够静音）===
        if np.any(is_speech):
            last_speech_frame = np.where(is_speech)[0][-1]
            silence_after = n_frames - last_speech_frame
            first_speech_frame = np.where(is_speech)[0][0]
            speech_duration = (last_speech_frame - first_speech_frame + 1) * 0.01

            # 连续说话快速切分（提高静音阈值：0.5s→0.8s，减少误切）
            quick_cut_dur = 1.5
            quick_cut_silence = int(0.8 / 0.01)
            if self.vad_force_cut and speech_duration > quick_cut_dur and silence_after >= quick_cut_silence:
                cut_point = (last_speech_frame + 1) * hop_len
                speech_segment = audio_data[:cut_point]
                remaining = audio_data[cut_point:]
                self.speech_gaps = []
                self.adaptive_threshold = 1.35
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