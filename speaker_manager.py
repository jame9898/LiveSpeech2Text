# -*- coding: utf-8 -*-
"""
说话人管理器 — 声纹识别、说话人命名
封装 CAM++ 说话人分离相关的所有状态和方法
"""
import asyncio
import numpy as np
import soundfile as sf
import time
from pathlib import Path


def _pre_denoise_audio(audio_data, sr=16000):
    """音频预降噪：在 CAM++ 提取声纹 embedding 前进行基础降噪处理。
    使用高通滤波（去除低频环境噪声）+ 简易谱减法，提升混音场景下的说话人区分度。
    返回降噪后的音频数组（与输入相同长度和采样率）。
    """
    if len(audio_data) < sr * 0.1:  # 短于0.1s不处理
        return audio_data

    audio = np.asarray(audio_data, dtype=np.float32).copy()

    # 1. 高通滤波：去除 80Hz 以下低频噪声（空调、风扇、电流声等）
    try:
        from scipy import signal
        sos = signal.butter(4, 80, btype='highpass', fs=sr, output='sos')
        audio = signal.sosfiltfilt(sos, audio)
    except (ImportError, Exception):
        # scipy 不可用或无 signal 模块时，回退到简易时域高通
        alpha = 0.97
        audio_hp = np.zeros_like(audio)
        audio_hp[0] = audio[0]
        for i in range(1, len(audio)):
            audio_hp[i] = alpha * audio_hp[i - 1] + alpha * (audio[i] - audio[i - 1])
        audio = audio_hp

    # 2. 简易谱减法：估算噪声基底并衰减
    # 取前 200ms 作为噪声参考（假设开头是静音/噪声段）
    noise_samples = min(int(sr * 0.2), len(audio) // 4)
    if noise_samples > 0:
        noise_floor = np.mean(np.abs(audio[:noise_samples])) * 2.0
        # 软阈值：低于噪声基底的部分衰减而非硬截断
        mask = np.abs(audio) < noise_floor
        audio[mask] *= 0.3  # 衰减到 30%，保留微弱语音信号

    # 3. 归一化到 [-1, 1] 范围，避免削波
    peak = np.max(np.abs(audio))
    if peak > 1.0:
        audio = audio / peak

    return audio.astype(np.float32)




class SpeakerManager:
    """说话人管理器 — 封装声纹识别、说话人命名等所有说话人相关逻辑"""

    def __init__(self, sv_pipeline=None, executor=None,
                 dict_dir=None, temp_dir=None):
        self.sv_pipeline = sv_pipeline
        self.executor = executor

        # 保护 speaker_profiles / _pending_new / last_speaker_label 等共享状态
        self._lock = None

        self.speaker_profiles = []
        self.last_speaker_id = 0
        self._last_speaker_label = 'Speaker0'
        self._host_speaker_label = None
        self._speaker_display_names = {}

        self._dict_dir = dict_dir
        self._temp_dir = temp_dir

        self._pending_new = None
        self._quality_reported = False
        self._quick_recognized = False

        self._page_creator = None
        self._page_platform = None
        self._page_type = 'web'
        self._video_offset = 0

        self._session_active_speakers = set()

        self.total_audio_seconds = 0

    # ===== 公共属性（替代直接访问私有属性） =====

    @property
    def page_creator(self):
        return self._page_creator

    @property
    def page_platform(self):
        return self._page_platform

    @property
    def page_type(self):
        return self._page_type

    @property
    def video_offset(self):
        return self._video_offset

    @property
    def last_speaker_label(self):
        return self._last_speaker_label

    @last_speaker_label.setter
    def last_speaker_label(self, value):
        self._last_speaker_label = value

    @property
    def host_speaker_label(self):
        return self._host_speaker_label

    @property
    def session_active_speakers(self):
        return self._session_active_speakers

    # ===== 公共方法 =====

    def set_page_info(self, creator=None, platform=None, page_type=None, video_offset=None):
        """设置页面信息（创作者、平台、类型、视频偏移）"""
        if creator is not None:
            self._page_creator = creator
        if platform is not None:
            self._page_platform = platform
        if page_type is not None:
            self._page_type = page_type
        if video_offset is not None:
            self._video_offset = video_offset

    def add_active_speaker(self, name):
        """添加活跃说话人"""
        self._session_active_speakers.add(name)

    def rename_speaker(self, speaker_id, new_label):
        """重命名说话人"""
        self._speaker_display_names[speaker_id] = new_label
        for profile in self.speaker_profiles:
            if profile.get('label') == speaker_id:
                profile['alias'] = new_label
                break

    def reset_session(self):
        """重置会话状态（start 和 clear 共享）"""
        self.last_speaker_id = 0
        self._pending_new = None
        self._last_speaker_label = 'Speaker0'
        self._host_speaker_label = None
        self._session_active_speakers = set()
        self._quick_recognized = False
        self._quality_reported = False

    def reset_speaker_profiles(self):
        """清空所有说话人档案（clear 时调用）"""
        self.speaker_profiles = []

    # ===== 声纹识别 =====

    def _ensure_lock(self):
        """延迟初始化 asyncio.Lock，避免在不可运行事件循环的线程中创建"""
        if self._lock is None:
            try:
                asyncio.get_running_loop()
                self._lock = asyncio.Lock()
            except RuntimeError:
                pass
        return self._lock

    async def detect_speaker(self, audio_data):
        """
        说话人识别 — 使用 CAM++ 声纹嵌入 (达摩院 3D-Speaker)
        CAM++ 在 200k 中文说话人 + VoxCeleb 英文数据集联合训练
        输出 192 维归一化向量，余弦相似度区分力远超 resemblyzer
        同一个人：余弦相似度 ≈ 0.60–0.95
        不同人：  余弦相似度 ≈ 0.05–0.30

        v3.0 改进：精细化动态阈值 + 非线性软更新
        - 灰色地带(0.36-0.66)：非线性软更新声纹，相似度越高权重越大
        - 新人即时确认：首次检测即创建标签，无需累积确认
        - 短句降至0.5s也跑声纹
        - 统一标准阈值，实时区分不同说话人
        """
        MIN_DURATION = int(16000 * 0.5)
        if len(audio_data) < MIN_DURATION:
            audio_data = np.pad(audio_data, (0, MIN_DURATION - len(audio_data)))

        if self.sv_pipeline is None:
            if not self.speaker_profiles:
                self.speaker_profiles.append({
                    'embedding': np.zeros(192, dtype=np.float32),
                    'count': 1, 'label': 'Speaker0', 'quality': 0.0,
                })
            return 'Speaker0'

        timestamp = int(time.time() * 1000000)
        temp_path = self._temp_dir / f'sp_{timestamp}.wav'
        result = None
        try:
            # 音频预降噪：提升 CAM++ 在混音场景下的说话人区分度
            audio_denoised = _pre_denoise_audio(audio_data, sr=16000)
            sf.write(str(temp_path), audio_denoised.astype(np.float32), 16000)

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                self.executor,
                lambda: self.sv_pipeline([str(temp_path), str(temp_path)], output_emb=True))
        finally:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass

        try:
            if result is None:
                print(f"[SPEAKER] 声纹提取失败: result is None", flush=True)
                return self._last_speaker_label
            embedding = np.array(result['embs'][0])
        except (KeyError, IndexError, TypeError) as e:
            print(f"[SPEAKER] 声纹提取失败: {e}, result keys={list(result.keys()) if isinstance(result, dict) else type(result)}", flush=True)
            return self._last_speaker_label
        embedding = embedding / (np.linalg.norm(embedding) + 1e-8)

        lock = self._ensure_lock()
        if lock is None:
            return await self._detect_speaker_sync(embedding)
        async with lock:
            return await self._detect_speaker_sync(embedding)

    async def _detect_speaker_sync(self, embedding):
        """在锁保护下执行说话人识别（所有共享状态修改在此完成）"""
        if not self.speaker_profiles:
            self.speaker_profiles.append({
                'embedding': embedding.copy(),
                'count': 1,
                'label': 'Speaker0',
                'quality': 1.0,
            })
            self._host_speaker_label = 'Speaker0'  # 首个说话人自动设为主播
            self._last_speaker_label = 'Speaker0'
            print(f"[SPEAKER] 创建 Speaker0 (count=1) [HOST]", flush=True)
            return 'Speaker0'

        # ===== 统一标准阈值（实时区分，无宽限期） =====
        SAME_THRESHOLD = 0.66
        NEW_THRESHOLD = 0.36
        REQUIRED_CONFIRMATIONS = 1  # 即时确认，首次检测即分配新标签

        best_score = -1.0
        best_idx = -1

        for i, profile in enumerate(self.speaker_profiles):
            score = float(np.dot(profile['embedding'], embedding))
            if score > best_score:
                best_score = score
                best_idx = i

        if best_score >= SAME_THRESHOLD:
            self._reset_pending_speaker()
            profile = self.speaker_profiles[best_idx]
            profile['embedding'] = (profile['embedding'] * profile['count'] + embedding) / (profile['count'] + 1)
            profile['count'] += 1
            profile['quality'] = min(1.0, profile['count'] / 30.0)
            if profile['count'] % 20 == 0:
                print(f"[SPEAKER] {profile['label']} 声纹成熟度: {profile['count']}样本 (quality={profile['quality']:.2f})", flush=True)
            self._last_speaker_label = profile['label']
            self._check_voiceprint_quality()
            return profile['label']

        if best_score < NEW_THRESHOLD:
            if self._pending_new is None:
                self._pending_new = {'count': 1, 'embeddings': [embedding.copy()]}
                print(f"[SPEAKER] 候选新人(1/{REQUIRED_CONFIRMATIONS}) score={best_score:.3f}", flush=True)
            else:
                self._pending_new['count'] += 1
                self._pending_new['embeddings'].append(embedding.copy())
                if self._pending_new['count'] >= REQUIRED_CONFIRMATIONS:
                    emb_list = self._pending_new['embeddings']
                    avg_emb = np.mean(emb_list, axis=0)
                    avg_emb = avg_emb / (np.linalg.norm(avg_emb) + 1e-8)
                    self.last_speaker_id += 1
                    label = f'Speaker{self.last_speaker_id}'
                    self.speaker_profiles.append({
                        'embedding': avg_emb,
                        'count': len(emb_list),
                        'label': label,
                        'quality': 0.1,
                    })
                    self._pending_new = None
                    self._last_speaker_label = label
                    print(f"[SPEAKER] 新角色确认: {label} (来自{len(emb_list)}个样本均值)", flush=True)
                    return label
                else:
                    print(f"[SPEAKER] 候选新人({self._pending_new['count']}/{REQUIRED_CONFIRMATIONS}) score={best_score:.3f}", flush=True)
            return self.speaker_profiles[best_idx]['label']

        # 灰色地带 (NEW_THRESHOLD ~ SAME_THRESHOLD)：非线性软更新
        # 三段渐进：低相似度微量试探 → 中相似度线性爬升 → 高相似度加速收敛
        normalized = (best_score - NEW_THRESHOLD) / (SAME_THRESHOLD - NEW_THRESHOLD)
        if normalized < 0.30:
            weight = normalized * 0.20          # 试探性微量更新
        elif normalized < 0.65:
            weight = 0.06 + (normalized - 0.30) * 0.50  # 线性爬升
        else:
            weight = 0.235 + (normalized - 0.65) * 0.65  # 加速收敛
        profile = self.speaker_profiles[best_idx]
        total_weight = profile['count'] + weight
        profile['embedding'] = (profile['embedding'] * profile['count'] + embedding * weight) / total_weight
        profile['count'] += weight
        print(f"[SPEAKER] 灰色软更新 {profile['label']} score={best_score:.3f} weight={weight:.2f} count={profile['count']:.1f}", flush=True)
        self._reset_pending_speaker()
        self._last_speaker_label = profile['label']
        return profile['label']

    def _reset_pending_speaker(self):
        self._pending_new = None

    def _check_voiceprint_quality(self):
        """2分钟后输出快速识别报告，30分钟后输出完整质量评估"""
        # 2分钟快速识别：自动标记声纹质量达标的 speaker
        if self.total_audio_seconds >= 120 and not self._quick_recognized:
            self._quick_recognized = True
            self._auto_name_quality_speakers()
            print(f"\n{'='*50}", flush=True)
            print(f"[VOICEPRINT] 2分钟快速识别 (累计 {self.total_audio_seconds:.0f}s)", flush=True)
            print(f"{'='*50}", flush=True)
            for i, profile in enumerate(self.speaker_profiles):
                count = profile.get('count', 0)
                quality = profile.get('quality', 0)
                label = profile.get('label', f'Speaker{i}')
                name = self.resolve_speaker_name(profile, i)
                if quality >= 0.5:
                    print(f"  ✅ {label} → {name} | 样本:{count:.0f} quality:{quality:.2f} 已自动标记", flush=True)
                else:
                    print(f"  ⏳ {label} → {name} | 样本:{count:.0f} quality:{quality:.2f} 继续积累...", flush=True)
            print(f"{'='*50}\n", flush=True)

        # 30分钟完整评估
        if self.total_audio_seconds < 1800:
            return
        if self._quality_reported:
            return
        self._quality_reported = True
        print(f"\n{'='*50}", flush=True)
        print(f"[VOICEPRINT] 声纹质量评估 (累计 {self.total_audio_seconds:.0f}s)", flush=True)
        print(f"{'='*50}", flush=True)
        for i, profile in enumerate(self.speaker_profiles):
            count = profile.get('count', 0)
            quality = profile.get('quality', 0)
            label = profile.get('label', f'Speaker{i}')
            name = self.resolve_speaker_name(profile, i)
            avg_sim = self._compute_avg_similarity(profile)
            status = '✅' if quality >= 0.85 else '⚠️ 需更多训练'
            print(f"  {label} → {name} | 样本:{count:.0f} quality:{quality:.2f} avg_sim:{avg_sim:.3f} {status}", flush=True)
        print(f"{'='*50}\n", flush=True)

    def _auto_name_quality_speakers(self):
        """2分钟时自动为声纹质量达标的 speaker 命名。"""
        for i, profile in enumerate(self.speaker_profiles):
            label = profile.get('label', f'Speaker{i}')
            quality = profile.get('quality', 0)
            if quality < 0.5:
                continue
            if label in self._speaker_display_names:
                continue
            if profile.get('alias'):
                self._speaker_display_names[label] = profile['alias']

    def _compute_avg_similarity(self, profile):
        """计算某speaker与其他speaker的平均余弦相似度"""
        if len(self.speaker_profiles) < 2:
            return 1.0
        emb = profile['embedding']
        sims = []
        for other in self.speaker_profiles:
            if other is profile:
                continue
            sim = float(np.dot(emb, other['embedding']))
            sims.append(sim)
        return sum(sims) / len(sims) if sims else 1.0

    # ===== 说话人命名与显示 =====

    def get_speaker_display(self, label):
        """获取说话人的显示名称。
        优先级: 用户手动命名 > profile alias > 原始label"""
        if not label:
            return 'Speaker'
        if label in self._speaker_display_names:
            return self._speaker_display_names[label]
        for profile in self.speaker_profiles:
            if profile.get('label') == label and profile.get('alias'):
                return profile['alias']
        return label

    def resolve_speaker_name(self, profile, index):
        label = profile.get('label', f'Speaker{index}')
        if label in self._speaker_display_names:
            return self._speaker_display_names[label]
        alias = profile.get('alias')
        if alias:
            return alias
        return label

    def get_all_display_names(self):
        """返回所有说话人的 {label: display_name} 映射，供报告生成使用。
        遍历 speaker_profiles，以 get_speaker_display 为唯一解析入口。"""
        result = {}
        for profile in self.speaker_profiles:
            label = profile.get('label')
            if label:
                result[label] = self.get_speaker_display(label)
        return result
