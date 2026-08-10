# -*- coding: utf-8 -*-

from core import load_config, get_default_config, save_config

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QGroupBox, QLabel, QComboBox, QCheckBox, QPushButton,
    QSlider, QSpinBox, QDoubleSpinBox, QMessageBox, QFileDialog, QLineEdit,
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


def _write_config(config):
    """写配置文件并返回是否成功。core.save_config 已返回 bool，此处仅做别名兼容。"""
    return save_config(config)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumSize(500, 420)
        self.resize(500, 420)
        self.setModal(True)

        self._config = load_config()
        self._settings = self._config.get("model_settings", {})
        self._dataset_settings = self._config.get("dataset_settings", {})
        self._local_settings = self._config.get("local_settings", {})
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
        self._build_dataset_tab(tabs)
        self._build_local_tab(tabs)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_reset = QPushButton("恢复默认")
        btn_reset.clicked.connect(self._reset_defaults)
        btn_layout.addWidget(btn_reset)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        btn_save = QPushButton("保存配置")
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
        self._spn_threads.setValue(self._settings.get("threads", 4))
        r2.addWidget(self._spn_threads)
        gl.addLayout(r2)
        # CPU int8 量化（仅 CPU 生效；支持 VNNI 指令集的 CPU 可提速，无 VNNI 可能变慢）
        self._chk_cpu_quantize = QCheckBox("CPU int8 量化（仅 CPU 模式；权重减 4 倍，支持 VNNI 的 CPU 提速明显）")
        self._chk_cpu_quantize.setChecked(self._settings.get("cpu_quantize", False))
        self._chk_cpu_quantize.setToolTip(
            "用 torchao int8 weight-only 量化 ASR 模型权重（2.4GB→0.6GB）。\n"
            "内存带宽是 CPU 推理瓶颈，权重变小后每 token 读取量降 4 倍。\n"
            "仅对支持 VNNI/AVX512 指令集的较新 CPU（11代酷睿及以后）有效；\n"
            "老 CPU 无 VNNI 时反量化开销可能反而变慢，如实测变慢请关闭。")
        gl.addWidget(self._chk_cpu_quantize)
        layout.addWidget(g)
        # 实际检测结果提示：auto 会解析成什么设备一目了然
        from core import resolve_device
        _det_dev = resolve_device(self._config)
        _det_lbl = QLabel()
        _det_lbl.setStyleSheet("color: #656d76; font-size: 11px")
        if _det_dev == "cuda":
            try:
                import torch
                _gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else ""
            except Exception:
                _gpu_name = ""
            _det_lbl.setText(
                f"当前检测：NVIDIA GPU（{_gpu_name}）→ 实际使用 cuda" if _gpu_name
                else "当前检测：NVIDIA GPU → 实际使用 cuda")
        else:
            _det_lbl.setText("当前检测：未发现 NVIDIA GPU → 实际使用 cpu（模型默认选 0.6B 轻量版）")
        layout.addWidget(_det_lbl)
        layout.addStretch()
        tabs.addTab(w, "设备")

    def _build_audio_tab(self, tabs):
        w = QWidget()
        layout = QVBoxLayout(w)
        g = QGroupBox("VAD 参数")
        gl = QVBoxLayout(g)

        # VAD 引擎选择
        r_engine = QHBoxLayout()
        r_engine.addWidget(QLabel("VAD 引擎:"))
        self._cmb_vad_engine = QComboBox()
        self._cmb_vad_engine.addItem("Silero（神经网络·推荐）", "silero")
        self._cmb_vad_engine.addItem("FSMN（达摩院·中文优化）", "fsmn")
        self._cmb_vad_engine.addItem("能量阈值（兼容·最快）", "energy")
        self._cmb_vad_engine.setToolTip(
            "Silero：实时+本地均可用（神经网络，推荐）\n"
            "能量阈值：实时+本地均可用（最快）\n"
            "FSMN：仅本地模式（实时模式自动回退能量阈值）")
        engine_val = self._settings.get("vad_engine", "silero")
        for i in range(self._cmb_vad_engine.count()):
            if self._cmb_vad_engine.itemData(i) == engine_val:
                self._cmb_vad_engine.setCurrentIndex(i)
                break
        r_engine.addWidget(self._cmb_vad_engine)
        r_engine.addStretch()
        gl.addLayout(r_engine)

        # 语言识别模式（auto / zh-only / zh-primary）
        r_lang = QHBoxLayout()
        r_lang.addWidget(QLabel("语言识别:"))
        self._cmb_language_mode = QComboBox()
        self._cmb_language_mode.addItem("自动（AUTO·默认）", "auto")
        self._cmb_language_mode.addItem("仅中文（过滤外文幻觉）", "zh-only")
        self._cmb_language_mode.addItem("中文优先（允许少量外文）", "zh-primary")
        lang_val = self._settings.get("language_mode", "auto")
        for i in range(self._cmb_language_mode.count()):
            if self._cmb_language_mode.itemData(i) == lang_val:
                self._cmb_language_mode.setCurrentIndex(i)
                break
        r_lang.addWidget(self._cmb_language_mode)
        r_lang.addStretch()
        gl.addLayout(r_lang)

        # 说话人识别模型（CAM++ / ERes2NetV2 / ERes2Net base）
        r_sp_model = QHBoxLayout()
        r_sp_model.addWidget(QLabel("说话人模型:"))
        self._cmb_speaker_model = QComboBox()
        self._cmb_speaker_model.addItem("CAM++（默认·快）", "cam++")
        self._cmb_speaker_model.addItem("ERes2NetV2（精度更高·推荐）", "eres2netv2")
        self._cmb_speaker_model.addItem("ERes2Net base（3D-Speaker）", "eres2net")
        sp_model_val = self._settings.get("speaker_model", "cam++")
        for i in range(self._cmb_speaker_model.count()):
            if self._cmb_speaker_model.itemData(i) == sp_model_val:
                self._cmb_speaker_model.setCurrentIndex(i)
                break
        r_sp_model.addWidget(self._cmb_speaker_model)
        r_sp_model.addStretch()
        gl.addLayout(r_sp_model)

        # 说话人识别严格度（宽松 / 标准 / 严格）
        r_sp_strict = QHBoxLayout()
        r_sp_strict.addWidget(QLabel("说话人严格度:"))
        self._cmb_speaker_strictness = QComboBox()
        self._cmb_speaker_strictness.addItem("宽松（相似音色合并）", "loose")
        self._cmb_speaker_strictness.addItem("标准", "standard")
        self._cmb_speaker_strictness.addItem("严格（默认，区分度高）", "strict")
        strict_val = self._settings.get("speaker_strictness", "strict")
        for i in range(self._cmb_speaker_strictness.count()):
            if self._cmb_speaker_strictness.itemData(i) == strict_val:
                self._cmb_speaker_strictness.setCurrentIndex(i)
                break
        r_sp_strict.addWidget(self._cmb_speaker_strictness)
        r_sp_strict.addStretch()
        gl.addLayout(r_sp_strict)

        # === 通用参数（三个引擎都生效） ===
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("静音断句阈值（秒）:"))
        self._vad_slider = QSlider(Qt.Horizontal)
        self._vad_slider.setRange(30, 150)
        val = round(self._settings.get("vad_threshold", 0.5) * 100)
        self._vad_slider.setValue(val)
        r1.addWidget(self._vad_slider)
        self._vad_lbl = QLabel(f"{val / 100:.2f} 秒")
        self._vad_lbl.setMinimumWidth(50)
        r1.addWidget(self._vad_lbl)
        self._vad_slider.valueChanged.connect(
            lambda v: self._vad_lbl.setText(f"{v / 100:.2f} 秒"))
        gl.addLayout(r1)

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
        # 范围 0.10s ~ 0.50s，步长 0.01s
        self._min_speech_slider.setRange(10, 50)
        val_ms = round(self._settings.get("min_speech_duration", 0.3) * 100)
        self._min_speech_slider.setValue(val_ms)
        r3.addWidget(self._min_speech_slider)
        self._min_speech_lbl = QLabel(f"{val_ms / 100:.2f} 秒")
        self._min_speech_lbl.setMinimumWidth(50)
        r3.addWidget(self._min_speech_lbl)
        self._min_speech_slider.valueChanged.connect(
            lambda v: self._min_speech_lbl.setText(f"{v / 100:.2f} 秒"))
        gl.addLayout(r3)

        # === 能量阈值引擎专属参数 ===
        self._lbl_energy_params = QLabel("── 能量阈值引擎专属参数 ──")
        self._lbl_energy_params.setStyleSheet("color:#656d76;font-size:11px;")
        gl.addWidget(self._lbl_energy_params)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("缓冲区上限:"))
        self._spn_buffer = QSpinBox()
        self._spn_buffer.setRange(10, 60)
        self._spn_buffer.setValue(self._settings.get("max_buffer_seconds", 30))
        r2.addWidget(self._spn_buffer)
        r2.addWidget(QLabel("秒"))
        r2.addStretch()
        gl.addLayout(r2)
        self._row_buffer = r2

        self._chk_force_cut = QCheckBox("VAD 强制切分（关闭后ASR模型自行判句）")
        self._chk_force_cut.setChecked(self._settings.get("vad_force_cut", True))
        gl.addWidget(self._chk_force_cut)

        # === Silero VAD 专属参数 ===
        self._lbl_silero_params = QLabel("── Silero VAD 专属参数 ──")
        self._lbl_silero_params.setStyleSheet("color:#656d76;font-size:11px;")
        gl.addWidget(self._lbl_silero_params)

        r_silero = QHBoxLayout()
        r_silero.addWidget(QLabel("语音概率阈值:"))
        self._silero_prob_slider = QSlider(Qt.Horizontal)
        self._silero_prob_slider.setRange(20, 80)  # 0.20 ~ 0.80
        val_prob = round(self._settings.get("silero_speech_prob_threshold", 0.5) * 100)
        self._silero_prob_slider.setValue(val_prob)
        r_silero.addWidget(self._silero_prob_slider)
        self._silero_prob_lbl = QLabel(f"{val_prob / 100:.2f}")
        self._silero_prob_lbl.setMinimumWidth(50)
        r_silero.addWidget(self._silero_prob_lbl)
        self._silero_prob_slider.valueChanged.connect(
            lambda v: self._silero_prob_lbl.setText(f"{v / 100:.2f}"))
        r_silero.addStretch()
        gl.addLayout(r_silero)
        self._row_silero = r_silero

        # === FSMN VAD 专属参数 ===
        self._lbl_fsmn_params = QLabel("── FSMN VAD 专属参数 ──")
        self._lbl_fsmn_params.setStyleSheet("color:#656d76;font-size:11px;")
        gl.addWidget(self._lbl_fsmn_params)

        r_fsmn = QHBoxLayout()
        r_fsmn.addWidget(QLabel("语音噪声阈值:"))
        self._fsmn_noise_slider = QSlider(Qt.Horizontal)
        self._fsmn_noise_slider.setRange(30, 90)  # 0.30 ~ 0.90
        val_noise = round(self._settings.get("fsmn_speech_noise_threshold", 0.6) * 100)
        self._fsmn_noise_slider.setValue(val_noise)
        r_fsmn.addWidget(self._fsmn_noise_slider)
        self._fsmn_noise_lbl = QLabel(f"{val_noise / 100:.2f}")
        self._fsmn_noise_lbl.setMinimumWidth(50)
        r_fsmn.addWidget(self._fsmn_noise_lbl)
        self._fsmn_noise_slider.valueChanged.connect(
            lambda v: self._fsmn_noise_lbl.setText(f"{v / 100:.2f}"))
        r_fsmn.addStretch()
        gl.addLayout(r_fsmn)
        self._row_fsmn = r_fsmn

        # 引擎切换时显示/隐藏专属参数
        self._cmb_vad_engine.currentIndexChanged.connect(self._on_vad_engine_changed)
        self._on_vad_engine_changed()

        layout.addWidget(g)
        layout.addStretch()
        tabs.addTab(w, "音频/VAD")

    def _on_vad_engine_changed(self):
        """根据 VAD 引擎选择显示/隐藏专属参数"""
        engine = self._cmb_vad_engine.currentData()
        # 能量阈值专属：缓冲区上限、VAD 强制切分开关
        energy_visible = (engine == "energy")
        self._lbl_energy_params.setVisible(energy_visible)
        self._spn_buffer.setVisible(energy_visible)
        # 缓冲区上限的标签也需要隐藏（跳过 stretch 等非 widget 项）
        for i in range(self._row_buffer.count()):
            item = self._row_buffer.itemAt(i)
            if item and item.widget() is not None and item.widget() is not self._spn_buffer:
                item.widget().setVisible(energy_visible)
        self._chk_force_cut.setVisible(energy_visible)
        # Silero 专属：语音概率阈值
        silero_visible = (engine == "silero")
        self._lbl_silero_params.setVisible(silero_visible)
        for i in range(self._row_silero.count()):
            item = self._row_silero.itemAt(i)
            if item and item.widget() is not None:
                item.widget().setVisible(silero_visible)
        # FSMN 专属：语音噪声阈值
        fsmn_visible = (engine == "fsmn")
        self._lbl_fsmn_params.setVisible(fsmn_visible)
        for i in range(self._row_fsmn.count()):
            item = self._row_fsmn.itemAt(i)
            if item and item.widget() is not None:
                item.widget().setVisible(fsmn_visible)

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
        self._spn_max_tokens.setRange(32, 8192)
        self._spn_max_tokens.setSingleStep(32)
        self._spn_max_tokens.setValue(self._settings.get("max_new_tokens", 128))
        self._spn_max_tokens.setToolTip("ASR模型单次最大输出token数，值越大可识别越长句子")
        r2.addWidget(self._spn_max_tokens)
        r2.addStretch()
        gl3.addLayout(r2)
        layout.addWidget(g3)

        layout.addStretch()
        tabs.addTab(w, "高级")

    def _build_dataset_tab(self, tabs):
        w = QWidget()
        layout = QVBoxLayout(w)

        g = QGroupBox("后训练数据集收集")
        gl = QVBoxLayout(g)

        self._chk_dataset = QCheckBox("启用后训练数据集收集（全局默认，对所有模式生效）")
        self._chk_dataset.setChecked(self._dataset_settings.get("enabled", False))
        gl.addWidget(self._chk_dataset)

        r_quality = QHBoxLayout()
        r_quality.addWidget(QLabel("质量评分阈值:"))
        self._dataset_slider = QSlider(Qt.Horizontal)
        self._dataset_slider.setRange(0, 100)
        val_q = round(self._dataset_settings.get("quality_threshold", 0.6) * 100)
        self._dataset_slider.setValue(val_q)
        r_quality.addWidget(self._dataset_slider)
        self._dataset_lbl = QLabel(f"{val_q / 100:.2f}")
        self._dataset_lbl.setMinimumWidth(40)
        r_quality.addWidget(self._dataset_lbl)
        self._dataset_slider.valueChanged.connect(
            lambda v: self._dataset_lbl.setText(f"{v / 100:.2f}"))
        gl.addLayout(r_quality)

        self._chk_dataset_filter = QCheckBox("多维度自动筛选（综合评分 + 削波 + 频谱平坦度）")
        self._chk_dataset_filter.setChecked(self._dataset_settings.get("auto_filter", True))
        gl.addWidget(self._chk_dataset_filter)

        layout.addWidget(g)
        layout.addStretch()
        tabs.addTab(w, "后训练")

    def _build_local_tab(self, tabs):
        w = QWidget()
        layout = QVBoxLayout(w)

        # ffmpeg 路径
        g_ff = QGroupBox("ffmpeg 路径（视频音频提取）")
        gl_ff = QVBoxLayout(g_ff)
        r_ff = QHBoxLayout()
        r_ff.addWidget(QLabel("ffmpeg:"))
        self._ln_ffmpeg = QLineEdit()
        self._ln_ffmpeg.setPlaceholderText("留空则从系统 PATH 查找")
        self._ln_ffmpeg.setText(self._local_settings.get("ffmpeg_path", ""))
        r_ff.addWidget(self._ln_ffmpeg, 1)
        btn_browse_ff = QPushButton("浏览")
        btn_browse_ff.clicked.connect(self._browse_ffmpeg)
        r_ff.addWidget(btn_browse_ff)
        gl_ff.addLayout(r_ff)
        layout.addWidget(g_ff)

        # 性能报告输出开关（默认关闭，勾选后本地处理结束输出阶段耗时/采样汇总/版本信息）
        g_perf = QGroupBox("性能报告")
        gl_perf = QVBoxLayout(g_perf)
        self._chk_perf_report = QCheckBox(
            "处理完成后输出性能报告（阶段耗时占比 / GPU/CPU 采样汇总 / 版本 commit 信息）")
        self._chk_perf_report.setChecked(self._local_settings.get("perf_report_enabled", False))
        self._chk_perf_report.setToolTip(
            "勾选后，每次本地处理结束会在日志中输出完整性能报告，\n"
            "包含版本分支/commit 与 GitHub/Gitee 远端地址，便于对照版本做测试与回退。\n"
            "默认关闭，日志更简洁。")
        gl_perf.addWidget(self._chk_perf_report)
        layout.addWidget(g_perf)

        layout.addStretch()
        tabs.addTab(w, "本地模式")

    def _browse_ffmpeg(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "选择 ffmpeg 可执行文件", "", "可执行文件 (*.exe *.bat *);;所有文件 (*)")
        if path:
            self._ln_ffmpeg.setText(path)

    def _gather_config(self):
        # 在磁盘最新配置基础上增量更新，保留对话框未涉及的键
        # （如 model_settings.hotwords，避免整文件覆盖写时被静默抹掉）
        cfg = load_config()
        cfg["current_model"] = MODEL_OPTIONS[self._cmb_model.currentIndex()]
        cfg["device"] = DEVICE_OPTIONS[self._cmb_device.currentIndex()]
        settings = cfg.setdefault("model_settings", {})
        settings.update({
            "vad_engine": self._cmb_vad_engine.currentData(),
            "vad_force_cut": self._chk_force_cut.isChecked(),
            "vad_threshold": round(self._vad_slider.value() / 100, 2),
            "force_cut_sec": round(self._spn_force_cut.value(), 1),
            "max_buffer_seconds": self._spn_buffer.value(),
            "min_speech_duration": round(self._min_speech_slider.value() / 100, 2),
            "silero_speech_prob_threshold": round(self._silero_prob_slider.value() / 100, 2),
            "fsmn_speech_noise_threshold": round(self._fsmn_noise_slider.value() / 100, 2),
            "threads": self._spn_threads.value(),
            "cpu_quantize": self._chk_cpu_quantize.isChecked(),
            "ws_port": self._spn_ws.value(),
            "max_new_tokens": self._spn_max_tokens.value(),
            "language_mode": self._cmb_language_mode.currentData(),
            "speaker_model": self._cmb_speaker_model.currentData(),
            "speaker_strictness": self._cmb_speaker_strictness.currentData(),
        })
        dataset = cfg.setdefault("dataset_settings", {})
        dataset.update({
            "enabled": self._chk_dataset.isChecked(),
            "quality_threshold": round(self._dataset_slider.value() / 100, 2),
            "auto_filter": self._chk_dataset_filter.isChecked(),
        })
        local = cfg.setdefault("local_settings", {})
        local.update({
            "ffmpeg_path": self._ln_ffmpeg.text().strip(),
            "perf_report_enabled": self._chk_perf_report.isChecked(),
        })
        return cfg

    def _save_and_restart(self):
        cfg = self._gather_config()
        if not _write_config(cfg):
            QMessageBox.critical(self, "保存失败",
                "配置写入失败，请检查 dict 目录是否可写后重试。")
            return
        self._needs_restart = True
        QMessageBox.information(self, "已保存",
            "配置已保存。\n\n如修改了模型、设备或端口，请重启服务以生效。")
        self.accept()

    def _reset_defaults(self):
        r = QMessageBox.question(self, "恢复默认",
            "确定要恢复所有设置为默认值吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r == QMessageBox.Yes:
            # 写入完整默认配置（含 dataset_settings / local_settings），
            # 与"恢复所有设置"的文案一致
            if not _write_config(get_default_config()):
                QMessageBox.critical(self, "保存失败",
                    "配置写入失败，请检查 dict 目录是否可写后重试。")
                return
            self._needs_restart = True
            self.accept()

    @property
    def needs_restart(self):
        return self._needs_restart

