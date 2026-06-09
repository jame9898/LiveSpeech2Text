# -*- coding: utf-8 -*-
from core import load_config, save_config, get_default_config

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QGroupBox, QLabel, QComboBox, QCheckBox, QPushButton,
    QSlider, QSpinBox, QDoubleSpinBox, QMessageBox,
)

MODEL_OPTIONS = [
    "auto",
    "qwen3-asr-1.7b", "qwen3-asr-0.6b",
]
MODEL_LABELS = [
    "auto（自动选择最优）",
    "Qwen3-ASR 1.7B（推荐·高精度）",
    "Qwen3-ASR 0.6B（轻量·省显存）",
]
DEVICE_OPTIONS = ["auto", "cuda", "cpu"]
DEVICE_LABELS = ["auto（自动检测）", "cuda（NVIDIA GPU）", "cpu（仅CPU）"]


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumSize(500, 420)
        self.resize(500, 420)
        self.setModal(True)

        self._config = load_config()
        self._settings = self._config.get("model_settings", {})
        self._needs_restart = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 8)
        root.setSpacing(0)

        tabs = QTabWidget()
        root.addWidget(tabs)

        self._build_model_tab(tabs)
        self._build_device_tab(tabs)
        self._build_audio_tab(tabs)
        self._build_advanced_tab(tabs)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_reset = QPushButton("恢复默认")
        btn_reset.clicked.connect(self._reset_defaults)
        btn_layout.addWidget(btn_reset)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        btn_save = QPushButton("保存并重启服务")
        btn_save.clicked.connect(self._save_and_restart)
        btn_save.setStyleSheet("font-weight:bold")
        btn_layout.addWidget(btn_save)
        root.addLayout(btn_layout)

    def _build_model_tab(self, tabs):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(8)

        g1 = QGroupBox("ASR 语音识别模型")
        gl1 = QVBoxLayout(g1)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("ASR 模型:"))
        self._cmb_model = QComboBox()
        self._cmb_model.addItems(MODEL_LABELS)
        cur = self._config.get("current_model", "auto")
        idx = MODEL_OPTIONS.index(cur) if cur in MODEL_OPTIONS else 0
        self._cmb_model.setCurrentIndex(idx)
        r1.addWidget(self._cmb_model)
        gl1.addLayout(r1)
        layout.addWidget(g1)
        layout.addStretch()
        tabs.addTab(w, "模型")

    def _build_device_tab(self, tabs):
        w = QWidget()
        layout = QVBoxLayout(w)
        g = QGroupBox("计算设备")
        gl = QVBoxLayout(g)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("计算设备:"))
        self._cmb_device = QComboBox()
        self._cmb_device.addItems(DEVICE_LABELS)
        dev = self._config.get("device", "auto")
        self._cmb_device.setCurrentIndex(DEVICE_OPTIONS.index(dev) if dev in DEVICE_OPTIONS else 0)
        r1.addWidget(self._cmb_device)
        gl.addLayout(r1)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("线程数:"))
        self._spn_threads = QSpinBox()
        self._spn_threads.setRange(1, 16)
        self._spn_threads.setValue(self._settings.get("threads", 8))
        r2.addWidget(self._spn_threads)
        r2.addStretch()
        gl.addLayout(r2)
        layout.addWidget(g)
        layout.addStretch()
        tabs.addTab(w, "设备")

    def _build_audio_tab(self, tabs):
        w = QWidget()
        layout = QVBoxLayout(w)
        g = QGroupBox("VAD 参数")
        gl = QVBoxLayout(g)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("静音断句阈值（秒）:"))
        self._vad_slider = QSlider(Qt.Horizontal)
        self._vad_slider.setRange(30, 150)
        val = int(self._settings.get("vad_threshold", 0.8) * 100)
        self._vad_slider.setValue(val)
        r1.addWidget(self._vad_slider)
        self._vad_lbl = QLabel(f"{val / 100:.2f} 秒")
        self._vad_lbl.setMinimumWidth(50)
        r1.addWidget(self._vad_lbl)
        self._vad_slider.valueChanged.connect(
            lambda v: self._vad_lbl.setText(f"{v / 100:.2f} 秒"))
        gl.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("缓冲区上限:"))
        self._spn_buffer = QSpinBox()
        self._spn_buffer.setRange(10, 60)
        self._spn_buffer.setValue(self._settings.get("max_buffer_seconds", 30))
        r2.addWidget(self._spn_buffer)
        r2.addWidget(QLabel("秒"))
        r2.addStretch()
        gl.addLayout(r2)

        r_force = QHBoxLayout()
        r_force.addWidget(QLabel("强制切分时长:"))
        self._spn_force_cut = QDoubleSpinBox()
        self._spn_force_cut.setRange(1.5, 15.0)
        self._spn_force_cut.setSingleStep(0.5)
        self._spn_force_cut.setDecimals(1)
        self._spn_force_cut.setValue(self._settings.get("force_cut_sec", 6.0))
        self._spn_force_cut.setSuffix(" 秒")
        r_force.addWidget(self._spn_force_cut)
        r_force.addStretch()
        gl.addLayout(r_force)

        r3 = QHBoxLayout()
        r3.addWidget(QLabel("最小语音段:"))
        self._min_speech_slider = QSlider(Qt.Horizontal)
        self._min_speech_slider.setRange(5, 30)
        val_ms = int(self._settings.get("min_speech_duration", 0.12) * 100)
        self._min_speech_slider.setValue(val_ms)
        r3.addWidget(self._min_speech_slider)
        self._min_speech_lbl = QLabel(f"0.{val_ms:02d} 秒")
        self._min_speech_lbl.setMinimumWidth(50)
        r3.addWidget(self._min_speech_lbl)
        self._min_speech_slider.valueChanged.connect(
            lambda v: self._min_speech_lbl.setText(f"0.{v:02d} 秒"))
        gl.addLayout(r3)

        self._chk_force_cut = QCheckBox("VAD 强制切分（关闭后ASR模型自行判句）")
        self._chk_force_cut.setChecked(self._settings.get("vad_force_cut", True))
        gl.addWidget(self._chk_force_cut)

        layout.addWidget(g)
        layout.addStretch()
        tabs.addTab(w, "音频/VAD")

    def _build_advanced_tab(self, tabs):
        w = QWidget()
        layout = QVBoxLayout(w)

        g2 = QGroupBox("服务器端口")
        gl2 = QVBoxLayout(g2)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("WebSocket 端口:"))
        self._spn_ws = QSpinBox()
        self._spn_ws.setRange(1024, 65535)
        self._spn_ws.setValue(self._settings.get("ws_port", 8765))
        r1.addWidget(self._spn_ws)
        r1.addStretch()
        gl2.addLayout(r1)
        layout.addWidget(g2)

        g3 = QGroupBox("模型输出")
        gl3 = QVBoxLayout(g3)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("最大输出Token:"))
        self._spn_max_tokens = QSpinBox()
        self._spn_max_tokens.setRange(32, 256)
        self._spn_max_tokens.setSingleStep(32)
        self._spn_max_tokens.setValue(self._settings.get("max_new_tokens", 128))
        self._spn_max_tokens.setToolTip("ASR模型单次最大输出token数，值越大可识别越长句子")
        r2.addWidget(self._spn_max_tokens)
        r2.addStretch()
        gl3.addLayout(r2)
        layout.addWidget(g3)

        layout.addStretch()
        tabs.addTab(w, "高级")

    def _gather_config(self):
        return {
            "current_model": MODEL_OPTIONS[self._cmb_model.currentIndex()],
            "device": DEVICE_OPTIONS[self._cmb_device.currentIndex()],
            "model_settings": {
                "vad_force_cut": self._chk_force_cut.isChecked(),
                "vad_threshold": round(self._vad_slider.value() / 100, 2),
                "force_cut_sec": round(self._spn_force_cut.value(), 1),
                "max_buffer_seconds": self._spn_buffer.value(),
                "min_speech_duration": round(self._min_speech_slider.value() / 100, 2),
                "threads": self._spn_threads.value(),
                "ws_port": self._spn_ws.value(),
                "max_new_tokens": self._spn_max_tokens.value(),
            }
        }

    def _save_and_restart(self):
        cfg = self._gather_config()
        save_config(cfg)
        self._needs_restart = True
        QMessageBox.information(self, "已保存",
            "配置已保存。\n\n如修改了模型、设备或端口，请重启服务以生效。")
        self.accept()

    def _reset_defaults(self):
        r = QMessageBox.question(self, "恢复默认",
            "确定要恢复所有设置为默认值吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r == QMessageBox.Yes:
            save_config({
                "current_model": "auto",
                "device": "auto",
                "model_settings": dict(get_default_config()["model_settings"]),
            })
            self._needs_restart = True
            self.accept()

    @property
    def needs_restart(self):
        return self._needs_restart

