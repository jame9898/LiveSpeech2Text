# -*- coding: utf-8 -*-
"""
批量音频转录脚本 — 复用项目 VAD/ASR/说话人分离/报告生成管线
用法: python batch_transcribe.py <音频文件或目录> [输出目录]
"""

import sys
import asyncio
import numpy as np
import librosa
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from core import ASREngine, load_config, resolve_device, MODELS_DIR, DICT_DIR, silence_noisy_loggers
from vad_processor import VADProcessor
from speaker_manager import SpeakerManager
from pinyin_utils import PinyinCorrector
from report_generator import (
    generate_comprehensive_report,
    merge_short_trailing,
    merge_semantic_continuation,
)

TEMP_DIR = Path(__file__).parent / "temp"
TEMP_DIR.mkdir(exist_ok=True)


def load_speaker_pipeline():
    silence_noisy_loggers()
    try:
        from modelscope.pipelines import pipeline
        from modelscope.utils.constant import Tasks

        cam_model_id = 'iic/speech_campplus_sv_zh-cn_16k-common'
        cam_local = None
        for candidate in list(MODELS_DIR.glob('**/speech_campplus_sv_zh-cn_16k-common')):
            if candidate.is_dir() and '.___' not in str(candidate):
                cam_local = str(candidate)
                break

        if cam_local:
            print(f"[SPEAKER] CAM++ from cache: {cam_local}", flush=True)
            return pipeline(task=Tasks.speaker_verification, model=cam_local)
        print(f"[SPEAKER] CAM++ from ModelScope: {cam_model_id}", flush=True)
        return pipeline(
            task=Tasks.speaker_verification,
            model=cam_model_id,
            model_revision='v1.0.0',
        )
    except Exception as e:
        print(f"[SPEAKER] CAM++ load failed: {e}", flush=True)
        return None


def batch_vad(audio, sr, vad):
    """模拟流式 VAD：逐块喂入音频，收集切出的语音段。
    返回 [(seg_audio, seg_time, seg_dur, vad_info), ...]
    """
    chunk_size = int(sr * 0.5)
    buf = np.array([], dtype=np.float32)
    segments = []
    cursor = 0.0
    min_flush_samples = int(sr * 0.3)

    for i in range(0, len(audio), chunk_size):
        chunk = audio[i:i + chunk_size]
        buf = np.concatenate([buf, chunk]) if len(buf) > 0 else chunk.copy()

        while True:
            seg, remaining, vad_info = vad.cut(buf, sr)
            if seg is not None and len(seg) > 0:
                seg_dur = len(seg) / sr
                segments.append((seg, cursor, seg_dur, vad_info))
                cursor += seg_dur
                if remaining is not None:
                    buf = remaining
                else:
                    buf = np.array([], dtype=np.float32)
                    break
            elif remaining is not None:
                buf = remaining
            else:
                break

    if len(buf) > min_flush_samples:
        seg_dur = len(buf) / sr
        vad_info = {'forced': True, 'silence': vad.vad_silence_threshold,
                    'adaptive_coeff': 1.0, 'overlap': 1.3, 'chunk_dur': seg_dur}
        segments.append((buf, cursor, seg_dur, vad_info))

    return segments


async def process_audio_file(audio_path, engine, vad, speaker_mgr, pinyin_corr):
    print(f"\n{'=' * 60}", flush=True)
    print(f"[BATCH] 处理: {audio_path.name}", flush=True)
    print(f"{'=' * 60}", flush=True)

    print("[BATCH] 读取音频...", flush=True)
    audio, sr = librosa.load(str(audio_path), sr=16000, mono=True)
    audio = audio.astype(np.float32)
    total_dur = len(audio) / sr
    print(f"[BATCH] 音频时长: {total_dur:.1f}s, 采样率: {sr}", flush=True)

    print("[BATCH] VAD 切分...", flush=True)
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
        vad_silence_threshold=settings.get("vad_threshold", 0.8),
        vad_force_cut=settings.get("vad_force_cut", True),
        vad_force_cut_sec=settings.get("force_cut_sec", 6.0),
        min_speech_duration=settings.get("min_speech_duration", 0.12),
        max_buffer_seconds=settings.get("max_buffer_seconds", 30),
    )

    print("[BATCH] 加载 CAM++ 说话人模型...", flush=True)
    sv_pipeline = load_speaker_pipeline()
    threads = settings.get("threads", 8)
    executor = ThreadPoolExecutor(max_workers=threads)
    speaker_mgr = SpeakerManager(
        sv_pipeline=sv_pipeline,
        executor=executor,
        dict_dir=DICT_DIR,
        temp_dir=TEMP_DIR,
    )
    pinyin_corr = PinyinCorrector()

    async def run_all():
        results = []
        for audio_path in audio_files:
            segments, total_dur = await process_audio_file(
                audio_path, engine, vad, speaker_mgr, pinyin_corr
            )
            results.append((audio_path, segments, total_dur))
        return results

    results = asyncio.run(run_all())

    print(f"\n{'=' * 60}", flush=True)
    print("[BATCH] 生成报告...", flush=True)
    print(f"{'=' * 60}", flush=True)
    for audio_path, segments, total_dur in results:
        if not segments:
            print(f"[BATCH] [WARN] {audio_path.name} 无有效识别内容，跳过报告生成", flush=True)
            continue

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

    executor.shutdown(wait=False)
    print("\n[BATCH] 全部完成", flush=True)


if __name__ == "__main__":
    main()
