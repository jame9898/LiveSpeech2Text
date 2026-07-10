# -*- coding: utf-8 -*-
import sys
import threading
from datetime import datetime

from core import load_config

import importlib.util

SERVER_THREAD = None

def check_deps():
    missing = []
    for mod in ["torch", "torchaudio", "qwen_asr", "PySide6"]:
        if importlib.util.find_spec(mod) is None:
            missing.append(mod)
    return missing

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QColor, QTextCharFormat, QIcon, QPixmap, QPainter, QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QFrame, QSplitter,
    QGroupBox, QMessageBox, QSystemTrayIcon, QMenu,
    QComboBox, QStackedWidget, QRadioButton, QButtonGroup,
    QCheckBox, QFileDialog, QProgressBar, QLineEdit, QSpinBox,
)
from realtime_panel import (
    SubtitleListView,
    MicCaptureThread, RealtimeWSClient, format_wall_time,
)

LIGHT = {
    "bg":           "#ffffff",
    "surface":      "#f6f8fa",
    "border":       "#d0d7de",
    "text":         "#1f2328",
    "text_dim":     "#656d76",
    "accent":       "#0969da",
    "green":        "#1a7f37",
    "red":          "#cf222e",
    "yellow":       "#9a6700",
    "purple":       "#8250df",
    "log_bg":       "#f6f8fa",
}

UI_REFRESH_MS = 3000


STYLE_SHEET = """
QMainWindow, QWidget {{
    background-color: {bg};
    color: {text};
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 13px;
}}
QMenuBar {{
    background-color: {surface};
    border-bottom: 1px solid {border};
    padding: 2px 0;
}}
QMenuBar::item {{
    padding: 4px 12px;
    background: transparent;
}}
QMenuBar::item:selected {{
    background: {accent};
    color: #fff;
    border-radius: 4px;
}}
QMenu {{
    background-color: #fff;
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 28px 6px 12px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: {accent};
    color: #fff;
}}
QGroupBox {{
    border: 1px solid {border};
    border-radius: 8px;
    margin-top: 14px;
    padding: 16px 14px 12px 16px;
    font-weight: bold;
    color: {text_dim};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    background: {surface};
}}
QPushButton {{
    border: 1px solid {border};
    border-radius: 6px;
    padding: 10px 20px 10px 22px;
    background-color: {surface};
    color: {text};
    font-weight: 500;
}}
QPushButton:hover {{
    border-color: {accent};
    color: {accent};
}}
QPushButton:pressed {{
    background-color: {border};
}}
QPushButton:disabled {{
    color: {text_dim};
}}
/* 工具栏按钮：小padding避免文字被裁剪 */
QPushButton#toolBtn {{
    padding: 6px 14px 6px 16px;
    min-height: 20px;
}}
QPushButton#btnStart {{
    background-color: {green};
    border-color: {green};
    color: #fff;
    font-weight: 600;
}}
QPushButton#btnStart:hover {{
    background-color: #1f6f32;
}}
QPushButton#btnStop {{
    background-color: {red};
    border-color: {red};
    color: #fff;
    font-weight: 600;
}}
QPushButton#btnStop:hover {{
    background-color: #b51d28;
}}
QTextEdit {{
    background-color: {log_bg};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 10px;
    font-family: "Cascadia Code", "Consolas", "Menlo", monospace;
    font-size: 12px;
    color: {text};
}}
QFrame#statusDot {{
    border-radius: 7px;
    min-width: 14px; max-width: 14px;
    min-height: 14px; max-height: 14px;
    margin-left: 4px;
    margin-right: 2px;
}}
QSplitter::handle {{
    background: {border};
    width: 1px;
}}
QSplitter::handle:hover {{
    background: {accent};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {border};
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
/* RadioButton：圆环样式
   未选中=空心灰边框 | 选中=实心绿色填充 | 禁用+选中=保持绿色（锁定当前模式）
   禁用+未选中=空心浅灰边框（其他模式变暗但保持空心） */
QRadioButton {{
    spacing: 10px;
    font-size: 13px;
    padding: 6px 8px 6px 6px;
    min-height: 22px;
    color: {text_dim};
    background: transparent;
}}
QRadioButton:checked {{
    color: {text};
    font-weight: 600;
}}
QRadioButton:!checked {{
    color: {text_dim};
}}
QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 7px;
    border: 2px solid {text_dim};
    background: #fff;
    margin-left: 4px;
    margin-right: 2px;
}}
QRadioButton::indicator:hover {{
    border-color: {accent};
}}
QRadioButton::indicator:checked {{
    border-color: {green};
    background: {green};
}}
QRadioButton::indicator:!checked {{
    border-color: {text_dim};
    background: #fff;
}}
/* 禁用状态下：选中的保持绿色（锁定当前模式），未选中的变浅灰 */
QRadioButton::indicator:checked:disabled {{
    border-color: {green};
    background: {green};
}}
QRadioButton::indicator:!checked:disabled {{
    border-color: {border};
    background: #fff;
}}
QRadioButton:checked:disabled {{
    color: {text};
    font-weight: 600;
}}
QRadioButton:!checked:disabled {{
    color: {border};
}}
/* ComboBox：设备下拉框（箭头用系统原生样式，避免被背景覆盖） */
QComboBox {{
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px 8px;
    background: #fff;
    color: {text};
    font-size: 12px;
}}
QComboBox:hover {{
    border-color: {accent};
}}
QComboBox QAbstractItemView {{
    border: 1px solid {border};
    border-radius: 4px;
    background: #fff;
    selection-background-color: {accent};
    selection-color: #fff;
    padding: 2px;
    outline: none;
}}
/* QStackedWidget 输入源区边框 */
QStackedWidget {{
    border: 1px solid {border};
    border-radius: 8px;
    background: {surface};
}}
/* QSpinBox：字号选择器（箭头用系统原生样式） */
QSpinBox {{
    border: 1px solid {border};
    border-radius: 6px;
    padding: 2px 4px;
    background: #fff;
    color: {text};
    font-size: 13px;
}}
""".format(**LIGHT)


def _make_icon():
    pix = QPixmap(32, 32)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(LIGHT["accent"]))
    p.setPen(Qt.NoPen)
    p.drawEllipse(4, 4, 24, 24)
    p.setPen(QColor(255, 255, 255))
    f = QFont("Segoe UI", 14, QFont.Bold)
    p.setFont(f)
    p.drawText(pix.rect(), Qt.AlignCenter, "A")
    p.end()
    return QIcon(pix)


def start_server_backend(config, log_cb):
    global SERVER_THREAD
    try:
        from core import ASREngine, resolve_device
        from server import run_server

        class LR:
            def __init__(self, cb):
                self._cb = cb; self._b = ""
            def write(self, s):
                if s:
                    self._b += s
                    if "\n" in self._b:
                        ls = self._b.split("\n"); self._b = ls.pop()
                        for l in ls:
                            if l.strip(): self._cb(l + "\n")
            def flush(self):
                if self._b.strip(): self._cb(self._b + "\n"); self._b = ""

        _so, _se = sys.stdout, sys.stderr
        sys.stdout = LR(log_cb)
        sys.stderr = LR(log_cb)

        _model_ready = threading.Event()
        _model_error = [None]

        def _run():
            nonlocal _model_ready, _model_error
            try:
                log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] \u6b63\u5728\u52a0\u8f7d\u6a21\u578b...\n")
                dev = resolve_device(config)
                eng = ASREngine(device=dev, config=config)
                pref = config.get("current_model", "auto")
                if pref == "auto": pref = None
                if not eng.load_model(preferred=pref):
                    log_cb("[ERROR] \u6a21\u578b\u52a0\u8f7d\u5931\u8d25\n")
                    _model_error[0] = "\u6a21\u578b\u52a0\u8f7d\u5931\u8d25"
                    return
                log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] \u6a21\u578b: {eng.model_name}\n")
                st = config.get("model_settings", {})
                port = st.get("ws_port", 8765)

                import subprocess as _sp, platform as _plat, os as _os
                if _plat.system() == 'Windows':
                    my_pid = str(_os.getpid())
                    try:
                        r = _sp.run(['netstat', '-ano'], capture_output=True, text=True)
                        for line in r.stdout.split('\n'):
                            if f':{port}' in line and 'LISTENING' in line:
                                parts = line.strip().split()
                                pid = parts[-1]
                                if pid == my_pid:
                                    log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] \u7aef\u53e3 {port} \u5c1a\u672a\u91ca\u653e\uff0c\u7b49\u5f85\u4e2d...\n")
                                    # 等旧服务退出后再重试，最长等5秒
                                    for _ in range(10):
                                        import time as _t
                                        _t.sleep(0.5)
                                        r2 = _sp.run(['netstat', '-ano'], capture_output=True, text=True)
                                        if not any(f':{port}' in l and 'LISTENING' in l for l in r2.stdout.split('\n')):
                                            break
                                else:
                                    _sp.run(['taskkill', '/F', '/PID', pid],
                                            capture_output=True)
                                    log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] \u5df2\u91ca\u653e\u7aef\u53e3 {port} (\u65e7\u8fdb\u7a0b PID={pid})\n")
                                break
                    except Exception:
                        pass

                _model_ready.set()
                log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] WebSocket ws://localhost:{port}\n")
                log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] \u7b49\u5f85\u8fde\u63a5...\n")
                run_server(eng, 'localhost', port)
                log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] \u670d\u52a1\u5df2\u505c\u6b62\n")
            except Exception as e:
                import traceback
                _model_error[0] = str(e)
                log_cb(f"[ERROR] {e}\n{traceback.format_exc()}\n")
            finally:
                sys.stdout = _so; sys.stderr = _se

        SERVER_THREAD = threading.Thread(target=_run, daemon=True)
        SERVER_THREAD.start()

        # Return event and error holder for non-blocking polling
        return _model_ready, _model_error
    except Exception as e:
        import traceback
        log_cb(f"[ERROR] {e}\n{traceback.format_exc()}\n")
        return None, [str(e)]


def stop_server_backend(log_cb):
    global SERVER_THREAD
    from server import _global_server
    if _global_server is not None:
        _global_server.is_running = False
        # 关闭线程池，释放资源
        if hasattr(_global_server, 'executor'):
            _global_server.executor.shutdown(wait=False)
        # 触发 shutdown_event 让服务端退出
        # 注意：_shutdown_event 在 server 子线程的 asyncio 循环中创建，
        # 直接 .set() 非线程安全，必须通过 call_soon_threadsafe 调度到该循环
        if hasattr(_global_server, '_shutdown_event') and hasattr(_global_server, '_loop'):
            try:
                _global_server._loop.call_soon_threadsafe(_global_server._shutdown_event.set)
            except RuntimeError:
                # loop 已关闭（服务已自行退出），忽略
                pass
    log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] \u6b63\u5728\u505c\u6b62\u670d\u52a1...\n")
    # 等待服务端线程真正退出（最多5秒）
    # 分段 join + processEvents 避免长时间冻结 UI
    if SERVER_THREAD is not None and SERVER_THREAD.is_alive():
        try:
            from PySide6.QtWidgets import QApplication
            waited = 0.0
            while SERVER_THREAD.is_alive() and waited < 5.0:
                SERVER_THREAD.join(timeout=0.1)
                waited += 0.1
                QApplication.processEvents()
        except ImportError:
            SERVER_THREAD.join(timeout=5.0)
        if SERVER_THREAD.is_alive():
            log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] [WARN] \u670d\u52a1\u7ebf\u7a0b\u672a\u5728 5s \u5185\u9000\u51fa\n")
        else:
            log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] \u670d\u52a1\u5df2\u505c\u6b62\n")
    SERVER_THREAD = None


class MainWindow(QMainWindow):
    log_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("\u5728\u7ebf\u5b9e\u65f6\u8bed\u97f3\u8bc6\u522b\u7cfb\u7edf")
        self.setMinimumSize(820, 620)
        self.resize(960, 780)
        self._running = False
        self._tray = None
        self._icon = _make_icon()
        self.setWindowIcon(self._icon)

        self._status_timer = QTimer()
        self._status_timer.setInterval(UI_REFRESH_MS)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start()

        self.log_signal.connect(self._append_log)

        self._build_menu()
        self._build_ui()
        self._apply_style()
        self._setup_tray()
        self._refresh_display()
        self._refresh_audio_devices()

        self._append_log_label("\u6b22\u8fce\u4f7f\u7528\u5728\u7ebf\u5b9e\u65f6\u8bed\u97f3\u8bc6\u522b\u7cfb\u7edf v1.0\n")
        missing = check_deps()
        if missing:
            self._append_log_label(f"[WARN] \u7f3a\u5c11\u4f9d\u8d56: {', '.join(missing)}\n")
            self._append_log_label("  \u8bf7\u53cc\u51fb \u542f\u52a8.bat \u5b89\u88c5\u4f9d\u8d56\n")
            self._emit_log(f"[WARN] \u7f3a\u5c11\u4f9d\u8d56: {', '.join(missing)}\n")
            self._emit_log("  \u8bf7\u53cc\u51fb \u542f\u52a8.bat \u5b89\u88c5\u4f9d\u8d56\n")
        self._append_log_label("\u70b9\u51fb \u542f\u52a8\u670d\u52a1 \u5f00\u59cb\u8bc6\u522b\n\n")

    def _build_menu(self):
        mb = self.menuBar()
        fm = mb.addMenu("\u670d\u52a1(&S)")
        a1 = QAction("\u542f\u52a8\u670d\u52a1", self)
        a1.setShortcut("Ctrl+Return")
        a1.triggered.connect(self._start_server)
        fm.addAction(a1)
        a2 = QAction("\u505c\u6b62\u670d\u52a1", self)
        a2.setShortcut("Ctrl+Shift+Return")
        a2.triggered.connect(self._stop_server)
        fm.addAction(a2)
        fm.addSeparator()
        aq = QAction("\u9000\u51fa(&Q)", self)
        aq.setShortcut("Ctrl+Q")
        aq.triggered.connect(self.close)
        fm.addAction(aq)
        sm = mb.addMenu("\u8bbe\u7f6e")
        as_ = QAction("\u6253\u5f00\u8bbe\u7f6e", self)
        as_.setShortcut("Ctrl+,")
        as_.triggered.connect(self._open_settings)
        sm.addAction(as_)

    def _build_ui(self):
        cw = QWidget()
        self.setCentralWidget(cw)
        root = QHBoxLayout(cw)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        sp = QSplitter(Qt.Horizontal)
        root.addWidget(sp)

        # ====== 左侧栏 ======
        left = QWidget()
        left.setMaximumWidth(240)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)

        # 识别模式选择
        mg = QGroupBox("识别模式")
        ml_box = QVBoxLayout(mg)
        ml_box.setSpacing(4)
        self._rb_audience = QRadioButton("观众模式")
        self._rb_audience.setChecked(True)
        self._rb_streamer = QRadioButton("主播模式")
        self._rb_meeting = QRadioButton("会议模式")
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._rb_audience, 0)
        self._mode_group.addButton(self._rb_streamer, 1)
        self._mode_group.addButton(self._rb_meeting, 2)
        ml_box.addWidget(self._rb_audience)
        ml_box.addWidget(self._rb_streamer)
        ml_box.addWidget(self._rb_meeting)
        self._mode_hint = QLabel("网页声音")
        self._mode_hint.setStyleSheet(f"color:{LIGHT['text_dim']};font-size:11px")
        ml_box.addWidget(self._mode_hint)
        ll.addWidget(mg)

        sg = QGroupBox("\u72b6\u6001")
        sl = QVBoxLayout(sg)
        sh = QHBoxLayout()
        self._dot = QFrame()
        self._dot.setObjectName("statusDot")
        self._dot.setStyleSheet(f"background:{LIGHT['text_dim']}")
        sh.addWidget(self._dot)
        self._slbl = QLabel("\u672a\u542f\u52a8")
        self._slbl.setStyleSheet(f"font-size:15px;font-weight:bold;color:{LIGHT['text_dim']}")
        sh.addWidget(self._slbl)
        sh.addStretch()
        sl.addLayout(sh)
        mrow = QHBoxLayout()
        self._mlbl = QLabel()
        self._mlbl.setStyleSheet(f"color:{LIGHT['text_dim']};font-size:11px")
        mrow.addWidget(self._mlbl)
        mrow.addStretch()
        self._dlbl = QLabel()
        self._dlbl.setStyleSheet(f"color:{LIGHT['text_dim']};font-size:11px")
        mrow.addWidget(self._dlbl)
        sl.addLayout(mrow)
        ll.addWidget(sg)

        stg = QGroupBox("\u7edf\u8ba1")
        stl = QVBoxLayout(stg)
        self._clbl = QLabel("\u5ba2\u6237\u7aef: 0")
        self._clbl.setStyleSheet(f"color:{LIGHT['text_dim']};font-size:12px")
        stl.addWidget(self._clbl)
        self._selbl = QLabel("\u8bc6\u522b: 0 \u53e5")
        self._selbl.setStyleSheet(f"color:{LIGHT['text_dim']};font-size:12px")
        stl.addWidget(self._selbl)
        ll.addWidget(stg)

        cg = QGroupBox("\u63a7\u5236")
        cl = QVBoxLayout(cg)
        cl.setSpacing(6)
        self._btn_start = QPushButton("\u542f\u52a8\u670d\u52a1")
        self._btn_start.setObjectName("btnStart")
        self._btn_start.clicked.connect(self._start_server)
        cl.addWidget(self._btn_start)
        self._btn_stop = QPushButton("\u505c\u6b62\u670d\u52a1")
        self._btn_stop.setObjectName("btnStop")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop_server)
        cl.addWidget(self._btn_stop)
        self._btn_cfg = QPushButton("\u8bbe\u7f6e")
        self._btn_cfg.clicked.connect(self._open_settings)
        cl.addWidget(self._btn_cfg)
        ll.addWidget(cg)
        ll.addStretch()

        # ====== 右侧：输入源区 + 日志区 ======
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)

        # 输入源区（QStackedWidget，随模式切换）
        self._source_stack = QStackedWidget()
        self._source_stack.setMinimumHeight(120)

        # 页0：观众模式 — 网页声音
        page_audience = QWidget()
        pl_a = QVBoxLayout(page_audience)
        pl_a.setContentsMargins(8, 8, 8, 8)
        pl_a.setSpacing(6)
        la1 = QLabel("观众模式：识别网页播放的声音")
        la1.setStyleSheet(f"font-size:13px;font-weight:600;color:{LIGHT['text']}")
        pl_a.addWidget(la1)
        la2 = QLabel("安装油猴脚本 asr_panel.user.js，在目标直播/视频页面打开，\n脚本通过 getDisplayMedia 捕获标签页音频并推送到本地服务。")
        la2.setStyleSheet(f"color:{LIGHT['text_dim']};font-size:12px")
        la2.setWordWrap(True)
        pl_a.addWidget(la2)
        pl_a.addStretch()
        self._source_stack.addWidget(page_audience)

        # 页1：主播模式 — 麦克风
        page_streamer = QWidget()
        pl_s = QVBoxLayout(page_streamer)
        pl_s.setContentsMargins(8, 8, 8, 8)
        pl_s.setSpacing(6)
        ls1 = QLabel("主播模式：拾取麦克风声音")
        ls1.setStyleSheet(f"font-size:13px;font-weight:600;color:{LIGHT['text']}")
        pl_s.addWidget(ls1)
        mic_row = QHBoxLayout()
        mic_row.addWidget(QLabel("麦克风:"))
        self._mic_combo = QComboBox()
        self._mic_combo.setEditable(False)
        self._mic_combo.addItem("（未检测设备）")
        mic_row.addWidget(self._mic_combo, 1)
        mic_row.addWidget(QLabel("音量:"))
        self._mic_level = QProgressBar()
        self._mic_level.setFixedHeight(12)
        self._mic_level.setMaximumWidth(120)
        self._mic_level.setRange(0, 100)
        self._mic_level.setTextVisible(False)
        self._mic_level.setStyleSheet(
            "QProgressBar { background: #e1e4e8; border-radius: 6px; }"
            "QProgressBar::chunk { background: #52c41a; border-radius: 6px; }"
        )
        mic_row.addWidget(self._mic_level)
        pl_s.addLayout(mic_row)

        # 工具栏：测试麦克风 + 打开字幕页 + 导出（统一高度32px）
        tool_row_s = QHBoxLayout()
        tool_row_s.setSpacing(8)
        self._btn_test_mic = QPushButton("测试麦克风")
        self._btn_test_mic.setObjectName("toolBtn")
        self._btn_test_mic.setFixedHeight(32)
        self._btn_test_mic.setMinimumWidth(104)
        self._btn_test_mic.clicked.connect(self._test_microphone)
        tool_row_s.addWidget(self._btn_test_mic)
        self._btn_subtitle = QPushButton("打开字幕页")
        self._btn_subtitle.setObjectName("toolBtn")
        self._btn_subtitle.setFixedHeight(32)
        self._btn_subtitle.setMinimumWidth(104)
        self._btn_subtitle.clicked.connect(self._open_subtitle_page)
        tool_row_s.addWidget(self._btn_subtitle)
        tool_row_s.addStretch()
        self._btn_export_s = QPushButton("导出 MD 文档")
        self._btn_export_s.setObjectName("toolBtn")
        self._btn_export_s.setFixedHeight(32)
        self._btn_export_s.setMinimumWidth(110)
        self._btn_export_s.clicked.connect(self._export_subtitles)
        tool_row_s.addWidget(self._btn_export_s)
        pl_s.addLayout(tool_row_s)

        # Speaker命名（下拉框和输入框统一高度32px、统一宽度140px）
        name_row_s = QHBoxLayout()
        name_row_s.setSpacing(8)
        name_row_s.addWidget(QLabel("说话人:"))
        self._speaker_combo = QComboBox()
        self._speaker_combo.addItem("Speaker0")
        self._speaker_combo.setFixedHeight(32)
        self._speaker_combo.setFixedWidth(140)
        self._speaker_combo.currentIndexChanged.connect(self._on_speaker_combo_changed)
        name_row_s.addWidget(self._speaker_combo)
        self._speaker_name_input = QLineEdit()
        self._speaker_name_input.setPlaceholderText("输入名字（回车应用）")
        self._speaker_name_input.setFixedHeight(32)
        self._speaker_name_input.setFixedWidth(140)
        self._speaker_name_input.returnPressed.connect(self._apply_speaker_name)
        name_row_s.addWidget(self._speaker_name_input)
        name_row_s.addStretch()
        pl_s.addLayout(name_row_s)

        # 字幕页 URL 显示与复制（主播模式）
        self._url_rows_s = self._build_url_rows(pl_s)

        ls2 = QLabel("选择麦克风后启动服务，本地将采集麦克风音频并实时识别。")
        ls2.setStyleSheet(f"color:{LIGHT['text_dim']};font-size:12px")
        ls2.setWordWrap(True)
        pl_s.addWidget(ls2)
        pl_s.addStretch()
        self._source_stack.addWidget(page_streamer)

        # 页2：会议模式 — 麦克风 + 系统音频
        page_meeting = QWidget()
        pl_m = QVBoxLayout(page_meeting)
        pl_m.setContentsMargins(8, 8, 8, 8)
        pl_m.setSpacing(6)
        lm1 = QLabel("会议模式：同时拾取麦克风和系统音频")
        lm1.setStyleSheet(f"font-size:13px;font-weight:600;color:{LIGHT['text']}")
        pl_m.addWidget(lm1)
        mmic_row = QHBoxLayout()
        mmic_row.addWidget(QLabel("麦克风（本地）:"))
        self._meet_mic_combo = QComboBox()
        self._meet_mic_combo.setEditable(False)
        self._meet_mic_combo.addItem("（未检测设备）")
        mmic_row.addWidget(self._meet_mic_combo, 1)
        pl_m.addLayout(mmic_row)
        msys_row = QHBoxLayout()
        msys_row.addWidget(QLabel("系统音频:"))
        self._meet_sys_combo = QComboBox()
        self._meet_sys_combo.setEditable(False)
        self._meet_sys_combo.addItem("（未检测设备）")
        msys_row.addWidget(self._meet_sys_combo, 1)
        msys_row.addWidget(QLabel("音量:"))
        self._meet_level = QProgressBar()
        self._meet_level.setFixedHeight(12)
        self._meet_level.setMaximumWidth(120)
        self._meet_level.setRange(0, 100)
        self._meet_level.setTextVisible(False)
        self._meet_level.setStyleSheet(
            "QProgressBar { background: #e1e4e8; border-radius: 6px; }"
            "QProgressBar::chunk { background: #52c41a; border-radius: 6px; }"
        )
        msys_row.addWidget(self._meet_level)
        pl_m.addLayout(msys_row)

        # 工具栏：测试麦克风 + 打开字幕页 + 导出（会议模式）
        tool_row_m = QHBoxLayout()
        tool_row_m.setSpacing(8)
        self._btn_test_mic_m = QPushButton("测试麦克风")
        self._btn_test_mic_m.setObjectName("toolBtn")
        self._btn_test_mic_m.setFixedHeight(32)
        self._btn_test_mic_m.setMinimumWidth(104)
        self._btn_test_mic_m.clicked.connect(self._test_microphone)
        tool_row_m.addWidget(self._btn_test_mic_m)
        self._btn_subtitle_m = QPushButton("打开字幕页")
        self._btn_subtitle_m.setObjectName("toolBtn")
        self._btn_subtitle_m.setFixedHeight(32)
        self._btn_subtitle_m.setMinimumWidth(104)
        self._btn_subtitle_m.clicked.connect(self._open_subtitle_page)
        tool_row_m.addWidget(self._btn_subtitle_m)
        tool_row_m.addStretch()
        self._btn_export_m = QPushButton("导出 MD 文档")
        self._btn_export_m.setObjectName("toolBtn")
        self._btn_export_m.setFixedHeight(32)
        self._btn_export_m.setMinimumWidth(110)
        self._btn_export_m.clicked.connect(self._export_subtitles)
        tool_row_m.addWidget(self._btn_export_m)
        pl_m.addLayout(tool_row_m)

        # Speaker命名（下拉框和输入框统一高度32px、统一宽度140px）
        name_row_m = QHBoxLayout()
        name_row_m.setSpacing(8)
        name_row_m.addWidget(QLabel("说话人:"))
        self._speaker_combo_m = QComboBox()
        self._speaker_combo_m.addItem("Speaker0")
        self._speaker_combo_m.setFixedHeight(32)
        self._speaker_combo_m.setFixedWidth(140)
        self._speaker_combo_m.currentIndexChanged.connect(self._on_speaker_combo_changed)
        name_row_m.addWidget(self._speaker_combo_m)
        self._speaker_name_input_m = QLineEdit()
        self._speaker_name_input_m.setPlaceholderText("输入名字（回车应用）")
        self._speaker_name_input_m.setFixedHeight(32)
        self._speaker_name_input_m.setFixedWidth(140)
        self._speaker_name_input_m.returnPressed.connect(self._apply_speaker_name)
        name_row_m.addWidget(self._speaker_name_input_m)
        name_row_m.addStretch()
        pl_m.addLayout(name_row_m)

        # 字幕页 URL 显示与复制（会议模式）
        self._url_rows_m = self._build_url_rows(pl_m)

        lm2 = QLabel("本地说话人由麦克风采集，远端参会者由系统音频采集（需虚拟声卡）。")
        lm2.setStyleSheet(f"color:{LIGHT['text_dim']};font-size:12px")
        lm2.setWordWrap(True)
        pl_m.addWidget(lm2)
        pl_m.addStretch()
        self._source_stack.addWidget(page_meeting)

        rl.addWidget(self._source_stack)

        # 模式切换 → 切换输入源页 + 更新提示
        self._mode_group.idClicked.connect(self._on_mode_changed)

        # 字幕展示区（所有模式共用，放在输入源和日志之间）
        rl.addWidget(QLabel("\u5b57\u5e55\u5c55\u793a"))
        self._subtitle_view = SubtitleListView()
        self._subtitle_view.setMinimumHeight(120)
        rl.addWidget(self._subtitle_view, stretch=1)

        # 日志区（程序性日志：VAD切分、连接状态、识别段数等）
        rl.addWidget(QLabel("\u63a7\u5236\u53f0\u65e5\u5fd7"))
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.document().setMaximumBlockCount(6000)
        self._log.setMaximumHeight(160)
        rl.addWidget(self._log)
        self._info = QLabel("Ctrl+Enter \u542f\u52a8 | Ctrl+Shift+Enter \u505c\u6b62 | Ctrl+, \u8bbe\u7f6e | Ctrl+Q \u9000\u51fa")
        self._info.setStyleSheet(f"color:{LIGHT['text_dim']};font-size:11px")
        rl.addWidget(self._info)

        # 实时采集/WS 客户端成员（主播/会议模式使用）
        self._mic_thread = None
        self._ws_client = None
        self._test_mic_thread = None
        self._test_ws_client = None
        self._pending_speaker_name = None  # 缓存的说话人名称（服务启动后发送）
        self._speaker_names = {"Speaker0": ""}  # 说话人名称字典 {speaker_id: name}

        sp.addWidget(left)
        sp.addWidget(right)
        sp.setStretchFactor(0, 0)
        sp.setStretchFactor(1, 1)
        sp.setSizes([240, 640])

    def _on_mode_changed(self, btn_id):
        """模式切换：切换输入源页 + 更新提示文字"""
        self._source_stack.setCurrentIndex(btn_id)
        hints = {0: "网页声音", 1: "麦克风", 2: "麦克风 + 系统音频"}
        self._mode_hint.setText(hints.get(btn_id, ""))

    def _refresh_audio_devices(self):
        """检测本地音频设备，填充下拉框
        输入设备（麦克风）→ 主播模式 + 会议模式的麦克风下拉
        输出设备（回环/喇叭）→ 会议模式的系统音频下拉
        """
        try:
            import sounddevice as sd
            devices = sd.query_devices()
        except Exception as e:
            self._append_log_label(f"[WARN] 音频设备检测失败: {e}\n")
            return

        input_devs = []   # 输入设备（麦克风）
        output_devs = []  # 输出设备（喇叭/回环）
        for i, d in enumerate(devices):
            name = d.get("name", "")
            if d.get("max_input_channels", 0) > 0:
                input_devs.append((i, name))
            if d.get("max_output_channels", 0) > 0:
                output_devs.append((i, name))

        def _fill(combo, items, placeholder):
            combo.clear()
            if not items:
                combo.addItem(placeholder)
                combo.setEnabled(False)
                return
            combo.setEnabled(True)
            for idx, name in items:
                combo.addItem(f"[{idx}] {name}", userData=idx)
            combo.setCurrentIndex(0)

        _fill(self._mic_combo, input_devs, "（未检测到输入设备）")
        _fill(self._meet_mic_combo, input_devs, "（未检测到输入设备）")
        _fill(self._meet_sys_combo, output_devs, "（未检测到输出设备）")

        self._append_log_label(
            f"[INFO] 检测到音频设备: 输入 {len(input_devs)} 个, 输出 {len(output_devs)} 个\n"
        )

    def _apply_style(self):
        self.setStyleSheet(STYLE_SHEET)

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(self._icon)
        self._tray.setToolTip("\u5728\u7ebf\u5b9e\u65f6\u8bed\u97f3\u8bc6\u522b\u7cfb\u7edf")
        m = QMenu()
        m.addAction("\u663e\u793a/\u9690\u85cf", self._toggle_window)
        m.addSeparator()
        m.addAction("\u9000\u51fa", self.close)
        self._tray.setContextMenu(m)
        self._tray.activated.connect(lambda r: self._toggle_window() if r == QSystemTrayIcon.DoubleClick else None)
        self._tray.show()

    def _toggle_window(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def closeEvent(self, event):
        if self._running:
            r = QMessageBox.question(self, "\u786e\u8ba4\u9000\u51fa",
                "\u670d\u52a1\u6b63\u5728\u8fd0\u884c\u4e2d\uff0c\u786e\u5b9a\u8981\u9000\u51fa\u5417\uff1f",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r == QMessageBox.No:
                event.ignore()
                return
            self._stop_server()
        if self._tray is not None:
            self._tray.hide()
        event.accept()

    @Slot(str)
    def _append_log(self, text):
        # 过滤掉识别文字相关的日志（这些已显示在字幕展示区，不重复在控制台显示）
        _FILTERS = (
            "Streaming transcription done",
            "[SEG]",
            "[SPEAKER]",
            "ASR \u65e0\u6587\u672c",
            "[\u8bc6\u522b]",
        )
        for kw in _FILTERS:
            if kw in text:
                return
        fmt = QTextCharFormat()
        if "[ERROR]" in text:
            fmt.setForeground(QColor(LIGHT["red"]))
        elif "[WARN]" in text:
            fmt.setForeground(QColor(LIGHT["yellow"]))
        elif "[OK]" in text:
            fmt.setForeground(QColor(LIGHT["green"]))
        else:
            fmt.setForeground(QColor(LIGHT["text"]))
        c = self._log.textCursor()
        c.movePosition(QTextCursor.End)
        c.insertText(text, fmt)
        self._log.verticalScrollBar().setValue(self._log.verticalScrollBar().maximum())

    def _append_log_label(self, text):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(LIGHT["text_dim"]))
        c = self._log.textCursor()
        c.movePosition(QTextCursor.End)
        c.insertText(text, fmt)
        self._log.verticalScrollBar().setValue(self._log.verticalScrollBar().maximum())

    def _emit_log(self, text):
        self.log_signal.emit(text)

    def _refresh_display(self):
        try:
            cfg = load_config()
            self._mlbl.setText(f"\u6a21\u578b: {cfg.get('current_model','auto')}")
            self._dlbl.setText(f"\u8bbe\u5907: {cfg.get('device','auto')}")
        except Exception as e:
            print(f"[UI] _refresh_display error: {e}", flush=True)

    def _start_server(self):
        if self._running:
            return
        cfg = load_config()
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self._emit_log(f"\n{'=' * 50}\n")
        self._emit_log(f"  \u542f\u52a8\u670d\u52a1 {ts}\n")
        self._emit_log(f"{'=' * 50}\n")
        ready_event, error_holder = start_server_backend(cfg, self._emit_log)
        if ready_event is None:
            self._emit_log("[ERROR] \u670d\u52a1\u542f\u52a8\u5931\u8d25\n")
            return

        # Disable start button immediately to prevent double-click
        self._btn_start.setEnabled(False)
        self._slbl.setText("\u542f\u52a8\u4e2d...")
        self._slbl.setStyleSheet(f"font-size:15px;font-weight:bold;color:{LIGHT['yellow']}")
        self._dot.setStyleSheet(f"background:{LIGHT['yellow']}")

        self._wait_start_time = __import__("time").time()
        self._ready_event = ready_event
        self._error_holder = error_holder
        self._wait_timer = QTimer()
        self._wait_timer.setInterval(500)
        self._wait_timer.timeout.connect(self._poll_server_ready)
        self._wait_timer.start()

    def _poll_server_ready(self):
        if self._ready_event.is_set():
            self._wait_timer.stop()
            self._running = True
            self._update_ui_state()
            self._emit_log("[OK] \u670d\u52a1\u5df2\u5c31\u7eea\n")
            # 主播/会议模式：启动麦克风采集 + WS 客户端
            self._start_realtime_capture()
        elif self._error_holder[0] is not None:
            self._wait_timer.stop()
            self._emit_log(f"[ERROR] \u670d\u52a1\u542f\u52a8\u5931\u8d25: {self._error_holder[0]}\n")
            self._running = False
            self._update_ui_state()
        elif __import__("time").time() - self._wait_start_time > 120:
            self._wait_timer.stop()
            self._emit_log("[ERROR] \u6a21\u578b\u52a0\u8f7d\u8d85\u65f6 (120s)\n")
            self._running = False
            self._update_ui_state()
            # 清理后台线程：超时后 server 线程可能仍在加载模型/起服务，
            # 必须主动停止，否则会占用端口导致下次启动冲突
            self._emit_log("[INFO] \u6b63\u5728\u6e05\u7406\u540e\u53f0\u7ebf\u7a0b...\n")
            stop_server_backend(self._emit_log)

    def _stop_server(self):
        if not self._running:
            return
        # 先停止实时采集
        self._stop_realtime_capture()
        stop_server_backend(self._emit_log)
        self._running = False
        self._update_ui_state()


    # ============================================================
    # 实时采集（主播/会议模式）
    # ============================================================
    def _get_current_mode(self):
        """返回当前模式索引: 0=观众 1=主播 2=会议"""
        return self._source_stack.currentIndex()

    def _get_selected_mic_index(self):
        """从当前模式的下拉框获取麦克风设备索引"""
        mode = self._get_current_mode()
        combo = self._mic_combo if mode == 1 else self._meet_mic_combo
        text = combo.currentText()
        if text.startswith("["):
            try:
                return int(text.split("]")[0].strip("["))
            except (ValueError, IndexError):
                pass
        return None

    def _start_realtime_capture(self):
        """服务就绪后，主播/会议模式启动麦克风采集 + WS客户端"""
        mode = self._get_current_mode()
        if mode == 0:
            # 观众模式：不需要本地采集，靠浏览器油猴脚本
            self._emit_log("[INFO] 观众模式：等待浏览器端连接\n")
            return

        mic_idx = self._get_selected_mic_index()
        if mic_idx is None:
            self._emit_log("[WARN] 未选择麦克风设备，无法启动本地采集\n")
            return

        # 启动 WS 客户端（接收识别结果），传递模式让服务端通知网页端禁用
        mode_str = "streamer" if mode == 1 else "meeting"
        self._ws_client = RealtimeWSClient("ws://localhost:8765", mode=mode_str)
        self._ws_client.partial_received.connect(self._on_partial)
        self._ws_client.transcription_received.connect(self._on_transcription)
        self._ws_client.connected.connect(self._on_ws_connected)
        self._ws_client.error_occurred.connect(
            lambda e: self._emit_log(f"[ERROR] WS: {e}\n")
        )
        self._ws_client.start()

        # 启动麦克风采集
        self._mic_thread = MicCaptureThread(device_index=mic_idx)
        self._mic_thread.audio_chunk.connect(self._on_mic_chunk)
        self._mic_thread.level_update.connect(self._on_mic_level)
        self._mic_thread.error_occurred.connect(
            lambda e: self._emit_log(f"[ERROR] 麦克风: {e}\n")
        )
        self._mic_thread.start()

    def _stop_realtime_capture(self):
        """停止麦克风采集 + WS客户端"""
        if self._mic_thread is not None:
            self._mic_thread.stop()
            self._mic_thread.wait(2000)
            self._mic_thread = None
        if self._ws_client is not None:
            self._ws_client.send_stop()
            self._ws_client.stop()
            self._ws_client.wait(2000)
            self._ws_client = None
        # 重置音量条
        self._mic_level.setValue(0)
        self._meet_level.setValue(0)

    def _on_mic_chunk(self, audio_data):
        """麦克风采集回调：转发到 WS 客户端"""
        if self._ws_client is not None and self._ws_client.isRunning():
            self._ws_client.feed_audio(audio_data.tobytes())

    def _on_mic_level(self, level):
        """音量电平更新"""
        mode = self._get_current_mode()
        bar = self._mic_level if mode == 1 else self._meet_level
        bar.setValue(int(level * 100))

    def _on_ws_connected(self):
        """WS客户端连接成功：发送缓存的说话人名称"""
        self._emit_log("[OK] WS客户端已连接，开始采集麦克风\n")
        if self._pending_speaker_name:
            spk_id, name = self._pending_speaker_name
            self._ws_client.send_speaker_rename(spk_id, name)
            self._emit_log(f"[OK] 说话人已重命名: {spk_id} -> {name}\n")
            self._pending_speaker_name = None
        # 发送所有已保存的说话人名称
        for spk_id, name in self._speaker_names.items():
            if name:
                self._ws_client.send_speaker_rename(spk_id, name)

    def _on_partial(self, text):
        """收到 partial 中间结果（无 speaker 信息，用白色）"""
        self._subtitle_view.set_partial(text)

    def _on_transcription(self, data):
        """收到 transcription 最终结果"""
        text = data.get("text", "")
        speaker = data.get("speaker", "") or data.get("speaker_label", "发言人")
        is_host = data.get("is_host", False)
        # 用墙钟时间（HH:MM:SS），优先用服务端的 timestamp
        time_str = format_wall_time(data.get("timestamp"))

        # 检测新 Speaker（如 Speaker1），自动添加到下拉框
        self._ensure_speaker(speaker)

        # 说话人显示：优先用已命名的名称
        display_name = self._speaker_names.get(speaker, "") or speaker

        # 追加到字幕展示区
        self._subtitle_view.add_segment(time_str, display_name, text, is_host)
        # partial 清空（等待下一段）
        self._subtitle_view.set_partial("")

    def _ensure_speaker(self, spk_id: str):
        """检测新 Speaker，自动添加到两个下拉框（主播+会议）"""
        if not spk_id or spk_id in self._speaker_names:
            return
        self._speaker_names[spk_id] = ""
        for combo in (self._speaker_combo, self._speaker_combo_m):
            if combo.findText(spk_id) < 0:
                combo.addItem(spk_id)
        self._emit_log(f"[INFO] 检测到新说话人: {spk_id}，可在下拉框选择并命名\n")

    def _get_speaker_name_input(self):
        """获取当前模式的说话人名称输入框"""
        mode = self._get_current_mode()
        return self._speaker_name_input if mode == 1 else self._speaker_name_input_m

    def _get_speaker_combo(self):
        """获取当前模式的说话人下拉框"""
        mode = self._get_current_mode()
        return self._speaker_combo if mode == 1 else self._speaker_combo_m

    def _on_speaker_combo_changed(self):
        """下拉框切换：加载已保存的说话人名称到输入框"""
        combo = self._get_speaker_combo()
        spk_id = combo.currentText()
        inp = self._get_speaker_name_input()
        inp.setText(self._speaker_names.get(spk_id, ""))

    def _apply_speaker_name(self):
        """应用说话人名称：对当前选中的 Speaker 发送 rename"""
        combo = self._get_speaker_combo()
        spk_id = combo.currentText()
        inp = self._get_speaker_name_input()
        name = inp.text().strip()
        if not name:
            self._emit_log(f"[INFO] {spk_id} 名称为空，保持默认\n")
            return
        # 保存到字典
        self._speaker_names[spk_id] = name
        if self._ws_client is not None and self._ws_client.isRunning():
            self._ws_client.send_speaker_rename(spk_id, name)
            self._emit_log(f"[OK] 说话人已重命名: {spk_id} -> {name}\n")
        else:
            self._emit_log("[WARN] WS未连接，名称将在服务启动后生效\n")
            # 缓存名称，服务启动后发送
            self._pending_speaker_name = (spk_id, name)

    def _open_subtitle_page(self):
        """打开字幕页设置（OBS 浏览器源配置）
        点击后打开配置模式（?settings=1），可在网页内调整字号/说话人名/历史句数。
        """
        config = load_config()
        port = config.get("model_settings", {}).get("ws_port", 8765)
        cfg_url = f"http://localhost:{port}/subtitle?settings=1"
        obs_url = f"http://localhost:{port}/subtitle"
        if not self._running:
            QMessageBox.information(self, "提示", f"请先启动服务，再打开字幕页。\n\n配置页（调字号/说话人名）：\n{cfg_url}\n\nOBS 浏览器源 URL：\n{obs_url}")
            return
        try:
            import webbrowser
            webbrowser.open(cfg_url)
            self._emit_log(f"[INFO] 已打开字幕页配置: {cfg_url}\n[INFO] OBS 浏览器源 URL(填入OBS): {obs_url}\n")
        except Exception as e:
            self._emit_log(f"[ERROR] 打开字幕页失败: {e}\n[INFO] OBS 浏览器源 URL: {obs_url}\n")

    def _build_url_rows(self, parent_layout):
        """构建字幕页 URL 显示行（字幕页 + 设置页），含复制按钮。
        未启动时显示提示文字，启动后显示真实 URL。
        返回控件引用字典，用于后续更新 URL。
        """
        config = load_config()
        port = config.get("model_settings", {}).get("ws_port", 8765)
        obs_url = f"http://localhost:{port}/subtitle"
        cfg_url = f"http://localhost:{port}/subtitle?settings=1"

        refs = {}
        # 字幕页 URL 行
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        lbl1 = QLabel("字幕页:")
        lbl1.setStyleSheet(f"color:{LIGHT['text_dim']};font-size:12px")
        lbl1.setFixedWidth(60)
        row1.addWidget(lbl1)
        url1 = QLineEdit("启动服务后，显示字幕页http地址")
        url1.setReadOnly(True)
        url1.setStyleSheet("font-size:12px;")
        row1.addWidget(url1, stretch=1)
        btn1 = QPushButton("复制")
        btn1.setObjectName("toolBtn")
        btn1.setFixedHeight(26)
        btn1.setFixedWidth(56)
        btn1.setEnabled(False)
        btn1.clicked.connect(lambda: self._copy_url(obs_url, btn1))
        row1.addWidget(btn1)
        parent_layout.addLayout(row1)

        # 设置页 URL 行
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        lbl2 = QLabel("设置页:")
        lbl2.setStyleSheet(f"color:{LIGHT['text_dim']};font-size:12px")
        lbl2.setFixedWidth(60)
        row2.addWidget(lbl2)
        url2 = QLineEdit("启动服务后，显示字幕设置页http地址")
        url2.setReadOnly(True)
        url2.setStyleSheet("font-size:12px;")
        row2.addWidget(url2, stretch=1)
        btn2 = QPushButton("复制")
        btn2.setObjectName("toolBtn")
        btn2.setFixedHeight(26)
        btn2.setFixedWidth(56)
        btn2.setEnabled(False)
        btn2.clicked.connect(lambda: self._copy_url(cfg_url, btn2))
        row2.addWidget(btn2)
        parent_layout.addLayout(row2)

        refs['obs_url'] = url1
        refs['cfg_url'] = url2
        refs['btn_obs'] = btn1
        refs['btn_cfg'] = btn2
        return refs

    def _copy_url(self, url, btn):
        """复制 URL 到剪贴板"""
        clipboard = QApplication.clipboard()
        clipboard.setText(url)
        old_text = btn.text()
        btn.setText("已复制")
        QTimer.singleShot(1500, lambda: btn.setText(old_text))

    # ============================================================
    # 测试麦克风
    # ============================================================
    def _test_microphone(self):
        """测试麦克风：采集5秒音频 → 发送到WS → 显示识别结果"""
        if self._test_mic_thread is not None or self._test_ws_client is not None:
            self._emit_log("[INFO] 测试进行中，请等待...\n")
            return

        mic_idx = self._get_selected_mic_index()
        if mic_idx is None:
            QMessageBox.warning(self, "提示", "请先选择麦克风设备")
            return

        self._emit_log("[测试] 开始测试麦克风（采集5秒）...\n")
        self._subtitle_view.set_partial("[测试中，请说话...]")

        # 如果服务没启动，提示用户
        if not self._running:
            QMessageBox.warning(self, "提示", "请先启动服务再测试麦克风")
            self._subtitle_view.set_partial("")
            return

        # 临时 WS 客户端（不复用主 WS 客户端，避免冲突）
        # 实际上直接用主 WS 客户端发音频更简单，但为了隔离测试逻辑，用独立的
        # 注意：server.py 同一时间只允许一个 recording 客户端
        # 如果主 WS 客户端已经在 recording，测试会失败
        # 方案：测试时用主 WS 客户端发音频（如果已连接），否则创建临时连接
        if self._ws_client is not None and self._ws_client.isRunning():
            # 主客户端已连接，直接用临时采集线程发音频
            self._test_mic_thread = MicCaptureThread(device_index=mic_idx)
            self._test_mic_thread.audio_chunk.connect(self._on_mic_chunk)
            self._test_mic_thread.error_occurred.connect(
                lambda e: self._emit_log(f"[测试] 麦克风错误: {e}\n")
            )
            self._test_mic_thread.start()
            # 5秒后停止
            QTimer.singleShot(5000, self._finish_test_mic)
        else:
            # 主客户端未连接（可能是观众模式），创建临时 WS 客户端
            mode = self._get_current_mode()
            mode_str = "streamer" if mode == 1 else "meeting" if mode == 2 else "audience"
            self._test_ws_client = RealtimeWSClient("ws://localhost:8765", mode=mode_str)
            self._test_ws_client.partial_received.connect(self._on_partial)
            self._test_ws_client.transcription_received.connect(self._on_transcription)
            self._test_ws_client.connected.connect(
                lambda: self._emit_log("[测试] WS已连接，开始采集\n")
            )
            self._test_ws_client.error_occurred.connect(
                lambda e: self._emit_log(f"[测试] WS错误: {e}\n")
            )
            self._test_ws_client.start()

            self._test_mic_thread = MicCaptureThread(device_index=mic_idx)
            self._test_mic_thread.audio_chunk.connect(
                lambda d: self._test_ws_client.feed_audio(d.tobytes()) if self._test_ws_client else None
            )
            self._test_mic_thread.start()
            QTimer.singleShot(5000, self._finish_test_mic)

    def _finish_test_mic(self):
        """结束麦克风测试"""
        if self._test_mic_thread is not None:
            self._test_mic_thread.stop()
            self._test_mic_thread.wait(2000)
            self._test_mic_thread = None
        # 如果是临时 WS 客户端，停止它
        if self._test_ws_client is not None:
            self._test_ws_client.send_stop()
            self._test_ws_client.stop()
            self._test_ws_client.wait(2000)
            self._test_ws_client = None
        self._emit_log("[测试] 麦克风测试结束\n")
        self._subtitle_view.set_partial("")

    # ============================================================
    # 导出字幕
    # ============================================================
    def _export_subtitles(self):
        """导出字幕展示区的内容为文本文件"""
        segments = self._subtitle_view.get_segments()
        if not segments:
            QMessageBox.information(self, "提示", "暂无字幕可导出")
            return

        default_name = f"字幕_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出字幕", default_name,
            "文本文件 (*.txt);;所有文件 (*.*)"
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                for time_str, speaker, text in segments:
                    f.write(f"[{time_str}] {speaker}: {text}\n")
            self._emit_log(f"[导出] 已保存到 {path}\n")
            QMessageBox.information(self, "导出成功", f"已导出 {len(segments)} 条字幕到:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))


    def _update_ui_state(self):
        if self._running:
            self._dot.setStyleSheet(f"background:{LIGHT['green']}")
            self._slbl.setText("\u8fd0\u884c\u4e2d")
            self._slbl.setStyleSheet(f"font-size:15px;font-weight:bold;color:{LIGHT['green']}")
            # 启动按钮文字变为"运行中"，禁用但仍可见（不隐藏，让用户看到状态）
            self._btn_start.setText("运行中")
            self._btn_start.setEnabled(False)
            self._btn_stop.setEnabled(True)
            # 锁定模式切换：服务运行时不允许切换识别模式
            self._rb_audience.setEnabled(False)
            self._rb_streamer.setEnabled(False)
            self._rb_meeting.setEnabled(False)
            # 启动后显示真实 URL
            self._update_url_rows(True)
        else:
            self._dot.setStyleSheet(f"background:{LIGHT['text_dim']}")
            self._slbl.setText("\u672a\u542f\u52a8")
            self._slbl.setStyleSheet(f"font-size:15px;font-weight:bold;color:{LIGHT['text_dim']}")
            self._btn_start.setText("\u542f\u52a8\u670d\u52a1")
            self._btn_start.setEnabled(True)
            self._btn_stop.setEnabled(False)
            # 解锁模式切换
            self._rb_audience.setEnabled(True)
            self._rb_streamer.setEnabled(True)
            self._rb_meeting.setEnabled(True)
            # 未启动时显示提示文字
            self._update_url_rows(False)

    def _update_url_rows(self, running):
        """根据服务状态更新字幕页/设置页 URL 框内容"""
        config = load_config()
        port = config.get("model_settings", {}).get("ws_port", 8765)
        if running:
            obs_url = f"http://localhost:{port}/subtitle"
            cfg_url = f"http://localhost:{port}/subtitle?settings=1"
        else:
            obs_url = "启动服务后，显示字幕页http地址"
            cfg_url = "启动服务后，显示字幕设置页http地址"
        for refs in (getattr(self, '_url_rows_s', None), getattr(self, '_url_rows_m', None)):
            if not refs:
                continue
            if 'obs_url' in refs:
                refs['obs_url'].setText(obs_url)
            if 'cfg_url' in refs:
                refs['cfg_url'].setText(cfg_url)
            # 同步启用/禁用复制按钮：未启动时禁用，启动后启用
            if 'btn_obs' in refs:
                refs['btn_obs'].setEnabled(running)
            if 'btn_cfg' in refs:
                refs['btn_cfg'].setEnabled(running)

    def _refresh_status(self):
        try:
            if self._running:
                import server as svr_mod
                srv = svr_mod._global_server
                if srv is not None:
                    self._clbl.setText(f"\u5ba2\u6237\u7aef: {1 if srv.client_connected else 0}")
                    self._selbl.setText(f"\u8bc6\u522b: {len(srv.segments)} \u53e5")
        except Exception as e:
            print(f"[UI] _refresh_status error: {e}", flush=True)

    def _open_settings(self):
        from settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.exec()
        if dlg.needs_restart and self._running:
            r = QMessageBox.question(self, "\u91cd\u542f\u670d\u52a1",
                "\u914d\u7f6e\u5df2\u66f4\u6539\uff0c\u9700\u8981\u91cd\u542f\u670d\u52a1\u4ee5\u751f\u6548\u3002\n\u662f\u5426\u7acb\u5373\u91cd\u542f\uff1f",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r == QMessageBox.Yes:
                self._stop_server()
                QTimer.singleShot(800, self._start_server)
        self._refresh_display()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ASR-Recognizer")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
