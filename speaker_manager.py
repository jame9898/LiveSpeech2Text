# -*- coding: utf-8 -*-
"""
说话人管理器 — 声纹识别、说话人命名
封装 CAM++ 说话人分离相关的所有状态和方法
"""
import asyncio
import numpy as np
import soundfile as sf
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

    # 2. 简易谱减法：用 RMS 低能量段作为噪声参考，而非盲目取前 200ms
    # 避免说话人一开口就说话时，把语音当成噪声参考导致误衰减
    # 把音频分成 50ms 帧，取 RMS 最低的 20% 帧作为噪声参考
    frame_len = int(sr * 0.05)
    n_frames = len(audio) // frame_len
    if n_frames >= 4:
        frame_rms = []
        for i in range(n_frames):
            frame = audio[i * frame_len : (i + 1) * frame_len]
            frame_rms.append(np.sqrt(np.mean(frame ** 2) + 1e-12))
        frame_rms = np.array(frame_rms)
        noise_threshold = np.percentile(frame_rms, 20)
        noise_frames = frame_rms <= noise_threshold
        if np.any(noise_frames):
            noise_floor = np.mean(frame_rms[noise_frames]) * 3.0
        else:
            noise_floor = np.mean(frame_rms) * 0.5
    else:
        noise_floor = np.mean(np.abs(audio)) * 0.3
    if noise_floor > 0:
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
                 dict_dir=None, temp_dir=None, same_threshold=None,
                 speaker_workers=None):
        self.sv_pipeline = sv_pipeline
        self.executor = executor
        # 批量声纹提取并行度：None/1=逐批调用主 pipeline（原逻辑），>1=每 worker
        # 克隆独立 pipeline 实例并行推理（modelscope pipeline 有共享状态，
        # 同一实例不能并发调用；单实例多段批量调用本身也是逐段串行推理）
        self._speaker_workers = max(1, int(speaker_workers)) if speaker_workers else 1
        self._pipelines = None
        self._pipelines_lock = None

        self.speaker_profiles = []
        self.last_speaker_id = 0
        self._last_speaker_label = 'Speaker0'
        self._host_speaker_label = None
        self._speaker_display_names = {}

        self._dict_dir = dict_dir
        # temp_dir 为 None 时回退到项目 temp 目录（参照 core.py 的 TEMP_DIR 约定），
        # 避免系统 temp 目录在进程崩溃后残留堆积
        self._temp_dir = Path(temp_dir) if temp_dir else Path(__file__).parent / "temp"
        self._temp_dir.mkdir(exist_ok=True)

        self._pending_new = None
        self._quality_reported = False
        self._quick_recognized = False

        self._page_creator = None
        self._page_platform = None
        self._page_type = 'web'
        self._video_offset = 0

        self._session_active_speakers = set()

        self.total_audio_seconds = 0

        # 说话人严格度阈值：None=默认 0.55，由 server.py 传入
        # 宽松=0.50（相似音色合并），标准=0.55，严格=0.62（区分度高）
        self.same_threshold = same_threshold if same_threshold is not None else 0.55

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

    async def extract_embeddings(self, audio_list, batch_size=16, should_stop=None,
                                 workers=None, progress_cb=None):
        """批量提取声纹 embedding（本地处理用，CPU 上提速关键）。

        每段降噪 + 写临时 wav。workers<=1 时按 batch_size 分组批量推理
        （每 batch 一次 pipeline 调用，避免逐段调用开销）；
        workers>1 时改为并行逐段推理（每个 worker 独立 pipeline 实例，
        单段 [p, p] 双拷贝调用，与实时模式 detect_speaker 一致）。

        参数:
            audio_list: numpy float32 16k 音频列表（可含 None，表示跳过）
            batch_size: 每批段数（默认 16，仅串行模式使用）
            should_stop: 可选取消回调 fn() -> bool，批间检查
            workers: 并行 worker 数，None 时用构造传入的 speaker_workers
            progress_cb: 可选进度回调 fn(done, total)，阶段内完成比例

        返回: 与 audio_list 等长的 embedding 列表（失败段为 None）。
        """
        if self.sv_pipeline is None:
            return [None] * len(audio_list)

        if workers is None:
            workers = self._speaker_workers
        workers = max(1, int(workers))
        if workers <= 1:
            return await self._extract_embeddings_batch(
                audio_list, batch_size, should_stop, progress_cb)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.executor, self._extract_embeddings_parallel,
            audio_list, workers, should_stop, progress_cb)

    def _get_parallel_pipelines(self, workers):
        """返回至少 workers 个可并行调用的 pipeline 实例（懒克隆，主线程安全）。"""
        if self._pipelines is None:
            import threading
            self._pipelines_lock = threading.Lock()
            self._pipelines = [self.sv_pipeline]
        if len(self._pipelines) >= workers:
            return self._pipelines
        with self._pipelines_lock:
            while len(self._pipelines) < workers:
                try:
                    from modelscope.pipelines import pipeline
                    from modelscope.utils.constant import Tasks
                    base = self._pipelines[0]
                    model_dir = getattr(getattr(base, 'model', None), 'model_dir', None)
                    if not model_dir:
                        break
                    self._pipelines.append(
                        pipeline(task=Tasks.speaker_verification, model=model_dir))
                except Exception as e:
                    print(f"[SPEAKER] 声纹 pipeline 克隆失败: {e}", flush=True)
                    break
        return self._pipelines

    def _extract_embeddings_parallel(self, audio_list, workers, should_stop, progress_cb=None):
        """并行逐段声纹推理（同步函数，跑在事件循环外）。

        每个 worker 独立 pipeline 实例 + 单段 [p, p] 双拷贝调用，
        规避 modelscope pipeline 多段批量调用在同一实例上的时序不稳定问题。
        """
        import uuid as _uuid
        import concurrent.futures

        MIN_DURATION = int(16000 * 0.5)
        embeddings = [None] * len(audio_list)
        pipes = self._get_parallel_pipelines(workers)
        if not pipes:
            return embeddings

        def _infer_one(idx_audio):
            i, a = idx_audio
            if a is None:
                return i, None
            pipe = pipes[i % len(pipes)]
            temp_path = self._temp_dir / f'sp_{_uuid.uuid4().hex}.wav'
            try:
                if len(a) < MIN_DURATION:
                    a = np.pad(a, (0, MIN_DURATION - len(a)))
                audio_denoised = _pre_denoise_audio(a, sr=16000)
                sf.write(str(temp_path), audio_denoised.astype(np.float32), 16000)
            except Exception as e:
                print(f"[SPEAKER] 音频写入失败: {e}", flush=True)
                return i, None
            try:
                result = pipe([str(temp_path), str(temp_path)], output_emb=True)
                embs = result.get('embs')
                if embs is None:
                    return i, None
                emb = np.array(embs[0], dtype=np.float32)
                norm = float(np.linalg.norm(emb))
                return i, emb / (norm + 1e-8)
            except Exception as e:
                print(f"[SPEAKER] 单段声纹推理失败: {e}", flush=True)
                return i, None
            finally:
                try:
                    if temp_path.exists():
                        temp_path.unlink()
                except OSError:
                    pass

        import torch as _torch
        _total_threads = _torch.get_num_threads()
        try:
            # torch 线程数按 worker 均分，避免并行推理互相争抢全部核心
            if _total_threads > workers:
                _torch.set_num_threads(max(1, _total_threads // workers))
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [ex.submit(_infer_one, (i, a)) for i, a in enumerate(audio_list)]
                _done = 0
                for fut in futures:
                    if should_stop is not None and should_stop():
                        ex.shutdown(wait=False, cancel_futures=True)
                        break
                    try:
                        i, emb = fut.result()
                        if emb is not None:
                            embeddings[i] = emb
                    except Exception:
                        pass
                    _done += 1
                    if progress_cb is not None and _done % max(1, len(futures) // 20) == 0:
                        try:
                            progress_cb(_done, len(futures))
                        except Exception:
                            pass
                if progress_cb is not None:
                    try:
                        progress_cb(_done, len(futures))
                    except Exception:
                        pass
        finally:
            try:
                _torch.set_num_threads(_total_threads)
            except Exception:
                pass
        return embeddings

    async def _extract_embeddings_batch(self, audio_list, batch_size=16, should_stop=None,
                                        progress_cb=None):
        import uuid as _uuid
        MIN_DURATION = int(16000 * 0.5)
        embeddings = [None] * len(audio_list)
        _total_batches = max(1, -(-len(audio_list) // batch_size))

        def _infer_batch(batch_audios):
            paths = []
            valid_idx = []
            for i, a in enumerate(batch_audios):
                if a is None:
                    continue
                if len(a) < MIN_DURATION:
                    a = np.pad(a, (0, MIN_DURATION - len(a)))
                p = self._temp_dir / f'sp_{_uuid.uuid4().hex}.wav'
                try:
                    audio_denoised = _pre_denoise_audio(a, sr=16000)
                    sf.write(str(p), audio_denoised.astype(np.float32), 16000)
                    paths.append(p)
                    valid_idx.append(i)
                except Exception as e:
                    print(f"[SPEAKER] 音频写入失败: {e}", flush=True)
            out = [None] * len(batch_audios)
            if not paths:
                return out
            try:
                result = self.sv_pipeline([str(p) for p in paths], output_emb=True)
                embs = result.get('embs')
                if embs is None:
                    embs = []
                for k, i in enumerate(valid_idx):
                    if k < len(embs) and embs[k] is not None:
                        emb = np.array(embs[k])
                        out[i] = emb / (np.linalg.norm(emb) + 1e-8)
            except Exception as e:
                import traceback as _tb
                print(f"[SPEAKER] 批量声纹推理失败: {e}", flush=True)
                _tb.print_exc()
            finally:
                for p in paths:
                    try:
                        if p.exists():
                            p.unlink()
                    except OSError:
                        pass
            return out

        import asyncio
        loop = asyncio.get_running_loop()
        _batch_no = 0
        for start in range(0, len(audio_list), batch_size):
            if should_stop is not None and should_stop():
                break
            chunk = audio_list[start:start + batch_size]
            chunk_embs = await loop.run_in_executor(self.executor, _infer_batch, chunk)
            embeddings[start:start + batch_size] = chunk_embs
            _batch_no += 1
            if progress_cb is not None:
                try:
                    progress_cb(min(_batch_no * batch_size, len(audio_list)), len(audio_list))
                except Exception:
                    pass
        return embeddings

    async def detect_speaker(self, audio_data):
        """
        说话人识别 — 使用 CAM++ 声纹嵌入 (达摩院 3D-Speaker)
        CAM++ 在 200k 中文说话人 + VoxCeleb 英文数据集联合训练
        输出 192 维归一化向量，余弦相似度区分力远超 resemblyzer
        同一个人：余弦相似度 ≈ 0.60–0.95
        不同人：  余弦相似度 ≈ 0.05–0.30

        v3.0 改进：精细化动态阈值 + 非线性软更新
        - 灰色地带(0.30-0.60)：非线性软更新声纹，相似度越高权重越大
        - 新人即时确认：首次检测即创建标签，无需累积确认
        - 短句降至0.5s也跑声纹
        - 统一标准阈值，实时区分不同说话人
        """
        import asyncio

        # 过短音频（<0.3s）直接继承上次说话人，不提取声纹
        # 避免 pad 静音后产生噪声 embedding 污染声纹库
        MIN_VALID_DURATION = int(16000 * 0.3)
        if len(audio_data) < MIN_VALID_DURATION:
            return self._last_speaker_label

        MIN_DURATION = int(16000 * 0.5)
        if len(audio_data) < MIN_DURATION:
            audio_data = np.pad(audio_data, (0, MIN_DURATION - len(audio_data)))

        if self.sv_pipeline is None:
            if not self.speaker_profiles:
                self.speaker_profiles.append({
                    'embedding': np.zeros(192, dtype=np.float32),
                    'count': 1, 'label': 'Speaker0', 'quality': 0.0,
                })
                self._host_speaker_label = 'Speaker0'
                print(f"[SPEAKER] [WARN] sv_pipeline is None — 说话人模型未加载，所有段标记为 Speaker0", flush=True)
            return 'Speaker0'

        import uuid as _uuid
        temp_path = self._temp_dir / f'sp_{_uuid.uuid4().hex}.wav'
        result = None

        def _denoise_write_and_infer():
            # 降噪 + 写盘 + 声纹推理全部放到工作线程执行，
            # 避免 _pre_denoise_audio（scipy 缺失时纯 Python 逐样本滤波）和
            # sf.write 在协程里同步执行阻塞事件循环
            audio_denoised = _pre_denoise_audio(audio_data, sr=16000)
            sf.write(str(temp_path), audio_denoised.astype(np.float32), 16000)
            return self.sv_pipeline([str(temp_path), str(temp_path)], output_emb=True)

        try:
            loop = asyncio.get_running_loop()
            try:
                result = await loop.run_in_executor(self.executor, _denoise_write_and_infer)
            except Exception as e:
                # 磁盘满/权限问题等导致写入失败，或声纹推理异常，不能让整个 detect_speaker 崩溃
                print(f"[SPEAKER] 音频写入或声纹提取失败: {e}", flush=True)
                return self._last_speaker_label
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

        return self._classify_embedding(embedding)

    def _classify_embedding(self, embedding):
        """把已提取的声纹 embedding 判定为说话人（顺序更新声纹库）。
        实时模式（detect_speaker）与本地批量模式共用；纯 numpy 计算，耗时可忽略。"""
        if not self.speaker_profiles:
            self.speaker_profiles.append({
                'embedding': embedding.copy(),
                'count': 1,
                'label': 'Speaker0',
                'quality': 1.0,
            })
            self._host_speaker_label = 'Speaker0'  # 首个说话人自动设为主播
            print(f"[SPEAKER] 创建 Speaker0 (count=1) [HOST]", flush=True)
            return 'Speaker0'

        # ===== 统一标准阈值（实时区分，无宽限期） =====
        # SAME_THRESHOLD 由构造函数传入（宽松/标准/严格），默认 0.55
        SAME_THRESHOLD = self.same_threshold
        NEW_THRESHOLD = 0.36  # 不同人最高 0.30，0.36 以上为灰色地带
        REQUIRED_CONFIRMATIONS = 2  # 需连续 2 次低于 NEW_THRESHOLD 才创建新说话人（防单次噪声误判）
        MAX_PROFILES = 20  # 说话人档案数量上限，防止异常情况下 profiles 只增不减

        best_score = -1.0
        best_idx = -1

        for i, profile in enumerate(self.speaker_profiles):
            score = float(np.dot(profile['embedding'], embedding))
            if score > best_score:
                best_score = score
                best_idx = i

        # 调试日志：打印每段的 best_score，便于排查说话人识别问题
        # 阈值参考：SAME_THRESHOLD={same}, NEW_THRESHOLD=0.36
        _matched_label = self.speaker_profiles[best_idx]['label'] if best_idx >= 0 else '?'
        print(f"[SPEAKER] score={best_score:.3f} → {_matched_label} (profiles={len(self.speaker_profiles)}, threshold={SAME_THRESHOLD})", flush=True)

        if best_score >= SAME_THRESHOLD:
            self._reset_pending_speaker()
            profile = self.speaker_profiles[best_idx]
            profile['embedding'] = (profile['embedding'] * profile['count'] + embedding) / (profile['count'] + 1)
            # 重新归一化：单位向量的加权平均不再是单位向量，必须重新归一化才能作为余弦相似度的输入
            profile['embedding'] = profile['embedding'] / (np.linalg.norm(profile['embedding']) + 1e-8)
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
            elif float(np.dot(self._pending_new['embeddings'][0], embedding)) < SAME_THRESHOLD:
                # 与首个 pending 样本差异过大 → 不是同一个候选人，
                # 重置 pending，避免不同人的 embedding 被平均成混合声纹的伪说话人
                self._pending_new = {'count': 1, 'embeddings': [embedding.copy()]}
                print(f"[SPEAKER] 候选样本与已有候选差异过大，重置候选(1/{REQUIRED_CONFIRMATIONS}) score={best_score:.3f}", flush=True)
            else:
                self._pending_new['count'] += 1
                self._pending_new['embeddings'].append(embedding.copy())
                print(f"[SPEAKER] 候选新人({self._pending_new['count']}/{REQUIRED_CONFIRMATIONS}) score={best_score:.3f}", flush=True)

            # 检查是否达到确认阈值（首次创建后也检查，REQUIRED_CONFIRMATIONS=1 时首次即分配）
            if self._pending_new['count'] >= REQUIRED_CONFIRMATIONS:
                if len(self.speaker_profiles) >= MAX_PROFILES:
                    # 达到档案数量上限，不再创建新说话人，归入最近匹配
                    self._pending_new = None
                    print(f"[SPEAKER] 说话人数量已达上限({MAX_PROFILES})，归入 {_matched_label}", flush=True)
                    return self.speaker_profiles[best_idx]['label']
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
            return self.speaker_profiles[best_idx]['label']

        # 灰色地带 (NEW_THRESHOLD ~ SAME_THRESHOLD)：走新人判定逻辑
        # 不再软更新到现有 profile，避免声纹被稀释成"所有人平均"导致后续无法区分
        # （滚雪球效应：软更新让 Speaker0 越来越像通用向量，后续任何人都被归为 Speaker0）
        if self._pending_new is None:
            self._pending_new = {'count': 1, 'embeddings': [embedding.copy()]}
            print(f"[SPEAKER] 候选新人(1/{REQUIRED_CONFIRMATIONS}) score={best_score:.3f} [灰色地带]", flush=True)
        elif float(np.dot(self._pending_new['embeddings'][0], embedding)) < SAME_THRESHOLD:
            # 与首个 pending 样本差异过大 → 不是同一个候选人，
            # 重置 pending，避免不同人的 embedding 被平均成混合声纹的伪说话人
            self._pending_new = {'count': 1, 'embeddings': [embedding.copy()]}
            print(f"[SPEAKER] 候选样本与已有候选差异过大，重置候选(1/{REQUIRED_CONFIRMATIONS}) score={best_score:.3f} [灰色地带]", flush=True)
        else:
            self._pending_new['count'] += 1
            self._pending_new['embeddings'].append(embedding.copy())
            print(f"[SPEAKER] 候选新人({self._pending_new['count']}/{REQUIRED_CONFIRMATIONS}) score={best_score:.3f} [灰色地带]", flush=True)

        if self._pending_new['count'] >= REQUIRED_CONFIRMATIONS:
            if len(self.speaker_profiles) >= MAX_PROFILES:
                # 达到档案数量上限，不再创建新说话人，归入最近匹配
                self._pending_new = None
                print(f"[SPEAKER] 说话人数量已达上限({MAX_PROFILES})，归入 {_matched_label} [灰色地带]", flush=True)
                return self.speaker_profiles[best_idx]['label']
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
            print(f"[SPEAKER] 新角色确认: {label} (来自{len(emb_list)}个样本均值) [灰色地带]", flush=True)
            return label
        return self.speaker_profiles[best_idx]['label']

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
