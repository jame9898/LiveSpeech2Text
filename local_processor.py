# -*- coding: utf-8 -*-
"""
本地处理模式 — 批量处理本地视频/音频文件

流程：
  1. 遍历文件夹，筛选视频/音频文件
  2. ffmpeg 提取音频为 16kHz mono wav（视频文件）
  3. VAD 切分（用本地模式独立设置）
  4. Qwen3-ASR 转录（用 transcribe_array，非伪流式）
  5. 说话人分离（CAM++）
  6. 生成 MD 报告
  7. 可选存入后训练数据集（mode="local"）

与 batch_transcribe.py 的区别：
  - 集成 ffmpeg 视频提取（batch_transcribe 只处理音频）
  - QThread + Signal 集成 UI（batch_transcribe 是纯命令行）
  - 用本地模式独立 VAD 设置（与实时模式分离）
  - 接入 DatasetManager（mode="local"）
"""

import asyncio
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import QThread, Signal

from core import ASREngine, load_config, resolve_device, MODELS_DIR, DICT_DIR
from common_utils import StdoutRedirect, STRICTNESS_THRESHOLDS, load_speaker_pipeline, load_audio_fast
from perf_utils import PerfMonitor, gpu_info, format_elapsed
from vad_processor import VADProcessor, silero_vad_segment, fsmn_vad_segment, batch_vad
from speaker_manager import SpeakerManager
from pinyin_utils import PinyinCorrector
from report_generator import (
    generate_comprehensive_report,
    merge_short_trailing,
    merge_semantic_continuation,
    split_long_segment,
)
from dataset_manager import get_dataset_manager

TEMP_DIR = Path(__file__).parent / "temp"
TEMP_DIR.mkdir(exist_ok=True)

# stdout/stderr 全局重定向锁：_run_impl 替换 sys.stdout/stderr 期间持有，
# 保证重定向与恢复在锁内配对执行，避免与项目内其他同类重定向
# （fsmn_vad_segment、load_fsmn_vad、说话人模型加载）并发时错位嵌套
_stdout_redirect_lock = threading.Lock()

# ASR 批量分组参数：组总样本上限（默认约 4 个 30s 段）与组内最长/最短段长度比
# GPU 推理可调大 batch 提升吞吐；CPU 建议维持默认防止显存/内存峰值
_ASR_MAX_BATCH_SAMPLES = int(16000 * 30 * 4)
_ASR_MAX_LEN_RATIO = 3.0

# 支持的视频/音频扩展名
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm", ".m4v", ".ts", ".mpg", ".mpeg"}
AUDIO_EXTS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac", ".wma", ".opus"}


def find_ffmpeg(custom_path=None):
    """查找 ffmpeg 可执行文件。
    优先级：custom_path > 项目模型文件夹下的 ffmpeg > PATH 中的 ffmpeg > 项目根目录下的 ffmpeg
    """
    if custom_path and Path(custom_path).is_file():
        return custom_path
    # 优先从项目模型文件夹查找（models/ffmpeg/）
    from core import MODELS_DIR
    ffmpeg_dir = MODELS_DIR / "ffmpeg"
    if sys.platform == "win32":
        for ext in (".exe", ".bat", ""):
            candidate = ffmpeg_dir / f"ffmpeg{ext}"
            if candidate.is_file():
                return str(candidate)
    else:
        candidate = ffmpeg_dir / "ffmpeg"
        if candidate.is_file():
            return str(candidate)
    # 回退到 PATH 中的 ffmpeg
    found = shutil.which("ffmpeg")
    if found:
        return found
    # 回退到项目根目录
    if sys.platform == "win32":
        for ext in (".exe", ".bat", ""):
            candidate = Path(__file__).parent / f"ffmpeg{ext}"
            if candidate.is_file():
                return str(candidate)
    else:
        candidate = Path(__file__).parent / "ffmpeg"
        if candidate.is_file():
            return str(candidate)
    return None


def scan_media_files(path):
    """扫描文件或文件夹中的视频和音频文件，返回 (video_files, audio_files) 两个列表。

    path 可以是文件夹（递归扫描）或单个文件。
    """
    path = Path(path)
    video_files = []
    audio_files = []

    if path.is_file():
        ext = path.suffix.lower()
        if ext in VIDEO_EXTS:
            video_files.append(path)
        elif ext in AUDIO_EXTS:
            audio_files.append(path)
        return video_files, audio_files

    # 文件夹：递归扫描
    for p in sorted(path.rglob("*")):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext in VIDEO_EXTS:
            video_files.append(p)
        elif ext in AUDIO_EXTS:
            audio_files.append(p)
    return video_files, audio_files


def extract_audio_with_ffmpeg(video_path, output_wav, ffmpeg_path, log_cb=None):
    """用 ffmpeg 从视频提取音频为 16kHz mono wav。
    返回 True 成功，False 失败。
    """
    cmd = [
        ffmpeg_path, "-y",
        "-i", str(video_path),
        "-vn",              # 不要视频
        "-acodec", "pcm_s16le",
        "-ar", "16000",     # 16kHz
        "-ac", "1",         # mono
        "-loglevel", "error",
        str(output_wav),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            if log_cb:
                log_cb(f"[ffmpeg] 失败: {result.stderr[:200]}\n")
            return False
        return output_wav.is_file()
    except subprocess.TimeoutExpired:
        if log_cb:
            log_cb(f"[ffmpeg] 超时（>600s）: {video_path.name}\n")
        return False
    except Exception as e:
        if log_cb:
            log_cb(f"[ffmpeg] 异常: {e}\n")
        return False


async def process_audio_file(audio_path, engine, vad, speaker_mgr, pinyin_corr,
                              dataset_mgr=None, save_dataset=False, log_cb=None,
                              source_name=None, seg_progress_cb=None, vad_engine="silero",
                              silero_speech_prob_threshold=0.5,
                              fsmn_speech_noise_threshold=0.6,
                              should_stop=None):
    """处理单个音频文件：VAD 切分 + ASR + 说话人分离 + 可选存储数据集。
    source_name: 后训练数据集第三级目录名（本地模式默认用音频文件名 stem）。
    seg_progress_cb: 段进度回调 fn(idx, total, filename)，None 时不回调。
    vad_engine: VAD 引擎选择，"silero" / "fsmn" / "energy"。
    silero_speech_prob_threshold: Silero VAD 语音概率阈值（0~1）。
    fsmn_speech_noise_threshold: FSMN VAD 语音噪声阈值（0~1）。
    should_stop: 可选取消回调 fn() -> bool，返回 True 时在可中断处尽快退出。
    返回 (segments, total_dur)
    """
    def _log(msg):
        if log_cb:
            log_cb(msg + "\n")
        else:
            print(msg, flush=True)

    def _stopped():
        return should_stop is not None and should_stop()

    _log(f"\n{'=' * 50}")
    _log(f"[LOCAL] 处理: {Path(audio_path).name}")

    perf = PerfMonitor(log_cb=None, label="LOCAL")  # 阶段计时，自己 _log 输出
    _log(f"[LOCAL] GPU: {gpu_info() or '未检测到 NVIDIA GPU（CPU 推理）'}")

    import librosa
    perf.start("音频加载")
    audio, sr = load_audio_fast(str(audio_path), target_sr=16000)
    perf.stop("音频加载")
    total_dur = len(audio) / sr
    _log(f"[LOCAL] 时长: {total_dur:.1f}s")

    # librosa.load 本身不可中断，加载完成后立即检查取消标志
    # （此时数据集会话尚未开始，无需 end_session 清理）
    if _stopped():
        _log("[LOCAL] 用户已取消，中断当前文件处理")
        return [], total_dur

    # 后训练数据集：开始会话 + 追加完整音频（本地模式一次性追加）
    # 异常路径的 end_session 由 _run_impl 的 except 块兜底
    if save_dataset and dataset_mgr and dataset_mgr.enabled:
        dataset_mgr.start_session("local", source_name or Path(audio_path).stem)
        dataset_mgr.append_session_audio(audio, sr)

    # 根据 vad_engine 选择不同的 VAD 引擎
    vad_silence = vad.vad_silence_threshold
    min_speech = vad.min_speech_duration
    force_cut = vad.vad_force_cut_sec

    engine_names = {"silero": "Silero", "fsmn": "FSMN", "energy": "能量阈值"}
    engine_name = engine_names.get(vad_engine, vad_engine)
    _log(f"[LOCAL] VAD 引擎: {engine_name}（静音>{vad_silence}s 切句，最短{min_speech}s，最长{force_cut}s）")

    raw_segments = None
    perf.start("VAD")
    if vad_engine == "silero":
        _log("[LOCAL] 正在加载 Silero VAD 模型...")
        try:
            raw_segments = silero_vad_segment(
                audio, sr,
                vad_silence_threshold=vad_silence,
                min_speech_duration=min_speech,
                force_cut_sec=force_cut,
                speech_prob_threshold=silero_speech_prob_threshold,
            )
            _log("[LOCAL] Silero VAD 加载成功，切分完成")
        except Exception as e:
            _log(f"[LOCAL] [WARN] Silero VAD 加载失败: {e}")
            _log("[LOCAL] [WARN] 回退到能量阈值法（RMS）")
            raw_segments = None

    elif vad_engine == "fsmn":
        _log("[LOCAL] 正在加载 FSMN VAD 模型...")
        try:
            raw_segments = fsmn_vad_segment(
                audio, sr,
                vad_silence_threshold=vad_silence,
                min_speech_duration=min_speech,
                force_cut_sec=force_cut,
                speech_noise_threshold=fsmn_speech_noise_threshold,
            )
            _log("[LOCAL] FSMN VAD 加载成功，切分完成")
        except Exception as e:
            import traceback
            _log(f"[LOCAL] [WARN] FSMN VAD 加载失败: {e}")
            _log(f"[LOCAL] [WARN] traceback:\n{traceback.format_exc()}")
            _log("[LOCAL] [WARN] 回退到能量阈值法（RMS）")
            raw_segments = None

    # energy 引擎或神经网络引擎回退
    if raw_segments is None:
        _log("[LOCAL] 使用能量阈值法切分...")
        vad.reset()
        raw_segments = batch_vad(audio, sr, vad)
    perf.stop("VAD")

    _log(f"[LOCAL] VAD 切出 {len(raw_segments)} 段")

    if not raw_segments:
        _log("[LOCAL] [WARN] 未切出任何语音段")
        # 后训练数据集：结束会话（无分段也要正确关闭）
        if save_dataset and dataset_mgr and dataset_mgr.enabled:
            dataset_mgr.end_session()
        return [], total_dur

    segments = []
    # ASR 模型要求输入长度 >= padding 大小（Qwen3-ASR 内部 padding=200），
    # 过短的段（<0.2s = 3200 样本）会导致 padding 报错，直接跳过
    _MIN_ASR_SAMPLES = int(16000 * 0.2)
    _total_segs = len(raw_segments)
    _fname = Path(audio_path).name

    # === 批量转录 ===
    # CPU 上逐段 ASR 单次推理 2-5s（编解码模型固定开销大）；将时长相近的段
    # 合并为一个 batch 一次推理，可数倍提速。qwen-asr 内部按组内最长段
    # padding，故按长度分组避免浪费。分组规则：组内最长/最短 <= 长度比，
    # 且组总样本量受限（控制内存）。实测（RTX 4070 SUPER + 60s 音频）：
    # GPU 用 8x30s/6x 比 4x30s/3x 快约 27%；CPU 保持 4x30s/3x 防内存峰值。
    _is_gpu = getattr(engine, '_device', None) == 'cuda'
    _MAX_BATCH_SAMPLES = _ASR_MAX_BATCH_SAMPLES if not _is_gpu else int(16000 * 30 * 8)
    _MAX_LEN_RATIO = _ASR_MAX_LEN_RATIO if not _is_gpu else 6.0
    asr_groups = []  # 每项: [段索引...]
    _cur_group = []
    _cur_len = 0
    _cur_max = 0
    for idx, (seg_audio, seg_time, seg_dur, vad_info) in enumerate(raw_segments):
        n = len(seg_audio)
        if n < _MIN_ASR_SAMPLES:
            _log(f"[LOCAL] [SKIP] 段 {idx + 1} 过短({n/16000:.2f}s)，跳过")
            continue
        if (_cur_group and (n > _cur_max * _MAX_LEN_RATIO or n * _MAX_LEN_RATIO < _cur_max
                            or _cur_len + n > _MAX_BATCH_SAMPLES)):
            asr_groups.append(_cur_group)
            _cur_group, _cur_len, _cur_max = [], 0, 0
        _cur_group.append(idx)
        _cur_len += n
        _cur_max = max(_cur_max, n)
    if _cur_group:
        asr_groups.append(_cur_group)
    if asr_groups:
        _log(f"[LOCAL] ASR 批量转录: {len(asr_groups)} 组 / {sum(len(g) for g in asr_groups)} 段")

    _seg_texts = {}  # 段索引 -> ASR 文本
    perf.start("ASR 转录")
    for gi, group in enumerate(asr_groups):
        # 每组 ASR 前检查取消标志（批量调用本身不可中断，在组间检查）
        if _stopped():
            _log("[LOCAL] 用户已取消，中断当前文件处理")
            # 数据集会话可能已开启，需正确关闭
            if save_dataset and dataset_mgr and dataset_mgr.enabled:
                dataset_mgr.end_session()
            return [], total_dur
        group_audio = [raw_segments[i][0] for i in group]
        try:
            group_texts = engine.transcribe_batch(group_audio, sr=16000)
        except Exception as e:
            _log(f"[LOCAL] [WARN] 第 {gi + 1} 组批量 ASR 失败: {e}")
            group_texts = [""] * len(group)
        for i, text in zip(group, group_texts):
            text = (text or "").strip()
            if text:
                _seg_texts[i] = text
    perf.stop("ASR 转录")

    for idx, (seg_audio, seg_time, seg_dur, vad_info) in enumerate(raw_segments):
        # 每段 VAD/说话人/数据集迭代前检查取消标志，可中断处尽快退出
        if _stopped():
            _log("[LOCAL] 用户已取消，中断当前文件处理")
            # 数据集会话可能已开启，需正确关闭
            if save_dataset and dataset_mgr and dataset_mgr.enabled:
                dataset_mgr.end_session()
            return [], total_dur
        # 段进度回调（文件名用原始媒体名，不带 temp 前缀）
        if seg_progress_cb:
            try:
                seg_progress_cb(idx + 1, _total_segs, _fname)
            except Exception:
                pass

        text = _seg_texts.get(idx, "")
        if not text:
            continue

        raw_text = text  # 保存原始 ASR 输出，供拼音纠正后对比
        text, corrections = pinyin_corr.correct_with_keywords(text)

        perf.start("说话人")
        try:
            if len(seg_audio) < int(16000 * 0.8):
                speaker_label = speaker_mgr.last_speaker_label
            else:
                speaker_label = await speaker_mgr.detect_speaker(seg_audio)
                speaker_mgr.last_speaker_label = speaker_label
        except Exception:
            speaker_label = speaker_mgr.last_speaker_label
        perf.stop("说话人")

        seg_entry = {
            'text': text,
            'time': seg_time,
            'speaker': speaker_label,
            'duration': seg_dur,
            'kw_corrected': len(corrections) > 0,
            'vad': vad_info,
            'corrections': corrections,
            'timestamp': datetime.now().isoformat(),
            'original_text': raw_text,
        }
        segments.append(seg_entry)

        preview = text[:40].replace('\n', ' ')
        _log(f"[LOCAL] 段 {idx + 1}/{len(raw_segments)} [{seg_time:.1f}s] {speaker_label}: {preview}")

        # 存入后训练数据集
        if save_dataset and dataset_mgr and dataset_mgr.enabled:
            try:
                dataset_mgr.save_segment(
                    audio_data=seg_audio,
                    text=text,
                    raw_text=text,
                    speaker_label=speaker_label,
                    vad_info=vad_info,
                    seg_audio_time=seg_time,
                    seg_duration=seg_dur,
                    sr=16000,
                    mode="local",
                    source_name=source_name or Path(audio_path).stem,
                )
            except Exception as e:
                _log(f"[LOCAL] [WARN] 数据集存储失败: {e}")

    # 后处理合并：用用户设置的 VAD 静音阈值作为合并间隔上限
    # 间隔 < vad_silence_threshold 的同说话人短片段会被合并（VAD 误切修复）
    merge_short_trailing(segments, vad_silence_threshold=vad.vad_silence_threshold)
    merge_semantic_continuation(segments)
    # 超长段落兜底切分（保留合并形式，避免单段 1000+ 字）
    split_long_segment(segments, max_chars=150, max_duration_sec=30)

    # 后训练数据集：结束会话，写入完整连续录音 + 分段索引
    if save_dataset and dataset_mgr and dataset_mgr.enabled:
        dataset_mgr.end_session()

    # 性能小结：总耗时 / 各阶段耗时与占比 / 实时率 / GPU 状态
    _log(perf.summary(extra={
        "实时率": f"{total_dur / perf.total():.2f}x" if perf.total() > 0 else "-",
        "音频时长": f"{total_dur:.1f}s",
        "段数": len(segments),
    }))

    return segments, total_dur


class LocalProcessThread(QThread):
    """本地处理线程：在后台执行批量转录，通过信号更新 UI。"""
    progress = Signal(str)          # 日志文本（含换行）
    file_progress = Signal(int, int)    # (当前文件序号, 总文件数)
    segment_progress = Signal(int, int, str)  # (当前段号, 总段数, 文件名)
    file_done = Signal(str, str)    # (文件名, 报告路径) 单个文件完成
    all_done = Signal(int)          # 处理完成的文件数
    error = Signal(str)             # 致命错误

    def __init__(self, folder, output_dir, engine=None, config=None,
                 ffmpeg_path=None, save_dataset=False, parent=None):
        super().__init__(parent)
        self.folder = Path(folder)
        self.output_dir = Path(output_dir)
        self.engine = engine
        self.config = config or load_config()
        self.ffmpeg_path = ffmpeg_path
        self.save_dataset = save_dataset
        self._running = True
        self._engine_owned = engine is None  # 标记是否自行加载的引擎（需自行关闭）

    def stop(self):
        self._running = False

    def run(self):
        try:
            self._run_impl()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))

    def _run_impl(self):
        # 重定向 stdout/stderr 到 progress 信号，让 speaker_manager 等模块的 print 能显示在 UI
        # 注意：ModelScope 等三方库内部可能再次重定向 sys.stdout，导致 fallback 失效
        # 因此 fallback 必须容错（None 时跳过）
        import sys
        _old_stdout, _old_stderr = sys.stdout, sys.stderr
        # 重定向与恢复在同一把模块级锁内配对执行，避免与其他模块的同类重定向错位嵌套
        with _stdout_redirect_lock:
            sys.stdout = StdoutRedirect(self.progress.emit, _old_stdout)
            sys.stderr = StdoutRedirect(self.progress.emit, _old_stderr)
            try:
                self._run_impl_inner()
            finally:
                sys.stdout = _old_stdout
                sys.stderr = _old_stderr

    def _run_impl_inner(self):
        # 处理开始时间，作为后训练数据集第三级目录名（YYYYMMDDHHMM，与其他模式统一）
        source_name = datetime.now().strftime("%Y%m%d%H%M")
        _t_all_start = time.perf_counter()

        # 1. 扫描文件（支持单文件或文件夹）
        input_path = Path(self.folder)
        if input_path.is_file():
            self.progress.emit(f"[LOCAL] 处理文件: {input_path.name}\n")
        else:
            self.progress.emit(f"[LOCAL] 扫描文件夹: {self.folder}\n")
        video_files, audio_files = scan_media_files(self.folder)
        all_files = video_files + audio_files
        total = len(all_files)
        if total == 0:
            self.progress.emit("[LOCAL] [ERROR] 未找到任何视频或音频文件\n")
            self.error.emit("未找到任何视频或音频文件")
            return

        self.progress.emit(f"[LOCAL] 视频 {len(video_files)} 个，音频 {len(audio_files)} 个，共 {total} 个\n")

        # 2. 检查 ffmpeg（有视频文件时）
        ffmpeg = None
        if video_files:
            ffmpeg = find_ffmpeg(self.ffmpeg_path)
            if not ffmpeg:
                self.progress.emit("[LOCAL] [ERROR] 未找到 ffmpeg，无法处理视频文件。请在设置中配置 ffmpeg 路径或将其加入 PATH。\n")
                self.error.emit("未找到 ffmpeg，无法处理视频文件")
                return
            self.progress.emit(f"[LOCAL] ffmpeg: {ffmpeg}\n")

        # 3. 加载 ASR 引擎（若未外部传入）
        if self.engine is None:
            self.progress.emit("[LOCAL] 加载 ASR 引擎...\n")
            device = resolve_device(self.config)
            engine = ASREngine(device=device, config=self.config)
            pref = self.config.get("current_model", "auto")
            if pref == "auto":
                pref = None
            if not engine.load_model(preferred=pref):
                self.error.emit("ASR 模型加载失败")
                return
            self.engine = engine
            self.progress.emit(f"[LOCAL] ASR 模型: {engine.model_name}\n")
        else:
            self.progress.emit(f"[LOCAL] 复用已加载模型: {self.engine.model_name}\n")

        # 4. 初始化 VAD（VAD 参数全部跟随全局 model_settings）
        local_settings = self.config.get("local_settings", {})
        model_settings = self.config.get("model_settings", {})
        # VAD 引擎和参数由「音频/VAD」选项卡全局设置，本地模式跟随该配置
        vad_engine = model_settings.get("vad_engine", "silero")
        vad = VADProcessor(
            vad_silence_threshold=model_settings.get("vad_threshold", 0.5),
            vad_force_cut=model_settings.get("vad_force_cut", True),
            vad_force_cut_sec=model_settings.get("force_cut_sec", 6.0),
            min_speech_duration=model_settings.get("min_speech_duration", 0.12),
            max_buffer_seconds=model_settings.get("max_buffer_seconds", 30),
            adaptive=False,  # 本地批处理：直接用用户设置的阈值，不做自适应
        )

        # 5. 加载说话人分离
        # 说话人识别模型选择 + 严格度
        sp_model_key = model_settings.get("speaker_model", "cam++")
        sp_strictness = model_settings.get("speaker_strictness", "strict")
        _same_threshold = STRICTNESS_THRESHOLDS.get(sp_strictness, 0.55)
        _SP_LABELS = {"cam++": "CAM++", "eres2netv2": "ERes2NetV2", "eres2net": "ERes2Net base"}
        self.progress.emit(f"[LOCAL] 加载 {_SP_LABELS.get(sp_model_key, 'CAM++')} 说话人模型...\n")
        from concurrent.futures import ThreadPoolExecutor
        # 临时用 StringIO 作为 stdout/stderr：避免 ModelScope 下载进度条调用 sys.stdout.flush()
        # 与 _UIWriter 重定向冲突（'NoneType' object has no attribute 'flush'）。
        # 不能用 sys.__stdout__：Windows GUI 程序下会弹出 CLI 控制台窗口。
        # 加载完后把 StringIO 内容 emit 到 UI 日志，便于排查加载失败原因。
        import sys as _sys, io as _io
        _ui_stdout, _ui_stderr = _sys.stdout, _sys.stderr
        _buf = _io.StringIO()
        _sys.stdout = _buf
        _sys.stderr = _buf
        try:
            sv_pipeline = load_speaker_pipeline(sp_model_key)
        finally:
            _sys.stdout = _ui_stdout
            _sys.stderr = _ui_stderr
            _buf_text = _buf.getvalue()
        if _buf_text.strip():
            # 把 ModelScope / load_speaker_pipeline 的输出转发到 UI 日志（每行加 [LOCAL] 前缀）
            for _line in _buf_text.splitlines():
                _line = _line.rstrip()
                if _line:
                    self.progress.emit(f"[LOCAL] {_line}\n")
        if sv_pipeline is None:
            self.progress.emit(f"[LOCAL] [WARN] 说话人模型加载失败，所有段将标记为 Speaker0（不进行说话人分离）\n")
        else:
            self.progress.emit(f"[LOCAL] {_SP_LABELS.get(sp_model_key, 'CAM++')} 说话人模型加载成功\n")
        threads = model_settings.get("threads", 4)
        executor = ThreadPoolExecutor(max_workers=threads)
        speaker_mgr = SpeakerManager(
            sv_pipeline=sv_pipeline,
            executor=executor,
            dict_dir=DICT_DIR,
            temp_dir=TEMP_DIR,
            same_threshold=_same_threshold,
        )
        pinyin_corr = PinyinCorrector()

        # 6. 数据集管理器
        dataset_mgr = get_dataset_manager()
        dataset_cfg = self.config.get("dataset_settings", {})
        dataset_mgr.configure(
            quality_threshold=dataset_cfg.get("quality_threshold", 0.6),
            auto_filter=dataset_cfg.get("auto_filter", True),
        )
        # 后训练启用条件：UI 勾选（单次启用）OR 设置里全局启用
        # - UI 勾选：仅对本次处理生效，不论设置里是否启用
        # - 设置里启用：所有模式默认启用后训练
        if self.save_dataset or dataset_cfg.get("enabled", False):
            if not dataset_mgr.enabled:
                dataset_mgr.enable()
            self.save_dataset = True  # 设置里启用时，强制本次也存
            self.progress.emit("[LOCAL] 后训练数据集收集已启用 (mode=local)\n")
        else:
            self.save_dataset = False

        # 7. 输出目录
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 8. 逐文件处理
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        done_count = 0

        try:
            for idx, media_path in enumerate(all_files):
                if not self._running:
                    self.progress.emit("[LOCAL] 用户已取消\n")
                    break

                # 每个文件开始前重置说话人状态，避免跨文件污染
                # （vad.reset 在 process_audio_file 的能量切分路径内已有）
                speaker_mgr.reset_session()
                speaker_mgr.reset_speaker_profiles()

                self.file_progress.emit(idx + 1, total)
                self.progress.emit(f"\n[LOCAL] ({idx + 1}/{total}) {media_path.name}\n")

                # 视频文件先提取音频
                is_video = media_path.suffix.lower() in VIDEO_EXTS
                if is_video:
                    wav_path = TEMP_DIR / f"_local_{media_path.stem}_{datetime.now().strftime('%H%M%S')}.wav"
                    # ffmpeg 子进程本身不可中断（timeout=600），在调用前后检查取消标志
                    ok = self._running and extract_audio_with_ffmpeg(media_path, wav_path, ffmpeg, self.progress.emit)
                    if not ok:
                        if self._running:
                            self.progress.emit(f"[LOCAL] [SKIP] 音频提取失败: {media_path.name}\n")
                        # 失败/取消路径同样清理临时 wav，避免 temp 目录残留
                        try:
                            if wav_path.exists():
                                wav_path.unlink()
                        except Exception:
                            pass
                        if not self._running:
                            break
                        continue
                    audio_input = wav_path
                else:
                    audio_input = media_path

                try:
                    segments, total_dur = loop.run_until_complete(
                        process_audio_file(
                            audio_input, self.engine, vad, speaker_mgr, pinyin_corr,
                            dataset_mgr=dataset_mgr,
                            save_dataset=self.save_dataset,
                            log_cb=self.progress.emit,
                            source_name=source_name,  # 用处理开始时间 YYYYMMDDHHMM 作为第三级目录
                            seg_progress_cb=lambda i, t, fn: self.segment_progress.emit(i, t, fn),
                            vad_engine=vad_engine,
                            silero_speech_prob_threshold=model_settings.get("silero_speech_prob_threshold", 0.5),
                            fsmn_speech_noise_threshold=model_settings.get("fsmn_speech_noise_threshold", 0.6),
                            should_stop=lambda: not self._running,
                        )
                    )
                except Exception as e:
                    self.progress.emit(f"[LOCAL] [ERROR] 处理失败: {e}\n")
                    # 异常路径也要结束会话，避免内存泄漏和跨文件状态污染
                    if self.save_dataset and dataset_mgr and dataset_mgr.enabled:
                        try:
                            dataset_mgr.end_session()
                        except Exception:
                            pass
                    continue
                finally:
                    # 清理临时 wav
                    if is_video and audio_input.exists():
                        try:
                            audio_input.unlink()
                        except Exception:
                            pass

                # 文件内处理被取消（process_audio_file 中断返回空段）：直接退出，不再生成报告
                if not self._running:
                    self.progress.emit("[LOCAL] 用户已取消\n")
                    break

                if not segments:
                    self.progress.emit(f"[LOCAL] [WARN] {media_path.name} 无有效识别内容\n")
                    continue

                # 生成报告
                _t_report = time.perf_counter()
                display_names = speaker_mgr.get_all_display_names()
                report = generate_comprehensive_report(
                    segments=segments,
                    speaker_profiles=speaker_mgr.speaker_profiles,
                    keyword_history=[],
                    total_audio_seconds=total_dur,
                    asr_model_name=self.engine.model_name or "qwen3-asr",
                    page_type='video',
                    video_offset=0,
                    display_names=display_names,
                    page_creator=None,
                    session_start_time=datetime.now(),
                    mode='local',
                )

                out_file = self.output_dir / (media_path.stem + '.md')
                out_file.write_text(report, encoding='utf-8')
                _report_elapsed = time.perf_counter() - _t_report
                self.progress.emit(f"[LOCAL] 报告生成: {format_elapsed(_report_elapsed)}\n")
                self.progress.emit(f"[LOCAL] 报告已保存: {out_file}\n")
                self.file_done.emit(media_path.name, str(out_file))
                done_count += 1
        finally:
            loop.close()
            if self._engine_owned and self.engine is not None:
                # 自行加载的引擎，通过 release() 统一释放资源
                # 包含 model.cpu() → model=None → gc.collect() → cuda.synchronize → empty_cache 完整流程
                try:
                    self.engine.release()
                except Exception as e:
                    print(f"[LOCAL] 引擎释放失败: {e}", flush=True)
            executor.shutdown(wait=False)

        _t_all = time.perf_counter() - _t_all_start
        self.progress.emit(f"\n[LOCAL] 全部完成，共处理 {done_count}/{total} 个文件\n")
        self.progress.emit(f"[LOCAL] 本次任务总耗时: {format_elapsed(_t_all)}（含模型加载/ffmpeg 提取/报告生成）\n")
        if self.save_dataset and dataset_mgr.enabled:
            stats = dataset_mgr.get_stats()
            self.progress.emit(f"[LOCAL] 数据集: 总计 {stats['total']} 段, 平均质量 {stats['avg_quality']}\n")
        self.all_done.emit(done_count)
