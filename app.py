# -*- coding: utf-8 -*-
import sys
import os
import threading
from datetime import datetime
from pathlib import Path

# ===== 崩溃诊断：启用 faulthandler 捕获 segfault =====
# 注意：不能用 dump_traceback_later，它在 Windows 上会创建后台线程
# 周期性获取 GIL，会干扰 PyTorch C++ 张量加载导致 access violation
_CRASH_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crash_trace.log")
try:
    import faulthandler
    _crash_fp = open(_CRASH_LOG_PATH, "a", encoding="utf-8")
    _crash_fp.write(f"\n{'=' * 60}\n[{datetime.now()}] 程序启动\n{'=' * 60}\n")
    _crash_fp.flush()
    faulthandler.enable(_crash_fp)
except Exception:
    _crash_fp = None

# 全局异常钩子：捕获未处理的 Python 异常
def _global_excepthook(exc_type, exc_value, exc_tb):
    import traceback
    try:
        with open(_CRASH_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now()}] 未捕获异常:\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = _global_excepthook
# ===== 崩溃诊断结束 =====

# ===== 预导入重模块：在程序启动时后台导入 torch/transformers/qwen_asr =====
# 这样点击「加载模型」时 step1→step2 几乎瞬间完成（省 3-4 秒）
import threading as _threading_mod

def _preload_heavy_modules():
    try:
        import torch  # noqa
        import transformers  # noqa
        import qwen_asr  # noqa
        print("[PRELOAD] torch/transformers/qwen_asr 预导入完成", flush=True)
    except Exception as e:
        print(f"[PRELOAD] 预导入失败（不影响功能）: {e}", flush=True)

_preload_thread = _threading_mod.Thread(target=_preload_heavy_modules, daemon=True)
_preload_thread.start()
# ===== 预导入结束 =====

try:
    from core import load_config
except ImportError as _e:
    print(f"[ERROR] 缺少核心依赖（{getattr(_e, 'name', _e)}）。请双击「start.bat」安装依赖后重试。", flush=True)
    sys.exit(1)

from common_utils import StdoutRedirect

import importlib.util

SERVER_THREAD = None

def check_deps():
    missing = []
    for mod in ["torch", "torchaudio", "qwen_asr", "PySide6"]:
        if importlib.util.find_spec(mod) is None:
            missing.append(mod)
    return missing

try:
    from PySide6.QtCore import Qt, QTimer, Signal, Slot
    from PySide6.QtGui import QColor, QTextCharFormat, QIcon, QPixmap, QPainter, QFont, QTextCursor
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
        QPushButton, QLabel, QTextEdit, QFrame, QSplitter,
        QGroupBox, QMessageBox, QSystemTrayIcon, QMenu,
        QComboBox, QStackedWidget, QButtonGroup,
        QCheckBox, QFileDialog, QProgressBar, QLineEdit,
    )
except ImportError as _e:
    print(f"[ERROR] 缺少 GUI 依赖（{getattr(_e, 'name', _e)}）。请双击「start.bat」安装依赖后重试。", flush=True)
    sys.exit(1)
from realtime_panel import (
    SubtitleListView,
    MicCaptureThread, LoopbackCaptureThread, RealtimeWSClient, format_wall_time,
)
from perf_utils import PerfSampler, gpu_info

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
/* 模式切换卡片按钮：2x2 网格，选中态高亮 */
QPushButton#modeBtn {{
    border: 1px solid {border};
    border-radius: 8px;
    padding: 10px 4px;
    background-color: {surface};
    color: {text_dim};
    font-size: 13px;
    font-weight: 500;
}}
QPushButton#modeBtn:hover {{
    border-color: {accent};
    color: {accent};
    background-color: #fff;
}}
QPushButton#modeBtn:checked {{
    background-color: {accent};
    border-color: {accent};
    color: #fff;
    font-weight: 600;
}}
QPushButton#modeBtn:checked:hover {{
    color: #fff;
}}
QPushButton#modeBtn:disabled {{
    color: {text_dim};
    background-color: {surface};
    border-color: {border};
}}
QPushButton#modeBtn:checked:disabled {{
    background-color: {green};
    border-color: {green};
    color: #fff;
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
/* 本地模式开始/停止按钮：复用主按钮配色，padding 保证文字完整显示 */
QPushButton#startBtn {{
    background-color: {green};
    border-color: {green};
    color: #fff;
    font-weight: 600;
    padding: 6px 18px;
    min-width: 80px;
}}
QPushButton#startBtn:hover {{
    background-color: #1f6f32;
}}
QPushButton#startBtn:disabled {{
    background-color: {surface};
    border-color: {border};
    color: {text_dim};
}}
QPushButton#stopBtn {{
    background-color: {red};
    border-color: {red};
    color: #fff;
    font-weight: 600;
    padding: 6px 18px;
    min-width: 60px;
}}
QPushButton#stopBtn:hover {{
    background-color: #b51d28;
}}
QPushButton#stopBtn:disabled {{
    background-color: {surface};
    border-color: {border};
    color: {text_dim};
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

        _so, _se = sys.stdout, sys.stderr
        sys.stdout = StdoutRedirect(log_cb)
        sys.stderr = StdoutRedirect(log_cb)

        _model_ready = threading.Event()
        _model_error = [None]

        def _run():
            nonlocal _model_ready, _model_error
            try:
                st = config.get("model_settings", {})
                port = st.get("ws_port", 8765)

                # 端口冲突检测与释放（必须在启动 WS 服务前完成）
                import subprocess as _sp, platform as _plat, os as _os
                if _plat.system() == 'Windows':
                    my_pid = str(_os.getpid())

                    def _find_listen_pid():
                        """精确匹配监听端口（本地地址列以 :port 结尾，避免误匹配 :87650 等），返回占用 PID 或 None"""
                        r = _sp.run(['netstat', '-ano'], capture_output=True, text=True)
                        for line in r.stdout.split('\n'):
                            if 'LISTENING' not in line:
                                continue
                            parts = line.strip().split()
                            if len(parts) >= 5 and parts[1].endswith(f':{port}'):
                                return parts[-1]
                        return None

                    try:
                        pid = _find_listen_pid()
                        if pid is not None:
                            if pid == my_pid:
                                log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] 端口 {port} 尚未释放，等待中...\n")
                                # 等旧服务退出后再重试，最长等5秒
                                for _ in range(10):
                                    import time as _t
                                    _t.sleep(0.5)
                                    if _find_listen_pid() is None:
                                        break
                            else:
                                # 其他进程占用端口：只提示用户，不强制结束他人进程
                                log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] [WARN] 端口 {port} 被其他进程占用 (PID={pid})，请手动关闭该进程或在设置中更换端口\n")
                    except Exception:
                        pass

                # 模型加载函数（在后台线程执行，由 server._load_model_background 调用）
                # 启动顺序优化：先启动 WebSocket（插件可秒连），再后台加载模型
                def _load_model():
                    nonlocal _model_ready, _model_error
                    try:
                        log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] 正在加载模型...\n")
                        # 加载前清理 GPU 缓存
                        try:
                            import torch
                            if torch.cuda.is_available():
                                torch.cuda.empty_cache()
                        except Exception:
                            pass
                        # 加载前强制释放残留引擎（上次服务异常退出可能留下）
                        try:
                            from server import _global_server as _gs
                            if _gs is not None and getattr(_gs, 'asr_engine', None) is not None:
                                # 检查服务是否已停止，避免与活跃转录并发释放导致崩溃
                                if not getattr(_gs, 'is_running', False):
                                    log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] 检测到残留引擎，先释放...\n")
                                    _release_asr_engine(_gs.asr_engine)
                                    _gs.asr_engine = None
                        except Exception:
                            pass
                        # 本地模式引擎也可能残留（加锁保护，避免与本地处理线程竞态）
                        try:
                            global _LOCAL_ENGINE
                            _local_eng_to_release = None
                            with _LOCAL_ENGINE_LOCK:
                                if _LOCAL_ENGINE is not None:
                                    log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] 检测到本地模式残留引擎，先释放...\n")
                                    _local_eng_to_release = _LOCAL_ENGINE
                                    _LOCAL_ENGINE = None
                            if _local_eng_to_release is not None:
                                _release_asr_engine(_local_eng_to_release)
                        except Exception:
                            pass
                        dev = resolve_device(config)
                        eng = ASREngine(device=dev, config=config)
                        pref = config.get("current_model", "auto")
                        if pref == "auto": pref = None
                        if not eng.load_model(preferred=pref):
                            log_cb("[ERROR] \u6a21\u578b\u52a0\u8f7d\u5931\u8d25\n")
                            _model_error[0] = "\u6a21\u578b\u52a0\u8f7d\u5931\u8d25"
                            return None
                        log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] \u6a21\u578b: {eng.model_name}\n")
                        # 加载说话人模型（与 ASR 模型并行，但同一线程内顺序执行）
                        from server import _load_speaker_pipeline
                        sv_pipeline, _ = _load_speaker_pipeline(config)
                        # 通知主线程：模型已就绪（更新 UI、启动采集）
                        _model_ready.set()
                        return (eng, sv_pipeline)
                    except Exception as e:
                        import traceback
                        _model_error[0] = str(e)
                        log_cb(f"[ERROR] {e}\n{traceback.format_exc()}\n")
                        return None

                log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] WebSocket ws://localhost:{port}\n")
                log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] \u7b49\u5f85\u8fde\u63a5...\n")
                # 启动 WebSocket 服务（model_loader 在后台线程加载模型，加载完成后自动注入）
                run_server(config, 'localhost', port, model_loader=_load_model)
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


# 本地模式专用：只加载模型，不启动 WS 服务
_LOCAL_ENGINE = None
_LOCAL_ENGINE_LOCK = threading.Lock()


def get_local_engine():
    """获取本地模式已加载的 ASR 引擎（未加载返回 None）"""
    with _LOCAL_ENGINE_LOCK:
        return _LOCAL_ENGINE


def start_model_only_backend(config, log_cb):
    """只加载 ASR 模型，不启动 WebSocket 服务（本地模式专用）。
    加载完成后引擎存入全局变量，供 LocalProcessThread 复用。
    返回 (ready_event, error_holder)。
    """
    global _LOCAL_ENGINE
    try:
        from core import ASREngine, resolve_device

        # 重定向 stdout/stderr 到 log_cb，让模型加载的详细日志可见
        _model_ready = threading.Event()
        _model_error = [None]

        def _run():
            nonlocal _model_ready, _model_error
            global _LOCAL_ENGINE  # 必须声明 global，否则下面的赋值只创建局部变量
            # 崩溃诊断日志：即使程序 segfault 也能保留最后一步信息
            import os as _os
            _crash_log = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "crash_load.log")
            def _crash_log_write(msg):
                try:
                    with open(_crash_log, "a", encoding="utf-8") as _f:
                        _f.write(f"[{datetime.now().strftime('%H:%M:%S.%f')}] {msg}\n")
                except Exception:
                    pass
            _crash_log_write("===== 开始加载模型 =====")
            _so, _se = sys.stdout, sys.stderr
            sys.stdout = StdoutRedirect(log_cb)
            sys.stderr = StdoutRedirect(log_cb)
            try:
                log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] 本地模式：正在加载模型...\n")
                # 加载前先释放可能残留的旧引擎（避免显存冲突导致 access violation）
                _crash_log_write("检查残留旧引擎")
                with _LOCAL_ENGINE_LOCK:
                    _old_eng = _LOCAL_ENGINE
                    _LOCAL_ENGINE = None
                if _old_eng is not None:
                    _crash_log_write("发现残留引擎，开始释放")
                    _release_asr_engine(_old_eng)
                    _crash_log_write("残留引擎已释放")
                _crash_log_write("准备清理 GPU 缓存")
                # 加载前清理 GPU 缓存
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                        log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] 已清理 GPU 缓存\n")
                        _crash_log_write("GPU 缓存清理完成")
                except Exception as _e:
                    _crash_log_write(f"GPU 缓存清理异常: {_e}")
                _crash_log_write("准备 resolve_device")
                dev = resolve_device(config)
                _crash_log_write(f"设备: {dev}")
                _crash_log_write("准备创建 ASREngine")
                eng = ASREngine(device=dev, config=config)
                _crash_log_write("ASREngine 创建完成")
                pref = config.get("current_model", "auto")
                if pref == "auto":
                    pref = None
                _crash_log_write(f"准备加载模型, preferred={pref}")
                if not eng.load_model(preferred=pref):
                    _crash_log_write("模型加载失败（load_model 返回 False）")
                    log_cb("[ERROR] 模型加载失败，请查看上方日志的详细错误信息\n")
                    _model_error[0] = "模型加载失败（详见日志）"
                    return
                _crash_log_write(f"模型加载成功: {eng.model_name}")
                log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] 模型就绪: {eng.model_name}\n")
                with _LOCAL_ENGINE_LOCK:
                    _LOCAL_ENGINE = eng
                _model_ready.set()
                _crash_log_write("===== 加载完成 =====")
            except Exception as e:
                import traceback
                _tb = traceback.format_exc()
                _crash_log_write(f"异常: {e}\n{_tb}")
                _model_error[0] = str(e)
                log_cb(f"[ERROR] {e}\n{_tb}\n")
            finally:
                sys.stdout = _so; sys.stderr = _se
                _crash_log_write("===== _run 结束 =====")

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return _model_ready, _model_error
    except Exception as e:
        import traceback
        log_cb(f"[ERROR] {e}\n{traceback.format_exc()}\n")
        return None, [str(e)]


def _release_asr_engine(eng):
    """释放 ASR 引擎，释放 GPU 显存。
    优先调用 ASREngine.release()（线程安全，封装完整），失败时回退到旧逻辑。
    """
    if eng is None:
        return
    # 优先使用 ASREngine.release()（封装了 _model_lock 保护）
    if hasattr(eng, 'release') and callable(eng.release):
        try:
            eng.release()
            return
        except Exception as e:
            print(f"[RELEASE] eng.release() 失败，回退到旧逻辑: {e}", flush=True)
    # 回退逻辑（兼容旧引擎对象）
    import gc
    try:
        if hasattr(eng, 'model') and eng.model is not None:
            import torch
            try:
                eng.model.cpu()
            except Exception:
                pass
            eng.model = None
    except Exception:
        pass
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
    except Exception:
        pass


def stop_server_backend(log_cb):
    """停止 WS 服务后端。

    返回 True 表示服务线程已退出并完成清理；
    返回 False 表示线程未在限时内退出（模型可能仍在加载），
    此时保持 _global_server/SERVER_THREAD 引用、不释放引擎，
    调用方应阻止立即重启，并在线程退出后调用 finalize_server_cleanup 收尾。
    """
    global SERVER_THREAD
    from server import _global_server
    if _global_server is not None:
        _global_server.is_running = False
        # 先触发 shutdown_event 让服务端退出（通过线程安全方法），
        # 再关闭线程池：避免关停窗口内 server 的 run_in_executor 提交抛 RuntimeError
        if hasattr(_global_server, '_safe_shutdown'):
            try:
                _global_server._safe_shutdown()
            except RuntimeError:
                pass
        # 关闭线程池，释放资源
        if hasattr(_global_server, 'executor'):
            _global_server.executor.shutdown(wait=False)
    log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] 正在停止服务...\n")
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
            log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] [WARN] 服务线程未在 5s 内退出（模型可能仍在加载），等待其后台结束\n")
            return False
        log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] 服务已停止\n")
    finalize_server_cleanup(log_cb)
    return True


def _mem_kind():
    """按当前实际设备返回资源文案：GPU 机器 → 'GPU 显存'，CPU 机器 → '内存'。"""
    try:
        from core import resolve_device
        return "GPU 显存" if resolve_device() == "cuda" else "内存"
    except Exception:
        return "GPU 显存"


def finalize_server_cleanup(log_cb):
    """服务线程真正退出后的收尾：释放 ASR 引擎、清空全局引用。"""
    global SERVER_THREAD
    SERVER_THREAD = None
    from server import _global_server as _gs_ref
    _eng_to_release = getattr(_gs_ref, 'asr_engine', None) if _gs_ref is not None else None
    # 释放 ASR 引擎（GPU 显存 / CPU 内存）
    _release_asr_engine(_eng_to_release)
    # 清除 _global_server 引用，避免残留
    if _gs_ref is not None:
        try:
            _gs_ref.asr_engine = None
        except Exception:
            pass
    import server as _server_mod
    _server_mod._global_server = None
    if _eng_to_release is not None:
        log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] 模型已释放，{_mem_kind()}已清理\n")


class MainWindow(QMainWindow):
    log_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("\u5728\u7ebf\u5b9e\u65f6\u8bed\u97f3\u8bc6\u522b\u7cfb\u7edf")
        self.setMinimumSize(820, 620)
        self.resize(960, 780)
        self._running = False
        self._starting = False   # 服务/模型启动中（就绪前拦截重复启动）
        self._stopping = False   # 服务停止中（后端线程未退出前阻止重启）
        self._cleaning_up = False  # 退出清理中（防 processEvents 重入）
        self._abandoned_load = None  # 被放弃的本地加载线程的 (ready_event, error_holder)
        self._pending_unload_after_finish = False  # 处理线程结束后待卸载模型
        self._stop_poll_timer = None   # "停止中"状态轮询定时器（按需创建）
        self._abandoned_timer = None   # 被放弃的本地加载线程的监视定时器（按需创建）
        self._detached_threads = set()  # wait 超时的采集线程引用，finished 后释放
        self._local_model_ready = False  # 本地模式模型加载状态
        self._local_ready_event = None
        self._local_error_holder = None
        self._local_wait_timer = QTimer()
        self._local_wait_timer.setInterval(500)
        self._local_wait_timer.timeout.connect(self._poll_local_model_ready)
        self._tray = None
        self._icon = _make_icon()
        self.setWindowIcon(self._icon)

        self._status_timer = QTimer()
        self._status_timer.setInterval(UI_REFRESH_MS)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start()

        # 性能监测：后台采样器 + 每 1s 刷新面板（无 GPU 时自动降级为 CPU/内存显示）
        self._perf_sampler = PerfSampler(interval=1.0)
        self._perf_sampler.start()
        self._perf_gpu_name = None
        _gi = gpu_info()
        if _gi:
            self._perf_gpu_name = _gi.split("|")[0].strip()
        self._perf_timer = QTimer()
        self._perf_timer.setInterval(1000)
        self._perf_timer.timeout.connect(self._refresh_perf_panel)
        self._perf_timer.start()

        self.log_signal.connect(self._append_log)

        self._build_ui()
        self._apply_style()
        self._setup_tray()
        self._refresh_display()
        self._refresh_audio_devices()

        self._append_log_label("\u6b22\u8fce\u4f7f\u7528\u5728\u7ebf\u5b9e\u65f6\u8bed\u97f3\u8bc6\u522b\u7cfb\u7edf v1.0\n")
        missing = check_deps()
        if missing:
            self._append_log_label(f"[WARN] \u7f3a\u5c11\u4f9d\u8d56: {', '.join(missing)}\n")
            self._append_log_label("  \u8bf7\u53cc\u51fb start.bat \u5b89\u88c5\u4f9d\u8d56\n")
            self._emit_log(f"[WARN] \u7f3a\u5c11\u4f9d\u8d56: {', '.join(missing)}\n")
            self._emit_log("  \u8bf7\u53cc\u51fb start.bat \u5b89\u88c5\u4f9d\u8d56\n")
        self._append_log_label("\u70b9\u51fb \u542f\u52a8\u670d\u52a1 \u5f00\u59cb\u8bc6\u522b\n\n")

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

        # 识别模式选择（2x2 卡片式切换按钮）
        mg = QGroupBox("识别模式")
        ml_box = QGridLayout(mg)
        ml_box.setContentsMargins(8, 12, 8, 8)
        ml_box.setHorizontalSpacing(8)
        ml_box.setVerticalSpacing(8)
        self._rb_audience = QPushButton("观众")
        self._rb_streamer = QPushButton("主播")
        self._rb_meeting = QPushButton("会议")
        self._rb_local = QPushButton("本地")
        for _b, _tip in (
            (self._rb_audience, "识别网页播放的声音（浏览器油猴脚本采集）"),
            (self._rb_streamer, "识别本机麦克风"),
            (self._rb_meeting, "同时拾取麦克风和系统音频（半双工）"),
            (self._rb_local, "批量处理本地视频/音频文件"),
        ):
            _b.setCheckable(True)
            _b.setObjectName("modeBtn")
            _b.setCursor(Qt.PointingHandCursor)
            _b.setToolTip(_tip)
        self._rb_audience.setChecked(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self._rb_audience, 0)
        self._mode_group.addButton(self._rb_streamer, 1)
        self._mode_group.addButton(self._rb_meeting, 2)
        self._mode_group.addButton(self._rb_local, 3)
        ml_box.addWidget(self._rb_audience, 0, 0)
        ml_box.addWidget(self._rb_streamer, 0, 1)
        ml_box.addWidget(self._rb_meeting, 1, 0)
        ml_box.addWidget(self._rb_local, 1, 1)
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

        self._audience_dataset_chk = QCheckBox("后训练数据集收集（存入 BackTrain/audience/）")
        self._audience_dataset_chk.setToolTip("启用后，识别的语音段将存入后训练数据集，供人工修正与模型微调")
        self._audience_dataset_chk.toggled.connect(self._on_dataset_chk_changed)
        pl_a.addWidget(self._audience_dataset_chk)
        pl_a.addStretch()
        self._source_stack.addWidget(page_audience)

        # 页1：主播模式 — 麦克风
        page_streamer = QWidget()
        pl_s = QVBoxLayout(page_streamer)
        pl_s.setContentsMargins(8, 8, 8, 8)
        pl_s.setSpacing(6)
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

        # 工具栏已移除（测试麦克风、打开字幕页、导出按钮已迁移）
        tool_row_s = QHBoxLayout()
        tool_row_s.addStretch()
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

        self._streamer_dataset_chk = QCheckBox("后训练数据集收集（存入 BackTrain/streamer/）")
        self._streamer_dataset_chk.setToolTip("启用后，识别的语音段将存入后训练数据集，供人工修正与模型微调")
        self._streamer_dataset_chk.toggled.connect(self._on_dataset_chk_changed)
        pl_s.addWidget(self._streamer_dataset_chk)
        pl_s.addStretch()
        self._source_stack.addWidget(page_streamer)

        # 页2：会议模式 — 麦克风 + 系统音频
        page_meeting = QWidget()
        pl_m = QVBoxLayout(page_meeting)
        pl_m.setContentsMargins(8, 8, 8, 8)
        pl_m.setSpacing(6)
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

        # 工具栏已移除（测试麦克风、打开字幕页、导出按钮已迁移）
        tool_row_m = QHBoxLayout()
        tool_row_m.addStretch()
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

        self._meeting_dataset_chk = QCheckBox("后训练数据集收集（存入 BackTrain/meeting/）")
        self._meeting_dataset_chk.setToolTip("启用后，识别的语音段将存入后训练数据集，供人工修正与模型微调")
        self._meeting_dataset_chk.toggled.connect(self._on_dataset_chk_changed)
        pl_m.addWidget(self._meeting_dataset_chk)
        pl_m.addStretch()
        self._source_stack.addWidget(page_meeting)

        # 页3：本地模式 — 文件夹批量处理
        page_local = QWidget()
        pl_l = QVBoxLayout(page_local)
        pl_l.setContentsMargins(8, 8, 8, 8)
        pl_l.setSpacing(6)

        # 输入路径选择（支持单文件或文件夹）
        in_row = QHBoxLayout()
        in_row.addWidget(QLabel("输入路径:"))
        self._local_input_edit = QLineEdit()
        self._local_input_edit.setPlaceholderText("选择视频/音频文件或包含媒体的文件夹")
        in_row.addWidget(self._local_input_edit, 1)
        btn_browse_file = QPushButton("选文件")
        btn_browse_file.clicked.connect(self._browse_local_input_file)
        in_row.addWidget(btn_browse_file)
        btn_browse_folder = QPushButton("选文件夹")
        btn_browse_folder.clicked.connect(self._browse_local_input)
        in_row.addWidget(btn_browse_folder)
        pl_l.addLayout(in_row)

        # 输出目录选择
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("输出目录:"))
        self._local_output_edit = QLineEdit()
        self._local_output_edit.setPlaceholderText("MD 报告输出目录（默认与输入相同）")
        out_row.addWidget(self._local_output_edit, 1)
        btn_browse_out = QPushButton("浏览")
        btn_browse_out.clicked.connect(self._browse_local_output)
        out_row.addWidget(btn_browse_out)
        pl_l.addLayout(out_row)

        # 后训练数据集收集开关
        self._local_save_dataset = QCheckBox("同时存入后训练数据集（存入 BackTrain/local/）")
        self._local_save_dataset.setToolTip("启用后，处理过程中切出的语音段将存入 BackTrain/local/ 目录，供人工修正与模型微调")
        cfg = load_config()
        ds_enabled = cfg.get("dataset_settings", {}).get("enabled", False)
        self._local_save_dataset.setChecked(ds_enabled)
        pl_l.addWidget(self._local_save_dataset)

        # 开始处理按钮
        btn_row = QHBoxLayout()
        self._btn_local_start = QPushButton("开始处理")
        self._btn_local_start.setObjectName("startBtn")
        self._btn_local_start.clicked.connect(self._start_local_process)
        btn_row.addWidget(self._btn_local_start)
        btn_row.addStretch()
        pl_l.addLayout(btn_row)

        # 进度条：段进度（显示当前段号/总段数/文件名）
        self._local_seg_progress = QProgressBar()
        self._local_seg_progress.setRange(0, 100)
        self._local_seg_progress.setTextVisible(True)
        self._local_seg_progress.setFormat("等待开始")
        self._local_seg_progress.setFixedHeight(18)
        pl_l.addWidget(self._local_seg_progress)
        pl_l.addStretch()
        self._source_stack.addWidget(page_local)

        rl.addWidget(self._source_stack)

        # 模式切换 → 切换输入源页 + 更新提示
        self._mode_group.idClicked.connect(self._on_mode_changed)

        # 字幕展示区（实时模式共用；本地模式隐藏，因处理结果直接输出到文件）
        self._subtitle_container = QFrame()
        sc_layout = QVBoxLayout(self._subtitle_container)
        sc_layout.setContentsMargins(0, 0, 0, 0)
        sub_header = QHBoxLayout()
        sub_header.addWidget(QLabel("\u5b57\u5e55\u5c55\u793a"))
        sub_header.addStretch()
        self._btn_export = QPushButton("导出 MD 文档")
        self._btn_export.setObjectName("toolBtn")
        self._btn_export.setFixedHeight(28)
        self._btn_export.setMinimumWidth(110)
        self._btn_export.clicked.connect(self._export_subtitles)
        sub_header.addWidget(self._btn_export)
        sc_layout.addLayout(sub_header)
        self._subtitle_view = SubtitleListView()
        self._subtitle_view.setMinimumHeight(120)
        sc_layout.addWidget(self._subtitle_view, stretch=1)
        rl.addWidget(self._subtitle_container)

        # 日志区（程序性日志：VAD切分、连接状态、识别段数等）
        rl.addWidget(QLabel("\u63a7\u5236\u53f0\u65e5\u5fd7"))
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.document().setMaximumBlockCount(6000)
        self._log.setMaximumHeight(160)
        rl.addWidget(self._log)

        # ====== 性能监测面板（控制台上方，实时采样 GPU/CPU 负载） ======
        self._perf_box = QGroupBox("\u6027\u80fd\u76d1\u6d4b")
        self._perf_box.setStyleSheet(
            "QGroupBox { font-size: 11px; font-weight: bold; border: 1px solid "
            f"{LIGHT['border']}; border-radius: 6px; margin-top: 6px; padding-top: 4px; }} "
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 8px; }} "
            "QLabel { font-size: 11px; color: " + LIGHT['text_dim'] + "; }"
        )
        pfl = QVBoxLayout(self._perf_box)
        pfl.setContentsMargins(10, 6, 10, 6)
        pfl.setSpacing(4)

        # GPU 行：标签 + 进度条 + 数值
        gpu_row = QHBoxLayout()
        self._gpu_lbl = QLabel("GPU \u5229\u7528\u7387")
        self._gpu_lbl.setFixedWidth(72)
        gpu_row.addWidget(self._gpu_lbl)
        self._gpu_bar = QProgressBar()
        self._gpu_bar.setRange(0, 100)
        self._gpu_bar.setFixedHeight(12)
        self._gpu_bar.setTextVisible(False)
        self._gpu_bar.setStyleSheet(
            "QProgressBar { background: #e1e4e8; border-radius: 5px; }"
            "QProgressBar::chunk { background: #8250df; border-radius: 5px; }"
        )
        gpu_row.addWidget(self._gpu_bar, 1)
        self._gpu_txt = QLabel("-")
        self._gpu_txt.setFixedWidth(150)
        gpu_row.addWidget(self._gpu_txt)
        pfl.addLayout(gpu_row)
        # CPU 环境（无 NVIDIA GPU）时整行隐藏
        self._gpu_row_widgets = (self._gpu_lbl, self._gpu_bar, self._gpu_txt)

        # CPU 行
        cpu_row = QHBoxLayout()
        self._cpu_lbl = QLabel("CPU \u5229\u7528\u7387")
        self._cpu_lbl.setFixedWidth(72)
        cpu_row.addWidget(self._cpu_lbl)
        self._cpu_bar = QProgressBar()
        self._cpu_bar.setRange(0, 100)
        self._cpu_bar.setFixedHeight(12)
        self._cpu_bar.setTextVisible(False)
        self._cpu_bar.setStyleSheet(
            "QProgressBar { background: #e1e4e8; border-radius: 5px; }"
            "QProgressBar::chunk { background: #0969da; border-radius: 5px; }"
        )
        cpu_row.addWidget(self._cpu_bar, 1)
        self._cpu_txt = QLabel("-")
        self._cpu_txt.setFixedWidth(150)
        cpu_row.addWidget(self._cpu_txt)
        pfl.addLayout(cpu_row)

        # 详情行：设备名 / 显存 / 温度
        self._perf_detail = QLabel("\u8bbe\u5907: -")
        self._perf_detail.setWordWrap(True)
        pfl.addWidget(self._perf_detail)
        rl.addWidget(self._perf_box)
        # ====== 性能监测面板结束 ======

        # 实时采集/WS 客户端成员（主播/会议模式使用）
        self._mic_thread = None
        self._loopback_thread = None  # 会议模式系统音频回环采集
        self._ws_client = None
        self._pending_speaker_name = None  # 缓存的说话人名称（服务启动后发送）
        self._speaker_names = {"Speaker0": ""}  # 说话人名称字典 {speaker_id: name}

        # 半双工仲裁状态（会议模式）
        self._half_duplex_sys_level = 0.0   # 系统音频当前电平
        self._half_duplex_sys_active = False  # 系统音频是否在说话（远端活跃）
        self._half_duplex_mic_muted = False   # 麦克风是否被静音
        self._half_duplex_silence_since = 0.0  # 系统音频安静下来的时间戳
        self._HALF_DUPLEX_THRESHOLD = 0.02    # 远端说话电平阈值
        self._HALF_DUPLEX_HOLD_MS = 300       # 远端安静后多久恢复麦克风（ms）

        sp.addWidget(left)
        sp.addWidget(right)
        sp.setStretchFactor(0, 0)
        sp.setStretchFactor(1, 1)
        sp.setSizes([240, 640])

    def _on_mode_changed(self, btn_id):
        """模式切换：切换输入源页"""
        self._source_stack.setCurrentIndex(btn_id)
        # 本地模式隐藏字幕展示区（处理结果直接输出到文件，不需要字幕展示和导出 MD）
        is_local = (btn_id == 3)
        self._subtitle_container.setVisible(not is_local)
        # 统一调用 _update_ui_state 更新按钮状态
        self._update_ui_state()
        # 切换模式时同步后训练状态（各模式复选框独立）
        self._sync_dataset_state()

    def _get_current_dataset_chk(self):
        """获取当前模式对应的后训练复选框"""
        mode = self._get_current_mode()
        if mode == 0:
            return getattr(self, '_audience_dataset_chk', None)
        if mode == 1:
            return getattr(self, '_streamer_dataset_chk', None)
        if mode == 2:
            return getattr(self, '_meeting_dataset_chk', None)
        return None  # 本地模式有自己的复选框，不在此处理

    def _on_dataset_chk_changed(self, checked):
        """后训练复选框状态变化：动态启用/禁用 server 的 dataset_manager"""
        if not self._running:
            return  # 服务未运行时仅记录状态，启动时再同步
        self._sync_dataset_state()

    def _sync_dataset_state(self):
        """根据当前模式复选框状态 + 设置页全局开关，同步 server 的 dataset_manager。

        启用逻辑（OR）：
          - 当前模式 UI 复选框勾选 → 启用（单次生效）
          - 设置页全局启用 → 启用（所有模式默认）
        两者任一为真即启用；仅当两者都为假时才禁用。
        """
        if not self._running:
            return
        try:
            from server import _global_server
            if _global_server is None:
                return
            chk = self._get_current_dataset_chk()
            if chk is None:
                return
            # 设置页全局开关
            cfg = load_config()
            global_enabled = cfg.get("dataset_settings", {}).get("enabled", False)
            should_enable = chk.isChecked() or global_enabled

            mgr = _global_server.dataset_manager
            if should_enable:
                if not mgr.enabled:
                    mgr.enable()
                    self._emit_log("[DATASET] 后训练数据集收集已启用\n")
            else:
                if mgr.enabled:
                    mgr.disable()
                    self._emit_log("[DATASET] 后训练数据集收集已禁用\n")
        except Exception as e:
            print(f"[DATASET] 同步状态失败: {e}", flush=True)

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
        # 先停止所有定时器，避免回调操作已销毁的 UI 导致崩溃
        for timer_attr in ('_status_timer', '_local_wait_timer', '_wait_timer',
                           '_stop_poll_timer', '_abandoned_timer'):
            t = getattr(self, timer_attr, None)
            if t is not None:
                try:
                    t.stop()
                except Exception:
                    pass
        # 启动中/停止中同样需要清理（后台线程可能在加载模型）
        if self._running or self._starting or self._stopping:
            r = QMessageBox.question(self, "\u786e\u8ba4\u9000\u51fa",
                "\u670d\u52a1\u6b63\u5728\u8fd0\u884c\u4e2d\uff0c\u786e\u5b9a\u8981\u9000\u51fa\u5417\uff1f\n\n"
                f"\u70b9\u51fb\u300c\u662f\u300d\u5c06\u5148\u5378\u8f7d\u6a21\u578b\u91ca\u653e{_mem_kind()}\uff0c\u7136\u540e\u5173\u95ed\u7a0b\u5e8f\u3002",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r == QMessageBox.No:
                event.ignore()
                return
            # 卸载模型并释放 GPU 显存
            self._cleanup_before_exit()
        if self._tray is not None:
            self._tray.hide()
        event.accept()

    def _cleanup_before_exit(self):
        """退出程序前的清理：停止采集 + 停止处理 + 卸载模型 + 释放 GPU 显存。

        覆盖三种状态：
        1. 本地模式加载中（_running=True 但模型未就绪）：停止定时器 + 等加载线程退出
        2. 本地模式处理中：停止处理线程 + 卸载模型
        3. 实时模式运行中：停止采集 + 停止 WS 服务 + 释放引擎
        """
        # processEvents 重入防护：清理过程中嵌套事件循环再次触发时直接返回
        if self._cleaning_up:
            return
        self._cleaning_up = True
        try:
            is_local = (self._get_current_mode() == 3)
            if is_local:
                # 停止本地处理线程（如果在跑）
                if hasattr(self, '_local_thread') and self._local_thread and self._local_thread.isRunning():
                    self._stop_local_process()
                # 卸载已加载的模型
                if self._local_model_ready or get_local_engine() is not None:
                    self._unload_local_model(force=True)
                else:
                    # 本地模式加载中（模型还没加载完就退出）
                    # _local_wait_timer 已在 closeEvent 中停止
                    # 加载线程是 daemon，会随进程退出而结束
                    # 加锁保护，避免与加载线程赋值 _LOCAL_ENGINE 竞态导致显存泄漏
                    try:
                        global _LOCAL_ENGINE
                        _eng_to_release = None
                        with _LOCAL_ENGINE_LOCK:
                            if _LOCAL_ENGINE is not None:
                                _eng_to_release = _LOCAL_ENGINE
                                _LOCAL_ENGINE = None
                        if _eng_to_release is not None:
                            _release_asr_engine(_eng_to_release)
                    except Exception:
                        pass
            else:
                # 实时模式：停止采集 + 停止 WS 服务 + 释放引擎
                self._stop_realtime_capture()
                stop_server_backend(self._emit_log)
            self._running = False
        except Exception as e:
            print(f"[EXIT] 清理失败: {e}", flush=True)
        finally:
            self._cleaning_up = False

    @Slot(str)
    def _append_log(self, text):
        # 过滤掉识别文字相关的日志（这些已显示在字幕展示区，不重复在控制台显示）
        # 注意：不能过滤全部 [SPEAKER] 行，否则会吞掉说话人模型加载失败的错误详情
        _FILTERS = (
            "Streaming transcription done",
            "[SEG]",
            "[SPEAKER] score=",
            "[SPEAKER] 声纹成熟度",
            "[SPEAKER] 候选新人",
            "[SPEAKER] 候选样本",
            "[SPEAKER] 新角色确认",
            "[SPEAKER] 创建 Speaker0",
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
        # 启动中/停止中拦截重复启动（_running 要到模型就绪才置 True）
        if self._running or self._starting or self._stopping:
            return
        cfg = load_config()
        is_local = (self._get_current_mode() == 3)

        if is_local:
            # 本地模式：「启动服务」= 加载模型
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self._emit_log(f"\n{'=' * 50}\n")
            self._emit_log(f"  加载模型 {ts}\n")
            self._emit_log(f"{'=' * 50}\n")
            ready_event, error_holder = start_model_only_backend(cfg, self._emit_log)
            if ready_event is None:
                self._emit_log("[ERROR] 模型加载启动失败\n")
                return
            self._running = True
            self._starting = True  # 模型加载中，就绪后由 _poll_local_model_ready 清除
            self._update_ui_state()
            self._local_ready_event = ready_event
            self._local_error_holder = error_holder
            self._wait_start_time = __import__("time").time()
            self._local_wait_timer.start()
            return

        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self._emit_log(f"\n{'=' * 50}\n")
        self._emit_log(f"  \u542f\u52a8\u670d\u52a1 {ts}\n")
        self._emit_log(f"{'=' * 50}\n")
        ready_event, error_holder = start_server_backend(cfg, self._emit_log)
        if ready_event is None:
            self._emit_log("[ERROR] \u670d\u52a1\u542f\u52a8\u5931\u8d25\n")
            return

        # Disable start button immediately to prevent double-click
        self._starting = True  # 启动中状态：就绪/失败/超时后由 _poll_server_ready 清除
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
            self._starting = False  # 启动完成，解除启动中状态
            self._update_ui_state()
            self._emit_log("[OK] \u670d\u52a1\u5df2\u5c31\u7eea\n")
            # 同步后训练数据集状态（由当前模式复选框控制，覆盖配置默认值）
            self._sync_dataset_state()
            # 主播/会议模式：启动麦克风采集 + WS 客户端
            self._start_realtime_capture()
        elif self._error_holder[0] is not None:
            self._wait_timer.stop()
            self._emit_log(f"[ERROR] \u670d\u52a1\u542f\u52a8\u5931\u8d25: {self._error_holder[0]}\n")
            self._running = False
            self._starting = False  # 启动失败，解除启动中状态
            self._update_ui_state()
            # 模型加载失败后 server 线程可能仍在运行（WS 服务可能已监听端口），
            # 必须同样做清理，否则 WS 服务残留、端口被占、永远无法再启动
            self._emit_log("[INFO] 正在清理后台线程...\n")
            if not stop_server_backend(self._emit_log):
                self._begin_stop_polling()
        elif __import__("time").time() - self._wait_start_time > 120:
            self._wait_timer.stop()
            self._emit_log("[ERROR] \u6a21\u578b\u52a0\u8f7d\u8d85\u65f6 (120s)\n")
            self._running = False
            self._starting = False  # 启动超时，解除启动中状态
            self._update_ui_state()
            # 清理后台线程：超时后 server 线程可能仍在加载模型/起服务，
            # 必须主动停止，否则会占用端口导致下次启动冲突
            self._emit_log("[INFO] \u6b63\u5728\u6e05\u7406\u540e\u53f0\u7ebf\u7a0b...\n")
            if not stop_server_backend(self._emit_log):
                self._begin_stop_polling()

    def _poll_local_model_ready(self):
        """轮询本地模式模型加载状态"""
        if self._local_ready_event is not None and self._local_ready_event.is_set():
            self._local_wait_timer.stop()
            self._local_model_ready = True
            self._starting = False  # 模型就绪，解除启动中状态
            self._emit_log("[OK] 本地模型已就绪，可点击「开始处理」\n")
            # 显示模型显存占用
            try:
                import torch
                if torch.cuda.is_available():
                    allocated = torch.cuda.memory_allocated() / 1024 / 1024
                    reserved = torch.cuda.memory_reserved() / 1024 / 1024
                    self._emit_log(f"[INFO] GPU 显存占用: 已分配 {allocated:.0f}MB, 已保留 {reserved:.0f}MB\n")
            except Exception:
                pass
            # 模型就绪，保持「运行中」状态（等待用户点击「停止服务」卸载）
            self._slbl.setText("运行中")
            self._slbl.setStyleSheet(f"font-size:15px;font-weight:bold;color:{LIGHT['green']}")
            self._dot.setStyleSheet(f"background:{LIGHT['green']}")
        elif self._local_error_holder is not None and self._local_error_holder[0] is not None:
            self._local_wait_timer.stop()
            self._emit_log(f"[ERROR] 模型加载失败: {self._local_error_holder[0]}\n")
            self._local_model_ready = False
            self._running = False
            self._starting = False  # 加载失败，解除启动中状态
            self._update_ui_state()
            self._slbl.setText("加载失败")
            self._slbl.setStyleSheet(f"font-size:15px;font-weight:bold;color:{LIGHT['red']}")
            self._dot.setStyleSheet(f"background:{LIGHT['red']}")
        elif __import__("time").time() - self._wait_start_time > 120:
            self._local_wait_timer.stop()
            self._emit_log("[ERROR] 模型加载超时 (120s)\n")
            self._local_model_ready = False
            self._running = False
            self._starting = False  # 加载超时，解除启动中状态
            self._update_ui_state()
            self._slbl.setText("超时")
            self._slbl.setStyleSheet(f"font-size:15px;font-weight:bold;color:{LIGHT['red']}")
            self._dot.setStyleSheet(f"background:{LIGHT['red']}")
            # 超时不清理加载线程会导致模型静默驻留 GPU：
            # 放弃本次加载，由后台监视在线程完成后释放引擎
            self._abandon_local_load()

    def _stop_server(self):
        # 本地模式：「停止服务」= 卸载模型
        is_local = (self._get_current_mode() == 3)
        if is_local:
            # 如果正在处理，先停止处理
            if hasattr(self, '_local_thread') and self._local_thread and self._local_thread.isRunning():
                self._stop_local_process()
                return
            # 模型加载中点停止：停掉等待定时器、重置状态，避免加载完成后
            # _poll_local_model_ready 把 UI 置为"运行中"但 _running=False 的状态机错乱
            if self._starting and not self._local_model_ready:
                self._local_wait_timer.stop()
                # 加载线程无法中途取消：放弃它，完成后由后台监视自动释放引擎
                self._abandon_local_load()
                self._starting = False
                self._running = False
                self._update_ui_state()
                self._emit_log("[INFO] 已停止等待模型加载（加载线程完成后将自动释放模型）\n")
                return
            # 卸载模型
            if self._local_model_ready or get_local_engine() is not None:
                self._unload_local_model()
            self._running = False
            self._update_ui_state()
            return
        if not self._running:
            # 启动中点停止：停止就绪轮询并清理后端线程（WS 服务可能已监听端口）
            if self._starting:
                _wt = getattr(self, '_wait_timer', None)
                if _wt is not None:
                    _wt.stop()
                self._starting = False
                if not stop_server_backend(self._emit_log):
                    self._begin_stop_polling()
                self._update_ui_state()
            return
        # 先停止实时采集
        self._stop_realtime_capture()
        if not stop_server_backend(self._emit_log):
            # 后端线程未在限时内退出（模型可能仍在加载）：
            # 保持"停止中"状态阻止立即重启，线程退出后再收尾
            self._begin_stop_polling()
        self._running = False
        self._update_ui_state()

    def _begin_stop_polling(self):
        """后端服务线程未在限时内退出：进入"停止中"状态，轮询直至线程真正退出后收尾"""
        self._stopping = True
        if self._stop_poll_timer is None:
            self._stop_poll_timer = QTimer(self)
            self._stop_poll_timer.setInterval(500)
            self._stop_poll_timer.timeout.connect(self._poll_stop_done)
        self._stop_poll_timer.start()
        self._update_ui_state()

    def _poll_stop_done(self):
        """轮询后端服务线程是否真正退出，退出后完成收尾清理并解除"停止中"状态"""
        if SERVER_THREAD is not None and SERVER_THREAD.is_alive():
            return
        if self._stop_poll_timer is not None:
            self._stop_poll_timer.stop()
        finalize_server_cleanup(self._emit_log)
        self._stopping = False
        self._emit_log(f"[{datetime.now().strftime('%H:%M:%S')}] 服务已停止\n")
        self._update_ui_state()

    def _abandon_local_load(self):
        """放弃正在进行的本地模型加载：记录 ready_event，
        由 _poll_abandoned_load 在加载线程完成后释放引擎（避免模型静默驻留 GPU）"""
        if self._local_ready_event is None:
            return
        self._abandoned_load = (self._local_ready_event, self._local_error_holder)
        self._local_ready_event = None
        self._local_error_holder = None
        if self._abandoned_timer is None:
            self._abandoned_timer = QTimer(self)
            self._abandoned_timer.setInterval(1000)
            self._abandoned_timer.timeout.connect(self._poll_abandoned_load)
        self._abandoned_timer.start()

    def _poll_abandoned_load(self):
        """监视被放弃的本地加载线程：完成后释放引擎；若期间已开始新加载则不再干预"""
        if self._abandoned_load is None:
            if self._abandoned_timer is not None:
                self._abandoned_timer.stop()
            return
        ready_event, error_holder = self._abandoned_load
        if error_holder is not None and error_holder[0] is not None:
            # 加载失败，线程即将退出且无引擎残留
            self._abandoned_load = None
            self._abandoned_timer.stop()
            return
        if not ready_event.is_set():
            return
        # 加载完成。若用户已发起新的加载，引擎归属新流程，此处不再释放
        self._abandoned_load = None
        self._abandoned_timer.stop()
        if self._starting or self._local_ready_event is not None:
            return
        global _LOCAL_ENGINE
        with _LOCAL_ENGINE_LOCK:
            eng = _LOCAL_ENGINE
            _LOCAL_ENGINE = None
        if eng is not None:
            self._emit_log(f"[{datetime.now().strftime('%H:%M:%S')}] 被放弃的加载线程已完成，正在释放模型...\n")
            _release_asr_engine(eng)
            self._emit_log(f"[{datetime.now().strftime('%H:%M:%S')}] 模型已释放，{_mem_kind()}已清理\n")

    # ============================================================
    # 本地模式（批量处理本地视频/音频文件）
    # ============================================================
    def _browse_local_input_file(self):
        """选择单个视频/音频文件"""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视频/音频文件", "",
            "媒体文件 (*.mp4 *.mkv *.avi *.mov *.flv *.wmv *.webm *.m4v *.ts *.mpg *.mpeg "
            "*.wav *.mp3 *.flac *.m4a *.ogg *.aac *.wma *.opus);;所有文件 (*)"
        )
        if path:
            self._local_input_edit.setText(path)
            # 输出目录默认为文件所在目录
            if not self._local_output_edit.text():
                self._local_output_edit.setText(str(Path(path).parent))

    def _browse_local_input(self):
        """选择文件夹"""
        from PySide6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, "选择包含视频/音频文件的文件夹")
        if folder:
            self._local_input_edit.setText(folder)
            # 输出目录默认与输入相同
            if not self._local_output_edit.text():
                self._local_output_edit.setText(folder)

    def _browse_local_output(self):
        from PySide6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, "选择 MD 报告输出目录")
        if folder:
            self._local_output_edit.setText(folder)

    def _start_local_process(self):
        """启动本地批量处理（支持单文件或文件夹）"""
        try:
            input_path = self._local_input_edit.text().strip()
            if not input_path:
                QMessageBox.warning(self, "提示", "请先选择输入文件或文件夹")
                return
            p = Path(input_path)
            if not p.exists():
                QMessageBox.warning(self, "提示", "输入路径不存在")
                return
            if not (p.is_file() or p.is_dir()):
                QMessageBox.warning(self, "提示", "输入路径无效")
                return

            # 检查模型是否已加载（本地模式需先点「加载模型」）
            engine = get_local_engine()
            if engine is None and not self._local_model_ready:
                QMessageBox.warning(self, "提示",
                    "请先点击「加载模型」按钮加载 ASR 模型，再开始处理文件。")
                return

            # 输出目录：若未指定，默认取输入路径所在目录
            output_dir = self._local_output_edit.text().strip()
            if not output_dir:
                output_dir = str(p.parent) if p.is_file() else input_path
            cfg = load_config()
            ffmpeg_path = cfg.get("local_settings", {}).get("ffmpeg_path", "")

            from local_processor import LocalProcessThread
            self._local_thread = LocalProcessThread(
                folder=input_path,
                output_dir=output_dir,
                config=cfg,
                ffmpeg_path=ffmpeg_path,
                save_dataset=self._local_save_dataset.isChecked(),
                engine=engine,  # 复用已加载的引擎
                parent=self,
            )
            self._local_thread.progress.connect(self._on_local_progress)
            self._local_thread.segment_progress.connect(self._on_local_segment_progress)
            self._local_thread.stage_progress.connect(self._on_local_stage_progress)
            self._local_thread.file_done.connect(self._on_local_file_done)
            self._local_thread.all_done.connect(self._on_local_all_done)
            self._local_thread.error.connect(self._on_local_error)

            self._btn_local_start.setEnabled(False)
            # 锁定模式切换
            for rb in (self._rb_audience, self._rb_streamer, self._rb_meeting, self._rb_local):
                rb.setEnabled(False)
            self._local_input_edit.setEnabled(False)
            self._local_output_edit.setEnabled(False)
            self._local_save_dataset.setEnabled(False)
            self._local_seg_progress.setFormat("准备中...")

            self._local_thread.start()
            # 重置性能采样统计，让面板数值覆盖本次处理
            self._perf_sampler.stop()
            self._perf_sampler = PerfSampler(interval=1.0)
            self._perf_sampler.start()
            self._emit_log(f"[LOCAL] 开始处理: {input_path}\n")
        except Exception as e:
            import traceback
            err = traceback.format_exc()
            self._emit_log(f"[LOCAL] [ERROR] {err}\n")
            QMessageBox.critical(self, "启动失败", f"启动本地处理失败:\n{e}")

    def _unload_local_model(self, force=False):
        """卸载本地模式已加载的模型，释放 GPU 显存/内存。

        参数:
            force: True 时跳过线程检查和弹窗，用于退出/重启场景强制释放。
                   若处理线程仍在运行，会先停止再卸载。
        """
        global _LOCAL_ENGINE
        # 如果正在处理，先停止
        if hasattr(self, '_local_thread') and self._local_thread and self._local_thread.isRunning():
            if force:
                # 退出/重启场景：强制停止线程，不弹窗
                # 保存线程引用，_stop_local_process 会置 None 导致无法后续检查
                _local_thread_ref = self._local_thread
                self._stop_local_process()
                # _stop_local_process 只等 3 秒，force 场景延长等待到 10 秒
                # 避免线程仍在调用 transcribe_array 时释放模型导致崩溃
                _extra_waited = 3.0
                while _local_thread_ref.isRunning() and _extra_waited < 10.0:
                    _local_thread_ref.wait(100)
                    _extra_waited += 0.1
                    from PySide6.QtWidgets import QApplication
                    QApplication.processEvents()
                if _local_thread_ref.isRunning():
                    # 线程仍未退出，不释放模型，避免崩溃
                    self._emit_log(f"[{datetime.now().strftime('%H:%M:%S')}] [WARN] 处理线程未退出，跳过模型释放（可能残留模型资源）\n")
                    # 挂接 finished 信号：线程结束后延迟卸载模型
                    self._pending_unload_after_finish = True
                    return
            else:
                QMessageBox.warning(self, "提示", "请先等待处理完成或停止处理后再卸载模型。")
                return

        try:
            with _LOCAL_ENGINE_LOCK:
                eng = _LOCAL_ENGINE
                _LOCAL_ENGINE = None
                self._local_model_ready = False

            # 用公共函数释放引擎（model.cpu → model=None → gc → cuda 清理）
            _release_asr_engine(eng)

            self._emit_log(f"[{datetime.now().strftime('%H:%M:%S')}] 模型已卸载，{_mem_kind()}已释放\n")
            if not force:
                # 退出/重启场景不需要更新 UI（窗口即将销毁）
                self._update_ui_state()
        except Exception as e:
            self._emit_log(f"[ERROR] 卸载模型失败: {e}\n")

    def _stop_local_process(self):
        """停止本地批量处理"""
        if hasattr(self, '_local_thread') and self._local_thread and self._local_thread.isRunning():
            self._local_thread.stop()
            self._emit_log("[LOCAL] 正在停止...\n")
            # 等待线程退出（最多3秒），避免残留状态
            waited = 0
            while self._local_thread.isRunning() and waited < 3.0:
                self._local_thread.wait(100)
                waited += 0.1
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()
            if self._local_thread.isRunning():
                # 线程未在限时内退出：保留引用并挂接 finished 信号延迟清理，
                # 直接置 None 会导致 QThread 运行中被销毁（abort）
                self._emit_log("[LOCAL] [WARN] 处理线程未在 3s 内退出，等待其后台结束\n")
                self._detach_thread(self._local_thread)
                # 不置 None：保留 self._local_thread 供 _unload_local_model / 退出清理检查
            else:
                self._local_thread = None
        self._btn_local_start.setEnabled(True)
        self._local_seg_progress.setFormat("已停止")
        # 注意：模式按钮（_rb_audience/streamer/meeting/local）的锁定/解锁
        # 由 _update_ui_state 根据 _running 状态统一管理，此处不解锁
        # 避免模型仍在时用户切换模式导致 _LOCAL_ENGINE 永久泄漏
        self._local_input_edit.setEnabled(True)
        self._local_output_edit.setEnabled(True)
        self._local_save_dataset.setEnabled(True)

    def _on_local_progress(self, text):
        """本地处理日志输出"""
        self._emit_log(text)

    def _on_local_segment_progress(self, current, total, filename):
        """段进度更新：显示当前处理到第几段、总段数、所属文件名"""
        pct = int(current * 100 / total) if total > 0 else 0
        self._local_seg_progress.setValue(pct)
        self._local_seg_progress.setFormat(f"段 {current}/{total} ({pct}%) - {filename}")

    def _on_local_stage_progress(self, stage, fraction):
        """阶段进度更新：把 vad/asr/speaker/segments 各阶段映射到 0~100% 总进度。

        阶段权重（本地处理耗时大头是 ASR）：VAD 0-10% / ASR 10-65% / 说话人 65-80% / 逐段 80-100%。
        """
        try:
            fraction = max(0.0, min(1.0, float(fraction)))
        except (TypeError, ValueError):
            return
        ranges = {
            "vad": (0.0, 0.10),
            "asr": (0.10, 0.65),
            "speaker": (0.65, 0.80),
            "segments": (0.80, 1.00),
        }
        lo, hi = ranges.get(stage, (0.0, 1.0))
        pct = int((lo + (hi - lo) * fraction) * 100)
        labels = {
            "vad": "VAD 切分", "asr": "ASR 批量转录",
            "speaker": "说话人识别", "segments": "段落处理",
        }
        label = labels.get(stage, stage)
        self._local_seg_progress.setValue(pct)
        self._local_seg_progress.setFormat(f"{label} {pct}%")

    def _on_local_file_done(self, filename, report_path):
        """单个文件处理完成"""
        self._emit_log(f"[LOCAL] 完成: {filename} → {report_path}\n")

    def _on_local_all_done(self, count):
        """全部处理完成"""
        self._emit_log(f"[LOCAL] 全部完成，共 {count} 个文件\n")
        # 整次任务的完整性能汇总（含 GPU/CPU 均值峰值），默认关闭（设置→本地模式→勾选后输出）
        if load_config().get("local_settings", {}).get("perf_report_enabled", False):
            self._emit_log(self._perf_sampler.summary(label="LOCAL-TASK") + "\n")
            try:
                from perf_utils import version_info
                _ver = version_info()
                if _ver:
                    for _vline in _ver.splitlines():
                        self._emit_log(f"[LOCAL-TASK] {_vline}\n")
            except Exception:
                pass
        self._local_seg_progress.setValue(100)
        self._local_seg_progress.setFormat(f"完成 ({count} 个文件)")
        self._reset_local_ui_state()
        if count > 0:
            QMessageBox.information(self, "本地处理完成", f"共处理 {count} 个文件。\nMD 报告已保存到输出目录。")

    def _on_local_error(self, err_msg):
        """本地处理错误"""
        self._emit_log(f"[LOCAL] [ERROR] {err_msg}\n")
        self._local_seg_progress.setFormat("处理失败")
        self._reset_local_ui_state()
        QMessageBox.critical(self, "本地处理错误", err_msg)

    def _reset_local_ui_state(self):
        """恢复本地模式 UI 状态"""
        self._btn_local_start.setEnabled(True)
        for rb in (self._rb_audience, self._rb_streamer, self._rb_meeting, self._rb_local):
            rb.setEnabled(True)
        self._local_input_edit.setEnabled(True)
        self._local_output_edit.setEnabled(True)
        self._local_save_dataset.setEnabled(True)
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
        """服务就绪后，主播/会议模式启动麦克风采集 + WS客户端。
        观众模式只启动 WS 客户端（接收字幕显示），不采集麦克风。"""
        mode = self._get_current_mode()

        # 启动 WS 客户端（接收识别结果），所有模式都需要
        # 端口从配置读取，与服务端监听端口一致
        _cfg = load_config()
        _ws_port = _cfg.get("model_settings", {}).get("ws_port", 8765)
        mode_str = "audience" if mode == 0 else ("streamer" if mode == 1 else "meeting")
        self._ws_client = RealtimeWSClient(f"ws://localhost:{_ws_port}", mode=mode_str)
        self._ws_client.partial_received.connect(self._on_partial)
        self._ws_client.transcription_received.connect(self._on_transcription)
        self._ws_client.connected.connect(self._on_ws_connected)
        self._ws_client.error_occurred.connect(
            lambda e: self._emit_log(f"[ERROR] WS: {e}\n")
        )
        self._ws_client.start()

        # 观众模式：不启动本地麦克风采集，靠浏览器油猴脚本
        if mode == 0:
            self._emit_log("[INFO] 观众模式：等待浏览器端连接\n")
            return

        mic_idx = self._get_selected_mic_index()
        if mic_idx is None:
            self._emit_log("[WARN] 未选择麦克风设备，无法启动本地采集\n")
            return

        # 启动麦克风采集
        self._mic_thread = MicCaptureThread(device_index=mic_idx)
        self._mic_thread.audio_chunk.connect(self._on_mic_chunk)
        self._mic_thread.level_update.connect(self._on_mic_level)
        self._mic_thread.error_occurred.connect(
            lambda e: self._emit_log(f"[ERROR] 麦克风: {e}\n")
        )
        self._mic_thread.start()

        # 会议模式：启动系统音频回环采集（半双工仲裁）
        if mode == 2:
            sys_dev_name = self._get_selected_sys_audio_name()
            self._loopback_thread = LoopbackCaptureThread(device_name=sys_dev_name)
            self._loopback_thread.audio_chunk.connect(self._on_loopback_chunk)
            self._loopback_thread.level_update.connect(self._on_loopback_level)
            self._loopback_thread.error_occurred.connect(
                lambda e: self._emit_log(f"[ERROR] 系统音频: {e}\n")
            )
            self._loopback_thread.start()
            # 重置半双工状态
            self._half_duplex_sys_level = 0.0
            self._half_duplex_sys_active = False
            self._half_duplex_mic_muted = False
            self._half_duplex_silence_since = 0.0
            self._emit_log("[INFO] 会议模式：半双工已启用（远端说话时麦克风静音）\n")

    def _get_selected_sys_audio_name(self):
        """从会议模式系统音频下拉框获取设备名（用于 loopback）"""
        text = self._meet_sys_combo.currentText()
        if text.startswith("["):
            # 格式 "[idx] 设备名"，提取设备名
            try:
                return text.split("] ", 1)[1]
            except IndexError:
                pass
        return None

    def _detach_thread(self, thread):
        """wait 超时的 QThread：保留引用并挂接 finished 信号延迟释放，
        避免 QThread 运行中被销毁导致 abort"""
        self._detached_threads.add(thread)
        thread.finished.connect(lambda t=thread: self._on_detached_thread_finished(t))
        if thread.isFinished():
            # 连接前线程已结束，finished 不会再触发，直接释放
            self._on_detached_thread_finished(thread)

    def _on_detached_thread_finished(self, thread):
        """被挂接的线程已结束：释放引用；如有待卸载的本地模型则此时卸载"""
        self._detached_threads.discard(thread)
        if thread is self._local_thread:
            self._local_thread = None
            if self._pending_unload_after_finish:
                self._pending_unload_after_finish = False
                self._unload_local_model(force=True)

    def _stop_realtime_capture(self):
        """停止麦克风采集 + WS客户端（wait 超时的线程保留引用，finished 后延迟释放）"""
        if self._mic_thread is not None:
            self._mic_thread.stop()
            if not self._mic_thread.wait(500):
                self._detach_thread(self._mic_thread)
            self._mic_thread = None
        if self._loopback_thread is not None:
            self._loopback_thread.stop()
            if not self._loopback_thread.wait(500):
                self._detach_thread(self._loopback_thread)
            self._loopback_thread = None
        if self._ws_client is not None:
            self._ws_client.send_stop()
            self._ws_client.stop()
            if not self._ws_client.wait(500):
                self._detach_thread(self._ws_client)
            self._ws_client = None
        # 重置音量条
        self._mic_level.setValue(0)
        self._meet_level.setValue(0)

    def _on_mic_chunk(self, audio_data):
        """麦克风采集回调：转发到 WS 客户端（会议模式受半双工控制）"""
        # 会议模式半双工：远端说话时麦克风静音，避免回声重复
        if self._get_current_mode() == 2 and self._half_duplex_mic_muted:
            return
        if self._ws_client is not None and self._ws_client.isRunning():
            self._ws_client.feed_audio(audio_data.tobytes())

    def _on_loopback_chunk(self, audio_data):
        """系统音频回环采集回调：转发到 WS 客户端（远端参会者声音）"""
        # 远端说话时不静音，直接发送
        if self._ws_client is not None and self._ws_client.isRunning():
            self._ws_client.feed_audio(audio_data.tobytes())

    def _on_loopback_level(self, level):
        """系统音频电平更新 + 半双工仲裁"""
        self._half_duplex_sys_level = level
        self._meet_level.setValue(int(level * 100))
        # 只在会议模式做半双工仲裁
        if self._get_current_mode() != 2:
            return
        import time
        now = time.time() * 1000  # ms
        if level >= self._HALF_DUPLEX_THRESHOLD:
            # 远端在说话 → 麦克风静音
            if not self._half_duplex_mic_muted:
                self._half_duplex_mic_muted = True
            self._half_duplex_silence_since = now
        else:
            # 远端安静 → 持续 HOLD_MS 后恢复麦克风
            if self._half_duplex_mic_muted:
                if self._half_duplex_silence_since == 0:
                    self._half_duplex_silence_since = now
                elif now - self._half_duplex_silence_since >= self._HALF_DUPLEX_HOLD_MS:
                    self._half_duplex_mic_muted = False
                    self._half_duplex_silence_since = 0

    def _on_mic_level(self, level):
        """音量电平更新（主播模式用 _mic_level，会议模式由 loopback 控制 _meet_level）"""
        mode = self._get_current_mode()
        if mode == 1:
            self._mic_level.setValue(int(level * 100))

    def _on_ws_connected(self):
        """WS客户端连接成功：发送缓存的说话人名称"""
        mode = self._get_current_mode()
        if mode == 0:
            # 观众模式：只接收字幕，不采集麦克风
            self._emit_log("[OK] WS客户端已连接，接收字幕中\n")
        else:
            self._emit_log("[OK] WS客户端已连接，开始采集麦克风\n")
        # 停止流程可能已把 _ws_client 置 None，使用前判空
        ws = self._ws_client
        if ws is None:
            return
        if self._pending_speaker_name:
            spk_id, name = self._pending_speaker_name
            ws.send_speaker_rename(spk_id, name)
            self._emit_log(f"[OK] 说话人已重命名: {spk_id} -> {name}\n")
            self._pending_speaker_name = None
        # 发送所有已保存的说话人名称
        for spk_id, name in self._speaker_names.items():
            if name:
                ws.send_speaker_rename(spk_id, name)

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
        # 按钮状态同步：启动中/停止中禁止启动，运行中/启动中允许停止
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
            self._rb_local.setEnabled(False)
            # 启动后显示真实 URL
            self._update_url_rows(True)
        else:
            if self._stopping:
                # 后端线程未退出前的"停止中"状态
                self._dot.setStyleSheet(f"background:{LIGHT['yellow']}")
                self._slbl.setText("停止中...")
                self._slbl.setStyleSheet(f"font-size:15px;font-weight:bold;color:{LIGHT['yellow']}")
                self._btn_start.setText("启动服务")
                self._btn_start.setEnabled(False)
                self._btn_stop.setText("停止服务")
                self._btn_stop.setEnabled(False)
                # 解锁模式切换
                self._rb_audience.setEnabled(True)
                self._rb_streamer.setEnabled(True)
                self._rb_meeting.setEnabled(True)
                self._rb_local.setEnabled(True)
                self._update_url_rows(False)
                return
            self._dot.setStyleSheet(f"background:{LIGHT['text_dim']}")
            self._slbl.setText("\u672a\u542f\u52a8")
            self._slbl.setStyleSheet(f"font-size:15px;font-weight:bold;color:{LIGHT['text_dim']}")
            self._btn_start.setText("\u542f\u52a8\u670d\u52a1")
            # 启动中/停止中保持禁用，防止重复启动
            self._btn_start.setEnabled(not (self._starting or self._stopping))
            self._btn_stop.setText("\u505c\u6b62\u670d\u52a1")
            # 启动中允许停止（本地模式加载中可中断等待）
            self._btn_stop.setEnabled(self._starting)
            # 解锁模式切换
            self._rb_audience.setEnabled(True)
            self._rb_streamer.setEnabled(True)
            self._rb_meeting.setEnabled(True)
            self._rb_local.setEnabled(True)
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

    def _refresh_perf_panel(self):
        """每秒刷新性能监测面板：GPU/CPU 利用率进度条 + 显存/温度详情（无 GPU 时隐藏 GPU 行，仅显示 CPU/内存）"""
        try:
            # 首次探测可能撞上启动期 torch 预导入高峰而失败，每秒重试一次直至成功
            if self._perf_gpu_name is None:
                _gi = gpu_info()
                if _gi:
                    self._perf_gpu_name = _gi.split("|")[0].strip()
            has_gpu = self._perf_gpu_name is not None
            for w in self._gpu_row_widgets:
                w.setVisible(has_gpu)
            snap = self._perf_sampler.snapshot()
            gpu, cpu, mem = snap if snap else (None, None, None)
            if gpu and has_gpu:
                util, mem_used, mem_total, temp = gpu
                self._gpu_bar.setValue(int(round(util)))
                self._gpu_txt.setText(f"{util:.0f}% | {mem_used:.1f}/{mem_total:.1f}GB | {temp:.0f}\u00b0C")
                self._gpu_txt.setToolTip(f"\u663e\u5b58: {mem_used:.1f}/{mem_total:.1f}GB")
            else:
                self._gpu_bar.setValue(0)
                self._gpu_txt.setText("-")
            if cpu is not None:
                self._cpu_bar.setValue(int(round(cpu)))
                self._cpu_txt.setText(f"{cpu:.0f}%")
            else:
                self._cpu_bar.setValue(0)
                self._cpu_txt.setText("-")
            detail = f"\u8bbe\u5907: {self._perf_gpu_name or '\u672a\u68c0\u6d4b\u5230 NVIDIA GPU\uff08CPU \u63a8\u7406\uff09'}"
            if mem:
                detail += f" | \u5185\u5b58 {mem[0]:.1f}/{mem[1]:.1f}GB"
            self._perf_detail.setText(detail)
        except Exception as e:
            print(f"[UI] _refresh_perf_panel error: {e}", flush=True)

    def _open_settings(self):
        from settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.exec()
        if dlg.needs_restart:
            # 配置已更改，需要重启程序（不是重启服务）
            r = QMessageBox.question(self, "\u91cd\u542f\u7a0b\u5e8f",
                "\u914d\u7f6e\u5df2\u66f4\u6539\uff0c\u9700\u8981\u91cd\u542f\u7a0b\u5e8f\u4ee5\u751f\u6548\u3002\n\n"
                f"\u70b9\u51fb\u300c\u662f\u300d\u5c06\uff1a\u5148\u5378\u8f7d\u6a21\u578b\u91ca\u653e{_mem_kind()}\uff0c\u7136\u540e\u5173\u95ed\u7a0b\u5e8f\u5e76\u91cd\u65b0\u542f\u52a8\u3002\n"
                "\u70b9\u51fb\u300c\u5426\u300d\u5c06\uff1a\u4fdd\u7559\u5f53\u524d\u8fd0\u884c\u72b6\u6001\uff0c\u4e0b\u6b21\u624b\u52a8\u542f\u52a8\u65f6\u751f\u6548\u3002",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r == QMessageBox.Yes:
                self._restart_program()
        self._refresh_display()

    def _restart_program(self):
        """重启程序：先卸载模型释放 GPU 显存/内存，再关闭程序并重新启动。"""
        import os
        import sys
        from PySide6.QtCore import QProcess

        # 1. 如果服务正在运行，先停止服务（会卸载模型释放资源）
        if self._running:
            self._emit_log("[RESTART] 正在停止服务并卸载模型...\n")
            # 本地模式
            is_local = (self._get_current_mode() == 3)
            if is_local:
                # 停止处理（如果正在处理）
                if hasattr(self, '_local_thread') and self._local_thread and self._local_thread.isRunning():
                    self._stop_local_process()
                # 卸载模型（force=True：重启场景强制释放，不弹窗）
                if self._local_model_ready or get_local_engine() is not None:
                    self._unload_local_model(force=True)
                self._running = False
            else:
                # 实时模式：停止采集 + 停止 WS 服务 + 释放引擎
                self._stop_realtime_capture()
                stop_server_backend(self._emit_log)
                self._running = False

        # 2. 准备重启命令
        python = sys.executable
        script = os.path.abspath(__file__)
        cwd = os.path.dirname(script)

        # 3. 延迟 1 秒后启动新进程（确保模型资源释放完成）
        def _do_restart():
            try:
                QProcess.startDetached(python, [script], cwd)
            except Exception as e:
                print(f"[RESTART] 启动新进程失败: {e}", flush=True)
            # 关闭当前程序
            QApplication.quit()

        QTimer.singleShot(1000, _do_restart)


def main():
    try:
        with open(_CRASH_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now()}] 进入 main()\n")
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setApplicationName("ASR-Recognizer")
    w = MainWindow()
    w.show()
    try:
        with open(_CRASH_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now()}] 进入事件循环\n")
    except Exception:
        pass
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
