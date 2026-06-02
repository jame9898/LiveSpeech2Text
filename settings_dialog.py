# -*- coding: utf-8 -*-
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QGroupBox, QLabel, QComboBox, QCheckBox, QPushButton,
    QSlider, QSpinBox, QDoubleSpinBox, QMessageBox,
)

DICT_DIR = Path(__file__).parent / "dict"
CONFIG_FILE = DICT_DIR / "asr_config.json"

DEFAULT_CONFIG = {
    "current_model": "auto",
    "device": "auto",
    "model_settings": {
        "vad_enabled": True,
        "vad_model": "fsmn-vad",
        "punc_enabled": True,
        "speaker_enabled": True,
        "lyrics_enabled": True,
        "keyword_expand_enabled": True,
        "adaptive_vad": True,
        "music_detect": True,
        "vad_force_cut": True,
        "vad_threshold": 0.85,
        "force_cut_sec": 3.8,
        "max_buffer_seconds": 30,
        "min_speech_duration": 0.08,
        "threads": 8,
        "ws_port": 8765,
        "auto_save_report": False,
        "transcription_mode": "streaming",
    }
}

MODEL_OPTIONS = [
    "auto",
    "qwen3-asr-1.7b", "qwen3-asr-0.6b",
    "sensevoice",
    "paraformer",
    "whisper-tiny", "whisper-base", "whisper-small", "whisper-medium", "whisper-large",
]
MODEL_LABELS = [
    "auto（自动选择最优）",
    "Qwen3-ASR 1.7B（推荐·高精度）",
    "Qwen3-ASR 0.6B（轻量·省显存）",
    "SenseVoice（阿里达摩院·多语言）",
    "Paraformer（阿里达摩院·中文专项）",
    "Whisper tiny（OpenAI·最小）",
    "Whisper base（OpenAI·基础）",
    "Whisper small（OpenAI·小）",
    "Whisper medium（OpenAI·中）",
    "Whisper large（OpenAI·大）",
]
DEVICE_OPTIONS = ["auto", "cuda", "cpu"]
DEVICE_LABELS = ["auto（自动检测）", "cuda（NVIDIA GPU）", "cpu（仅CPU）"]
VAD_MODELS = ["FSMN-VAD", "Silero VAD"]
VAD_MODEL_KEYS = ["fsmn-vad", "silero-vad"]


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "current_model": "auto",
        "device": "auto",
        "model_settings": dict(DEFAULT_CONFIG["model_settings"]),
    }


def save_config(config):
    DICT_DIR.mkdir(exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


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

        g2 = QGroupBox("辅助模型")
        gl2 = QVBoxLayout(g2)
        self._chk_vad = QCheckBox("启用 VAD 语音断句")
        self._chk_vad.setChecked(self._settings.get("vad_enabled", True))
        gl2.addWidget(self._chk_vad)
        r3 = QHBoxLayout()
        r3.addWidget(QLabel("VAD 模型:"))
        self._cmb_vad = QComboBox()
        self._cmb_vad.addItems(VAD_MODELS)
        vm = self._settings.get("vad_model", "fsmn-vad")
        self._cmb_vad.setCurrentIndex(0 if vm == "fsmn-vad" else 1)
        r3.addWidget(self._cmb_vad)
        r3.addStretch()
        gl2.addLayout(r3)
        self._chk_punc = QCheckBox("启用标点模型 CT-Transformer")
        self._chk_punc.setChecked(self._settings.get("punc_enabled", True))
        gl2.addWidget(self._chk_punc)
        self._chk_speaker = QCheckBox("启用声纹识别 CAM++")
        self._chk_speaker.setChecked(self._settings.get("speaker_enabled", True))
        gl2.addWidget(self._chk_speaker)
        layout.addWidget(g2)
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
        r1.addWidget(QLabel("静音阈值:"))
        self._vad_slider = QSlider(Qt.Horizontal)
        self._vad_slider.setRange(30, 150)
        val = int(self._settings.get("vad_threshold", 0.85) * 100)
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
        self._spn_force_cut.setValue(self._settings.get("force_cut_sec", 3.8))
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

        self._chk_adaptive = QCheckBox("自适应VAD（嘈杂环境自动调整）")
        self._chk_adaptive.setChecked(self._settings.get("adaptive_vad", True))
        gl.addWidget(self._chk_adaptive)

        self._chk_music = QCheckBox("音乐检测（音乐场景特殊处理）")
        self._chk_music.setChecked(self._settings.get("music_detect", True))
        gl.addWidget(self._chk_music)

        self._chk_force_cut = QCheckBox("VAD 强制切分（关闭后ASR模型自行判句）")
        self._chk_force_cut.setChecked(self._settings.get("vad_force_cut", True))
        gl.addWidget(self._chk_force_cut)

        r_mode = QHBoxLayout()
        r_mode.addWidget(QLabel("转录模式"))
        self._cmb_mode = QComboBox()
        self._cmb_mode.addItem("整句模式（准确度最高）", "sentence")
        self._cmb_mode.addItem("流式模式（毫秒级实时输出）", "streaming")
        cur_mode = self._settings.get("transcription_mode", "streaming")
        idx = self._cmb_mode.findData(cur_mode)
        if idx >= 0:
            self._cmb_mode.setCurrentIndex(idx)
        r_mode.addWidget(self._cmb_mode)
        gl.addLayout(r_mode)

        layout.addWidget(g)
        layout.addStretch()
        tabs.addTab(w, "音频/VAD")

    def _build_advanced_tab(self, tabs):
        w = QWidget()
        layout = QVBoxLayout(w)

        g1 = QGroupBox("功能开关")
        gl1 = QVBoxLayout(g1)
        self._chk_lyrics = QCheckBox("歌词匹配（自动匹配）")
        self._chk_lyrics.setChecked(self._settings.get("lyrics_enabled", True))
        gl1.addWidget(self._chk_lyrics)
        self._chk_kw = QCheckBox("关键词扩展（话题标签加载）")
        self._chk_kw.setChecked(self._settings.get("keyword_expand_enabled", True))
        gl1.addWidget(self._chk_kw)
        layout.addWidget(g1)

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

        g3 = QGroupBox("其他")
        gl3 = QVBoxLayout(g3)
        self._chk_report = QCheckBox("识别结束后自动保存 HTML 报告")
        self._chk_report.setChecked(self._settings.get("auto_save_report", False))
        gl3.addWidget(self._chk_report)
        layout.addWidget(g3)
        layout.addStretch()
        tabs.addTab(w, "高级")

    def _gather_config(self):
        return {
            "current_model": MODEL_OPTIONS[self._cmb_model.currentIndex()],
            "device": DEVICE_OPTIONS[self._cmb_device.currentIndex()],
            "model_settings": {
                "vad_enabled": self._chk_vad.isChecked(),
                "vad_model": VAD_MODEL_KEYS[self._cmb_vad.currentIndex()],
                "punc_enabled": self._chk_punc.isChecked(),
                "speaker_enabled": self._chk_speaker.isChecked(),
                "lyrics_enabled": self._chk_lyrics.isChecked(),
                "keyword_expand_enabled": self._chk_kw.isChecked(),
                "adaptive_vad": self._chk_adaptive.isChecked(),
                "music_detect": self._chk_music.isChecked(),
                "vad_force_cut": self._chk_force_cut.isChecked(),
                "vad_threshold": round(self._vad_slider.value() / 100, 2),
                "force_cut_sec": round(self._spn_force_cut.value(), 1),
                "max_buffer_seconds": self._spn_buffer.value(),
                "min_speech_duration": round(self._min_speech_slider.value() / 100, 2),
                "threads": self._spn_threads.value(),
                "ws_port": self._spn_ws.value(),
                "auto_save_report": self._chk_report.isChecked(),
                "transcription_mode": self._cmb_mode.currentData(),
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
                "model_settings": dict(DEFAULT_CONFIG["model_settings"]),
            })
            self._needs_restart = True
            self.accept()

    @property
    def needs_restart(self):
        return self._needs_restart


# 兼容旧代码的别名
SettingsDialogTk = SettingsDialog
