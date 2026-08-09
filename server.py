# -*- coding: utf-8 -*-
"""
在线实时语音识别系统 - WebSocket Server
VAD断句 + KW关键词纠错 + 说话人分离 (CAM++)
"""

import asyncio
import websockets
from websockets.http11 import Response, Headers
from websockets.protocol import State
import json
import numpy as np
from collections import OrderedDict

import time
import logging
import re
from pathlib import Path
from datetime import datetime

STATUS_PAGE = Path(__file__).parent / "static" / "index.html"
SUBTITLE_PAGE = Path(__file__).parent / "static" / "subtitle.html"
from concurrent.futures import ThreadPoolExecutor
from core import DICT_DIR, resolve_device
from common_utils import (
    resample_audio, SPEAKER_MODEL_MAP, STRICTNESS_THRESHOLDS, load_speaker_pipeline,
)
from pinyin_utils import PinyinCorrector, CATEGORIES, CATEGORY_ICONS
from creator_detector import CreatorDetector
from speaker_manager import SpeakerManager
from text_utils import (
    dedup_overlap,
    normalize_letter_adjacent_numbers,
)
from vad_processor import VADProcessor, SileroStreamingVAD
from report_generator import generate_comprehensive_report, generate_structured_log
from dataset_manager import get_dataset_manager

logging.getLogger('websockets.server').setLevel(logging.CRITICAL)
logging.getLogger('websockets').setLevel(logging.CRITICAL)

TEMP_DIR = Path(__file__).parent / "temp"
TEMP_DIR.mkdir(exist_ok=True)


def _load_speaker_pipeline(config):
    """加载说话人识别 pipeline。返回 (sv_pipeline, sp_model_info) 或 (None, info) 失败时。
    抽取自 RealtimeASRServer.__init__，便于在模型延迟加载场景下复用。"""
    sp_model_key = config.get("model_settings", {}).get("speaker_model", "cam++")
    sp_model_info = SPEAKER_MODEL_MAP.get(sp_model_key, SPEAKER_MODEL_MAP["cam++"])
    print(f"[SPEAKER] Loading {sp_model_info['label']} speaker model (key={sp_model_key})...", flush=True)
    sv_pipeline = load_speaker_pipeline(sp_model_key)
    if sv_pipeline is None:
        print("[SPEAKER] Speaker diarization disabled, ASR will still work", flush=True)
    return sv_pipeline, sp_model_info


class RealtimeASRServer:

    def __init__(self, asr_engine=None, host='localhost', port=8765, config=None):
        """初始化服务。
        - asr_engine: ASR 引擎（可选，用于立即就绪场景）；为 None 时启用延迟加载，需后续调用 set_asr_engine
        - config: 配置字典（必需，用于初始化 VAD/说话人等子组件）
        """
        self.asr_engine = asr_engine
        # 配置直接存储，避免依赖 asr_engine._config（asr_engine 可能为 None）
        self._config = config or {}
        self.host = host
        self.port = port

        # 模型就绪标志：asr_engine 非 None 表示启动时已加载完成
        self._model_ready = asr_engine is not None
        self._model_error = None
        # asyncio 事件循环引用（set_asr_engine 需要 call_soon_threadsafe 跨线程通知）
        self._loop = None
        # 模型未就绪时排队的 start 请求：[(msg, ws), ...]
        # 模型加载完成后由 _process_pending_starts 重新处理
        self._pending_starts = []

        self.is_running = False
        self.client = None
        self.client_connected = False
        self.recording_ws = None
        self._recording_mode = 'audience'  # 当前录音客户端的模式：audience/streamer/meeting
        self._current_handler_ws = None
        self._clients = set()
        # 桌面观察者客户端：观众模式下，桌面 app 连接但不录音，需要接收字幕显示
        # 通过 observer 消息标识自己，与 OBS 字幕页/其他浏览器插件区分
        self._observer_clients = set()
        # 后训练数据集来源标识：录音开始时设置为 YYYYMMDDHHMM 格式（如 202607111230）
        # 作为第三级目录名，对应"这段录音开始于 xxx"
        self._session_source_name = None
        threads = self._config.get("model_settings", {}).get("threads", 8)
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
        # 说话人识别模型选择：cam++ / eres2netv2 / eres2net
        # 默认 cam++（CAM++ 通用中英文），可切换到 ERes2NetV2（精度更高）或 ERes2Net base（3D-Speaker）
        sp_strictness = self._config.get("model_settings", {}).get("speaker_strictness", "strict")
        # asr_engine 为 None 时延迟加载说话人模型（避免阻塞 WebSocket 启动）
        if asr_engine is not None:
            sv_pipeline, _ = _load_speaker_pipeline(self._config)
        else:
            sv_pipeline = None
            print("[SPEAKER] Deferred: will load after ASR engine set", flush=True)

        DICT_DIR.mkdir(exist_ok=True)

        # 严格度阈值传给 SpeakerManager
        _same_threshold = STRICTNESS_THRESHOLDS.get(sp_strictness, 0.55)
        self.speaker_manager = SpeakerManager(
            sv_pipeline=sv_pipeline,
            executor=self.executor,
            dict_dir=DICT_DIR,
            temp_dir=TEMP_DIR,
            same_threshold=_same_threshold,
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
        self.vad_silence_threshold = self._config.get("model_settings", {}).get("vad_threshold", 0.5)

        self.vad_force_cut = self._config.get("model_settings", {}).get("vad_force_cut", True)
        self.vad_force_cut_sec = self._config.get("model_settings", {}).get("force_cut_sec", 6.0)
        self.min_speech_duration = self._config.get("model_settings", {}).get("min_speech_duration", 0.12)
        # VAD 引擎选择（实时模式同样生效）：
        #   silero = 流式神经网络 VAD（推荐，实时可用）
        #   energy = 能量阈值（无依赖、最快）
        #   fsmn  = 批处理接口，仅本地模式可用，实时模式回退 energy
        self.vad_engine = self._config.get("model_settings", {}).get("vad_engine", "silero")

        # 避免重复发送已识别的文本（仅近邻去重，防止把用户复述的短句误删）
        # 原窗口 300 过大：用户重复说"然后呢/好吧/对"等短句会被当成幻觉重复整段丢弃
        self.sent_texts = OrderedDict()
        self._MAX_SENT_TEXTS = 5

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
        # CPU 模式下 Qwen3-ASR 单次推理 2-5s：若保持 GPU 的 0.3s 刷新频率，
        # partial 会在 executor 队列大量堆积、挤占 finalize，反而拖慢最终字幕
        # partial 参数可在 config model_settings 中覆盖（partial_interval /
        # partial_min_sec / partial_max_sec），默认按设备自适应
        eng_dev = getattr(self.asr_engine, '_device', None)
        self._is_cpu = (eng_dev == 'cpu') or resolve_device(self._config) == 'cpu'
        ms_cfg = self._config.get("model_settings", {})
        self._stream_last_partial = ""
        self._stream_partial_time = 0
        self._stream_partial_interval = float(ms_cfg.get(
            "partial_interval", 1.0 if self._is_cpu else 0.3))
        self._partial_min_sec = float(ms_cfg.get(
            "partial_min_sec", 0.5 if self._is_cpu else 0.3))
        self._partial_max_sec = float(ms_cfg.get(
            "partial_max_sec", 2.0 if self._is_cpu else 3.0))
        self._partial_in_flight = False
        # 说话人声纹检测冷却：CPU 模式下 CAM++/ERes2Net 单次推理 1-3s，
        # 冷却期内继承上一说话人，避免每段都跑检测拖慢字幕输出
        self._last_speaker_detect_time = 0.0
        self._speaker_detect_cooldown = float(ms_cfg.get(
            "speaker_detect_cooldown", 3.0 if self._is_cpu else 0.0))

        # 分片有序提交（解决并发 _finalize_segment 乱序问题）
        self._seg_emit_lock = asyncio.Lock()
        self._next_seg_seq = 0           # 分片提交序号（单调递增）
        self._pending_emit_seq = 0        # 下一个待提交的序号
        self._pending_segments = {}       # {seq: (corrected, corrections, original, audio, vad_info, seg_time, seg_dur)}
        self._draining = False            # emit 泵防重入标志

        # 会话代次号：每次 _reset_session_state 递增；旧会话遗留的 executor 任务
        # 完成时检查代次，失效则丢弃结果，避免旧文本插入新会话
        self._session_generation = 0
        # transcription 有序发送队列：网络发送移出 _seg_emit_lock，
        # 避免慢客户端 TCP 反压冻结整条转写管线（put 在锁内保证顺序，send 在锁外）
        self._transcription_send_queue = None
        self._transcription_sender_task = None

        self.vad_processor = self._make_vad_processor()

        # 后训练数据集管理器（根据配置决定是否启用）
        self.dataset_manager = get_dataset_manager()
        dataset_cfg = self._config.get("dataset_settings", {})
        self.dataset_manager.configure(
            quality_threshold=dataset_cfg.get("quality_threshold", 0.6),
            auto_filter=dataset_cfg.get("auto_filter", True),
        )
        if dataset_cfg.get("enabled", False):
            self.dataset_manager.enable()
        print(f"[DATASET] enabled={self.dataset_manager.enabled} "
              f"threshold={self.dataset_manager.quality_threshold} "
              f"auto_filter={self.dataset_manager.auto_filter}", flush=True)

    def _make_vad_processor(self):
        """根据配置构造实时 VAD 处理器（silero 流式 / energy 能量 / fsmn 回退能量）。"""
        vad_kwargs = dict(
            vad_silence_threshold=self.vad_silence_threshold,
            vad_force_cut=self.vad_force_cut,
            vad_force_cut_sec=self.vad_force_cut_sec,
            min_speech_duration=self.min_speech_duration,
            max_buffer_seconds=self.max_buffer_seconds,
        )
        if self.vad_engine == "silero":
            try:
                sp = SileroStreamingVAD(
                    speech_prob_threshold=self._config.get("model_settings", {}).get(
                        "silero_speech_prob_threshold", 0.5),
                    **vad_kwargs,
                )
                print(f"[VAD] 实时模式使用 Silero 流式 VAD（静音>{self.vad_silence_threshold}s）", flush=True)
                return sp
            except Exception as e:
                print(f"[VAD] Silero 流式 VAD 加载失败，回退能量阈值: {e}", flush=True)
        elif self.vad_engine == "fsmn":
            print("[VAD] FSMN 不支持实时流式切分，实时模式回退能量阈值", flush=True)
        else:
            print("[VAD] 实时模式使用能量阈值 VAD", flush=True)
        return VADProcessor(**vad_kwargs)

    def _resample_audio(self, audio_data, from_rate, to_rate):
        return resample_audio(audio_data, from_rate, to_rate)

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
                'model': (self.asr_engine.model_name if self.asr_engine
                          else ('加载失败' if self._model_error else '加载中...')),
                'model_ready': self._model_ready,
                'timestamp': datetime.now().isoformat()
            }, ensure_ascii=False))

            print(f"[WS] Client connected: {websocket.remote_address}")
            self.client = websocket
            self.client_connected = True
            self._clients.add(websocket)

            # 模型未就绪时通知客户端真实状态（加载中/加载失败），而非一律"加载中"
            if not self._model_ready:
                if self._model_error:
                    await self._send_to(websocket, {
                        'type': 'error',
                        'message': f'模型加载失败: {self._model_error}',
                    })
                else:
                    await self._send_to(websocket, {
                        'type': 'model_loading',
                        'message': '模型加载中，请稍候...',
                    })

            # 新客户端连接时，若已有其他端在录音，通知当前录音状态+模式
            if self.recording_ws is not None and self.recording_ws is not websocket:
                await self._send_to(websocket, {
                    'type': 'recording_state',
                    'recording': True,
                    'mode': self._recording_mode,
                })

            async for message in websocket:
                if isinstance(message, bytes):
                    await self.process_audio(message, websocket)
                elif isinstance(message, str):
                    # 局部保护：一条畸形文本帧只跳过该帧，不终止整个连接
                    try:
                        control_msg = json.loads(message)
                    except (json.JSONDecodeError, ValueError):
                        print(f"[WS] 忽略畸形文本帧: {message[:120]!r}")
                        continue
                    await self.handle_control_message(control_msg, websocket)

        except websockets.exceptions.ConnectionClosedOK:
            print("[WS] Client disconnected normally")
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"[WS] Client disconnected: {e}")
        except Exception as e:
            print(f"[WS] Error: {e}")
        finally:
            self._clients.discard(websocket)
            self._observer_clients.discard(websocket)
            if self.client is websocket:
                self.client = None
            # client_connected 反映是否有任意客户端在线（而非仅最近连接的 self.client），
            # 避免 A 断开时误报"无客户端"，或 B 断开后 A 仍在线却显示 0
            self.client_connected = len(self._clients) > 0
            if self.recording_ws is websocket:
                self.recording_ws = None
                self.is_running = False
                print("[WS] Recording client disconnected")
                # 客户端异常断开时也要保存完整录音（避免会话泄漏与内存泄漏）
                if self.dataset_manager.enabled:
                    try:
                        self.dataset_manager.end_session()
                    except Exception as e:
                        print(f"[DATASET] 异常断开时保存完整录音失败: {e}", flush=True)
            if self._current_handler_ws is websocket:
                self._current_handler_ws = None

    async def handle_control_message(self, msg, websocket):
        msg_type = msg.get('type')
        try:
            if msg_type == 'observer':
                # 桌面观察者客户端（观众模式下桌面 app 连接，只接收字幕不录音）
                self._observer_clients.add(websocket)
                print(f"[WS] Observer client registered: {websocket.remote_address}")
                return

            if msg_type == 'start':
                # 模型未就绪：排队等待，模型加载完成后自动重新处理
                if not self._model_ready:
                    # 加载已失败：告知真实状态，不再排队（避免 _pending_starts 无界增长）
                    if self._model_error:
                        await self._send_to(websocket, {
                            'type': 'error',
                            'message': f'模型加载失败: {self._model_error}',
                        })
                        return
                    self._pending_starts.append((msg, websocket))
                    await self._send_to(websocket, {
                        'type': 'model_loading',
                        'message': '模型加载中，请稍候...',
                    })
                    print(f"[WS] Start queued: model not ready")
                    return
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
                self._recording_mode = msg.get('mode', 'audience')
                self._session_start_time = datetime.now()
                # 后训练数据集第三级目录名：录音开始时间 YYYYMMDDHHMM（如 202607111230）
                self._session_source_name = self._session_start_time.strftime("%Y%m%d%H%M")
                self._reset_session_state()
                # 后训练数据集：开始会话（完整连续录音）
                if self.dataset_manager.enabled:
                    ds_mode2 = "streamer"
                    if self._recording_mode == "meeting":
                        ds_mode2 = "meeting"
                    elif self._recording_mode == "audience":
                        ds_mode2 = "audience"
                    self.dataset_manager.start_session(ds_mode2, self._session_source_name)
                await self._send_to(websocket, {
                    'type': 'status', 'status': 'recording',
                    'message': 'Started', 'model': self.asr_engine.model_name,
                    'keywords': list(self.pinyin_corrector.kw_set)
                })
                print(f"[WS] Recording started (mode={self._recording_mode})")
                for client in list(self._clients):
                    if client is not websocket:
                        try:
                            await self._send_to(client, {
                                'type': 'recording_state',
                                'recording': True,
                                'mode': self._recording_mode,
                            })
                        except Exception:
                            pass

            elif msg_type == 'stop':
                # 非录音客户端无权停止录音（与 start 互斥保护一致）
                if self.recording_ws is not websocket:
                    await self._send_to(websocket, {
                        'type': 'error',
                        'message': '非录音客户端无权停止录音'
                    })
                    return
                self.recording_ws = None
                self._recording_mode = 'audience'
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
                # 后训练数据集：结束会话，写入完整连续录音
                if self.dataset_manager.enabled:
                    self.dataset_manager.end_session()
                await self._send_to(websocket, {
                    'type': 'status', 'status': 'stopped',
                    'message': 'Stopped', 'full_text': self.full_text.strip(),
                    'segments': self.segments
                })

                print("[WS] Recording stopped")
                for client in list(self._clients):
                    if client is not websocket:
                        try:
                            await self._send_to(client, {
                                'type': 'recording_state',
                                'recording': False,
                                'mode': 'audience',
                            })
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
                        await self._send_keywords_updated(websocket)

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
                    # 主讲人名字不参与拼音纠正（避免"寅子"把"银子"等正常词误改）
                    if cat != 'speaker':
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
                # 已停用标题提取关键词：extract_title_keywords 会把长词拆成 2-4 字碎片
                # （如"价格量程"被拆成"格量"），再被拼音纠正误改成"个量"，产生反向伤害
                pass

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
                    # 广播给所有客户端（含字幕页），让字幕页更新名字映射
                    rename_msg = {
                        'type': 'speaker_renamed',
                        'old_id': speaker_id,
                        'new_label': new_label,
                    }
                    for ws in list(self._clients):
                        try:
                            await self._send_to(ws, rename_msg)
                        except Exception:
                            pass

            elif msg_type == 'save_report':
                display_names = self._prepare_report_data()
                report = generate_comprehensive_report(
                    self.segments, self.speaker_manager.speaker_profiles,
                    self.keyword_history,
                    self.total_audio_seconds,
                    self.asr_engine.model_name if self.asr_engine else 'unknown',
                    self.speaker_manager.page_type, self.speaker_manager.video_offset,
                    display_names=display_names,
                    page_creator=self.speaker_manager.page_creator,
                    session_start_time=getattr(self, '_session_start_time', None),
                    mode=self._recording_mode,
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
                    mode=self._recording_mode,
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
        # 会话代次递增：旧会话遗留的 executor 任务完成时发现代次失效，丢弃结果
        self._session_generation += 1

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
        self._partial_in_flight = False
        # 首帧加速：interval - offset 后触发第一次 partial
        # offset = 0.15 → 首次在 0.15s 后触发（interval 0.3s - 0.15s = 0.15s）
        self._stream_partial_time = time.time() - self._stream_partial_interval + 0.15
        # 声纹检测冷却重置：新会话立即做一次检测，避免继承旧会话说话人
        self._last_speaker_detect_time = 0.0

        # 分片有序提交队列重置（避免旧会话残留 seq 污染新会话）
        self._next_seg_seq = 0
        self._pending_emit_seq = 0
        self._pending_segments = {}

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
        # 模型未就绪：丢弃音频（避免缓冲区无限增长；用户会从 model_loading 消息得知状态）
        if not self._model_ready or self.asr_engine is None:
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

            # 后训练数据集：追加音频块到会话缓冲区（完整连续录音）
            if self.dataset_manager.enabled:
                self.dataset_manager.append_session_audio(audio_array, self.target_sample_rate)

            # 每0.3s发一次实时字幕条（纯定时器，不与完整转录耦合）
            # partial 用从段开始到现在的完整音频做 ASR（最多 3 秒）
            # 3s 窗口优先保证低延迟（ASR 更快，字幕跟手）；句子超长时由
            # finalize 用完整段修正，字幕条只是实时预览
            # _partial_in_flight 防止 executor 队列堆积导致延迟线性增长
            now = time.time()
            if now - self._stream_partial_time >= self._stream_partial_interval:
                self._stream_partial_time = now
                self._flush_audio_chunks()
                buf = self._audio_buf
                if len(buf) / 16000 >= self._partial_min_sec and not self._partial_in_flight:
                    # partial 用从段开始到现在的完整音频做 ASR（CPU 模式最多 2s 防推理过久，
                    # GPU 模式最多 3s 保证字幕完整；超长时取末尾窗口，finalize 用完整段修正）
                    max_partial_samples = int(self._partial_max_sec * self.target_sample_rate)
                    if len(buf) > max_partial_samples:
                        buf = buf[-max_partial_samples:]
                    # 同步置位标志，防止 event loop 调度下一个 process_audio 时重复创建 partial task
                    self._partial_in_flight = True
                    asyncio.ensure_future(self._send_streaming_partial(buf.copy(), session_gen=self._session_generation))

            # 每0.3秒检查一次是否可以转录
            self._flush_audio_chunks()
            buffer_dur = len(self._audio_buf) / 16000
            if buffer_dur >= 0.5 and len(self._audio_buf) > 0:
                # 用VAD检测是否有完整的语音段
                # VAD 是 CPU 密集同步操作，丢进 executor 避免阻塞 event loop
                # 捕获会话代次：reset 期间（start/clear）cut 可能基于旧缓冲计算，
                # 其结果（段/剩余缓冲）必须丢弃，否则会污染新会话
                gen_before_cut = self._session_generation
                audio_seg, remaining, vad_info = await loop.run_in_executor(
                    self.executor, self.vad_processor.cut, self._audio_buf, 16000
                )
                if gen_before_cut != self._session_generation:
                    return

                if audio_seg is not None and len(audio_seg) > int(self.min_speech_duration * 16000):
                    # 立即推进 total_audio_seconds，避免并发段捕获相同时间戳
                    # （_finalize_segment 是并发调度的，若在 _emit_segment 末尾才推进，
                    #  多个并发段入口会捕获到相同的 total_audio_seconds，导致时间轴错乱）
                    seg_dur_now = len(audio_seg) / 16000
                    seg_time_now = self.total_audio_seconds
                    self.total_audio_seconds += seg_dur_now
                    # 统一ASR管线：一次识别，同时输出 partial(字幕条) + transcription(右边记录)
                    asyncio.ensure_future(self._finalize_segment(audio_seg, vad_info, seg_time_now, seg_dur_now, session_gen=self._session_generation))
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

    async def _send_streaming_partial(self, audio_array, session_gen=None):
        """实时字幕条：对完整段音频（最多 3 秒）做 ASR → 去重/格式化 → 发送 partial 到前端。

        简化方案：partial 使用从段开始到现在的完整音频做 ASR（最多 3 秒），
        ASR 输出本身就是整句，前面的字不会被挤掉，无需任何累积逻辑。
        句号出现后由 _finalize_segment 处理段边界，下一段从空白开始。

        _partial_sent_seq 仅在有文本成功发送时更新，避免空结果误杀旧 partial。
        _partial_in_flight 确保同一时间最多 1 个 ASR partial 在跑，防止 executor 队列堆积。
        """
        self._partial_in_flight = True
        self._partial_seq += 1
        my_seq = self._partial_seq
        # 捕获会话代次（任务创建时传入）：reset 后旧会话的 partial 结果直接丢弃
        seg_gen = session_gen if session_gen is not None else self._session_generation
        try:
            # 静音/低能量跳过：阈值 0.005（约 -46dB）
            # 过低会导致 ASR 在背景音乐/噪声上产生幻觉（尤其传了热词 context 时）
            rms = np.sqrt(np.mean(np.asarray(audio_array, dtype=np.float32) ** 2))
            if rms < 0.005:
                return

            loop = asyncio.get_running_loop()
            raw_text = await loop.run_in_executor(
                self.executor, self.asr_engine.transcribe_array, audio_array, 16000)

            # 会话已重置（start/clear 递增代次）：丢弃旧会话结果，避免覆盖新会话字幕条
            if seg_gen != self._session_generation:
                return

            if not raw_text or not raw_text.strip():
                return

            raw_text = raw_text.strip()

            # 同 _finalize_segment 管线：段间去重 + 格式化（已关闭字符/短语去重）
            if self.segments:
                prev = self.segments[-1]['text']
                raw_text = dedup_overlap(prev, raw_text)
                if not raw_text:
                    return
            raw_text = normalize_letter_adjacent_numbers(raw_text)
            if not raw_text or not raw_text.strip():
                return

            # 与上次发送的文本相同 → 跳过（防抖）
            if raw_text == self._stream_last_partial:
                return

            # 有更新的 partial 已发送 → 本 partial 过时
            if my_seq <= self._partial_sent_seq:
                return

            self._partial_sent_seq = my_seq
            self._stream_last_partial = raw_text

            await self._send_to_recording({
                'type': 'partial',
                'text': raw_text,
            })
        except Exception as e:
            print(f"[WS] Partial error: {e}", flush=True)
            import traceback
            traceback.print_exc()
        finally:
            self._partial_in_flight = False

    async def _finalize_segment(self, audio_seg, vad_info, seg_audio_time=None, seg_duration=None, session_gen=None):
        """段边界处理：VAD 检测到说话结束 → 字幕条对完整段做最终 ASR → 直接复制到 speaker 面板。

        字幕条是唯一的文本生产管线：
        - 说话中：字幕条用从段开始到现在的完整音频做实时预览（最多 3s，见 _send_streaming_partial）
        - VAD 切段时：字幕条对完整音频段做最终 ASR，修正后的文本就是最终版本
        - speaker 面板直接复制字幕条的最终文本，不做第二次 ASR

        使用分片序号 + 有序队列，确保 transcription 按 VAD 检测顺序发送。

        参数:
            seg_audio_time: 段在完整音频流中的起始时间（秒）。由 process_audio 在切出
                           audio_seg 时立即传入，避免并发段捕获相同 total_audio_seconds。
            seg_duration:   段时长（秒）。同上。
        """
        # 捕获会话代次（任务创建时传入）：reset 后旧会话任务的结果直接丢弃
        seg_gen = session_gen if session_gen is not None else self._session_generation
        seg_seq = self._next_seg_seq
        self._next_seg_seq += 1
        # 使用调用方传入的时间戳（已避免并发竞态）；未传入时回退到当前 total_audio_seconds
        if seg_audio_time is None:
            seg_audio_time = self.total_audio_seconds
        if seg_duration is None:
            seg_duration = len(audio_seg) / 16000

        seg_data = None

        try:
            # 字幕条管线：对完整音频段做最终 ASR（替代 10s 窗口预览，确保不漏字）
            loop = asyncio.get_running_loop()
            raw_text = await loop.run_in_executor(
                self.executor, self.asr_engine.transcribe_array, audio_seg, 16000)

            # 会话已重置（start/clear 递增代次）：旧会话任务结果直接丢弃，避免旧文本插入新会话
            if seg_gen != self._session_generation:
                return

            if not raw_text or not raw_text.strip():
                dur = len(audio_seg) / 16000
                if dur >= 0.3:
                    print(f"    [SEG] ASR 无文本 ({dur:.1f}s) — 已跳过", flush=True)
                return

            text = raw_text.strip()

            # 字幕条标准后处理管线：格式化（已关闭字符/短语去重，保留用户真实重复语音）
            text = normalize_letter_adjacent_numbers(text)
            if not text or not text.strip():
                return

            # 纯标点过滤：剔除只有标点/空白的内容（如 "。" "，" "！。"）
            # 这类内容无语义价值，不应输出到字幕条/报告
            if not re.sub(r'[\s\W_]', '', text, flags=re.UNICODE):
                # 移除所有标点/空白后为空 → 纯标点段落
                print(f"    [SEG] 纯标点段落已跳过: {text}", flush=True)
                return

            # 段间去重：与上一个 segment 的重叠部分
            if self.segments:
                prev = self.segments[-1]['text']
                text = dedup_overlap(prev, text)
            if not text:
                return

            # 句子级别/全局精确去重已移入 _drain_pending_segments 的锁内快路径
            # （_speaker_fast_path），避免并发段在锁外各自通过检查、穿透去重

            # 关键词拼音纠正（输出前最后一步）：关键词→拼音→匹配文本→替换
            # 例如：关键词"寅子"，ASR输出"银子" → 拼音都是 yin+zi → 替换为"寅子"
            # 关键词较多时拼音匹配是 CPU 密集操作，丢进 executor 避免阻塞事件循环
            text, kw_corrections = await loop.run_in_executor(
                self.executor, self.pinyin_corrector.correct_with_keywords, text)
            kw_applied = len(kw_corrections) > 0
            if kw_applied:
                for orig, corr in kw_corrections:
                    print(f"    [KW] 关键词纠正: {orig} → {corr}", flush=True)

            # 更新字幕条为最终文本（完整段 ASR 比 partial 预览更准确，直接替换整句作为纠错）
            # 先设置屏障再发送（同一事件循环原子区间），防止 await 让出事件循环后旧 raw partial 覆盖最终文本
            self._partial_sent_seq = self._partial_seq
            self._stream_last_partial = text
            # 热词上下文窗口：把最终段文本推入滑动窗口（内部有锁，partial/finalize 并发安全；
            # 未开启 hotwords 时为空操作），供后续 ASR 的 context 注入使用
            self.asr_engine.update_hotwords_window(text)
            await self._send_to_recording({
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
            # 会话已重置（代次失效）：不写入有序队列，避免旧 seq 污染新会话队列导致丢段
            if seg_gen == self._session_generation:
                async with self._seg_emit_lock:
                    self._pending_segments[seg_seq] = seg_data
                # 泵：锁内快路径（去重/说话人继承）+ 锁外声纹检测 + 有序发射
                await self._drain_pending_segments()

    async def _drain_pending_segments(self):
        """有序 emit 泵：按 _pending_emit_seq 串行处理队列中的段。

        锁内只做同步快路径（去重检查、说话人继承决策、字幕条屏障），
        慢速声纹检测（写 wav + 模型推理）在锁外 await，避免检测期间
        阻塞其他 _finalize_segment 的入队与字幕条（_pending_segments 无限堆积）。

        说话人 last_speaker_label 的读写全部由本泵串行完成，
        顺序与发射顺序一致，不引入标签乱序。
        """
        if self._draining:
            return
        self._draining = True
        try:
            while True:
                async with self._seg_emit_lock:
                    if self._pending_emit_seq not in self._pending_segments:
                        return
                    data = self._pending_segments.pop(self._pending_emit_seq)
                    if data is None:
                        self._pending_emit_seq += 1
                        continue
                    (corr, corrs, orig, audio, vi, seg_time, seg_dur, kw_applied) = data
                    gen_at_pop = self._session_generation
                    # 阻止并发 raw partial 覆盖 + 清空字幕条缓存，让字幕条从新段重新开始显示
                    # （锁内原子区间，与旧实现一致：对重复段也执行）
                    self._partial_sent_seq = self._partial_seq
                    self._stream_last_partial = ""
                    # 锁内同步快路径：重复跳过 / 说话人继承决策
                    need_detect, speaker_label = self._speaker_fast_path(audio, corr)
                    if need_detect is None:
                        self._pending_emit_seq += 1
                        continue
                try:
                    if need_detect:
                        try:
                            speaker_label = await self.speaker_manager.detect_speaker(audio)
                            self._last_speaker_detect_time = time.time()
                            self.speaker_manager.last_speaker_label = speaker_label
                        except Exception as e:
                            print(f"    [SPEAKER] 声纹检测失败，继承上一说话人: {e}", flush=True)
                            speaker_label = self.speaker_manager.last_speaker_label
                    async with self._seg_emit_lock:
                        # 会话已重置（reset 清空队列，但 pop 后检测期间可能重置）：丢弃
                        if gen_at_pop == self._session_generation:
                            await self._emit_segment(audio, corr, kw_applied,
                                                     speaker_label=speaker_label, vad_info=vi,
                                                     corrections=corrs, original_text=orig,
                                                     seg_audio_time=seg_time, seg_duration=seg_dur)
                            status = f"[WS] [{self.transcription_count}] [SEG]"
                            print(f"{status} {corr[:60]}...", flush=True)
                except Exception as e:
                    print(f"[WS] _emit_segment 失败 seq={self._pending_emit_seq}: {e}", flush=True)
                    import traceback
                    traceback.print_exc()
                finally:
                    # 异常保护：无论发射成功失败，都必须推进序号，否则后续段永久堆积死锁
                    async with self._seg_emit_lock:
                        self._pending_emit_seq += 1
        finally:
            self._draining = False

    def _speaker_fast_path(self, audio_data, text):
        """锁内同步执行的说话人快路径：去重检查 + 继承决策。

        返回 (need_detect, speaker_label)：
          - need_detect is None → 该段应跳过（重复文本）
          - need_detect False   → 直接使用返回的 speaker_label（继承）
          - need_detect True    → 需要由 emit 泵在锁外做声纹检测
        """
        # 句子级别去重：与上一段完全相同 → 跳过
        if self.segments and self.segments[-1]['text'] == text:
            return None, None
        # 全局精确去重：近期已发送过完全相同的文本 → 跳过
        if text in self.sent_texts:
            print(f"    [DEDUP] 重复文本已跳过: {text[:40]}", flush=True)
            return None, None
        # 短音频不跑声纹（<0.8s 的片段嵌入向量不稳定），直接用上一个说话人
        if len(audio_data) < int(16000 * 0.8):
            return False, self.speaker_manager.last_speaker_label
        # 极短文本片段：中文<3字 且 非中文<5字母 → VAD强制切分尾部碎片，继承说话人
        # 英文/俄语等纯字母文本（如 "Hello" 或 "Привет"）满足中文字数=0，但仍有有效语音内容
        # 需同时检查非中文字符数，避免外语语音永远不走 CAM++
        if text:
            cn_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
            non_cn_chars = len(re.findall(r'[a-zA-Z\u0400-\u04FF]', text))
            if cn_chars < 3 and non_cn_chars < 5:
                print(f"    [SPEAKER] 短文本片段({cn_chars}字+{non_cn_chars}字母) "
                      f"继承说话人: {self.speaker_manager.last_speaker_label}", flush=True)
                return False, self.speaker_manager.last_speaker_label
            # 声纹检测前做能量预检：极低能量片段可能只有噪声，跳过以避免污染声纹库
            rms = np.sqrt(np.mean(np.asarray(audio_data, dtype=np.float32) ** 2))
            if rms < 0.003:
                print(f"    [SPEAKER] 低能量片段(RMS={rms:.4f})继承说话人: "
                      f"{self.speaker_manager.last_speaker_label}", flush=True)
                return False, self.speaker_manager.last_speaker_label
            # CPU 模式冷却：声纹检测较重，冷却期内继承上一说话人
            # （冷却时间配置见 __init__，仅 CPU 模式默认开启）
            if self._speaker_detect_cooldown > 0:
                now = time.time()
                if now - self._last_speaker_detect_time < self._speaker_detect_cooldown:
                    return False, self.speaker_manager.last_speaker_label
        return True, None

    async def _emit_segment(self, audio_data, text, kw_applied=False, speaker_label=None,
                            vad_info=None, corrections=None, original_text=None,
                            seg_audio_time=None, seg_duration=None):
        """创建一条识别记录并发送到前端（仅由 _drain_pending_segments 泵持 _seg_emit_lock 调用）。

        去重与说话人继承决策由 _speaker_fast_path 在锁内同步完成，
        慢速声纹检测由泵在锁外完成，speaker_label 在此处直接使用。
        """
        if speaker_label is None:
            speaker_label = self.speaker_manager.last_speaker_label

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
        # total_audio_seconds 已在 process_audio 切出 audio_seg 时推进
        # （避免并发段捕获相同时间戳），此处仅同步给 speaker_manager
        self.speaker_manager.total_audio_seconds = self.total_audio_seconds
        self.transcription_count += 1

        transcription_msg = {
            'type': 'transcription',
            'text': text,
            'speaker': display_name,
            'speaker_label': speaker_label,
            'display_speaker': display_name,
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
        }
        # 网络发送移出 _seg_emit_lock：放入有序队列由 _transcription_sender 协程发送，
        # 锁内只做状态更新/队列推进，慢客户端 TCP 反压不再冻结整条转写管线
        if self._transcription_send_queue is not None:
            self._transcription_send_queue.put_nowait(transcription_msg)
        else:
            await self._send_to_recording(transcription_msg)

        # 后训练数据集存储（开关启用时，在后台线程落盘，避免阻塞转录流程）
        if self.dataset_manager.enabled:
            # 数据集模式映射：4个模式各自独立目录
            if self._recording_mode == "meeting":
                ds_mode = "meeting"
            elif self._recording_mode == "audience":
                ds_mode = "audience"
            else:
                ds_mode = "streamer"
            try:
                loop = asyncio.get_running_loop()
                loop.run_in_executor(
                    self.executor,
                    self._save_dataset_segment,
                    audio_data, text, original_text, speaker_label,
                    vad_info, seg_audio_time, seg_duration, ds_mode,
                    self._session_source_name,
                )
            except Exception as e:
                print(f"[DATASET] 提交存储任务失败: {e}", flush=True)

    def _save_dataset_segment(self, audio_data, text, original_text, speaker_label,
                               vad_info, seg_audio_time, seg_duration, mode="streamer",
                               source_name=None):
        """后训练数据集片段存储（在线程池中执行，避免阻塞事件循环）。"""
        try:
            seg_id = self.dataset_manager.save_segment(
                audio_data=audio_data,
                text=text,
                raw_text=original_text if original_text else text,
                speaker_label=speaker_label,
                vad_info=vad_info,
                seg_audio_time=seg_audio_time,
                seg_duration=seg_duration,
                sr=16000,
                mode=mode,
                source_name=source_name,
            )
            if seg_id:
                stats = self.dataset_manager.get_stats()
                print(f"[DATASET] 已保存片段 {seg_id} [{mode}] (总计 {stats['total']} 段, "
                      f"平均质量 {stats['avg_quality']})", flush=True)
        except Exception as e:
            print(f"[DATASET] 存储失败: {e}", flush=True)

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
        """准备报告所需的公共数据（保留 VAD 原始分段，不做合并/拆分）
        用户要求：报告保持一句一句的原始分段，该是哪句就是哪句，不做聚合或切分"""
        return self.speaker_manager.get_all_display_names()

    async def generate_and_send_report(self, websocket):
        display_names = self._prepare_report_data()
        report = generate_comprehensive_report(
            self.segments, self.speaker_manager.speaker_profiles,
            self.keyword_history,
            self.total_audio_seconds,
            self.asr_engine.model_name if self.asr_engine else 'unknown',
            self.speaker_manager.page_type, self.speaker_manager.video_offset,
            display_names=display_names,
            page_creator=self.speaker_manager.page_creator,
            session_start_time=getattr(self, '_session_start_time', None),
            mode=self._recording_mode,
        )
        await self._send_to(websocket, {'type': 'report', 'content': report})

    async def _send_to(self, websocket, message):
        try:
            await websocket.send(json.dumps(message, ensure_ascii=False))
        except Exception as e:
            print(f"[WS] Send failed: {e}")
            self._clients.discard(websocket)
            # 发送失败说明连接已坏：一并清理录音/观察者引用，避免残留状态
            self._observer_clients.discard(websocket)
            if self.recording_ws is websocket:
                self.recording_ws = None
                self.is_running = False

    async def send(self, message):
        """广播给所有已连接客户端"""
        for ws in list(self._clients):
            await self._send_to(ws, message)

    async def _send_to_recording(self, message):
        """发给录音客户端；主播/会议模式同时广播给其他客户端（含字幕页浏览器源）。

        观众模式：发给 recording_ws（浏览器插件）+ observer_clients（桌面 app）。
          - 不广播给其他客户端，避免 OBS 字幕页/其他标签页插件串扰
        主播/会议模式：广播给所有客户端。
          - OBS 字幕页需要接收 partial/transcription 才能显示字幕
          - 桌面客户端也需要接收字幕显示
        """
        if self.recording_ws is not None:
            await self._send_to(self.recording_ws, message)
        # 观众模式：只发给桌面观察者客户端（不广播给 OBS 字幕页/其他浏览器插件）
        if self._recording_mode == 'audience':
            for ws in list(self._observer_clients):
                if ws is not self.recording_ws:
                    try:
                        await self._send_to(ws, message)
                    except Exception:
                        pass
            return
        # 主播/会议模式：广播给其他客户端（字幕页浏览器源、桌面客户端）
        for ws in list(self._clients):
            if ws is not self.recording_ws:
                try:
                    await self._send_to(ws, message)
                except Exception:
                    pass

    async def _transcription_sender(self):
        """transcription 有序发送协程：从队列取消息依次发送。
        网络发送在 _seg_emit_lock 外执行，慢客户端 TCP 反压只堆积队列、不冻结转写管线。"""
        while True:
            message = await self._transcription_send_queue.get()
            try:
                await self._send_to_recording(message)
            except Exception as e:
                print(f"[WS] Transcription send error: {e}", flush=True)

    async def start(self, model_loader=None):
        page = STATUS_PAGE.read_text(encoding='utf-8').replace("{host}", self.host).replace("{port}", str(self.port))
        subtitle_page = SUBTITLE_PAGE.read_text(encoding='utf-8') if SUBTITLE_PAGE.exists() else None
        async def process_request(connection, request):
            path = request.path if hasattr(request, 'path') else '/'
            print(f"[WS] HTTP request: {path}", flush=True)
            if request.headers.get("Upgrade", "").lower().strip() == "websocket":
                print(f"[WS] WebSocket upgrade request", flush=True)
                return None
            h = Headers()
            h['Connection'] = 'close'
            h['Content-Type'] = 'text/html; charset=utf-8'

            # /subtitle → OBS 浏览器源字幕页（透明背景）
            if path.startswith('/subtitle') and subtitle_page:
                return Response(200, "OK", h, subtitle_page.encode("utf-8"))

            # 其他请求 → 控制面板主页
            print(f"[WS] Serving status page ({len(page)} bytes)", flush=True)
            return Response(200, "OK", h, page.encode("utf-8"))

        print(f"\n[WS] WebSocket server: ws://{self.host}:{self.port}", flush=True)
        print(f"[WS] Status page:     http://{self.host}:{self.port}", flush=True)
        # Subtitle page 提示由客户端根据模式决定是否显示（观众模式不需要 OBS 字幕页）
        async with websockets.serve(
            self.handler, self.host, self.port,
            ping_interval=20, ping_timeout=60, close_timeout=10,
            max_size=2**24,
            process_request=process_request,
        ):
            print("[WS] Service ready", flush=True)
            self._shutdown_event = asyncio.Event()
            self._loop = asyncio.get_running_loop()
            # transcription 有序发送队列：put 在 _seg_emit_lock 内保证顺序，send 在锁外执行
            self._transcription_send_queue = asyncio.Queue()
            self._transcription_sender_task = asyncio.ensure_future(self._transcription_sender())
            # 模型延迟加载：在后台线程执行 model_loader，加载完成后通过 set_asr_engine 切换
            # 这样 WebSocket 立即可用，插件能秒连，模型在后台加载
            if model_loader is not None and not self._model_ready:
                asyncio.ensure_future(self._load_model_background(model_loader))
            await self._shutdown_event.wait()  # 阻塞直到 _safe_shutdown() 被调用
            print("[WS] Shutting down...", flush=True)
            if self._transcription_sender_task is not None:
                self._transcription_sender_task.cancel()
                self._transcription_sender_task = None

    async def _load_model_background(self, model_loader):
        """后台加载模型：在 executor 线程中调用 model_loader，加载完成后切换引擎。
        model_loader 返回 (eng, sv_pipeline) 或 None（失败）。"""
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, model_loader)
            if result is None:
                # loader 未给出具体错误时也落一个通用错误，
                # 保证新客户端/新 start 看到真实失败状态而非"加载中"
                self._model_error = self._model_error or "模型加载失败"
                err = self._model_error
                print(f"[SERVER] Model loader returned None: {err}", flush=True)
                # 加载失败：清空排队的 start（不再重放，避免 _pending_starts 无界增长）
                self._pending_starts = []
                # 通知所有已连接客户端加载失败
                for client in list(self._clients):
                    try:
                        await self._send_to(client, {
                            'type': 'error',
                            'message': f'模型加载失败: {err}',
                        })
                    except Exception:
                        pass
                return
            eng, sv_pipeline = result
            # set_asr_engine 是同步方法，但操作 asyncio 状态，需在 loop 线程上执行
            # 我们已经在 loop 线程上（run_in_executor 返回后回到 loop），可直接调用
            self.set_asr_engine(eng, sv_pipeline)
        except Exception as e:
            import traceback
            print(f"[SERVER] Background model load failed: {e}\n{traceback.format_exc()}", flush=True)
            self._model_error = str(e)
            # 加载失败：清空排队的 start（不再重放，避免 _pending_starts 无界增长）
            self._pending_starts = []
            # 通知所有等待的客户端加载失败
            for client in list(self._clients):
                try:
                    await self._send_to(client, {
                        'type': 'error',
                        'message': f'模型加载失败: {e}',
                    })
                except Exception:
                    pass

    def set_asr_engine(self, eng, sv_pipeline=None):
        """设置 ASR 引擎（延迟加载完成后调用）。
        必须在 asyncio loop 线程上调用。会重新处理排队的 start 请求并通知所有客户端。"""
        self.asr_engine = eng
        # 如果 speaker_manager 还没有 sv_pipeline，注入新加载的
        if sv_pipeline is not None and getattr(self.speaker_manager, 'sv_pipeline', None) is None:
            self.speaker_manager.sv_pipeline = sv_pipeline
        self._model_ready = True
        print(f"[SERVER] ASR engine ready: {eng.model_name}", flush=True)
        # 调度异步任务：重新处理排队的 start + 通知所有客户端模型就绪
        if self._loop and self._loop.is_running():
            asyncio.ensure_future(self._on_model_ready(), loop=self._loop)

    async def _on_model_ready(self):
        """模型就绪后：通知所有客户端 + 重新处理排队的 start 请求。"""
        # 1. 通知所有已连接客户端模型已就绪
        for client in list(self._clients):
            try:
                await self._send_to(client, {
                    'type': 'model_ready',
                    'model': self.asr_engine.model_name,
                    'message': '模型加载完成，可以开始录音',
                })
            except Exception:
                pass
        # 2. 重新处理排队的 start 请求
        pending = self._pending_starts
        self._pending_starts = []
        for msg, ws in pending:
            # per-item try：单个失败不影响其余重放
            try:
                # 客户端可能已断开（websockets 16 移除了 .open 属性，改用 state 判断）
                if ws.state is not State.OPEN:
                    continue
                await self.handle_control_message(msg, ws)
            except Exception as e:
                print(f"[WS] Re-process pending start failed: {e}", flush=True)

    def _safe_shutdown(self):
        """线程安全关闭：通过 _loop.call_soon_threadsafe 唤醒 asyncio.Event。
        外部代码（主线程）必须调用此方法，不能直接 .set()。"""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._shutdown_event.set)


_global_server = None

def run_server(config, host='localhost', port=8765, asr_engine=None, model_loader=None):
    """启动 WebSocket 服务。
    - config: 配置字典（必需）
    - asr_engine: 已加载的 ASR 引擎（可选）；为 None 时通过 model_loader 延迟加载
    - model_loader: 可调用对象，返回 (eng, sv_pipeline)；为 None 时不进行延迟加载
    """
    global _global_server
    server = RealtimeASRServer(asr_engine, host, port, config=config)
    _global_server = server
    try:
        asyncio.run(server.start(model_loader=model_loader))
    except KeyboardInterrupt:
        print("\n[WS] Stopped")
    except Exception as e:
        print(f"\n[WS] Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 关闭线程池：确保进行中的 ASR/落盘任务完成，避免异常退出时泄漏线程
        server.executor.shutdown(wait=True)
        # 数据集异步落盘线程池（end_session 的重活在后台执行）：等待落盘完成再退出
        disk_executor = getattr(server.dataset_manager, '_disk_executor', None)
        if disk_executor is not None:
            disk_executor.shutdown(wait=True)
        _global_server = None
