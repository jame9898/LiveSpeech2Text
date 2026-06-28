# -*- coding: utf-8 -*-
"""
在线实时语音识别系统 - WebSocket Server
VAD断句 + KW关键词纠错 + 说话人分离 (CAM++)
"""

import asyncio
import websockets
from websockets.http11 import Response, Headers
import json
import numpy as np
from collections import OrderedDict

import time
import logging
import re
from pathlib import Path
from datetime import datetime

STATUS_PAGE = Path(__file__).parent / "static" / "index.html"
from concurrent.futures import ThreadPoolExecutor
from core import MODELS_DIR, DICT_DIR, silence_noisy_loggers
from pinyin_utils import PinyinCorrector, CATEGORIES, CATEGORY_ICONS
from creator_detector import CreatorDetector
from speaker_manager import SpeakerManager
from text_utils import (
    extract_title_keywords,
    dedup_overlap, dedup_chars, dedup_phrase_repeats,
    normalize_letter_adjacent_numbers,
)
from vad_processor import VADProcessor
from report_generator import generate_comprehensive_report, generate_structured_log, merge_short_trailing, merge_semantic_continuation

logging.getLogger('websockets.server').setLevel(logging.CRITICAL)
logging.getLogger('websockets').setLevel(logging.CRITICAL)

TEMP_DIR = Path(__file__).parent / "temp"
TEMP_DIR.mkdir(exist_ok=True)


class RealtimeASRServer:

    def __init__(self, asr_engine, host='localhost', port=8765):
        self.asr_engine = asr_engine
        self.host = host
        self.port = port

        self.is_running = False
        self.client = None
        self.client_connected = False
        self.recording_ws = None
        self._current_handler_ws = None
        self._clients = set()
        threads = self.asr_engine._config.get("model_settings", {}).get("threads", 8)
        self.executor = ThreadPoolExecutor(max_workers=threads)

        self.full_text = ""
        self.segments = []
        self.keyword_store = {cat: set() for cat in CATEGORIES}
        self._session_new_keywords = set()  # 本会话手动添加的关键词(用于自动保存到画像库)

        self.pinyin_corrector = PinyinCorrector(
            keyword_store=self.keyword_store,
        )

        # 智能纠错引擎（实体识别、模糊匹配、语法检查、置信度评分）
        self.creator_detector = CreatorDetector()

        # 说话人分离 (CAM++ 中英文通用声纹模型)
        print("[SPEAKER] Loading CAM++ speaker verification model...", flush=True)
        sv_pipeline = None
        try:
            silence_noisy_loggers()

            from modelscope.pipelines import pipeline
            from modelscope.utils.constant import Tasks

            cam_model_id = 'iic/speech_campplus_sv_zh-cn_16k-common'
            cam_local = None
            cam_search_paths = [
                MODELS_DIR / 'hub' / 'models' / 'iic' / 'speech_campplus_sv_zh-cn_16k-common',
            ]
            for candidate in list(MODELS_DIR.glob('**/speech_campplus_sv_zh-cn_16k-common')):
                if not candidate.is_dir():
                    continue
                if candidate in cam_search_paths:
                    continue
                if '.___' in str(candidate):
                    continue
                cam_search_paths.insert(0, candidate)
            for p in cam_search_paths:
                if p.is_dir() and '.___' not in str(p):
                    cam_local = str(p)
                    print(f"[SPEAKER] CAM++ from project cache: {cam_local}", flush=True)
                    break

            if cam_local:
                sv_pipeline = pipeline(
                    task=Tasks.speaker_verification,
                    model=cam_local,
                )
            else:
                sv_pipeline = pipeline(
                    task=Tasks.speaker_verification,
                    model=cam_model_id,
                    model_revision='v1.0.0'
                )
            print("[SPEAKER] CAM++ model loaded", flush=True)
        except Exception as e:
            print(f"[SPEAKER] CAM++ load failed: {e}", flush=True)
            print("[SPEAKER] Speaker diarization disabled, ASR will still work", flush=True)
            sv_pipeline = None

        DICT_DIR.mkdir(exist_ok=True)

        self.speaker_manager = SpeakerManager(
            sv_pipeline=sv_pipeline,
            executor=self.executor,
            dict_dir=DICT_DIR,
            temp_dir=TEMP_DIR,
        )

        # 音频缓冲区
        self._audio_buf = np.array([], dtype=np.float32)
        # chunk 累积区：达到阈值后一次性 concatenate 到 _audio_buf，减少全量拷贝频率
        self._audio_buf_chunks = []
        self._audio_buf_chunk_threshold = 16000 * 0.5  # 累积 0.5s 音频后再合并
        self.browser_sample_rate = 48000
        self.target_sample_rate = 16000
        self.max_buffer_seconds = 30
        self.max_buffer_size = 16000 * self.max_buffer_seconds
        self.vad_silence_threshold = self.asr_engine._config.get("model_settings", {}).get("vad_threshold", 0.85)

        self.vad_force_cut = self.asr_engine._config.get("model_settings", {}).get("vad_force_cut", True)
        self.vad_force_cut_sec = self.asr_engine._config.get("model_settings", {}).get("force_cut_sec", 6.0)
        self.min_speech_duration = self.asr_engine._config.get("model_settings", {}).get("min_speech_duration", 0.12)

        # 避免重复发送已识别的文本（LRU 滚动窗口，防止长会话 O(n²) 退化）
        self.sent_texts = OrderedDict()
        self._MAX_SENT_TEXTS = 300

        self.total_audio_seconds = 0
        self.speaker_manager.total_audio_seconds = 0
        self.transcription_count = 0
        self.last_segment_wall_time = 0
        self.last_segment_end_audio_time = 0

        self._session_start_time = None

        self.keyword_history = []

        self._partial_seq = 0  # 递增序号，用于标识partial请求
        self._partial_sent_seq = 0  # 已发送的最大序号（空结果不更新）

        # 连接稳定性
        self.last_activity = time.time()

        print(f"[VAD] vad_force_cut={self.vad_force_cut}", flush=True)

        # 流式模式（伪流式：短chunk快速partial + 整句final修正）
        self._stream_last_partial = ""
        self._stream_partial_time = 0
        self._stream_partial_interval = 0.25
        self._partial_in_flight = False

        # 分片有序提交（解决并发 _finalize_segment 乱序问题）
        self._seg_emit_lock = asyncio.Lock()
        self._next_seg_seq = 0           # 分片提交序号（单调递增）
        self._pending_emit_seq = 0        # 下一个待提交的序号
        self._pending_segments = {}       # {seq: (corrected, corrections, original, audio, vad_info, seg_time, seg_dur)}

        self.vad_processor = VADProcessor(
            vad_silence_threshold=self.vad_silence_threshold,
            vad_force_cut=self.vad_force_cut,
            vad_force_cut_sec=self.vad_force_cut_sec,
            min_speech_duration=self.min_speech_duration,
            max_buffer_seconds=self.max_buffer_seconds,
        )

    def _resample_audio(self, audio_data, from_rate, to_rate):
        if from_rate == to_rate:
            return audio_data
        try:
            from scipy import signal
            return signal.resample_poly(audio_data.astype(np.float64), to_rate, from_rate).astype(np.float32)
        except ImportError:
            ratio = from_rate // to_rate
            if ratio > 1:
                audio = audio_data.astype(np.float64)
                kernel = np.ones(ratio) / ratio
                filtered = np.convolve(audio, kernel, mode='same')
                return filtered[::ratio].astype(np.float32)
            return audio_data.astype(np.float32)

    def _flush_audio_chunks(self):
        """把累积的 chunk 合并到 _audio_buf，确保 _audio_buf 是完整的 ndarray。"""
        if not self._audio_buf_chunks:
            return
        if len(self._audio_buf) > 0:
            self._audio_buf = np.concatenate([self._audio_buf] + self._audio_buf_chunks)
        else:
            self._audio_buf = np.concatenate(self._audio_buf_chunks)
        self._audio_buf_chunks = []

    async def handler(self, websocket):
        self._current_handler_ws = websocket
        try:
            await websocket.send(json.dumps({
                'type': 'welcome',
                'message': 'Realtime ASR service connected',
                'model': self.asr_engine.model_name,
                'timestamp': datetime.now().isoformat()
            }, ensure_ascii=False))

            print(f"[WS] Client connected: {websocket.remote_address}")
            self.client = websocket
            self.client_connected = True
            self._clients.add(websocket)

            async for message in websocket:
                if isinstance(message, bytes):
                    await self.process_audio(message, websocket)
                elif isinstance(message, str):
                    await self.handle_control_message(json.loads(message), websocket)

        except websockets.exceptions.ConnectionClosedOK:
            print("[WS] Client disconnected normally")
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"[WS] Client disconnected: {e}")
        except Exception as e:
            print(f"[WS] Error: {e}")
        finally:
            self._clients.discard(websocket)
            if self.client is websocket:
                self.client = None
                self.client_connected = False
            if self.recording_ws is websocket:
                self.recording_ws = None
                self.is_running = False
                print("[WS] Recording client disconnected")
            if self._current_handler_ws is websocket:
                self._current_handler_ws = None

    async def handle_control_message(self, msg, websocket):
        msg_type = msg.get('type')
        try:
            if msg_type == 'start':
                # 单录制互斥：已有一个页面在录音时，新页面拒绝
                if self.recording_ws and self.recording_ws is not websocket:
                    await self._send_to(websocket, {
                        'type': 'error',
                        'message': '另一个页面正在录音，请先停止后再试'
                    })
                    print(f"[WS] Start rejected: another client is recording")
                    return
                self.is_running = True
                self.recording_ws = websocket
                self._session_start_time = datetime.now()
                self._reset_session_state()
                await self._send_to(websocket, {
                    'type': 'status', 'status': 'recording',
                    'message': 'Started', 'model': self.asr_engine.model_name,
                    'keywords': list(self.pinyin_corrector.kw_set)
                })
                print("[WS] Recording started")
                for client in list(self._clients):
                    if client is not websocket:
                        try:
                            await self._send_to(client, {'type': 'recording_state', 'recording': True})
                        except Exception:
                            pass

            elif msg_type == 'stop':
                if self.recording_ws is websocket:
                    self.recording_ws = None
                self.is_running = False
                # Flush remaining buffer（降低阈值：>=最小语音段即可转录，避免结尾丢字）
                min_flush_samples = int(self.min_speech_duration * 16000)
                self._flush_audio_chunks()
                remaining_buf = self._audio_buf.copy()
                if len(remaining_buf) >= max(min_flush_samples, 4000):
                    remaining_dur = len(remaining_buf) / 16000
                    print(f"[WS] stop: 刷新剩余缓冲区 {remaining_dur:.1f}s", flush=True)
                    await self._finalize_segment(remaining_buf, {'voice_start': 0, 'voice_end': remaining_dur, 'seg_type': 'flush'})
                elif len(remaining_buf) > 800:
                    print(f"[WS] stop: 刷新极短尾音 {len(remaining_buf)/16000:.2f}s", flush=True)
                    await self._finalize_segment(remaining_buf, {'voice_start': 0, 'voice_end': len(remaining_buf)/16000, 'seg_type': 'flush'})
                self._audio_buf = np.array([], dtype=np.float32)
                self._audio_buf_chunks = []
                await self._send_to(websocket, {
                    'type': 'status', 'status': 'stopped',
                    'message': 'Stopped', 'full_text': self.full_text.strip(),
                    'segments': self.segments
                })

                print("[WS] Recording stopped")
                for client in list(self._clients):
                    if client is not websocket:
                        try:
                            await self._send_to(client, {'type': 'recording_state', 'recording': False})
                        except Exception:
                            pass

            elif msg_type == 'clear':
                self._reset_session_state(reset_speakers=True)
                self.pinyin_corrector.kw_set.clear()
                await self._send_to(websocket, {'type': 'status', 'status': 'cleared'})
                await self._send_to(websocket, {'type': 'keywords_updated', 'keywords': []})

            elif msg_type == 'update_keywords':
                keywords = msg.get('keywords', [])
                kcat = msg.get('category', 'other')
                if isinstance(keywords, list) and keywords:
                    added = set()
                    for kw in keywords:
                        kw = str(kw).strip()
                        if kw and len(kw) >= 2 and kw not in self.pinyin_corrector.kw_set:
                            self.keyword_store.setdefault(kcat, set()).add(kw)
                            self.pinyin_corrector.kw_set.add(kw)
                            added.add(kw)
                            self.keyword_history.append({'time': datetime.now().strftime('%H:%M:%S'), 'keyword': kw, 'category': kcat})
                    if added:
                        print(f"[KW] New keywords [{CATEGORIES.get(kcat, '关键词')}]: {list(added)[:10]}")

            elif msg_type == 'generate_report':
                await self.generate_and_send_report(websocket)

            elif msg_type == 'page_creator':
                self.speaker_manager.set_page_info(
                    creator=msg.get('creator'),
                    platform=msg.get('platform'),
                    page_type=msg.get('page_type', 'web'),
                    video_offset=msg.get('video_offset', 0),
                )

                print(f"[WS] 页面信息: 创作者={self.speaker_manager.page_creator} 平台={self.speaker_manager.page_platform} 类型={self.speaker_manager.page_type} 偏移={self.speaker_manager.video_offset}s", flush=True)

                # 网页端无 creator 但提供了 URL 时，尝试服务端抓取页面提取 UP 主名
                page_url = msg.get('url', '')
                if not msg.get('creator') and page_url:
                    asyncio.ensure_future(self._auto_detect_creator(page_url, websocket))

            elif msg_type == 'new_speaker':
                name = msg.get('name', f'发言人{self.speaker_manager.last_speaker_id}')
                for profile in self.speaker_manager.speaker_profiles:
                    if profile['label'] == f"Speaker{msg.get('id', 0)}":
                        profile['alias'] = name
                        break

            elif msg_type == 'ping':
                await self._send_to(websocket, {'type': 'pong'})

            elif msg_type == 'keyword_add':
                keyword = msg.get('keyword', '').strip()
                cat = msg.get('category', 'other')
                if cat not in CATEGORIES:
                    cat = 'other'
                if keyword and len(keyword) >= 2:
                    self.keyword_store[cat].add(keyword)
                    self.pinyin_corrector.kw_set.add(keyword)
                    all_kws = self._get_all_keywords()
                    self.keyword_history.append({
                        'time': datetime.now().strftime('%H:%M:%S'),
                        'keyword': keyword, 'category': cat
                    })
                    icon = CATEGORY_ICONS.get(cat, '')
                    print(f"[WS] {icon}添加关键词 [{CATEGORIES[cat]}]: {keyword} (共{len(all_kws)}个)", flush=True)
                    self._session_new_keywords.add(keyword)
                    await self._send_keywords_updated(websocket)

                    if cat == 'speaker':
                        self.speaker_manager.add_active_speaker(keyword)

            elif msg_type == 'video_title':
                title = msg.get('title', '').strip()
                if title:
                    extracted = extract_title_keywords(title)
                    added = 0
                    for kw in extracted:
                        if kw and len(kw) >= 2 and kw not in self.pinyin_corrector.kw_set:
                            self.pinyin_corrector.kw_set.add(kw)
                            added += 1
                    if added:
                        print(f"[WS] 📺 标题提取: '{title[:40]}' → {added}个关键词", flush=True)
                        await self._send_keywords_updated(websocket)

            elif msg_type == 'speaker_profile_get':
                speaker_id = msg.get('speaker_id', self.speaker_manager.last_speaker_label)
                await self._send_to(websocket, {
                    'type': 'speaker_profile',
                    'speaker_id': speaker_id,
                    'label': speaker_id,
                    'all_speakers': [p.get('label', '') for p in self.speaker_manager.speaker_profiles],
                })


            elif msg_type == 'speaker_rename':
                speaker_id = msg.get('speaker_id', '')
                new_label = msg.get('label', '')
                if speaker_id and new_label:
                    self.speaker_manager.rename_speaker(speaker_id, new_label)
                    print(f"[WS] 重命名: {speaker_id} → {new_label}", flush=True)
                    await self._send_to(websocket, {
                        'type': 'speaker_renamed',
                        'old_id': speaker_id,
                        'new_label': new_label,
                    })

            elif msg_type == 'save_report':
                display_names = self._prepare_report_data()
                report = generate_comprehensive_report(
                    self.segments, self.speaker_manager.speaker_profiles,
                    self.keyword_history,
                    self.total_audio_seconds,
                    self.asr_engine.model_name,
                    self.speaker_manager.page_type, self.speaker_manager.video_offset,
                    display_names=display_names,
                    page_creator=self.speaker_manager.page_creator,
                    session_start_time=getattr(self, '_session_start_time', None),
                )
                await self._send_to(websocket, {'type': 'save_report', 'content': report, 'filename': f'asr_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.md'})

            elif msg_type == 'save_log':
                display_names = self._prepare_report_data()
                log = generate_structured_log(
                    self.segments, self.speaker_manager.speaker_profiles,
                    self.keyword_history,
                    self.total_audio_seconds,
                    self.asr_engine.model_name if self.asr_engine else 'unknown',
                    self.speaker_manager.page_type, self.speaker_manager.video_offset,
                    display_names=display_names,
                    page_creator=self.speaker_manager.page_creator,
                )
                await self._send_to(websocket, {'type': 'save_log', 'content': log, 'filename': f'asr_log_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'})

        except Exception as e:
            print(f"[WS] Control error: {e}")
            await self._send_to(websocket, {'type': 'error', 'message': '处理请求时发生内部错误'})

    def _get_all_keywords(self):
        """获取所有分类的去重关键词"""
        return list(self.pinyin_corrector.kw_set)

    def _reset_session_state(self, reset_speakers=False):
        """重置会话状态（start 和 clear 共享的重置逻辑）
        统一管理所有会话级状态的重置，确保不遗漏
        """
        # 文本与片段
        self.full_text = ""
        self.segments = []
        self.sent_texts = OrderedDict()

        # 音频缓冲
        self._audio_buf = np.array([], dtype=np.float32)
        self._audio_buf_chunks = []

        # 关键词
        self.keyword_store = {cat: set() for cat in CATEGORIES}
        self.keyword_history = []
        self._session_new_keywords = set()

        # 时间统计
        self.total_audio_seconds = 0
        self.speaker_manager.total_audio_seconds = 0
        self.transcription_count = 0
        self.last_segment_wall_time = 0
        self.last_segment_end_audio_time = 0

        # 流式模式状态
        self._partial_seq = 0
        self._partial_sent_seq = 0
        self._stream_last_partial = ""
        # 首帧加速：0.15s 后即可发第一次 partial，不等 interval 走完
        self._stream_partial_time = time.time() - self._stream_partial_interval + 0.15

        # 子模块会话重置
        self.pinyin_corrector.reset_session()
        self.speaker_manager.reset_session()
        self.vad_processor.reset()

        # 说话人档案（仅在 clear 时清空）
        if reset_speakers:
            self.speaker_manager.reset_speaker_profiles()

    async def _send_keywords_updated(self, websocket, extra=None):
        """发送 keywords_updated 消息，附加可选 extra 字段"""
        msg = {
            'type': 'keywords_updated',
            'keywords': list(self.pinyin_corrector.kw_set),
            'keyword_store': {c: list(v) for c, v in self.keyword_store.items() if v},
            'categories': CATEGORIES,
            'category_icons': CATEGORY_ICONS,
        }
        if extra:
            msg.update(extra)
        await self._send_to(websocket, msg)

    async def process_audio(self, audio_data, websocket):
        if not self.is_running or websocket is not self.recording_ws:
            return
        loop = asyncio.get_running_loop()
        try:
            audio_array = np.frombuffer(audio_data, dtype=np.float32)

            if self.browser_sample_rate != self.target_sample_rate:
                audio_array = self._resample_audio(
                    audio_array, self.browser_sample_rate, self.target_sample_rate)

            # 累积 chunk，达到阈值后一次性 concatenate，避免每次 np.append 全量拷贝（O(n²) 退化）
            self._audio_buf_chunks.append(audio_array)
            if sum(len(c) for c in self._audio_buf_chunks) >= self._audio_buf_chunk_threshold:
                self._flush_audio_chunks()

            # 每0.25s发一次实时字幕条（纯定时器，不与完整转录耦合）
            # 只对最近3秒音频做ASR，避免buffer滚大后延迟越来越高
            # _partial_in_flight 防止 executor 队列堆积导致延迟线性增长
            now = time.time()
            if now - self._stream_partial_time >= self._stream_partial_interval:
                self._stream_partial_time = now
                self._flush_audio_chunks()
                buf = self._audio_buf
                if len(buf) / 16000 >= 0.2 and not self._partial_in_flight:
                    max_partial_samples = 3 * self.target_sample_rate  # 只取最近3秒
                    if len(buf) > max_partial_samples:
                        buf = buf[-max_partial_samples:]
                    # 同步置位标志，防止 event loop 调度下一个 process_audio 时重复创建 partial task
                    self._partial_in_flight = True
                    asyncio.ensure_future(self._send_streaming_partial(buf.copy()))

            # 每0.5秒检查一次是否可以转录
            self._flush_audio_chunks()
            buffer_dur = len(self._audio_buf) / 16000
            if buffer_dur >= 0.5 and len(self._audio_buf) > 0:
                # 用VAD检测是否有完整的语音段
                # VAD 是 CPU 密集同步操作，丢进 executor 避免阻塞 event loop
                audio_seg, remaining, vad_info = await loop.run_in_executor(
                    self.executor, self.vad_processor.cut, self._audio_buf, 16000
                )

                if audio_seg is not None and len(audio_seg) > int(self.min_speech_duration * 16000):
                    # 统一ASR管线：一次识别，同时输出 partial(字幕条) + transcription(右边记录)
                    asyncio.ensure_future(self._finalize_segment(audio_seg, vad_info))
                    if remaining is not None:
                        self._audio_buf = remaining if len(remaining) > 0 else np.array([], dtype=np.float32)
                elif remaining is not None:
                    self._audio_buf = remaining if len(remaining) > 0 else np.array([], dtype=np.float32)

                # 限制缓冲区大小：优先保留头部旧音频（未转写的语音段）
                if len(self._audio_buf) > self.max_buffer_size:
                    overflow_sec = (len(self._audio_buf) - self.max_buffer_size) / 16000
                    # 保留前 70% 旧音频（含待转写段）+ 后 30% 新音频
                    keep_old = int(self.max_buffer_size * 0.7)
                    keep_new = self.max_buffer_size - keep_old
                    self._audio_buf = np.concatenate([
                        self._audio_buf[:keep_old],
                        self._audio_buf[-keep_new:],
                    ])
                    print(f"[WS] ⚠ 音频缓冲区溢出，丢弃中间{overflow_sec:.1f}s "
                          f"(保留头部待转写段+尾部新音频)", flush=True)

        except Exception as e:
            print(f"[WS] Audio error: {e}")
            import traceback
            traceback.print_exc()

    async def _send_streaming_partial(self, audio_array):
        """实时字幕条：快速ASR → 去重/格式化 → 发送partial到前端。

        字幕条是唯一的文本生产管线，右侧 speaker 面板不再跑独立 ASR，
        而是直接使用字幕条的当前文本（见 _finalize_segment）。

        _partial_sent_seq 仅在有文本成功发送时更新，避免空结果误杀旧partial。
        _partial_in_flight 确保同一时间最多1个ASR partial在跑，防止executor队列堆积。

        防反复修正：如果新文本比旧文本短且旧文本以新文本结尾（3s窗口滑动导致），
        不更新字幕条，保持已显示的较长文本，避免"今天天气不错"→"天气不错"→"不错"的抖动。
        """
        self._partial_in_flight = True
        self._partial_seq += 1
        my_seq = self._partial_seq
        try:
            # 静音跳过
            rms = np.sqrt(np.mean(np.asarray(audio_array, dtype=np.float32) ** 2))
            if rms < 0.002:
                return

            loop = asyncio.get_running_loop()
            raw_text = await loop.run_in_executor(
                self.executor, self.asr_engine.transcribe_array, audio_array, 16000)

            if not raw_text or not raw_text.strip():
                return

            raw_text = raw_text.strip()

            # 同 _finalize_segment 管线：段间去重 + 字符去重 + 短语去重 + 格式化
            if self.segments:
                prev = self.segments[-1]['text']
                raw_text = dedup_overlap(prev, raw_text)
                if not raw_text:
                    return
            raw_text = dedup_chars(raw_text)
            raw_text = dedup_phrase_repeats(raw_text)
            if not raw_text:
                return
            raw_text = normalize_letter_adjacent_numbers(raw_text)
            if not raw_text or not raw_text.strip():
                return

            # 与上次发送的文本相同 → 跳过
            if raw_text == self._stream_last_partial:
                return

            # 防反复修正：新文本比旧文本短且旧文本以新文本结尾
            # 说明是3s滑动窗口导致的截断（如"今天天气不错"→"天气不错"），保持长文本
            if (self._stream_last_partial
                    and len(raw_text) < len(self._stream_last_partial)
                    and self._stream_last_partial.endswith(raw_text)):
                return

            # 有更新的 partial 已发送 → 本 partial 过时
            if my_seq <= self._partial_sent_seq:
                return

            self._partial_sent_seq = my_seq
            self._stream_last_partial = raw_text

            await self.send({
                'type': 'partial',
                'text': raw_text,
            })
        except Exception as e:
            print(f"[WS] Partial error: {e}", flush=True)
            import traceback
            traceback.print_exc()
        finally:
            self._partial_in_flight = False

    async def _finalize_segment(self, audio_seg, vad_info):
        """段边界处理：VAD 检测到说话结束 → 字幕条对完整段做最终 ASR → 直接复制到 speaker 面板。

        字幕条是唯一的文本生产管线：
        - 说话中：字幕条用 3s 滑动窗口做实时预览（快速反馈）
        - VAD 切段时：字幕条对完整音频段做最终 ASR，修正后的文本就是最终版本
        - speaker 面板直接复制字幕条的最终文本，不做第二次 ASR

        使用分片序号 + 有序队列，确保 transcription 按 VAD 检测顺序发送。
        """
        seg_seq = self._next_seg_seq
        self._next_seg_seq += 1
        seg_audio_time = self.total_audio_seconds
        seg_duration = len(audio_seg) / 16000

        seg_data = None

        try:
            # 字幕条管线：对完整音频段做最终 ASR（替代 3s 窗口预览，确保不漏字）
            loop = asyncio.get_running_loop()
            raw_text = await loop.run_in_executor(
                self.executor, self.asr_engine.transcribe_array, audio_seg, 16000)

            if not raw_text or not raw_text.strip():
                dur = len(audio_seg) / 16000
                if dur >= 0.3:
                    print(f"    [SEG] ASR 无文本 ({dur:.1f}s) — 已跳过", flush=True)
                return

            text = raw_text.strip()

            # 字幕条标准后处理管线：字符去重 + 短语去重 + 格式化
            text = dedup_chars(text)
            text = dedup_phrase_repeats(text)
            if not text:
                return
            text = normalize_letter_adjacent_numbers(text)
            if not text or not text.strip():
                return

            # 段间去重：与上一个 segment 的重叠部分
            if self.segments:
                prev = self.segments[-1]['text']
                text = dedup_overlap(prev, text)
            if not text:
                return

            # 句子级别去重：与上一段完全相同 → 跳过
            if self.segments and self.segments[-1]['text'] == text:
                return

            # 全局精确去重：近期已发送过完全相同的文本 → 跳过
            if text in self.sent_texts:
                print(f"    [DEDUP] 重复文本已跳过: {text[:40]}", flush=True)
                return

            # 关键词拼音纠正（输出前最后一步）：关键词→拼音→匹配文本→替换
            # 例如：关键词"寅子"，ASR输出"银子" → 拼音都是 yin+zi → 替换为"寅子"
            text, kw_corrections = self.pinyin_corrector.correct_with_keywords(text)
            kw_applied = len(kw_corrections) > 0
            if kw_applied:
                for orig, corr in kw_corrections:
                    print(f"    [KW] 关键词纠正: {orig} → {corr}", flush=True)

            # 更新字幕条为最终文本（字幕条从预览模式切换到最终版本）
            self._stream_last_partial = text
            await self.send({
                'type': 'partial',
                'text': text,
            })

            seg_data = (text, kw_corrections, raw_text.strip(),
                        audio_seg, vad_info, seg_audio_time, seg_duration, kw_applied)

        except Exception as e:
            print(f"[WS] Segment error: {e}", flush=True)
            import traceback
            traceback.print_exc()
        finally:
            async with self._seg_emit_lock:
                self._pending_segments[seg_seq] = seg_data

                while self._pending_emit_seq in self._pending_segments:
                    data = self._pending_segments.pop(self._pending_emit_seq)

                    if data is not None:
                        (corr, corrs, orig, audio, vi, seg_time, seg_dur, kw_applied) = data

                        # 阻止并发 raw partial 覆盖
                        self._partial_sent_seq = self._partial_seq
                        # 清空字幕条缓存，让字幕条从新段重新开始显示
                        self._stream_last_partial = ""

                        await self._emit_segment(audio, corr, kw_applied, vad_info=vi,
                                                  corrections=corrs, original_text=orig,
                                                  seg_audio_time=seg_time, seg_duration=seg_dur)

                        status = f"[WS] [{self.transcription_count}] [SEG]"
                        print(f"{status} {corr[:60]}...", flush=True)

                    self._pending_emit_seq += 1

    async def _emit_segment(self, audio_data, text, kw_applied=False, speaker_label=None,
                            vad_info=None, corrections=None, original_text=None,
                            seg_audio_time=None, seg_duration=None):
        """创建一条识别记录并发送到前端"""

        # 如果调用方已提供 speaker_label（多句 chunk 共享），直接使用
        if speaker_label is not None:
            pass
        # 短音频不跑声纹（<0.8s 的片段嵌入向量不稳定），直接用上一个说话人
        elif len(audio_data) < int(16000 * 0.8):
            speaker_label = self.speaker_manager.last_speaker_label
        # 极短文本片段：中文<3字 且 非中文<5字母 → VAD强制切分尾部碎片，继承说话人
        # 英文/俄语等纯字母文本（如 "Hello" 或 "Привет"）满足中文字数=0，但仍有有效语音内容
        # 需同时检查非中文字符数，避免外语语音永远不走 CAM++
        elif text:
            cn_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
            non_cn_chars = len(re.findall(r'[a-zA-Z\u0400-\u04FF]', text))
            if cn_chars < 3 and non_cn_chars < 5:
                speaker_label = self.speaker_manager.last_speaker_label
                print(f"    [SPEAKER] 短文本片段({cn_chars}字+{non_cn_chars}字母) "
                      f"继承说话人: {speaker_label}", flush=True)
            else:
                # 声纹检测前做能量预检：极低能量片段可能只有噪声，跳过以避免污染声纹库
                rms = np.sqrt(np.mean(np.asarray(audio_data, dtype=np.float32) ** 2))
                if rms < 0.003:
                    speaker_label = self.speaker_manager.last_speaker_label
                    print(f"    [SPEAKER] 低能量片段(RMS={rms:.4f})继承说话人: {speaker_label}", flush=True)
                else:
                    speaker_label = await self.speaker_manager.detect_speaker(audio_data)
                    self.speaker_manager.last_speaker_label = speaker_label
        else:
            speaker_label = await self.speaker_manager.detect_speaker(audio_data)
            self.speaker_manager.last_speaker_label = speaker_label

        # 使用提交时捕获的时间戳（避免并发完成乱序导致时间错误）
        if seg_audio_time is None:
            seg_audio_time = self.total_audio_seconds
        if seg_duration is None:
            seg_duration = len(audio_data) / 16000
        now_wall = time.time()

        gap_audio = 0.0
        gap_wall = 0.0
        if self.last_segment_wall_time > 0:
            gap_wall = now_wall - self.last_segment_wall_time
            gap_audio = seg_audio_time - self.last_segment_end_audio_time

        self.last_segment_wall_time = now_wall
        self.last_segment_end_audio_time = seg_audio_time + seg_duration

        display_name = self.speaker_manager.get_speaker_display(speaker_label)

        seg_entry = {
            'text': text,
            'time': seg_audio_time,
            'speaker': speaker_label,
            'speaker_display': display_name,
            'duration': seg_duration,
            'kw_corrected': kw_applied,
            'timestamp': datetime.now().isoformat(),
            'vad': vad_info or {},
            'gap_audio': gap_audio,
            'gap_wall': gap_wall,
            'corrections': corrections or [],
        }
        self.segments.append(seg_entry)
        # 仅在乱序时排序（正常时序下新 segment 时间戳递增，无需排序）
        if len(self.segments) > 1 and seg_audio_time < self.segments[-2].get('time', 0):
            self.segments.sort(key=lambda s: s['time'])

        if display_name and display_name != "Speaker":
            display = f"[{display_name}] {text}"
        else:
            display = text

        self.full_text += display + " "
        # LRU 滚动窗口：超出上限时弹出最旧的，避免长会话去重失效
        self.sent_texts[text] = True
        if len(self.sent_texts) > self._MAX_SENT_TEXTS:
            self.sent_texts.popitem(last=False)
        # total_audio_seconds 在 segment 成功创建时推进（空识别不回滚）
        if seg_duration and seg_duration > 0:
            self.total_audio_seconds += seg_duration
            self.speaker_manager.total_audio_seconds = self.total_audio_seconds
        self.transcription_count += 1

        await self.send({
            'type': 'transcription',
            'text': text,
            'speaker': display_name,
            'speaker_label': speaker_label,
            'full_text': self.full_text.strip(),
            'timestamp': datetime.now().isoformat(),
            'duration': self.total_audio_seconds,
            'seg_time': seg_audio_time,
            'seg_dur': seg_duration,
            'gap_audio': gap_audio,
            'gap_wall': gap_wall,
            'keywords': list(self.pinyin_corrector.kw_set)[:10],
            'kw_corrected': kw_applied,
            'kw_count': len(self.pinyin_corrector.kw_set),
            'corrections': corrections or [],
            'original_text': original_text or text,
            'is_host': speaker_label == self.speaker_manager.host_speaker_label if speaker_label else False,
        })

    async def _auto_detect_creator(self, page_url, websocket):
        """通过平台 API 提取 UP 主 / 主播名（代理到 CreatorDetector）"""
        try:
            creator, platform, page_type = await self.creator_detector.detect_creator(page_url)
            if not creator:
                print(f"[WS] 未识别到创作者 (URL={page_url[:60]})", flush=True)
                return

            self.speaker_manager.set_page_info(creator=creator, platform=platform, page_type=page_type)
            self.speaker_manager.add_active_speaker(creator)
            print(f"[WS] 自动识别创作者: {creator} (from {page_url[:60]})", flush=True)

            await self._send_to(websocket, {
                "type": "page_creator",
                "creator": creator,
                "platform": platform,
                "page_type": page_type,
                "video_offset": self.speaker_manager.video_offset,
            })
            await self._send_to(websocket, {
                "type": "keyword_added",
                "keyword": creator,
                "category": "speaker",
            })
            await self._send_to(websocket, {
                "type": "toast",
                "text": f"✅ 自动识别创作者: {creator}",
                "ok": True,
            })
        except Exception as e:
            print(f"[WS] 自动识别创作者失败: {e}", flush=True)

    def _prepare_report_data(self):
        """准备报告所需的公共数据（修复短尾句 + 语义合并 + 获取显示名称）"""
        merge_short_trailing(self.segments)
        merge_semantic_continuation(self.segments)
        return self.speaker_manager.get_all_display_names()

    async def generate_and_send_report(self, websocket):
        display_names = self._prepare_report_data()
        report = generate_comprehensive_report(
            self.segments, self.speaker_manager.speaker_profiles,
            self.keyword_history,
            self.total_audio_seconds,
            self.asr_engine.model_name,
            self.speaker_manager.page_type, self.speaker_manager.video_offset,
            display_names=display_names,
            page_creator=self.speaker_manager.page_creator,
            session_start_time=getattr(self, '_session_start_time', None),
        )
        await self._send_to(websocket, {'type': 'report', 'content': report})

    async def _send_to(self, websocket, message):
        try:
            await websocket.send(json.dumps(message, ensure_ascii=False))
        except Exception as e:
            print(f"[WS] Send failed: {e}")
            self._clients.discard(websocket)

    async def send(self, message):
        for ws in list(self._clients):
            await self._send_to(ws, message)

    async def start(self):
        page = STATUS_PAGE.read_text(encoding='utf-8').replace("{host}", self.host).replace("{port}", str(self.port))
        async def process_request(connection, request):
            path = request.path if hasattr(request, 'path') else '/'
            print(f"[WS] HTTP request: {path}", flush=True)
            if request.headers.get("Upgrade", "").lower().strip() == "websocket":
                print(f"[WS] WebSocket upgrade request", flush=True)
                return None
            h = Headers()
            h['Connection'] = 'close'

            h['Content-Type'] = 'text/html; charset=utf-8'
            print(f"[WS] Serving status page ({len(page)} bytes)", flush=True)
            return Response(200, "OK", h, page.encode("utf-8"))

        print(f"\n[WS] WebSocket server: ws://{self.host}:{self.port}", flush=True)
        print(f"[WS] Status page:     http://{self.host}:{self.port}", flush=True)
        async with websockets.serve(
            self.handler, self.host, self.port,
            ping_interval=20, ping_timeout=60, close_timeout=10,
            max_size=2**24,
            process_request=process_request,
        ):
            print("[WS] Service ready", flush=True)
            self._shutdown_event = asyncio.Event()
            # 保存 event loop 引用，供主线程跨线程唤醒（asyncio.Event.set() 非线程安全）
            self._loop = asyncio.get_running_loop()
            await self._shutdown_event.wait()  # 阻塞直到外部调用 _shutdown_event.set()
            print("[WS] Shutting down...", flush=True)


_global_server = None

def run_server(asr_engine, host='localhost', port=8765):
    global _global_server
    server = RealtimeASRServer(asr_engine, host, port)
    _global_server = server
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("\n[WS] Stopped")
    except Exception as e:
        print(f"\n[WS] Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        _global_server = None
