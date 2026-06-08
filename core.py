# -*- coding: utf-8 -*-
"""
在线实时语音识别系统 - 核心模块
支持模型: Qwen3-ASR
"""
import logging


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
from pathlib import Path

import os as _os

BASE_DIR = Path(__file__).parent
DICT_DIR = BASE_DIR / "dict"
TEMP_DIR = BASE_DIR / "temp"
MODELS_DIR = BASE_DIR / "models"
CONFIG_FILE = DICT_DIR / "asr_config.json"

for d in [DICT_DIR, TEMP_DIR, MODELS_DIR]:
    d.mkdir(exist_ok=True)

_os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')

_DEFAULT_CONFIG = {
    "current_model": "auto",
    "device": "auto",
    "model_settings": {
        "vad_force_cut": True,
        "vad_threshold": 0.8,
        "force_cut_sec": 8.0,
        "max_buffer_seconds": 30,
        "min_speech_duration": 0.08,
        "threads": 8,
        "ws_port": 8765,
        "max_new_tokens": 128,
    }
}


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for k, v in _DEFAULT_CONFIG.items():
                if k not in data:
                    data[k] = v
            for k, v in _DEFAULT_CONFIG["model_settings"].items():
                if k not in data.get("model_settings", {}):
                    data.setdefault("model_settings", {})[k] = v
            return data
        except Exception as e:
            print(f"[WARN] load_config failed: {e}", flush=True)
    return {
        "current_model": _DEFAULT_CONFIG["current_model"],
        "device": _DEFAULT_CONFIG["device"],
        "model_settings": dict(_DEFAULT_CONFIG["model_settings"]),
    }


def save_config(config):
    DICT_DIR.mkdir(exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def resolve_device(config=None):
    if config is None:
        config = load_config()
    device = config.get("device", "auto")
    if device == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        return "cpu"
    return device


class CorrectionManager:
    """纠错管理器"""
    
    def __init__(self):
        self.correction_file = DICT_DIR / "correction.json"
        self.data = self._load()
    
    def _load(self):
        if self.correction_file.exists():
            try:
                with open(self.correction_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[WARN] load_config failed: {e}", flush=True)
        return {}
    
    def correct_text(self, text):
        if not self.data or not text:
            return text
        corrected = text
        for wrong, correct in sorted(self.data.items(), key=lambda x: len(x[0]), reverse=True):
            corrected = corrected.replace(wrong, correct)
        return corrected


class ASREngine:
    """ASR识别引擎"""

    def __init__(self, device=None, config=None):
        self.model = None
        self.model_name = None
        self._config = config if config is not None else load_config()
        self._device = device if device is not None else resolve_device(self._config)
        self._settings = self._config.get("model_settings", {})

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
            # auto: try 1.7B first, then 0.6B
            if self._try_load('_load_qwen3_asr', 'Qwen3-ASR', size='1.7B'):
                return True
            if self._try_load('_load_qwen3_asr', 'Qwen3-ASR', size='0.6B'):
                return True
            return False

    def _try_load(self, method_name, display_name, **kwargs):
        """尝试加载指定模型"""
        try:
            method = getattr(self, method_name)
            return method(**kwargs)
        except Exception as e:
            print(f"[WARN] {display_name} 加载失败: {e}")
            return False
    
    def _load_qwen3_asr(self, size=None):
        """Qwen3-ASR  --  1.7B / 0.6B, GPU / CPU"""
        try:
            import os

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
                for candidate in list(MODELS_DIR.glob(f'**/{folder_name}')):
                    if candidate.is_dir() and candidate not in search_paths:
                        search_paths.insert(0, candidate)
                for p in search_paths:
                    if p.is_dir():
                        model_path = str(p)
                        model_variant = (folder_name, size_label, ms_id, hf_id)
                        print(f"[LOAD] Qwen3-ASR {size_label} from local: {model_path}", flush=True)
                        break
                if model_path:
                    break

            if not model_path:
                os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
                model_path = "Qwen/Qwen3-ASR-1.7B"
                print(f"[LOAD] Qwen3-ASR from HuggingFace: {model_path}", flush=True)

            has_cuda = torch.cuda.is_available()
            dtype = torch.bfloat16 if has_cuda else torch.float32
            device_map = "cuda" if has_cuda else "cpu"
            print(f"[LOAD] Qwen3-ASR device={device_map} dtype={'bfloat16' if has_cuda else 'float32'}", flush=True)

            print("[LOAD] Qwen3-ASR step1: importing qwen_asr...", flush=True)
            from qwen_asr import Qwen3ASRModel
            print("[LOAD] Qwen3-ASR step2: import OK", flush=True)

            max_tokens = self._config.get("model_settings", {}).get("max_new_tokens", 128)
            print("[LOAD] Qwen3-ASR step3: from_pretrained...", flush=True)
            self.model = Qwen3ASRModel.from_pretrained(
                model_path,
                dtype=dtype,
                device_map=device_map,
                max_new_tokens=max_tokens,
            )
            print("[LOAD] Qwen3-ASR step4: model loaded", flush=True)
            size_info = model_variant[1] if model_variant else "?"
            self.model_name = f"qwen3-asr-{size_info}"
            print(f"[OK] Qwen3-ASR {size_info} loaded on {device_map}")
            return True
        except Exception as e:
            print(f"[WARN] Qwen3-ASR failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def transcribe(self, audio_path):
        """转录音频文件"""
        if self.model is None:
            raise RuntimeError("ASR model not loaded")
        
        import time
        start = time.time()
        
        result = self._transcribe_qwen(audio_path)
        
        elapsed = time.time() - start
        print(f"[OK] Transcription done ({len(result)} chars, {elapsed:.1f}s)")
        return result

    def transcribe_array(self, audio_array, sr=16000):
        """流式快速转录：直接接受numpy数组，跳过文件IO，用更少token加速"""
        import time
        start = time.time()

        if self.model is None:
            raise RuntimeError("ASR model not loaded")

        import soundfile as sf
        import numpy as np

        audio_data = np.asarray(audio_array, dtype=np.float32)
        if len(audio_data.shape) > 1:
            audio_data = np.mean(audio_data, axis=1)

        if sr != 16000:
            import librosa
            audio_data = librosa.resample(audio_data, orig_sr=sr, target_sr=16000)

        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        try:
            sf.write(tmp.name, audio_data, 16000)
            results = self.model.transcribe(
                audio=tmp.name,
                language=None,
            )
            result = results[0].text.strip()
        finally:
            os.unlink(tmp.name)

        elapsed = time.time() - start
        print(f"[OK] Streaming transcription done ({len(result)} chars, {elapsed:.1f}s)")
        return result

    def _transcribe_qwen(self, audio_path):
        """Qwen3-ASR 官方 qwen-asr 转录"""
        results = self.model.transcribe(
            audio=str(audio_path),
            language=None,
        )
        return results[0].text.strip()
