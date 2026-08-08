# -*- coding: utf-8 -*-
"""
后训练数据集存储管理器

目录结构（三级：模式/日期/来源名称）：
  BackTrain/
    audience/                           # 模式：audience(观众) / streamer(主播) / meeting(会议) / local(本地)
      YYYYMMDD/
        YYYYMMDDHHMM/                   # 来源名称=处理开始时间(录音/处理启动时刻)
          full_YYYYMMDDHHMM.flac        # 完整连续录音（整场会话）
          full_YYYYMMDDHHMM.json        # 完整录音元数据 + 分段索引
          seg_YYYYMMDD_HHMMSS_xxxxxx.flac   # 音频片段（分段）
          seg_YYYYMMDD_HHMMSS_xxxxxx.json   # 同名文字标注（音频+文字一一对应）
    streamer/
      YYYYMMDD/
        202607111230/                  # 录音开始时间
          seg_...flac
          seg_...json
    meeting/
      YYYYMMDD/
        202607111430/                  # 会议开始时间
          seg_...flac
          seg_...json
    local/
      YYYYMMDD/
        202607111500/                  # 处理开始时间（与其他模式统一）
          seg_...flac
          seg_...json
    manifest.json                        # 所有片段的元数据清单（含 mode 字段）
    manifest.example.json                # 模板（不入库内容）

说明：
  - 第三级目录用"来源名称"而非"说话人"，因为 CAM++ 可能把单人音频误判为多人，
    用音频名称/会话标识更稳定，也便于按音频文件归集训练样本。
  - 说话人标签仍记录在每条 JSON 标注的 speaker 字段里，供后期筛选使用。

manifest.json 结构：
  {
    "_说明": "...",
    "_评分维度": {...},
    "segments": [
      {
        "id": "seg_20250711_143022_123456",
        "mode": "streamer",            # audience / streamer / meeting / local
        "source_name": "session_111555",  # 来源名称（第三级目录名）
        "audio_path": "streamer/20250711/session_111555/seg_...flac",
        "corrected_path": "streamer/20250711/session_111555/seg_...json",
        "raw_text": "模型原始识别",
        "corrected_text": null,
        "speaker": "Speaker_0",        # 说话人标签（仅记录，不作为目录）
        "duration": 3.21,
        "seg_audio_time": 12.34,
        "timestamp": "2025-07-11T14:30:22",
        "quality": { "snr": 0.8, "rms": 0.15, "clipping": 0.0,
                     "spectral_flatness": 0.2, "overall": 0.85 },
        "status": "pending",            # pending / corrected / rejected
        "vad": {...}
      }
    ]
  }

设计原则：
  - 线程安全：manifest 读写加锁，可在 ThreadPoolExecutor 中调用。
  - 失败容错：单段存储失败不影响转录流程，仅打印告警。
  - 筛选：低于质量阈值的片段不落盘（可配置）。
  - 预留接口：update_correction(id, text) 供后期人工修正工具调用。
  - 模式隔离：不同模式（本地/主播/会议）的音频分目录存放，便于按场景训练。
"""

import json
import shutil
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np

from audio_quality import score_audio, is_high_quality


# 合法模式名（防止路径注入）
_VALID_MODES = {"local", "streamer", "meeting", "audience"}


class DatasetManager:
    """后训练数据集存储管理器（单例，线程安全）"""

    def __init__(self, base_dir=None, quality_threshold=0.0, auto_filter=True):
        """
        参数:
            base_dir:           dataset 目录根路径。None 时用项目根/dataset。
            quality_threshold:  综合评分阈值，低于此值的片段不落盘。0.0=不过滤。
            auto_filter:        True 时启用 is_high_quality() 多维度过滤（削波/平坦度等）。
        """
        if base_dir is None:
            base_dir = Path(__file__).parent / "BackTrain"
        self.base_dir = Path(base_dir)
        self.manifest_path = self.base_dir / "manifest.json"

        self.quality_threshold = float(quality_threshold)
        self.auto_filter = bool(auto_filter)

        self._lock = threading.Lock()
        self._manifest = None
        self._enabled = False

        # 会话管理：完整连续录音
        # _session_lock 用 RLock：start_session 内部会调用 end_session，需要可重入
        self._session_lock = threading.RLock()
        self._session_active = False
        self._session_audio = []          # list of numpy arrays
        self._session_audio_samples = 0   # 累积样本数（用于触发周期性合并，控制内存）
        self._session_sr = 16000
        self._session_mode = None
        self._session_source = None
        self._session_start = None
        self._session_segments = []       # 分段索引
        # 每 5 分钟音频合并一次 list，减少 list 项数和 end_session 时 concatenate 峰值
        # 5min * 16000 = 4,800,000 samples
        self._session_merge_threshold = 5 * 60 * self._session_sr
        # 会话内存上限：超过 30 分钟（16kHz float32 ≈ 115MB）时把已累积音频
        # 分片落盘为临时文件，end_session 时合并，避免长会话全量驻留内存导致 OOM
        self._session_max_samples = 30 * 60 * self._session_sr
        self._session_spill_files = []    # 临时分片文件路径（由 _disk_executor 单线程维护）
        # 专用单线程落盘 executor：会话录音的拼接/FLAC 编码/写盘在后台执行，
        # 避免 end_session 在 WebSocket async handler 中同步调用时冻结事件循环。
        # 独立于 ASR 线程池，互不拖慢；单线程保证分片写入与会话合并的先后顺序
        self._disk_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dataset-io")
        # manifest 延迟批量写：每 N 段才全量落盘一次，避免每段 O(n) 重写累积成 O(n^2)
        self._manifest_dirty_count = 0
        self._manifest_flush_threshold = 10

        # 目录在 enable() 时创建，避免未启用时产生空目录

    # ------------------------------------------------------------------
    # 启用 / 禁用
    # ------------------------------------------------------------------
    def enable(self):
        """启用数据集收集：创建目录、加载/初始化 manifest。"""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        # 清理上次异常退出遗留的会话音频临时分片
        tmp_dir = self.base_dir / "_session_tmp"
        if tmp_dir.exists():
            for p in tmp_dir.glob("spill_*.npy"):
                try:
                    p.unlink()
                except Exception:
                    pass
        self._load_manifest()
        self._enabled = True
        print(f"[DATASET] 已启用后训练数据集收集: {self.base_dir}", flush=True)

    def disable(self):
        """禁用数据集收集。已落盘的数据保留。"""
        self._enabled = False
        print("[DATASET] 已禁用后训练数据集收集", flush=True)

    @property
    def enabled(self):
        return self._enabled

    def configure(self, quality_threshold=None, auto_filter=None):
        """运行时更新配置（不重启）。"""
        if quality_threshold is not None:
            self.quality_threshold = float(quality_threshold)
        if auto_filter is not None:
            self.auto_filter = bool(auto_filter)

    # ------------------------------------------------------------------
    # Manifest 管理
    # ------------------------------------------------------------------
    def _load_manifest(self):
        """加载或初始化 manifest。"""
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    self._manifest = json.load(f)
                if "segments" not in self._manifest:
                    self._manifest["segments"] = []
            except Exception as e:
                print(f"[DATASET] manifest 损坏，重建: {e}", flush=True)
                self._init_manifest()
        else:
            self._init_manifest()

    def _init_manifest(self):
        """初始化空 manifest。"""
        self._manifest = {
            "_说明": "后训练数据集清单。每条记录对应一个音频片段及其标注。"
                     "corrected_text 为人工修正后的文本，raw_text 为模型原始识别。"
                     "quality 由系统自动评分（0.0~1.0）。"
                     "status: pending=待修正, corrected=已修正, rejected=已弃用。",
            "_评分维度": {
                "snr": "信噪比估计（纯净度，越高越干净）",
                "rms": "音量电平（0.0~1.0）",
                "clipping": "削波比例（0.0~1.0）",
                "spectral_flatness": "频谱平坦度（越低=语音特征越明显）",
                "overall": "综合评分（0.0~1.0）",
            },
            "segments": [],
        }
        self._save_manifest()

    def _save_manifest(self):
        """保存 manifest（调用方需持有 _lock）。

        失败时输出明确告警：manifest 落盘失败意味着已写入的音频/标注文件
        未登记到清单，成为孤儿文件，清单与实际数据不一致，需要人工关注。
        """
        try:
            tmp = self.manifest_path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._manifest, f, ensure_ascii=False, indent=2)
            tmp.replace(self.manifest_path)
        except Exception as e:
            print(f"[DATASET][ERROR] manifest 保存失败: {e} —— "
                  f"清单可能与实际文件不一致（出现未登记的孤儿文件），请检查磁盘/权限",
                  flush=True)
            import traceback
            traceback.print_exc()

    # ------------------------------------------------------------------
    # 片段存储
    # ------------------------------------------------------------------
    def save_segment(self, audio_data, text, raw_text=None, speaker_label=None,
                     vad_info=None, seg_audio_time=None, seg_duration=None,
                     sr=16000, extra=None, mode="streamer", source_name=None):
        """存储一个语音片段及其标注。

        参数:
            audio_data:      numpy array (mono float32, 16kHz)
            text:            最终识别文本（经过后处理）
            raw_text:        模型原始识别文本（未经纠正），None 时用 text
            speaker_label:   说话人标签（仅记录到 JSON，不作为目录）
            vad_info:        VAD 信息 dict
            seg_audio_time:  该段在会话中的起始时间（秒）
            seg_duration:    该段时长（秒）
            sr:              采样率
            extra:           额外元数据（如 kw_corrections）
            mode:            数据来源模式 "local" / "streamer" / "meeting" / "audience"
            source_name:     来源名称，作为第三级目录名。
                             - 本地模式：音频文件名（去扩展名）
                             - 实时模式：会话标识（如 session_HHMMSS）
                             None 时用 "session"。

        返回:
            segment_id (str) 若成功落盘；None 若被过滤或失败。
        """
        if not self._enabled:
            return None

        # 模式名校验（防路径注入）
        if mode not in _VALID_MODES:
            mode = "streamer"

        try:
            arr = np.asarray(audio_data, dtype=np.float32)
            if arr.ndim > 1:
                arr = np.mean(arr, axis=1).astype(np.float32)
            if len(arr) == 0:
                return None

            # 质量评分
            scores = score_audio(arr, sr)

            # 质量过滤
            if self.auto_filter and not is_high_quality(scores, threshold=self.quality_threshold):
                return None
            if not self.auto_filter and scores.get("overall", 0.0) < self.quality_threshold:
                return None

            # 生成 ID 和路径
            now = datetime.now()
            date_str = now.strftime("%Y%m%d")
            time_str = now.strftime("%Y%m%d_%H%M%S")
            unique = uuid.uuid4().hex[:6]
            seg_id = f"seg_{time_str}_{unique}"

            # 第三级目录：来源名称（本地模式=音频文件名，实时模式=会话标识）
            # 说话人标签仅记录在 JSON 标注里，不作为目录（避免单人被误判为多人导致目录碎片）
            if not source_name:
                source_name = "session"
            # 清理来源名称中的非法路径字符
            source_dir_name = "".join(c for c in str(source_name) if c not in '<>:"/\\|?*').strip() or "session"

            # 三级目录：[mode]/YYYYMMDD/[source_name]/seg_xxx.flac + seg_xxx.json
            # 音频和文字标注存在同一目录下，一一对应
            seg_subdir = self.base_dir / mode / date_str / source_dir_name
            seg_subdir.mkdir(parents=True, exist_ok=True)
            audio_file = seg_subdir / f"{seg_id}.flac"
            json_file = seg_subdir / f"{seg_id}.json"
            audio_rel = f"{mode}/{date_str}/{source_dir_name}/{seg_id}.flac"
            json_rel = f"{mode}/{date_str}/{source_dir_name}/{seg_id}.json"

            # 写入音频（FLAC 无损压缩，体积约为 WAV 的 50%）
            self._write_flac(audio_file, arr, sr)

            # 写入同目录 JSON 标注（初始 corrected_text=null，待人工修正）
            corrected_data = {
                "id": seg_id,
                "mode": mode,
                "source_name": source_dir_name,
                "audio_path": audio_rel,
                "raw_text": raw_text if raw_text is not None else text,
                "corrected_text": None,
                "speaker": speaker_label,
                "duration": float(seg_duration) if seg_duration else len(arr) / sr,
                "timestamp": now.isoformat(),
                "status": "pending",
            }
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(corrected_data, f, ensure_ascii=False, indent=2)

            # 更新 manifest
            entry = {
                "id": seg_id,
                "mode": mode,
                "source_name": source_dir_name,
                "audio_path": audio_rel,
                "corrected_path": json_rel,
                "raw_text": raw_text if raw_text is not None else text,
                "corrected_text": None,
                "text": text,
                "speaker": speaker_label,
                "duration": float(seg_duration) if seg_duration else len(arr) / sr,
                "seg_audio_time": float(seg_audio_time) if seg_audio_time is not None else 0.0,
                "timestamp": now.isoformat(),
                "quality": scores,
                "status": "pending",
                "vad": vad_info or {},
            }
            if extra:
                entry["extra"] = extra

            with self._lock:
                self._manifest["segments"].append(entry)
                self._manifest_dirty_count += 1
                # 延迟批量写：攒够阈值才全量落盘，避免每段 O(n) 重写累积成 O(n^2)；
                # 会话结束（end_session 后台任务）时也会强制刷盘兜底
                if self._manifest_dirty_count >= self._manifest_flush_threshold:
                    self._save_manifest()
                    self._manifest_dirty_count = 0

            # 注册分段到当前会话（供完整录音索引使用）
            # 用 _session_lock 保护，避免与 end_session 的遍历/清空竞态
            with self._session_lock:
                if self._session_active:
                    self._session_segments.append({
                        "seg_id": seg_id,
                        "start_time": float(seg_audio_time) if seg_audio_time is not None else 0.0,
                        "duration": float(seg_duration) if seg_duration else len(arr) / sr,
                        "text": text,
                        "speaker": speaker_label,
                        "audio_file": audio_rel,
                    })

            return seg_id

        except Exception as e:
            print(f"[DATASET] 存储片段失败: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return None

    def _write_flac(self, path, audio, sr):
        """写入 FLAC 文件。优先 soundfile，其次项目自带 ffmpeg，最后才回退为 WAV 字节。

        soundfile 依赖 libsndfile，缺失时用 ffmpeg 转码以保证文件是真正的 FLAC；
        仅当两者都不可用时才写入 WAV 内容（并打印告警，此时扩展名与内容不符）。
        """
        audio_int16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
        try:
            import soundfile as sf
            sf.write(str(path), audio_int16, sr, format="FLAC", subtype="PCM_16")
            return
        except Exception as e:
            print(f"[DATASET] soundfile FLAC 写入失败，尝试 ffmpeg 编码: {e}", flush=True)

        # 回退 1：用 ffmpeg（优先项目 models/ffmpeg/）把 WAV 转码为真实 FLAC
        try:
            from core import MODELS_DIR
            ff = None
            for _cand in (MODELS_DIR / "ffmpeg" / "ffmpeg.exe",
                          MODELS_DIR / "ffmpeg" / "ffmpeg"):
                if _cand.is_file():
                    ff = str(_cand)
                    break
            if ff is None:
                ff = shutil.which("ffmpeg")
            if ff:
                tmp_wav = path.with_suffix(".tmp.wav")
                try:
                    from scipy.io import wavfile as _wavfile
                    _wavfile.write(str(tmp_wav), sr, audio_int16)
                    r = subprocess.run(
                        [ff, "-y", "-i", str(tmp_wav), str(path)],
                        capture_output=True, text=True, timeout=120)
                finally:
                    try:
                        if tmp_wav.exists():
                            tmp_wav.unlink()
                    except Exception:
                        pass
                if r.returncode == 0 and path.is_file() and path.stat().st_size > 0:
                    return
                print(f"[DATASET] ffmpeg 编码 FLAC 失败: {r.stderr[:200]}", flush=True)
        except Exception as e:
            print(f"[DATASET] ffmpeg 编码 FLAC 异常: {e}", flush=True)

        # 回退 2：仅剩 WAV 写入能力，写 WAV 字节到 .flac 路径并告警
        try:
            from scipy.io import wavfile
            wavfile.write(str(path), sr, audio_int16)
            print("[DATASET] 警告：无 FLAC 编码能力，已写入 WAV 数据到 .flac 路径", flush=True)
        except Exception as e:
            print(f"[DATASET] 音频写入彻底失败: {e}", flush=True)

    # ------------------------------------------------------------------
    # 人工修正接口（预留，供后期工具调用）
    # ------------------------------------------------------------------
    def update_correction(self, seg_id, corrected_text, status="corrected"):
        """更新某片段的人工修正文本。

        参数:
            seg_id:         片段 ID
            corrected_text: 人工修正后的文本
            status:         corrected / rejected
        """
        if not self._enabled:
            return False

        with self._lock:
            for seg in self._manifest["segments"]:
                if seg["id"] == seg_id:
                    seg["corrected_text"] = corrected_text
                    seg["status"] = status
                    # 同步更新同目录下的 JSON 标注文件
                    json_path = self.base_dir / seg["corrected_path"]
                    try:
                        if json_path.exists():
                            with open(json_path, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            data["corrected_text"] = corrected_text
                            data["status"] = status
                            with open(json_path, "w", encoding="utf-8") as f:
                                json.dump(data, f, ensure_ascii=False, indent=2)
                    except Exception as e:
                        print(f"[DATASET] 更新标注文件失败: {e}", flush=True)
                    self._save_manifest()
                    self._manifest_dirty_count = 0
                    return True
        return False

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------
    def get_stats(self):
        """返回数据集统计信息。"""
        if not self._enabled or self._manifest is None:
            return {"enabled": False, "total": 0}
        with self._lock:
            segs = self._manifest.get("segments", [])
            total = len(segs)
            pending = sum(1 for s in segs if s.get("status") == "pending")
            corrected = sum(1 for s in segs if s.get("status") == "corrected")
            rejected = sum(1 for s in segs if s.get("status") == "rejected")
            total_dur = sum(s.get("duration", 0) for s in segs)
            avg_quality = (sum(s.get("quality", {}).get("overall", 0) for s in segs) / total) if total else 0
            return {
                "enabled": True,
                "total": total,
                "pending": pending,
                "corrected": corrected,
                "rejected": rejected,
                "total_duration": round(total_dur, 2),
                "avg_quality": round(avg_quality, 3),
            }

    # ------------------------------------------------------------------
    # 会话管理：完整连续录音
    # ------------------------------------------------------------------
    def start_session(self, mode, source_name):
        """开始一个新的录音会话。

        若前一会话未正常 end_session（如异常断开、跨模式切换），
        会自动保存旧会话的完整录音，避免数据丢失和内存泄漏。

        参数:
            mode:        数据来源模式 "local" / "streamer" / "meeting" / "audience"
            source_name: 来源名称（第三级目录名）
        """
        if not self._enabled:
            return
        # 检查-结束旧会话-重置-启动必须在同一把锁内完成：
        # 锁外读 _session_active 存在竞态窗口，窗口内 append 的音频会被静默丢弃
        with self._session_lock:
            # 若前一会话未结束，先自动保存（RLock 可重入；end_session 锁内只取快照
            # 并提交后台任务，不会长时间持锁）
            if self._session_active:
                print("[DATASET] 检测到前一会话未结束，自动保存", flush=True)
                self.end_session()
            self._session_active = True
            self._session_audio = []
            self._session_audio_samples = 0
            self._session_sr = 16000
            self._session_mode = mode if mode in _VALID_MODES else "streamer"
            self._session_source = source_name or "session"
            self._session_start = datetime.now()
            self._session_segments = []
            self._session_spill_files = []
            print(f"[DATASET] 会话开始: mode={mode}, source={source_name}", flush=True)

    def append_session_audio(self, chunk, sr=16000):
        """追加音频块到会话缓冲区。

        在实时模式下，每个收到的音频块都调用此方法，
        最终 end_session() 时拼接为完整连续录音。

        参数:
            chunk: numpy array 或可转为 array 的音频数据
            sr:    采样率，必须与会话采样率（16000）一致，否则会报错
                   （不同采样率拼接会导致播放变速/失真，且时长计算错误）
        """
        if not self._enabled or not self._session_active:
            return
        if sr != self._session_sr:
            print(f"[DATASET] append_session_audio 采样率不匹配: 期望 {self._session_sr}，"
                  f"实际 {sr}，跳过此音频块", flush=True)
            return
        try:
            arr = np.asarray(chunk, dtype=np.float32)
            if arr.ndim > 1:
                arr = np.mean(arr, axis=1).astype(np.float32)
            if len(arr) > 0:
                with self._session_lock:
                    if self._session_active:
                        self._session_audio.append(arr)
                        self._session_audio_samples += len(arr)
                        # 周期性合并：累积超过阈值时把 list 合并为单个 array
                        # 减少 list 项数，控制 end_session 时 concatenate 的内存峰值
                        if self._session_audio_samples >= self._session_merge_threshold:
                            try:
                                merged = np.concatenate(self._session_audio)
                                self._session_audio = [merged]
                                # samples 数不变，但 list 项数降到 1
                            except Exception as e:
                                print(f"[DATASET] 周期性合并音频失败: {e}", flush=True)
                        # 内存上限：超过后把已累积音频分片落盘为临时文件（后台线程执行），
                        # end_session 时与内存中的剩余音频合并，避免长会话 OOM
                        if self._session_audio_samples >= self._session_max_samples:
                            self._spill_session_audio_locked()
        except Exception as e:
            print(f"[DATASET] append_session_audio 异常: {e}", flush=True)

    def _spill_session_audio_locked(self):
        """把当前会话累积音频分片写入临时文件并释放内存（调用方需持有 _session_lock）。

        实际写盘提交到 _disk_executor 后台执行；单线程 executor 保证分片写入
        先于同一会话的 end_session 合并任务完成。
        """
        if not self._session_audio:
            return
        try:
            merged = (np.concatenate(self._session_audio)
                      if len(self._session_audio) > 1 else self._session_audio[0])
        except Exception as e:
            print(f"[DATASET][ERROR] 会话音频分片前合并失败: {e}", flush=True)
            return
        self._session_audio = []
        self._session_audio_samples = 0
        self._disk_executor.submit(self._write_spill_file, merged, self._session_spill_files)

    def _write_spill_file(self, arr, spill_files):
        """后台线程（_disk_executor）：把音频分片写入临时 .npy 文件。"""
        try:
            spill_dir = self.base_dir / "_session_tmp"
            spill_dir.mkdir(parents=True, exist_ok=True)
            path = spill_dir / (f"spill_{datetime.now().strftime('%Y%m%d_%H%M%S')}_"
                                f"{uuid.uuid4().hex[:8]}.npy")
            np.save(str(path), arr)
            spill_files.append(path)
            print(f"[DATASET] 会话音频超内存上限，分片落盘: {path.name} "
                  f"({len(arr)} 样本)", flush=True)
        except Exception as e:
            print(f"[DATASET][ERROR] 会话音频分片落盘失败，该部分音频将丢失: {e}", flush=True)
            import traceback
            traceback.print_exc()

    @staticmethod
    def _cleanup_spill_files(spill_files):
        """后台线程（_disk_executor）：删除临时分片文件。"""
        for p in spill_files:
            try:
                Path(p).unlink()
            except Exception:
                pass

    def end_session(self):
        """结束会话，写入完整连续录音和分段索引。

        生成两个文件：
          full_YYYYMMDDHHMM.flac  — 完整连续录音
          full_YYYYMMDDHHMM.json  — 元数据 + 分段索引（含每段的起止时间、文本、说话人）

        线程安全：用 _session_lock 保护会话状态。锁内只快速取出快照并清空缓冲，
        拼接/FLAC 编码/落盘等重活提交到 _disk_executor 后台执行——
        server.py 在 WebSocket async handler 中同步调用本方法，
        若锁内做重活会冻结事件循环数秒到几十秒，导致 WebSocket 全部超时。
        """
        with self._session_lock:
            if not self._enabled or not self._session_active:
                # 即使 _enabled=False 也要清理 _session_active，防止会话状态泄漏
                # （运行中禁用数据集功能时，end_session 因 not _enabled 提前返回
                #  但 _session_active 仍为 True，导致下次 start_session 调用陷入死循环）
                self._session_active = False
                self._session_audio = []
                self._session_audio_samples = 0
                self._session_segments = []
                # 已落盘的临时分片也要删除（数据按原逻辑丢弃）
                spill_files = self._session_spill_files
                self._session_spill_files = []
                if spill_files:
                    self._disk_executor.submit(self._cleanup_spill_files, spill_files)
                return
            self._session_active = False

            # 锁内快速取出快照并清空缓冲（新会话可立即 start_session）
            audio_chunks = self._session_audio
            spill_files = self._session_spill_files
            segments = self._session_segments
            sr = self._session_sr
            mode = self._session_mode
            source = self._session_source
            session_start = self._session_start
            self._session_audio = []
            self._session_audio_samples = 0
            self._session_segments = []
            self._session_spill_files = []

            if not audio_chunks and not spill_files:
                print("[DATASET] 会话结束: 无音频数据，跳过完整录音", flush=True)
                return

            # 重活后台执行：_disk_executor 单线程保证分片写入先于本次合并完成
            self._disk_executor.submit(
                self._finalize_session_recording,
                audio_chunks, spill_files, segments, sr, mode, source, session_start)

    def _finalize_session_recording(self, audio_chunks, spill_files, segments,
                                    sr, mode, source, session_start):
        """后台线程（_disk_executor）：拼接会话音频、FLAC 编码并落盘。

        所有输入均为 end_session 锁内取出的快照，不再访问会话状态，线程安全。
        """
        try:
            # 临时分片时间顺序在内存块之前，先读分片再拼接
            arrays = []
            for p in spill_files:
                try:
                    arrays.append(np.load(str(p)))
                except Exception as e:
                    print(f"[DATASET][ERROR] 读取会话临时分片失败 {p}: {e}", flush=True)
            arrays.extend(audio_chunks)
            if not arrays:
                print("[DATASET] 会话结束: 无音频数据，跳过完整录音", flush=True)
                return

            # 拼接所有音频块
            full_audio = np.concatenate(arrays) if len(arrays) > 1 else arrays[0]
            total_duration = len(full_audio) / sr

            # 生成文件名和目录
            # 加 6 位随机后缀防止分钟级冲突（同分钟处理多个文件时后者覆盖前者）
            session_time = session_start.strftime("%Y%m%d%H%M")
            unique_suffix = uuid.uuid4().hex[:6]
            date_str = session_start.strftime("%Y%m%d")
            source_dir = "".join(
                c for c in str(source)
                if c not in '<>:"/\\|?*'
            ).strip() or "session"

            seg_subdir = self.base_dir / mode / date_str / source_dir
            seg_subdir.mkdir(parents=True, exist_ok=True)

            full_audio_file = seg_subdir / f"full_{session_time}_{unique_suffix}.flac"
            full_json_file = seg_subdir / f"full_{session_time}_{unique_suffix}.json"
            audio_rel = f"{mode}/{date_str}/{source_dir}/full_{session_time}_{unique_suffix}.flac"

            # 写入完整音频
            self._write_flac(full_audio_file, full_audio, sr)

            # 写入元数据 + 分段索引
            # 每个分段记录其在完整录音中的起止时间，便于后期对齐
            segments_index = []
            for seg in segments:
                segments_index.append({
                    "seg_id": seg["seg_id"],
                    "start_time": round(seg["start_time"], 3),
                    "end_time": round(seg["start_time"] + seg["duration"], 3),
                    "duration": round(seg["duration"], 3),
                    "text": seg["text"],
                    "speaker": seg["speaker"],
                    "audio_file": seg["audio_file"],
                })

            metadata = {
                "type": "full_recording",
                "mode": mode,
                "source_name": source_dir,
                "session_start": session_start.isoformat(),
                "session_end": datetime.now().isoformat(),
                "total_duration": round(total_duration, 2),
                "sample_rate": sr,
                "audio_file": audio_rel,
                "segment_count": len(segments_index),
                "segments": segments_index,
            }
            with open(full_json_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)

            print(f"[DATASET] 完整录音已保存: full_{session_time}.flac "
                  f"({total_duration:.1f}s, {len(segments_index)}段)", flush=True)

        except Exception as e:
            print(f"[DATASET] 保存完整录音失败: {e}", flush=True)
            import traceback
            traceback.print_exc()
        finally:
            # 删除临时分片文件
            self._cleanup_spill_files(spill_files)
            # 会话结束是天然的批量落盘点：把未落盘的 manifest 变更强制刷盘，
            # 避免进程退出时丢失最近几段的清单记录（音频/标注文件已成孤儿）
            with self._lock:
                if self._manifest is not None and self._manifest_dirty_count > 0:
                    self._save_manifest()
                    self._manifest_dirty_count = 0


# ----------------------------------------------------------------------
# 模块级单例（供 server.py 直接导入使用）
# ----------------------------------------------------------------------
_manager_instance = None
_manager_lock = threading.Lock()


def get_dataset_manager():
    """获取 DatasetManager 单例（未启用状态）。"""
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = DatasetManager()
    return _manager_instance
