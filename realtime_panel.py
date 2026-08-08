# -*- coding: utf-8 -*-
"""
实时语音识别面板组件

包含：
- SubtitleListView: 字幕展示区（滚动展示识别文字+时间戳，嵌入主播/会议页面）
- MicCaptureThread: 麦克风采集线程（48kHz mono float32，发到WS）
- RealtimeWSClient: WebSocket客户端（接收partial/transcription，驱动字幕更新）

字幕条悬浮窗已移除：改用 OBS 浏览器源，访问 http://<host>:<port>/subtitle

音频格式约定（与 server.py 对齐）：
- 采样率 48000 Hz
- 单声道
- float32 PCM
- 二进制帧发送
"""
import json
import queue
import asyncio
import html as _html
import numpy as np
from datetime import datetime

from common_utils import resample_audio

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QLabel, QVBoxLayout, QTextEdit, QFrame,
)


# ============================================================
# 1. 字幕展示区（滚动展示识别文字+时间戳）
# ============================================================
class SubtitleListView(QFrame):
    """字幕展示区：顶部斜体实时区 + 滚动记录区

    顶部：当前正在说的文字（斜体、灰色、闪烁光标）
    下方：滚动记录区，每条 = 时间戳 + 说话人 + 文字
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("subtitleListView")
        self._segments = []  # 全部已完成的段 [(time_str, speaker, text), ...]
        self._partial_text = ""
        # QTextEdit 文档块数上限（仅裁剪显示，_segments 全量保留供导出）
        self._max_blocks = 5000

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # 顶部实时区（斜体）
        self._partial_label = QLabel("")
        self._partial_label.setStyleSheet(
            "color: #888; font-size: 14px; font-style: italic; "
            "background: rgba(0,0,0,0.04); border-radius: 6px; "
            "padding: 8px 12px; min-height: 24px;"
        )
        self._partial_label.setWordWrap(True)
        self._partial_label.setTextFormat(Qt.RichText)
        layout.addWidget(self._partial_label)

        # 滚动记录区
        self._scroll = QTextEdit()
        self._scroll.setReadOnly(True)
        self._scroll.setStyleSheet(
            "QTextEdit {"
            "  background: #fafbfc;"
            "  border: 1px solid #e1e4e8;"
            "  border-radius: 6px;"
            "  padding: 6px;"
            "  font-size: 14px;"
            "  color: #24292f;"
            "}"
        )
        self._scroll.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # 限制文档块数，避免长时间会议内存膨胀；导出走 _segments 不受影响
        self._scroll.document().setMaximumBlockCount(self._max_blocks)
        layout.addWidget(self._scroll, stretch=1)

        self._cursor_timer = QTimer(self)
        self._cursor_timer.timeout.connect(self._toggle_cursor)
        self._cursor_on = True
        self._cursor_timer.start(500)
        self._update_partial()

    def _toggle_cursor(self):
        self._cursor_on = not self._cursor_on
        self._update_partial()

    def _update_partial(self):
        cursor = '<span style="color:#52c41a;">|</span>' if self._cursor_on else '<span style="color:#ddd;">|</span>'
        text = _html.escape(self._partial_text or "")
        if text:
            self._partial_label.setText(
                f'<span style="color:#888;font-style:italic;">{text}</span> {cursor}'
            )
        else:
            self._partial_label.setText(
                f'<span style="color:#ccc;font-style:italic;">等待语音...</span> {cursor}'
            )

    def set_partial(self, text: str):
        """更新实时斜体区文字"""
        self._partial_text = text or ""
        self._update_partial()

    def add_segment(self, time_str: str, speaker: str, text: str, is_host: bool = False):
        """追加一条已完成的转录段到滚动记录区"""
        self._segments.append((time_str, speaker, text))

        # 说话人颜色
        if is_host:
            sp_color = "#0969da"
            sp_label = speaker or "主持人"
        else:
            sp_color = "#6f42c1"
            sp_label = speaker or "发言人"

        html = (
            f'<div style="margin-bottom:6px;padding:4px 6px;border-left:3px solid {sp_color};">'
            f'<span style="color:#888;font-size:12px;">[{_html.escape(time_str)}]</span> '
            f'<span style="color:{sp_color};font-weight:600;font-size:13px;">{_html.escape(sp_label)}</span> '
            f'<span style="color:#24292f;">{_html.escape(text)}</span>'
            f'</div>'
        )
        self._scroll.append(html)
        # 自动滚动到底部
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def clear_all(self):
        self._segments.clear()
        self._partial_text = ""
        self._scroll.clear()
        self._update_partial()

    def get_full_text(self) -> str:
        """获取全部纯文本（用于导出）"""
        lines = []
        for time_str, speaker, text in self._segments:
            lines.append(f"[{time_str}] {speaker}: {text}")
        return "\n".join(lines)

    def get_segments(self) -> list:
        return list(self._segments)


# ============================================================
# 2. 麦克风采集线程（48kHz mono float32）
# ============================================================
class MicCaptureThread(QThread):
    """麦克风采集线程

    用 sounddevice.InputStream 采集 48kHz/mono/float32 PCM，
    通过 audio_chunk signal 发出 numpy 数组。
    """
    audio_chunk = Signal(object)  # np.ndarray float32, 48kHz, mono
    error_occurred = Signal(str)
    level_update = Signal(float)  # 音量电平 0.0~1.0

    def __init__(self, device_index=None, samplerate=48000, blocksize=8192):
        super().__init__()
        self._device = device_index
        self._samplerate = samplerate
        self._blocksize = blocksize
        self._running = False
        self._stream = None

    def run(self):
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as e:
            self.error_occurred.emit(f"缺少依赖: {e}")
            return

        self._running = True
        try:
            self._stream = sd.InputStream(
                device=self._device,
                samplerate=self._samplerate,
                channels=1,
                dtype="float32",
                blocksize=self._blocksize,
                callback=self._callback,
            )
            self._stream.start()

            while self._running:
                self.msleep(100)

        except Exception as e:
            self.error_occurred.emit(f"麦克风采集失败: {e}")
        finally:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass

    def _callback(self, indata, frames, time_info, status):
        if not self._running:
            return
        # indata 是 np.ndarray, shape=(frames, 1), dtype=float32
        data = indata.copy().flatten()
        self.audio_chunk.emit(data)
        # 计算音量电平
        try:
            import numpy as np
            level = float(min(1.0, abs(data).max()))
            self.level_update.emit(level)
        except Exception:
            pass

    def stop(self):
        self._running = False


# ============================================================
# 2.5 系统音频回环采集线程（WASAPI loopback，用 PyAudioWPatch）
# ============================================================
class LoopbackCaptureThread(QThread):
    """系统音频回环采集线程

    用 PyAudioWPatch（PyAudio 的 fork，支持 WASAPI loopback）采集
    系统输出设备（喇叭）播放的音频。喇叭正常发声，同时拿到音频流。
    48kHz/mono/float32，与 MicCaptureThread 输出格式一致。
    """
    audio_chunk = Signal(object)  # np.ndarray float32, 48kHz, mono
    error_occurred = Signal(str)
    level_update = Signal(float)  # 音量电平 0.0~1.0

    def __init__(self, device_name=None, samplerate=48000, blocksize=8192):
        super().__init__()
        self._device_name = device_name  # 输出设备名，None=默认
        self._samplerate = samplerate
        self._blocksize = blocksize
        self._running = False
        self._stream = None
        self._pyaudio = None

    def _find_loopback_device(self, pyaudio):
        """查找 loopback 设备（PyAudioWPatch 官方推荐用法）。

        用 WASAPI hostApi 的默认输出设备名，去 get_loopback_device_info_generator()
        里匹配对应的 loopback 设备。不能用 get_default_output_device_info()，
        那返回的是 MME 设备，索引和 WASAPI 不一致，open 时会报 Invalid device。
        """
        try:
            wasapi_info = pyaudio.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError:
            return None
        default_out = pyaudio.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
        default_name = default_out["name"]

        # 如果指定了设备名，优先匹配指定设备；否则匹配默认输出设备
        target_name = self._device_name if self._device_name else default_name
        for loopback in pyaudio.get_loopback_device_info_generator():
            if target_name in loopback["name"]:
                return loopback
        # 指定设备名找不到，退回默认输出设备
        if self._device_name:
            for loopback in pyaudio.get_loopback_device_info_generator():
                if default_name in loopback["name"]:
                    return loopback
        return None

    def run(self):
        try:
            import numpy as np
            import pyaudiowpatch as pyaudio
        except ImportError as e:
            self.error_occurred.emit(f"缺少依赖 PyAudioWPatch: {e}")
            return

        self._running = True
        try:
            self._pyaudio = pyaudio.PyAudio()
            # 查找 loopback 设备
            dev_info = self._find_loopback_device(self._pyaudio)
            if dev_info is None:
                self.error_occurred.emit("未找到系统音频回环设备，请检查音频输出设备")
                return

            dev_rate = int(dev_info["defaultSampleRate"])
            channels = int(dev_info["maxInputChannels"])

            self._stream = self._pyaudio.open(
                format=pyaudio.paFloat32,
                channels=channels,
                rate=dev_rate,
                input=True,
                frames_per_buffer=self._blocksize,
                input_device_index=int(dev_info["index"]),
            )

            while self._running:
                try:
                    raw = self._stream.read(self._blocksize, exception_on_overflow=False)
                except Exception:
                    continue
                if not self._running:
                    break
                data = np.frombuffer(raw, dtype=np.float32).copy()
                # 多声道取均值转单声道
                if channels > 1:
                    data = data.reshape(-1, channels).mean(axis=1)
                # 重采样到目标采样率
                if dev_rate != self._samplerate:
                    data = self._resample(data, dev_rate, self._samplerate)
                self.audio_chunk.emit(data)
                try:
                    level = float(min(1.0, abs(data).max()))
                    self.level_update.emit(level)
                except Exception:
                    pass

        except Exception as e:
            self.error_occurred.emit(f"系统音频回环采集失败: {e}")
        finally:
            if self._stream is not None:
                try:
                    self._stream.stop_stream()
                    self._stream.close()
                except Exception:
                    pass
            if self._pyaudio is not None:
                try:
                    self._pyaudio.terminate()
                except Exception:
                    pass

    def _resample(self, audio_data, from_rate, to_rate):
        """简单线性重采样（实现见 common_utils.resample_audio）"""
        return resample_audio(audio_data, from_rate, to_rate)

    def stop(self):
        self._running = False


# ============================================================
# 3. WebSocket 客户端线程（接收 partial/transcription）
# ============================================================
class RealtimeWSClient(QThread):
    """WebSocket 客户端线程

    连接本地 ws://localhost:8765，发送 {type:start} 开始录音，
    接收 partial / transcription / status 消息。
    同时从 audio_queue 取音频数据转发到服务端。
    """
    partial_received = Signal(str)
    transcription_received = Signal(dict)
    status_received = Signal(str)  # "recording" / "stopped" / "cleared"
    connected = Signal()
    disconnected = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, url="ws://localhost:8765", mode="audience"):
        super().__init__()
        self._url = url
        self._mode = mode  # 录音模式：audience/streamer/meeting
        self._running = False
        self._ws = None
        self._loop = None
        self._audio_queue = queue.Queue(maxsize=200)
        # 观众模式：不发 start（避免覆盖浏览器插件的录音状态），只接收字幕显示
        # 主播/会议模式：发 start 占用 recording_ws
        self._send_start = (mode != "audience")

    def feed_audio(self, audio_bytes: bytes):
        """主线程调用：把音频数据放入队列（线程安全）"""
        try:
            self._audio_queue.put_nowait(audio_bytes)
        except queue.Full:
            pass  # 队列满则丢弃

    def _post_json(self, obj: dict):
        """线程安全地把 JSON 消息投递到 WS 事件循环；循环已关闭时安静降级"""
        loop = self._loop
        if not loop or not self._ws or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self._send_json(obj), loop)
        except RuntimeError:
            pass  # 事件循环已关闭，忽略

    def send_stop(self):
        """请求停止录音"""
        self._post_json({"type": "stop"})

    def send_clear(self):
        self._post_json({"type": "clear"})

    def send_speaker_rename(self, speaker_id: str, label: str):
        """重命名说话人"""
        self._post_json({"type": "speaker_rename", "speaker_id": speaker_id, "label": label})

    async def _send_json(self, obj: dict):
        if self._ws:
            await self._ws.send(json.dumps(obj))

    def run(self):
        self._running = True
        try:
            asyncio.run(self._async_run())
        except Exception as e:
            self.error_occurred.emit(f"WS客户端异常: {e}")
        finally:
            self.disconnected.emit("连接已断开")

    async def _async_run(self):
        import websockets

        self._loop = asyncio.get_event_loop()

        # 尝试连接（localhost 失败则回退 127.0.0.1）
        # 增加重试：服务端 WebSocket 监听可能刚启动还未就绪
        urls = [self._url]
        if "localhost" in self._url:
            urls.append(self._url.replace("localhost", "127.0.0.1"))

        last_err = None
        max_retries = 10  # 最多重试 10 次，每次间隔 0.5s，共 5s
        for attempt in range(max_retries):
            if not self._running:
                return  # stop() 已请求退出，放弃重试
            for url in urls:
                if not self._running:
                    return
                try:
                    self._ws = await asyncio.wait_for(
                        websockets.connect(url, ping_interval=20, ping_timeout=60),
                        timeout=2.0,
                    )
                    break
                except Exception as e:
                    last_err = e
                    self._ws = None
            if self._ws is not None:
                break
            # 未就绪，等待后重试（最后一次不等待）；分片 sleep 便于 stop() 及时中断
            if attempt < max_retries - 1:
                for _ in range(5):
                    if not self._running:
                        return
                    await asyncio.sleep(0.1)
        else:
            self.error_occurred.emit(f"无法连接到服务器: {last_err}")
            return

        self.connected.emit()

        forward_task = None
        try:
            # 观众模式：不发 start，但发 observer 标识，让服务端把字幕发给自己
            # 主播/会议模式：发 start 占用 recording_ws
            if self._send_start:
                await self._ws.send(json.dumps({"type": "start", "mode": self._mode}))
            else:
                # 观众模式：标识为桌面观察者，服务端会向其发送字幕
                await self._ws.send(json.dumps({"type": "observer", "mode": self._mode}))

            # 启动音频转发任务
            forward_task = asyncio.create_task(self._forward_audio())

            # 接收消息循环
            async for message in self._ws:
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    continue
                t = data.get("type")
                if t == "partial":
                    self.partial_received.emit(data.get("text", ""))
                elif t == "transcription":
                    self.transcription_received.emit(data)
                elif t == "status":
                    self.status_received.emit(data.get("status", ""))
                elif t == "error":
                    self.error_occurred.emit(data.get("message", "未知错误"))

        except Exception as e:
            if self._running:
                self.error_occurred.emit(f"WS接收异常: {e}")
        finally:
            if forward_task is not None:
                forward_task.cancel()
                try:
                    await forward_task
                except asyncio.CancelledError:
                    pass

    async def _forward_audio(self):
        """从 audio_queue 取数据转发到服务端"""
        while self._running and self._ws:
            try:
                data = await asyncio.get_event_loop().run_in_executor(
                    None, self._queue_get, 0.1
                )
                if data:
                    await self._ws.send(data)
            except asyncio.CancelledError:
                break
            except Exception:
                continue

    def _queue_get(self, timeout):
        try:
            return self._audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        self._running = False
        if self._ws:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._ws.close(), self._loop
                )
            except Exception:
                pass


# ============================================================
# 4. 时间戳格式化工具
# ============================================================
def format_wall_time(timestamp_str: str = None) -> str:
    """把 ISO 时间戳或当前时间转为 HH:MM:SS 格式（精确到秒）"""
    if timestamp_str:
        try:
            dt = datetime.fromisoformat(timestamp_str)
            return dt.strftime("%H:%M:%S")
        except (ValueError, TypeError):
            pass
    return datetime.now().strftime("%H:%M:%S")
