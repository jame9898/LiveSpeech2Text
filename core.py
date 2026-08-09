# -*- coding: utf-8 -*-
"""
在线实时语音识别系统 - 核心模块
支持模型: Qwen3-ASR
"""
import logging
import threading


def silence_noisy_loggers():
    """静默第三方库的冗余日志"""
    for _name in ["transformers", "diffusers", "huggingface_hub",
                  "datasets", "accelerate", "tokenizers"]:
        _lg = logging.getLogger(_name)
        _lg.handlers.clear()
        _lg.addHandler(logging.NullHandler())
        _lg.propagate = False


silence_noisy_loggers()

import torch
import json
import time
import copy
from pathlib import Path

import os as _os

BASE_DIR = Path(__file__).parent
DICT_DIR = BASE_DIR / "dict"
TEMP_DIR = BASE_DIR / "temp"
MODELS_DIR = BASE_DIR / "models"
CONFIG_FILE = DICT_DIR / "asr_config.json"

for d in [DICT_DIR, TEMP_DIR, MODELS_DIR]:
    d.mkdir(exist_ok=True)

# modelscope 默认系统缓存路径
_MODELSCOPE_HUB = Path.home() / ".cache" / "modelscope" / "hub"

# 创空间持久化目录（容器重启后不丢失）
# 优先级：MODELS_DIR > /mnt/workspace/livespeech2text_models > ~/.cache/modelscope
_PERSISTENT_ROOTS = []
_mnt = Path("/mnt/workspace/livespeech2text_models")
if _mnt.exists() or Path("/mnt/workspace").exists():
    _PERSISTENT_ROOTS.append(_mnt)

_os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')

_DEFAULT_CONFIG = {
    "current_model": "auto",
    "device": "auto",
    "model_settings": {
        "vad_engine": "energy",
        "vad_force_cut": True,
        "vad_threshold": 0.5,
        "force_cut_sec": 6.0,
        "max_buffer_seconds": 30,
        "min_speech_duration": 0.3,
        "silero_speech_prob_threshold": 0.5,
        "fsmn_speech_noise_threshold": 0.6,
        "threads": 4,
        "ws_port": 8765,
        "max_new_tokens": 4096,
        "language_mode": "auto",
        "speaker_model": "cam++",
        "speaker_strictness": "strict",
        "hotwords": {
            "enabled": False,
            "lib_path": "dict/hotwords.json",
            "window_size": 5,
            "min_freq": 1
        }
    },
    "dataset_settings": {
        "enabled": False,
        "quality_threshold": 0.6,
        "auto_filter": True,
    },
    "local_settings": {
        "ffmpeg_path": "",
    }
}


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # 用深拷贝合并默认配置，避免直接引用 _DEFAULT_CONFIG 的嵌套 dict
            # 否则修改返回值会永久污染全局默认配置
            for k, v in _DEFAULT_CONFIG.items():
                if k not in data:
                    data[k] = copy.deepcopy(v)
            for k, v in _DEFAULT_CONFIG["model_settings"].items():
                if k not in data.get("model_settings", {}):
                    data.setdefault("model_settings", {})[k] = copy.deepcopy(v)
            for k, v in _DEFAULT_CONFIG["dataset_settings"].items():
                if k not in data.get("dataset_settings", {}):
                    data.setdefault("dataset_settings", {})[k] = copy.deepcopy(v)
            for k, v in _DEFAULT_CONFIG["local_settings"].items():
                if k not in data.get("local_settings", {}):
                    data.setdefault("local_settings", {})[k] = copy.deepcopy(v)
            return data
        except Exception as e:
            print(f"[WARN] load_config failed: {e}", flush=True)
    return copy.deepcopy(_DEFAULT_CONFIG)


def save_config(config):
    """写配置到磁盘。成功返回 True，失败返回 False（并打印告警）。"""
    DICT_DIR.mkdir(exist_ok=True)
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except OSError as e:
        print(f"[WARN] save_config failed: {e}", flush=True)
        return False


def resolve_device(config=None):
    if config is None:
        config = load_config()
    device = config.get("device", "auto")
    if device == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        return "cpu"
    return device


def get_default_config():
    """返回默认配置的深拷贝（供外部模块使用）"""
    return copy.deepcopy(_DEFAULT_CONFIG)


# 中文/标点/数字判定（用于 zh-only / zh-primary 后置过滤）
import re as _re_filter
# CJK 统一表意文字 + 兼容汉字 + 全角标点
_ZH_CHAR = _re_filter.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]')
# 句末标点（中英文）
_SENT_END = _re_filter.compile(r'[。！？!?\.]')
# 停顿标点
_PAUSE = _re_filter.compile(r'[，,；;、：:]')


def filter_non_chinese(text, mode='auto'):
    """根据语言识别模式过滤 ASR 幻觉产生的外文文本。

    mode:
        'auto'       - 不过滤，原样返回
        'zh-only'    - 只保留中文 + 标点 + 数字
                       - 若整段中文占比 < 30% 且不含句末标点 → 视为幻觉，返回空
                       - 剔除孤立的外文词（前后无中文）
        'zh-primary' - 中文优先，允许句中少量外文（如 "AI""GDP"）
                       - 若整段中文占比 < 20% → 视为幻觉，返回空
                       - 保留夹杂的短外文词
    """
    if not text or mode == 'auto':
        return text

    text = text.strip()
    if not text:
        return text

    # 统计字符数（剔除空白和标点后的字符总数）
    non_space = [c for c in text if not c.isspace() and not _SENT_END.match(c) and not _PAUSE.match(c)]
    if not non_space:
        # 全是标点/空格，原样返回
        return text
    total_chars = len(non_space)
    zh_chars = sum(1 for c in non_space if _ZH_CHAR.match(c))
    zh_ratio = zh_chars / total_chars if total_chars > 0 else 0

    if mode == 'zh-only':
        # 中文极少（<2 个汉字）且不含句末标点 → 视为幻觉丢弃
        # 放宽原"整段中文占比 <30%"的整段丢弃：合法中英混说（如
        # "Let me think about it 今天"）会保留中文部分，再由下方
        # "剔除孤立外文词"清理外文，避免误杀真实中文语音
        has_sent_end = bool(_SENT_END.search(text))
        if zh_chars < 2 and not has_sent_end:
            print(f"[ASR-FILTER] zh-only 丢弃无有效中文内容文本 (zh={zh_chars}, ratio={zh_ratio:.2f}): {text[:50]}", flush=True)
            return ""
        # 剔除孤立的外文词（前后无中文）
        # 匹配连续的非中文非标点非数字片段（长度 >=2）
        def _strip_isolated(m):
            start, end = m.span()
            prev_ch = text[start-1] if start > 0 else ''
            next_ch = text[end] if end < len(text) else ''
            prev_zh = bool(_ZH_CHAR.match(prev_ch)) if prev_ch else False
            next_zh = bool(_ZH_CHAR.match(next_ch)) if next_ch else False
            # 前后都不是中文 → 孤立外文，剔除
            if not prev_zh and not next_zh:
                return ''
            return m.group(0)
        # 外文片段：连续的拉丁/西里尔/韩文/日文假名等非中文字符
        filtered = _re_filter.sub(r'[A-Za-z\u00C0-\u024F\u0400-\u04FF\u3040-\u30FF\uAC00-\uD7AF]{2,}', _strip_isolated, text)
        filtered = filtered.strip()
        if not filtered:
            return ""
        return filtered

    if mode == 'zh-primary':
        # 中文占比 < 20% → 幻觉
        if zh_ratio < 0.20:
            print(f"[ASR-FILTER] zh-primary 丢弃低中文占比文本 (ratio={zh_ratio:.2f}): {text[:50]}", flush=True)
            return ""
        return text

    return text


class ASREngine:
    """ASR识别引擎"""

    def __init__(self, device=None, config=None):
        self.model = None
        # model 级锁：qwen_asr 的线程安全性未知，partial 与 segment 会并发调用 transcribe，
        # 加锁串行化避免 KV cache/临时 tensor 共享导致崩溃或结果错乱
        self._model_lock = threading.Lock()
        self.model_name = None
        self._config = config if config is not None else load_config()
        self._device = device if device is not None else resolve_device(self._config)
        self._settings = self._config.get("model_settings", {})

        # === 热词库（主题感知分层调度）===
        # 加载热词库 JSON，初始化滑动窗口和主题识别器
        self._hotwords_enabled = self._settings.get("hotwords", {}).get("enabled", False)
        self._hotwords_lib = None
        self._hotwords_window = []  # 滑动窗口：最近 N 段已识别文本
        self._hotwords_window_size = int(self._settings.get("hotwords", {}).get("window_size", 5))
        self._hotwords_min_freq = int(self._settings.get("hotwords", {}).get("min_freq", 1))
        self._hotwords_current_topic = None
        self._hotwords_current_context = ""
        # 热词状态锁：partial 与 finalize 可能并发调用 update_hotwords_window
        self._hotwords_lock = threading.Lock()
        if self._hotwords_enabled:
            self._load_hotwords_lib()

    def _load_hotwords_lib(self):
        """加载热词库 JSON 文件"""
        import json
        lib_path = self._settings.get("hotwords", {}).get("lib_path", "dict/hotwords.json")
        # 相对路径基于项目根目录
        lib_full_path = Path(__file__).parent / lib_path if not Path(lib_path).is_absolute() else Path(lib_path)
        try:
            with open(lib_full_path, "r", encoding="utf-8") as f:
                self._hotwords_lib = json.load(f)
            print(f"[HOTWORDS] 热词库已加载: {lib_full_path}", flush=True)
            # 预处理：为每个子主题构建 exclusive 词的小写匹配集合（加速主题识别）
            self._hotwords_topic_index = {}  # {topic_name: set(lowercased_exclusive_words)}
            categories = self._hotwords_lib.get("categories", {})
            for cat_name, cat in categories.items():
                for topic_name, topic in cat.get("subtopics", {}).items():
                    exclusive = topic.get("exclusive", [])
                    self._hotwords_topic_index[topic_name] = [
                        w.lower() for w in exclusive if w
                    ]
            print(f"[HOTWORDS] 子主题数: {len(self._hotwords_topic_index)}", flush=True)
        except Exception as e:
            print(f"[HOTWORDS] 热词库加载失败: {e}", flush=True)
            self._hotwords_enabled = False
            self._hotwords_lib = None

    def update_hotwords_window(self, text):
        """喂入一段已识别文本，更新滑动窗口并重新识别主题。

        在 server.py / local_processor.py 中每段识别完成后调用。
        线程安全：partial 与 finalize 可能并发调用，用 _hotwords_lock 保护。
        """
        if not self._hotwords_enabled or not text:
            return
        with self._hotwords_lock:
            self._hotwords_window.append(text)
            # 保持窗口大小
            if self._hotwords_window_size <= 0:
                # window_size <= 0 视为不保留窗口
                # （注意 list[-0:] 是整个 list，不特判会无界增长）
                self._hotwords_window = []
            elif len(self._hotwords_window) > self._hotwords_window_size:
                self._hotwords_window = self._hotwords_window[-self._hotwords_window_size:]
            # 重新识别主题并构造 context
            self._detect_topic_and_build_context()

    def _detect_topic_and_build_context(self):
        """根据滑动窗口中的文本命中 exclusive 词的频次，识别当前主题并构造 context"""
        if not self._hotwords_lib or not self._hotwords_topic_index:
            return
        # 合并窗口文本（小写）
        window_text = " ".join(self._hotwords_window).lower()
        if not window_text.strip():
            return
        # 统计每个子主题的 exclusive 词命中频次
        # 英文词用词边界匹配（避免 "Meta" 命中 "metadata"、"IDE" 命中 "idea"）
        # 中文词保持子串匹配（中文无词边界）
        import re as _re
        topic_scores = {}
        for topic_name, words_lower in self._hotwords_topic_index.items():
            count = 0
            for w in words_lower:
                if not w:
                    continue
                # 判断是否为纯 ASCII（英文词）：用词边界匹配
                if w.isascii():
                    # \b 词边界：避免短词误命中长词内部
                    pattern = r'\b' + _re.escape(w) + r'\b'
                    count += len(_re.findall(pattern, window_text))
                else:
                    # 中文词：子串匹配
                    count += window_text.count(w)
            if count >= self._hotwords_min_freq:
                topic_scores[topic_name] = count
        if not topic_scores:
            # 无主题命中：不传 default_exclusive，避免冷启动时 context 诱导幻觉
            # （default_exclusive 含"大模型""LLM"等词，ASR 在背景音乐上会幻觉出它们）
            self._hotwords_current_topic = None
            self._hotwords_current_context = ""
            return
        # 取频次最高的主题作为当前主题
        current_topic = max(topic_scores, key=topic_scores.get)
        self._hotwords_current_topic = current_topic
        # 构造 context：当前主题 exclusive（强）+ related（弱）
        categories = self._hotwords_lib.get("categories", {})
        exclusive_words = []
        related_words = []
        for cat in categories.values():
            topic = cat.get("subtopics", {}).get(current_topic)
            if topic:
                exclusive_words = topic.get("exclusive", [])
                related_words = topic.get("related", [])
                break
        parts = []
        if exclusive_words:
            # 限制数量避免 context 过长（前 25 个）
            # 参考式弱引导：明确是"拼写参考"，减少模型在静音/音乐上的幻觉
            parts.append(
                f"如识别到以下专有名词，请保持标准写法（仅供拼写参考，勿主动生成）："
                f"{', '.join(exclusive_words[:25])}。"
            )
        if related_words:
            # 相关词限制前 12 个，且措辞用"也可能"弱化权重
            parts.append(
                f"也可能涉及的相关术语（同样仅供拼写参考）："
                f"{', '.join(related_words[:12])}。"
            )
        self._hotwords_current_context = " ".join(parts)

    def get_hotwords_context(self):
        """获取当前热词 context（供 transcribe 调用）。
        已停用：热词库 context 会诱导 ASR 在非语音段产生幻觉（输出"大模型""LLM"等）。
        热词表只用于后处理拼音纠正（pinyin_corrector），不传给 ASR。
        """
        return ""

    def load_model(self, preferred=None):
        if preferred is None:
            preferred = self._config.get("current_model", "auto")
        if preferred in ('qwen3-asr-1.7b',):
            return self._try_load('_load_qwen3_asr', 'Qwen3-ASR 1.7B', size='1.7B')
        elif preferred in ('qwen3-asr-0.6b',):
            return self._try_load('_load_qwen3_asr', 'Qwen3-ASR 0.6B', size='0.6B')
        elif preferred in ('qwen3-asr',):
            return self._try_load('_load_qwen3_asr', 'Qwen3-ASR')
        else:
            # auto: try 0.6B first (faster), then 1.7B
            if self._try_load('_load_qwen3_asr', 'Qwen3-ASR', size='0.6B'):
                return True
            if self._try_load('_load_qwen3_asr', 'Qwen3-ASR', size='1.7B'):
                return True
            return False

    def _try_load(self, method_name, display_name, **kwargs):
        """尝试加载指定模型"""
        import time
        try:
            method = getattr(self, method_name)
            print(f"[LOAD] Trying {display_name}...", flush=True)
            t0 = time.time()
            result = method(**kwargs)
            elapsed = time.time() - t0
            if result:
                print(f"[LOAD] {display_name} 加载耗时: {elapsed:.2f}s", flush=True)
            return result
        except Exception as e:
            print(f"[WARN] {display_name} 加载失败: {e}")
            return False
    
    def _load_qwen3_asr(self, size=None):
        """Qwen3-ASR  --  1.7B / 0.6B, GPU / CPU"""
        try:
            model_variants = [
                ("Qwen3-ASR-1___7B", "1.7B", "Qwen/Qwen3-ASR-1.7B", "Qwen/Qwen3-ASR-1.7B"),
                ("Qwen3-ASR-0___6B", "0.6B", "Qwen/Qwen3-ASR-0.6B", "Qwen/Qwen3-ASR-0.6B"),
            ]

            if size:
                model_variants = [v for v in model_variants if v[1] == size]
                if not model_variants:
                    print(f"[WARN] Qwen3-ASR 未知尺寸: {size}", flush=True)
                    return False

            model_path = None
            model_variant = None

            for folder_name, size_label, ms_id, hf_id in model_variants:
                search_paths = [
                    MODELS_DIR / 'hub' / 'models' / 'Qwen' / folder_name,
                ]
                # 创空间持久化目录
                for root in _PERSISTENT_ROOTS:
                    search_paths.append(root / 'hub' / 'models' / 'Qwen' / folder_name)
                # modelscope 默认缓存
                search_paths.append(_MODELSCOPE_HUB / 'models' / 'Qwen' / folder_name)

                # 额外递归搜索（兜底）
                for candidate in list(MODELS_DIR.glob(f'**/{folder_name}')):
                    if candidate.is_dir() and candidate not in search_paths:
                        search_paths.insert(0, candidate)
                for root in _PERSISTENT_ROOTS:
                    if root.exists():
                        for candidate in list(root.glob(f'**/{folder_name}')):
                            if candidate.is_dir() and candidate not in search_paths:
                                search_paths.insert(0, candidate)
                for candidate in list(_MODELSCOPE_HUB.glob(f'**/{folder_name}')):
                    if candidate.is_dir() and candidate not in search_paths:
                        search_paths.insert(0, candidate)
                for p in search_paths:
                    if p.is_dir():
                        # 验证目录有权重文件
                        weights = list(p.rglob("*.safetensors")) + list(p.rglob("*.bin"))
                        if not weights:
                            print(f"[LOAD] 跳过（无权重文件）: {p}", flush=True)
                            continue
                        model_path = str(p)
                        model_variant = (folder_name, size_label, ms_id, hf_id)
                        print(f"[LOAD] Qwen3-ASR {size_label} from local: {model_path}", flush=True)
                        break
                if model_path:
                    break

            if not model_path:
                # 使用正确的模型 ID，而不是硬编码 1.7B
                if model_variants:
                    model_path = model_variants[0][2]  # ms_id
                    model_variant = model_variants[0]
                else:
                    model_path = "Qwen/Qwen3-ASR-0.6B"  # 兜底
                    model_variant = None
                print(f"[LOAD] Qwen3-ASR from ModelScope: {model_path}", flush=True)

            has_cuda = torch.cuda.is_available()
            # float16：4070 (Ada) 原生支持 FP16 Tensor Core，比 bfloat16 快 30-50%
            # bfloat16 在 Ada 架构上无 Tensor Core 加速，GPU 利用率低
            dtype = torch.float16 if has_cuda else torch.float32
            device_map = "cuda" if has_cuda else "cpu"
            print(f"[LOAD] Qwen3-ASR device={device_map} dtype={'float16' if has_cuda else 'float32'}", flush=True)
            if not has_cuda:
                # CPU 推理线程数：默认物理核数（超线程对串行 LLM 推理有争抢，反而降速）
                # 可用 config model_settings.cpu_threads 覆盖（0 = 自动）
                cpu_threads = int(self._settings.get("cpu_threads", 0) or 0)
                if cpu_threads <= 0:
                    try:
                        import psutil
                        cpu_threads = psutil.cpu_count(logical=False) or (os.cpu_count() or 4)
                    except Exception:
                        cpu_threads = max(1, (os.cpu_count() or 4) // 2)
                cpu_threads = max(1, cpu_threads)
                torch.set_num_threads(cpu_threads)
                print(f"[LOAD] CPU 推理线程数: {torch.get_num_threads()}", flush=True)

            print("[LOAD] Qwen3-ASR step1: importing qwen_asr...", flush=True)
            from qwen_asr import Qwen3ASRModel
            print("[LOAD] Qwen3-ASR step2: import OK", flush=True)

            # from_pretrained 前 再次静默 transformers logger
            # （transformers 内部会在加载时重新配置 handler，可能引用已失效的 sys.stdout）
            silence_noisy_loggers()
            import sys as _sys
            # 检测 stdout/stderr 是否被替换为不可写/不完整的对象（如 app.py 的 LR）
            # 用 try/finally 保证 from_pretrained 后能还原，避免永久破坏日志重定向
            _orig_stdout = _sys.stdout
            _orig_stderr = _sys.stderr
            _devnull_stdout = None
            _devnull_stderr = None
            _need_restore = False
            try:
                if (not hasattr(_sys.stdout, 'write') or _sys.stdout is None
                        or not hasattr(_sys.stdout, 'fileno')):
                    _devnull_stdout = open(_os.devnull, 'w')
                    _sys.stdout = _devnull_stdout
                    _need_restore = True
                if (not hasattr(_sys.stderr, 'write') or _sys.stderr is None
                        or not hasattr(_sys.stderr, 'fileno')):
                    _devnull_stderr = open(_os.devnull, 'w')
                    _sys.stderr = _devnull_stderr
                    _need_restore = True

                max_tokens = self._config.get("model_settings", {}).get("max_new_tokens", 128)
                print("[LOAD] Qwen3-ASR step3: from_pretrained...", flush=True)
                # 模型切换：持锁先释放旧模型再加载，避免新旧两份同时占显存
                # （1.7B fp16 两份约 7GB+ 易 OOM）。_model_lock 非可重入，
                # 不能直接调 release()，用 _release_model_locked()；
                # 持锁期间转录调用会阻塞等待，不会与加载并发。
                # 加载失败时 self.model 保持 None（旧模型已释放），引擎处于一致的未加载状态。
                with self._model_lock:
                    self._release_model_locked()
                    import gc as _gc
                    _gc.collect()
                    if has_cuda:
                        torch.cuda.synchronize()
                        torch.cuda.empty_cache()
                    # low_cpu_mem_usage=True: 减少CPU内存峰值，加速加载
                    # use_safetensors=True: 优先使用safetensors格式（mmap方式，比.bin快）
                    self.model = Qwen3ASRModel.from_pretrained(
                        model_path,
                        dtype=dtype,
                        device_map=device_map,
                        max_new_tokens=max_tokens,
                        low_cpu_mem_usage=True,
                        use_safetensors=True,
                    )
                    print("[LOAD] Qwen3-ASR step4: model loaded", flush=True)
                    size_info = model_variant[1] if model_variant else "?"
                    self.model_name = f"qwen3-asr-{size_info}"
                    print(f"[OK] Qwen3-ASR {size_info} loaded on {device_map}")
                return True
            finally:
                # 还原 stdout/stderr，保证 app.py 的 LR 日志重定向继续工作
                if _need_restore:
                    _sys.stdout = _orig_stdout
                    _sys.stderr = _orig_stderr
                # 关闭打开的 /dev/null 句柄，避免资源泄漏
                if _devnull_stdout is not None:
                    _devnull_stdout.close()
                if _devnull_stderr is not None:
                    _devnull_stderr.close()
        except Exception as e:
            print(f"[WARN] Qwen3-ASR failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def transcribe(self, audio_path):
        """转录音频文件"""
        if self.model is None:
            raise RuntimeError("ASR model not loaded")

        start = time.time()
        
        result = self._transcribe_qwen(audio_path)
        
        elapsed = time.time() - start
        print(f"[OK] Transcription done ({len(result)} chars, {elapsed:.1f}s)")
        return result

    def release(self):
        """释放模型占用的资源（含 GPU 显存）。

        顺序：model.cpu() → model=None → gc.collect() → cuda.synchronize + empty_cache
        线程安全：用 _model_lock 保护，避免与 transcribe_array 并发。
        所有调用方应统一调用 engine.release() 而非直接操作 eng.model。
        """
        import gc
        with self._model_lock:
            self._release_model_locked()
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
        except Exception:
            pass

    def _release_model_locked(self):
        """释放 self.model 并清空 model_name。调用方必须已持有 _model_lock。"""
        try:
            if self.model is not None:
                try:
                    import torch
                    # 将模型从 GPU 移到 CPU，释放 GPU 显存
                    self.model.cpu()
                except Exception:
                    pass
                self.model = None
            self.model_name = None
        except Exception as e:
            print(f"[RELEASE] 释放模型异常: {e}", flush=True)

    def transcribe_array(self, audio_array, sr=16000):
        """流式快速转录：接受numpy数组，直接传给模型（避免临时WAV文件IO）"""
        start = time.time()

        if self.model is None:
            raise RuntimeError("ASR model not loaded")

        import numpy as np

        audio_data = np.asarray(audio_array, dtype=np.float32)
        if len(audio_data.shape) > 1:
            audio_data = np.mean(audio_data, axis=1)

        if sr != 16000:
            try:
                import librosa
            except ImportError:
                print("[ASR] librosa not installed, cannot resample", flush=True)
                return ""
            audio_data = librosa.resample(audio_data, orig_sr=sr, target_sr=16000)

        # === 非语音预检（两道防线，避免 ASR 在音乐/噪声上产生幻觉） ===
        # 防线1：RMS 能量阈值。低于 0.005（约 -46dB）视为静音/极低能量，直接返回空
        rms = float(np.sqrt(np.mean(audio_data ** 2))) if len(audio_data) > 0 else 0.0
        if rms < 0.005:
            return ""
        # 防线2：频谱平坦度（Spectral Flatness）。区分语音与音乐/噪声
        #   语音：频谱有共振峰，峰谷明显，平坦度低（典型 < 0.3）
        #   音乐/噪声：频谱较均匀，平坦度高（典型 > 0.4）
        #   静音：平坦度接近 1.0
        # 阈值 0.45：高于此值认为是音乐/噪声而非语音，返回空
        # （0.40 会误杀带背景音乐的语音，恢复为 0.45）
        if len(audio_data) >= 512:  # 至少 32ms@16kHz 才能算有意义的频谱
            spectrum = np.fft.rfft(audio_data * np.hanning(len(audio_data)))
            power = np.abs(spectrum) ** 2 + 1e-12
            # 频谱平坦度 = exp(mean(log(power))) / mean(power)
            sf = float(np.exp(np.mean(np.log(power))) / np.mean(power))
            if sf > 0.45:
                print(f"[ASR] 跳过非语音音频 (RMS={rms:.4f}, 频谱平坦度={sf:.3f} > 0.45)", flush=True)
                return ""

        # 直接传 (ndarray, sr) 元组给 qwen-asr，跳过临时文件
        # 加锁串行化：qwen_asr 线程安全性未知，并发调用可能崩溃
        with self._model_lock:
            # 锁内再检查一次：上面的检查与拿锁之间存在窗口，
            # release() 可能在窗口内置 model=None，不查会崩 AttributeError
            if self.model is None:
                raise RuntimeError("ASR model not loaded")
            # 热词 context 已停用：_ctx 始终为空字符串
            _ctx = self.get_hotwords_context()
            results = self.model.transcribe(
                audio=(audio_data, 16000),
                context=_ctx,
                language=None,
            )
            try:
                result = results[0].text.strip() if results else ""
            except (AttributeError, IndexError, TypeError):
                print("[ASR] transcribe returned unexpected result structure", flush=True)
                result = ""

        # 语言识别模式后置过滤（auto / zh-only / zh-primary）
        lang_mode = self._settings.get("language_mode", "auto")
        if lang_mode != "auto" and result:
            result = filter_non_chinese(result, mode=lang_mode)

        elapsed = time.time() - start
        print(f"[OK] Streaming transcription done ({len(result)} chars, {elapsed:.1f}s)", flush=True)
        return result

    def transcribe_batch(self, audio_arrays, sr=16000):
        """批量转录（本地模式）：一次模型调用处理多个音频段，CPU 上显著加速。

        段内过短/低能量的样本直接跳过（返回空字符串）。
        批量失败时自动回退逐段转录，保证不丢结果。
        """
        import numpy as np

        if self.model is None:
            raise RuntimeError("ASR model not loaded")

        arrays = []
        for a in audio_arrays:
            arr = np.asarray(a, dtype=np.float32)
            if arr.ndim > 1:
                arr = np.mean(arr, axis=1)
            # RMS 预检：低能量/空样本直接返回空（与 transcribe_array 一致）
            rms = float(np.sqrt(np.mean(arr ** 2))) if len(arr) > 0 else 0.0
            if len(arr) == 0 or rms < 0.005:
                arrays.append(None)
                continue
            # 频谱平坦度预检：区分语音与音乐/噪声
            if len(arr) >= 512:
                spectrum = np.fft.rfft(arr * np.hanning(len(arr)))
                power = np.abs(spectrum) ** 2 + 1e-12
                sf = float(np.exp(np.mean(np.log(power))) / np.mean(power))
                if sf > 0.45:
                    arrays.append(None)
                    continue
            arrays.append((arr, 16000))

        results = [""] * len(arrays)
        batch = [(i, a) for i, a in enumerate(arrays) if a is not None]
        if not batch:
            return results

        with self._model_lock:
            # 锁内再检查一次：与 transcribe_array 相同的窗口保护
            if self.model is None:
                raise RuntimeError("ASR model not loaded")
            _ctx = self.get_hotwords_context()
            try:
                outs = self.model.transcribe(
                    audio=[a for _, a in batch],
                    context=_ctx,
                    language=None,
                )
            except Exception as e:
                print(f"[ASR] 批量转录失败，回退逐段: {e}", flush=True)
                outs = []
                for _, (arr, _sr) in batch:
                    try:
                        r = self.model.transcribe(
                            audio=(arr, 16000), context=_ctx, language=None)
                        outs.append(r[0] if r else None)
                    except Exception as e2:
                        print(f"[ASR] 逐段回退失败: {e2}", flush=True)
                        outs.append(None)
            lang_mode = self._settings.get("language_mode", "auto")
            for (i, _), out in zip(batch, outs):
                try:
                    text = out.text.strip() if out is not None else ""
                except (AttributeError, IndexError, TypeError):
                    text = ""
                if lang_mode != "auto" and text:
                    text = filter_non_chinese(text, mode=lang_mode)
                results[i] = text
        return results


    def _transcribe_qwen(self, audio_path):
        """Qwen3-ASR 官方 qwen-asr 转录"""
        with self._model_lock:
            # 锁内再检查一次：transcribe() 的外层检查与拿锁之间存在窗口，
            # release() 可能在窗口内置 model=None，不查会崩 AttributeError
            if self.model is None:
                raise RuntimeError("ASR model not loaded")
            _ctx = self.get_hotwords_context()
            results = self.model.transcribe(
                audio=str(audio_path),
                context=_ctx,
                language=None,
            )
            try:
                result = results[0].text.strip() if results else ""
            except (AttributeError, IndexError, TypeError):
                print("[ASR] _transcribe_qwen: unexpected result structure", flush=True)
                result = ""
        # 语言识别模式后置过滤
        lang_mode = self._settings.get("language_mode", "auto")
        if lang_mode != "auto" and result:
            result = filter_non_chinese(result, mode=lang_mode)
        return result
