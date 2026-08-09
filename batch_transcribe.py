# -*- coding: utf-8 -*-
"""
批量音频转录脚本 — 复用项目 VAD/ASR/说话人分离/报告生成管线
用法: python batch_transcribe.py <音频文件或目录> [输出目录]
"""

import sys
import asyncio
import time
import numpy as np
import librosa
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from core import ASREngine, load_config, resolve_device, DICT_DIR
from common_utils import load_speaker_pipeline, STRICTNESS_THRESHOLDS
from perf_utils import gpu_info, format_elapsed
from vad_processor import VADProcessor, batch_vad, silero_vad_segment, fsmn_vad_segment
from speaker_manager import SpeakerManager
from pinyin_utils import PinyinCorrector
from report_generator import (
    generate_comprehensive_report,
    merge_short_trailing,
    merge_semantic_continuation,
)

TEMP_DIR = Path(__file__).parent / "temp"
TEMP_DIR.mkdir(exist_ok=True)


async def process_audio_file(audio_path, engine, vad, speaker_mgr, pinyin_corr,
                             vad_engine="silero", silero_speech_prob_threshold=0.5,
                             fsmn_speech_noise_threshold=0.6):
    """处理单个音频文件：VAD 切分 + ASR + 说话人分离。
    vad_engine: "silero" / "fsmn" / "energy"，与本地模式一致（跟随全局配置）。
    """
    print(f"\n{'=' * 60}", flush=True)
    print(f"[BATCH] 处理: {audio_path.name}", flush=True)
    print(f"{'=' * 60}", flush=True)

    print("[BATCH] 读取音频...", flush=True)
    audio, sr = librosa.load(str(audio_path), sr=16000, mono=True)
    audio = audio.astype(np.float32)
    total_dur = len(audio) / sr
    print(f"[BATCH] 音频时长: {total_dur:.1f}s, 采样率: {sr}", flush=True)

    # VAD 引擎选择与本地模式（local_processor.process_audio_file）完全一致：
    # 全局配置 vad_engine → silero/fsmn/energy，神经网络引擎失败时回退能量阈值
    engine_names = {"silero": "Silero", "fsmn": "FSMN", "energy": "能量阈值"}
    print(f"[BATCH] VAD 引擎: {engine_names.get(vad_engine, vad_engine)}"
          f"（静音>{vad.vad_silence_threshold}s 切句）", flush=True)
    raw_segments = None
    if vad_engine == "silero":
        print("[BATCH] 加载 Silero VAD 模型...", flush=True)
        try:
            raw_segments = silero_vad_segment(
                audio, sr,
                vad_silence_threshold=vad.vad_silence_threshold,
                min_speech_duration=vad.min_speech_duration,
                force_cut_sec=vad.vad_force_cut_sec,
                speech_prob_threshold=silero_speech_prob_threshold,
            )
        except Exception as e:
            print(f"[BATCH] [WARN] Silero VAD 加载失败: {e}", flush=True)
            print("[BATCH] [WARN] 回退到能量阈值法（RMS）", flush=True)
            raw_segments = None
    elif vad_engine == "fsmn":
        print("[BATCH] 加载 FSMN VAD 模型...", flush=True)
        try:
            raw_segments = fsmn_vad_segment(
                audio, sr,
                vad_silence_threshold=vad.vad_silence_threshold,
                min_speech_duration=vad.min_speech_duration,
                force_cut_sec=vad.vad_force_cut_sec,
                speech_noise_threshold=fsmn_speech_noise_threshold,
            )
        except Exception as e:
            print(f"[BATCH] [WARN] FSMN VAD 加载失败: {e}", flush=True)
            print("[BATCH] [WARN] 回退到能量阈值法（RMS）", flush=True)
            raw_segments = None
    if raw_segments is None:
        print("[BATCH] 使用能量阈值法切分...", flush=True)
        vad.reset()
        raw_segments = batch_vad(audio, sr, vad)
    print(f"[BATCH] VAD 切出 {len(raw_segments)} 段", flush=True)

    if not raw_segments:
        print("[BATCH] [WARN] 未切出任何语音段", flush=True)
        return [], total_dur

    print("[BATCH] 逐段 ASR + 说话人分离...", flush=True)
    segments = []
    for idx, (seg_audio, seg_time, seg_dur, vad_info) in enumerate(raw_segments):
        try:
            text = engine.transcribe_array(seg_audio, sr=16000)
        except Exception as e:
            print(f"[BATCH] [WARN] 段 {idx + 1} ASR 失败: {e}", flush=True)
            text = ""

        text = (text or "").strip()
        if not text:
            print(f"[BATCH] 段 {idx + 1}/{len(raw_segments)} [{seg_time:.1f}s] 空识别，跳过", flush=True)
            continue

        text, corrections = pinyin_corr.correct_with_keywords(text)

        try:
            if len(seg_audio) < int(16000 * 0.8):
                speaker_label = speaker_mgr.last_speaker_label
            else:
                speaker_label = await speaker_mgr.detect_speaker(seg_audio)
                speaker_mgr.last_speaker_label = speaker_label
        except Exception as e:
            print(f"[BATCH] [WARN] 段 {idx + 1} 说话人识别失败: {e}", flush=True)
            speaker_label = speaker_mgr.last_speaker_label

        segments.append({
            'text': text,
            'time': seg_time,
            'speaker': speaker_label,
            'duration': seg_dur,
            'kw_corrected': len(corrections) > 0,
            'vad': vad_info,
            'corrections': corrections,
            'timestamp': datetime.now().isoformat(),
        })
        preview = text[:50].replace('\n', ' ')
        print(f"[BATCH] 段 {idx + 1}/{len(raw_segments)} [{seg_time:.1f}s] "
              f"{speaker_label}: {preview}{'...' if len(text) > 50 else ''}", flush=True)

    print(f"[BATCH] 合并误切片段...", flush=True)
    merge_short_trailing(segments)
    merge_semantic_continuation(segments)

    return segments, total_dur


def main():
    if len(sys.argv) < 2:
        print("用法: python batch_transcribe.py <音频文件或目录> [输出目录]")
        sys.exit(1)

    input_path = Path(sys.argv[1]).resolve()
    output_dir = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else input_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    if input_path.is_dir():
        audio_files = sorted(
            list(input_path.glob('*.m4a')) +
            list(input_path.glob('*.mp3')) +
            list(input_path.glob('*.wav')) +
            list(input_path.glob('*.flac')) +
            list(input_path.glob('*.ogg'))
        )
    else:
        audio_files = [input_path]

    if not audio_files:
        print(f"[ERROR] 未找到音频文件: {input_path}")
        sys.exit(1)

    print(f"[BATCH] 待处理 {len(audio_files)} 个文件", flush=True)
    for f in audio_files:
        print(f"  - {f.name}")

    config = load_config()
    device = resolve_device(config)
    print(f"[BATCH] 加载 ASR 引擎 (device={device})...", flush=True)
    print(f"[BATCH] GPU: {gpu_info() or '未检测到 NVIDIA GPU（CPU 推理）'}", flush=True)
    _t0 = time.perf_counter()
    engine = ASREngine(device=device, config=config)
    pref = config.get("current_model", "auto")
    if pref == "auto":
        pref = None
    if not engine.load_model(preferred=pref):
        print("[ERROR] 模型加载失败")
        sys.exit(1)
    print(f"[BATCH] ASR 模型: {engine.model_name}", flush=True)

    settings = config.get("model_settings", {})
    vad = VADProcessor(
        vad_silence_threshold=settings.get("vad_threshold", 0.5),
        vad_force_cut=settings.get("vad_force_cut", True),
        vad_force_cut_sec=settings.get("force_cut_sec", 6.0),
        min_speech_duration=settings.get("min_speech_duration", 0.12),
        max_buffer_seconds=settings.get("max_buffer_seconds", 30),
        adaptive=False,  # 与本地模式一致：直接用用户设置的阈值，不做自适应
    )
    vad_engine = settings.get("vad_engine", "silero")
    silero_speech_prob_threshold = settings.get("silero_speech_prob_threshold", 0.5)
    fsmn_speech_noise_threshold = settings.get("fsmn_speech_noise_threshold", 0.6)

    # 说话人模型与严格度跟随全局配置（与本地模式一致）
    sp_model_key = settings.get("speaker_model", "cam++")
    sp_strictness = settings.get("speaker_strictness", "strict")
    same_threshold = STRICTNESS_THRESHOLDS.get(sp_strictness, 0.55)
    print(f"[BATCH] 加载说话人模型 ({sp_model_key}, 严格度={sp_strictness})...", flush=True)
    sv_pipeline = load_speaker_pipeline(sp_model_key)
    threads = settings.get("threads", 8)
    executor = ThreadPoolExecutor(max_workers=threads)
    speaker_mgr = SpeakerManager(
        sv_pipeline=sv_pipeline,
        executor=executor,
        dict_dir=DICT_DIR,
        temp_dir=TEMP_DIR,
        same_threshold=same_threshold,
    )
    pinyin_corr = PinyinCorrector()

    async def run_all():
        for audio_path in audio_files:
            # 每个文件前重置说话人状态，避免跨文件声纹库/标签污染
            speaker_mgr.reset_session()
            speaker_mgr.reset_speaker_profiles()
            try:
                segments, total_dur = await process_audio_file(
                    audio_path, engine, vad, speaker_mgr, pinyin_corr,
                    vad_engine=vad_engine,
                    silero_speech_prob_threshold=silero_speech_prob_threshold,
                    fsmn_speech_noise_threshold=fsmn_speech_noise_threshold,
                )
            except Exception as e:
                print(f"[BATCH] [ERROR] 处理失败 {audio_path.name}: {e}", flush=True)
                continue

            if not segments:
                print(f"[BATCH] [WARN] {audio_path.name} 无有效识别内容，跳过报告生成", flush=True)
                continue

            # 每完成一个文件就立即生成并落盘报告，避免后续文件异常导致已完成结果丢失
            try:
                display_names = speaker_mgr.get_all_display_names()
                report = generate_comprehensive_report(
                    segments=segments,
                    speaker_profiles=speaker_mgr.speaker_profiles,
                    keyword_history=[],
                    total_audio_seconds=total_dur,
                    asr_model_name=engine.model_name or "qwen3-asr",
                    page_type='video',
                    video_offset=0,
                    display_names=display_names,
                    page_creator=None,
                    session_start_time=datetime.now(),
                )
                out_file = output_dir / (audio_path.stem + '.md')
                out_file.write_text(report, encoding='utf-8')
                print(f"[BATCH] 报告已保存: {out_file}", flush=True)
                print(f"        段数: {len(segments)}, 时长: {total_dur:.1f}s", flush=True)
            except Exception as e:
                print(f"[BATCH] [ERROR] 报告生成失败 {audio_path.name}: {e}", flush=True)

    asyncio.run(run_all())

    executor.shutdown(wait=False)
    print(f"\n[BATCH] 全部完成, 总耗时: {format_elapsed(time.perf_counter() - _t0)}", flush=True)


if __name__ == "__main__":
    main()
