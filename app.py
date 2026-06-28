# -*- coding: utf-8 -*-
import sys
import threading
from datetime import datetime

from core import load_config

import importlib.util

SERVER_THREAD = None

def check_deps():
    missing = []
    for mod in ["torch", "torchaudio", "transformers", "PySide6"]:
        if importlib.util.find_spec(mod) is None:
            missing.append(mod)
    return missing

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QColor, QTextCharFormat, QIcon, QPixmap, QPainter, QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QFrame, QSplitter,
    QGroupBox, QMessageBox, QSystemTrayIcon, QMenu,
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
    padding: 16px 12px 12px 12px;
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
    padding: 10px 18px;
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
                                    log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] 端口 {port} 尚未释放，等待中...\n")
                                    for _ in range(10):
                                        import time as _t
                                        _t.sleep(0.5)
                                        r2 = _sp.run(['netstat', '-ano'], capture_output=True, text=True)
                                        if not any(f':{port}' in l and 'LISTENING' in l for l in r2.stdout.split('\n')):
                                            break
                                else:
                                    # 验证目标进程是否为 python 进程，避免误杀无关程序
                                    try:
                                        proc_check = _sp.run(
                                            ['wmic', 'process', 'where', f'ProcessId={pid}', 'get', 'CommandLine'],
                                            capture_output=True, text=True, timeout=3)
                                        cmd_line = proc_check.stdout.lower() if proc_check.stdout else ''
                                        is_python = any(kw in cmd_line for kw in ['python', 'pythonw', 'conda'])
                                    except Exception:
                                        is_python = False

                                    if is_python:
                                        _sp.run(['taskkill', '/F', '/PID', pid],
                                                capture_output=True)
                                        log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] 已释放端口 {port} (旧进程 PID={pid})\n")
                                    else:
                                        log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] [WARN] 端口 {port} 被非 Python 进程占用 (PID={pid})，请手动释放\n")
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
        if hasattr(_global_server, '_shutdown_event'):
            _global_server._shutdown_event.set()
    log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] \u6b63\u5728\u505c\u6b62\u670d\u52a1...\n")
    # 等待服务端线程真正退出（最多5秒）
    if SERVER_THREAD is not None and SERVER_THREAD.is_alive():
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
        self.setMinimumSize(680, 480)
        self.resize(760, 580)
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

        left = QWidget()
        left.setMaximumWidth(240)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)

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
        ml = QHBoxLayout()
        self._mlbl = QLabel()
        self._mlbl.setStyleSheet(f"color:{LIGHT['text_dim']};font-size:11px")
        ml.addWidget(self._mlbl)
        ml.addStretch()
        self._dlbl = QLabel()
        self._dlbl.setStyleSheet(f"color:{LIGHT['text_dim']};font-size:11px")
        ml.addWidget(self._dlbl)
        sl.addLayout(ml)
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

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        rl.addWidget(QLabel("\u63a7\u5236\u53f0\u65e5\u5fd7"))
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.document().setMaximumBlockCount(6000)
        rl.addWidget(self._log)
        self._info = QLabel("Ctrl+Enter \u542f\u52a8 | Ctrl+Shift+Enter \u505c\u6b62 | Ctrl+, \u8bbe\u7f6e | Ctrl+Q \u9000\u51fa")
        self._info.setStyleSheet(f"color:{LIGHT['text_dim']};font-size:11px")
        rl.addWidget(self._info)

        sp.addWidget(left)
        sp.addWidget(right)
        sp.setStretchFactor(0, 0)
        sp.setStretchFactor(1, 1)
        sp.setSizes([220, 520])

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
            _m = cfg.get('current_model', 'auto')
            _m_map = {"auto": "auto（自动）", "qwen3-asr-1.7b": "Qwen3-ASR 1.7B-hf",
                      "qwen3-asr-0.6b": "Qwen3-ASR 0.6B-hf"}
            self._mlbl.setText(f"\u6a21\u578b: {_m_map.get(_m, _m)}")
            self._dlbl.setText(f"\u8bbe\u5907: {cfg.get('device','auto')}")
        except Exception as e:
            print(f"[UI] _refresh_display error: {e}", flush=True)

    def _start_server(self):
        # 防止按钮和菜单快捷键重复触发：运行中或启动过程中都直接返回
        if self._running or getattr(self, '_starting', False):
            return
        self._starting = True
        self._update_ui_state()

        cfg = load_config()
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self._emit_log(f"\n{'=' * 50}\n")
        self._emit_log(f"  \u542f\u52a8\u670d\u52a1 {ts}\n")
        self._emit_log(f"{'=' * 50}\n")
        ready_event, error_holder = start_server_backend(cfg, self._emit_log)
        if ready_event is None:
            self._emit_log("[ERROR] \u670d\u52a1\u542f\u52a8\u5931\u8d25\n")
            self._starting = False
            self._update_ui_state()
            return

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
            self._starting = False
            self._running = True
            self._update_ui_state()
            self._emit_log("[OK] \u670d\u52a1\u5df2\u5c31\u7eea\n")
        elif self._error_holder[0] is not None:
            self._wait_timer.stop()
            self._starting = False
            self._running = False
            self._emit_log(f"[ERROR] \u670d\u52a1\u542f\u52a8\u5931\u8d25: {self._error_holder[0]}\n")
            self._update_ui_state()
        elif __import__("time").time() - self._wait_start_time > 120:
            self._wait_timer.stop()
            self._starting = False
            self._running = False
            self._emit_log("[ERROR] \u6a21\u578b\u52a0\u8f7d\u8d85\u65f6 (120s)\n")
            self._update_ui_state()

    def _stop_server(self):
        if not self._running:
            return
        stop_server_backend(self._emit_log)
        self._running = False
        self._update_ui_state()


    def _update_ui_state(self):
        if self._running:
            self._dot.setStyleSheet(f"background:{LIGHT['green']}")
            self._slbl.setText("\u8fd0\u884c\u4e2d")
            self._slbl.setStyleSheet(f"font-size:15px;font-weight:bold;color:{LIGHT['green']}")
            self._btn_start.setEnabled(False)
            self._btn_stop.setEnabled(True)
        elif getattr(self, '_starting', False):
            self._dot.setStyleSheet(f"background:{LIGHT['yellow']}")
            self._slbl.setText("\u542f\u52a8\u4e2d...")
            self._slbl.setStyleSheet(f"font-size:15px;font-weight:bold;color:{LIGHT['yellow']}")
            self._btn_start.setEnabled(False)
            self._btn_stop.setEnabled(False)
        else:
            self._dot.setStyleSheet(f"background:{LIGHT['text_dim']}")
            self._slbl.setText("\u672a\u542f\u52a8")
            self._slbl.setStyleSheet(f"font-size:15px;font-weight:bold;color:{LIGHT['text_dim']}")
            self._btn_start.setEnabled(True)
            self._btn_stop.setEnabled(False)

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
