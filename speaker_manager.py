# -*- coding: utf-8 -*-
"""
说话人管理器 — 声纹识别、说话人命名
封装 CAM++ 说话人分离相关的所有状态和方法
"""
import numpy as np
import soundfile as sf
import time
from pathlib import Path




class SpeakerManager:
    """说话人管理器 — 封装声纹识别、说话人命名等所有说话人相关逻辑"""

    def __init__(self, sv_pipeline=None, executor=None,
                 dict_dir=None, temp_dir=None):
        self.sv_pipeline = sv_pipeline
        self.executor = executor

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

    # ===== 声纹识别 =====

    async def detect_speaker(self, audio_data):
        """
        说话人识别 — 使用 CAM++ 声纹嵌入 (达摩院 3D-Speaker)
        CAM++ 在 200k 中文说话人 + VoxCeleb 英文数据集联合训练
        输出 192 维归一化向量，余弦相似度区分力远超 resemblyzer
        同一个人：余弦相似度 ≈ 0.60–0.95
        不同人：  余弦相似度 ≈ 0.05–0.30

        v2.9 改进：越用越灵敏
        - 灰色地带(0.30-0.60)：软更新声纹，不再浪费数据
        - 新人冷启动：3次确认 + 保存所有原始embedding，确认后取均值
        - 短句降至0.5s也跑声纹
        """
        import asyncio

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
        try:
            sf.write(str(temp_path), audio_data.astype(np.float32), 16000)

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                self.executor,
                lambda: self.sv_pipeline([str(temp_path), str(temp_path)], output_emb=True))
        finally:
            if temp_path.exists():
                temp_path.unlink()

        embedding = np.array(result['embs'][0])
        embedding = embedding / (np.linalg.norm(embedding) + 1e-8)

        if not self.speaker_profiles:
            self.speaker_profiles.append({
                'embedding': embedding.copy(),
                'count': 1,
                'label': 'Speaker0',
                'quality': 1.0,
            })
            print(f"[SPEAKER] 创建 Speaker0 (count=1)", flush=True)
            return 'Speaker0'

        SAME_THRESHOLD = 0.60
        NEW_THRESHOLD = 0.30
        training_minutes = self.total_audio_seconds / 60.0
        if training_minutes < 5.0:
            SAME_THRESHOLD = 0.50
            NEW_THRESHOLD = 0.20
        elif training_minutes < 30.0:
            ratio = (training_minutes - 5.0) / 25.0
            SAME_THRESHOLD = 0.50 + ratio * 0.10
            NEW_THRESHOLD = 0.20 + ratio * 0.10
        REQUIRED_CONFIRMATIONS = 3

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
                    print(f"[SPEAKER] 新角色确认: {label} (来自{len(emb_list)}个样本均值)", flush=True)
                    return label
                else:
                    print(f"[SPEAKER] 候选新人({self._pending_new['count']}/{REQUIRED_CONFIRMATIONS}) score={best_score:.3f}", flush=True)
            return self.speaker_profiles[best_idx]['label']

        # 灰色地带 (0.30 ~ 0.60)：软更新，不浪费数据
        # 相似度越高，更新权重越大
        weight = (best_score - NEW_THRESHOLD) / (SAME_THRESHOLD - NEW_THRESHOLD)
        weight = weight * 0.5  # 最大0.5的权重，防止污染
        profile = self.speaker_profiles[best_idx]
        total_weight = profile['count'] + weight
        profile['embedding'] = (profile['embedding'] * profile['count'] + embedding * weight) / total_weight
        profile['count'] += weight
        print(f"[SPEAKER] 灰色软更新 {profile['label']} score={best_score:.3f} weight={weight:.2f} count={profile['count']:.1f}", flush=True)
        self._reset_pending_speaker()
        return profile['label']

    def _reset_pending_speaker(self):
        self._pending_new = None

    def _check_voiceprint_quality(self):
        """5分钟后输出快速识别报告，30分钟后输出完整质量评估"""
        # 5分钟快速识别：自动标记声纹质量达标的 speaker
        if self.total_audio_seconds >= 300 and not self._quick_recognized:
            self._quick_recognized = True
            self._auto_name_quality_speakers()
            print(f"\n{'='*50}", flush=True)
            print(f"[VOICEPRINT] 5分钟快速识别 (累计 {self.total_audio_seconds:.0f}s)", flush=True)
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
        """5分钟时自动为声纹质量达标的 speaker 命名。"""
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