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
import os
import sys
import json
import time
import queue
import asyncio
import threading
from datetime import datetime, timedelta
from collections import deque

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QTextEdit, QFrame,
    QApplication,
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
        text = self._partial_text or ""
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
            f'<span style="color:#888;font-size:12px;">[{time_str}]</span> '
            f'<span style="color:{sp_color};font-weight:600;font-size:13px;">{sp_label}</span> '
            f'<span style="color:#24292f;">{text}</span>'
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
        self._send_start = True  # 连接后是否自动发 start

    def feed_audio(self, audio_bytes: bytes):
        """主线程调用：把音频数据放入队列（线程安全）"""
        try:
            self._audio_queue.put_nowait(audio_bytes)
        except queue.Full:
            pass  # 队列满则丢弃

    def send_stop(self):
        """请求停止录音"""
        if self._loop and self._ws:
            asyncio.run_coroutine_threadsafe(
                self._send_json({"type": "stop"}), self._loop
            )

    def send_clear(self):
        if self._loop and self._ws:
            asyncio.run_coroutine_threadsafe(
                self._send_json({"type": "clear"}), self._loop
            )

    def send_speaker_rename(self, speaker_id: str, label: str):
        """重命名说话人"""
        if self._loop and self._ws:
            asyncio.run_coroutine_threadsafe(
                self._send_json({"type": "speaker_rename", "speaker_id": speaker_id, "label": label}),
                self._loop
            )

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
        urls = [self._url]
        if "localhost" in self._url:
            urls.append(self._url.replace("localhost", "127.0.0.1"))

        last_err = None
        for url in urls:
            try:
                self._ws = await asyncio.wait_for(
                    websockets.connect(url, ping_interval=20, ping_timeout=60),
                    timeout=5.0,
                )
                break
            except Exception as e:
                last_err = e
                self._ws = None
        else:
            self.error_occurred.emit(f"无法连接到服务器: {last_err}")
            return

        self.connected.emit()

        try:
            # 发送 start，附带模式信息（主播/会议模式让服务端通知网页端禁用按钮）
            if self._send_start:
                await self._ws.send(json.dumps({"type": "start", "mode": self._mode}))

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
