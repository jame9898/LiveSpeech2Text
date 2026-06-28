# -*- coding: utf-8 -*-
"""
在线实时语音识别系统 - 核心模块（HF 原生版）
支持模型: Qwen3-ASR-*-hf（HuggingFace Transformers 原生加载，不依赖 qwen-asr SDK）
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

# modelscope 默认系统缓存路径（仍用于 CAM++ 说话人模型）
_MODELSCOPE_HUB = Path.home() / ".cache" / "modelscope" / "hub"
# huggingface 默认系统缓存路径（HF 版 ASR 模型）
_HF_HUB = Path.home() / ".cache" / "huggingface" / "hub"

# 使用 HF 镜像加速国内下载
_os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')

_DEFAULT_CONFIG = {
    "current_model": "auto",
    "device": "auto",
    "model_settings": {
        "vad_force_cut": True,
        "vad_threshold": 1.0,
        "force_cut_sec": 6.0,
        "max_buffer_seconds": 30,
        "min_speech_duration": 0.12,
        "threads": 4,
        "ws_port": 8765,
        "max_new_tokens": 256,
        "torch_compile": False,
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
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"[WARN] save_config failed: {e}", flush=True)


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


class ASREngine:
    """ASR识别引擎（HF 原生版）"""

    def __init__(self, device=None, config=None):
        self.model = None
        self.processor = None
        self.model_name = None
        self._max_new_tokens = 128
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
            # auto: try 0.6B first (faster), then 1.7B
            if self._try_load('_load_qwen3_asr', 'Qwen3-ASR', size='0.6B'):
                return True
            if self._try_load('_load_qwen3_asr', 'Qwen3-ASR', size='1.7B'):
                return True
            return False

    def _try_load(self, method_name, display_name, **kwargs):
        """尝试加载指定模型"""
        try:
            method = getattr(self, method_name)
            print(f"[LOAD] Trying {display_name}...", flush=True)
            return method(**kwargs)
        except Exception as e:
            print(f"[WARN] {display_name} 加载失败: {e}")
            return False

    def _load_qwen3_asr(self, size=None):
        """Qwen3-ASR-*-hf  --  1.7B / 0.6B, GPU / CPU（Transformers 原生加载）"""
        try:
            # (本地目录名, 尺寸标签, HF model_id)
            model_variants = [
                ("Qwen3-ASR-1.7B-hf", "1.7B", "Qwen/Qwen3-ASR-1.7B-hf"),
                ("Qwen3-ASR-0.6B-hf", "0.6B", "Qwen/Qwen3-ASR-0.6B-hf"),
            ]

            if size:
                model_variants = [v for v in model_variants if v[1] == size]
                if not model_variants:
                    print(f"[WARN] Qwen3-ASR 未知尺寸: {size}", flush=True)
                    return False

            model_path = None
            size_label = None

            for folder_name, s_label, hf_id in model_variants:
                search_paths = []
                # 项目内 models 目录（任意层级匹配）
                for candidate in list(MODELS_DIR.glob(f'**/{folder_name}')):
                    if candidate.is_dir():
                        search_paths.append(candidate)
                # HF 默认缓存: models--Qwen--Qwen3-ASR-1.7B-hf/snapshots/*
                hf_cache_model_dir = _HF_HUB / f"models--Qwen--{folder_name}" / "snapshots"
                if hf_cache_model_dir.is_dir():
                    for candidate in hf_cache_model_dir.iterdir():
                        if candidate.is_dir():
                            search_paths.append(candidate)
                for p in search_paths:
                    if p.is_dir():
                        model_path = str(p)
                        size_label = s_label
                        print(f"[LOAD] Qwen3-ASR {s_label} from local: {model_path}", flush=True)
                        break
                if model_path:
                    break

            if not model_path:
                # 本地未找到，使用 HF model_id 自动下载（经 hf-mirror 镜像）
                model_path = model_variants[0][2]  # hf_id
                size_label = model_variants[0][1]
                print(f"[LOAD] Qwen3-ASR {size_label} from HuggingFace: {model_path}", flush=True)

            has_cuda = torch.cuda.is_available()
            dtype = torch.bfloat16 if has_cuda else torch.float32
            device_map = "cuda" if has_cuda else "cpu"
            print(f"[LOAD] Qwen3-ASR device={device_map} dtype={'bfloat16' if has_cuda else 'float32'}", flush=True)

            print("[LOAD] Qwen3-ASR step1: importing transformers...", flush=True)
            from transformers import AutoProcessor, AutoModelForMultimodalLM
            print("[LOAD] Qwen3-ASR step2: import OK", flush=True)

            # max_new_tokens 在 generate 阶段传入（HF 版不再在 from_pretrained 传入）
            self._max_new_tokens = self._config.get("model_settings", {}).get("max_new_tokens", 128)

            print("[LOAD] Qwen3-ASR step3: from_pretrained (processor)...", flush=True)
            self.processor = AutoProcessor.from_pretrained(model_path)
            print("[LOAD] Qwen3-ASR step4: from_pretrained (model)...", flush=True)
            self.model = AutoModelForMultimodalLM.from_pretrained(
                model_path,
                dtype=dtype,
                device_map=device_map,
            )
            self.model.eval()
            print("[LOAD] Qwen3-ASR step5: model loaded (eval mode)", flush=True)
            # 可选：torch.compile 加速（官方实测 ASR generate 约 2.4x，需 GPU）
            if self._config.get("model_settings", {}).get("torch_compile", False) and has_cuda:
                try:
                    self.model.forward = torch.compile(self.model.forward)
                    print("[LOAD] Qwen3-ASR torch.compile enabled", flush=True)
                except Exception as _ce:
                    print(f"[WARN] torch.compile failed, fallback to eager: {_ce}", flush=True)
            self.model_name = f"Qwen3-ASR-{size_label}-hf"
            print(f"[OK] Qwen3-ASR {size_label} loaded on {device_map}")
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

        start = time.time()

        result = self._transcribe_qwen(audio_path)

        elapsed = time.time() - start
        print(f"[OK] Transcription done ({len(result)} chars, {elapsed:.1f}s)")
        return result

    def transcribe_array(self, audio_array, sr=16000):
        """流式快速转录：接受numpy数组，直接传给模型（避免临时WAV文件IO）"""
        start = time.time()

        if self.model is None or self.processor is None:
            raise RuntimeError("ASR model not loaded")

        import numpy as np

        audio_data = np.asarray(audio_array, dtype=np.float32)
        if len(audio_data.shape) > 1:
            audio_data = np.mean(audio_data, axis=1)

        if sr != 16000:
            import librosa
            audio_data = librosa.resample(audio_data, orig_sr=sr, target_sr=16000)

        # 直接传裸 ndarray 给 HF processor（feature_extractor 固定 16kHz，
        # 上方已 resample 到 16000，无需再传采样率；元组输入不被接受）
        inputs = self.processor.apply_transcription_request(
            audio=audio_data,
        ).to(self.model.device, self.model.dtype)

        with torch.inference_mode():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=self._max_new_tokens,
                do_sample=False,
            )
        generated_ids = output_ids[:, inputs["input_ids"].shape[1]:]

        result = self.processor.decode(generated_ids, return_format="transcription_only")[0] or ""
        result = result.strip()

        elapsed = time.time() - start
        print(f"[OK] Streaming transcription done ({len(result)} chars, {elapsed:.1f}s)")
        return result

    def _transcribe_qwen(self, audio_path):
        """Qwen3-ASR-*-hf Transformers 原生转录（文件路径）"""
        inputs = self.processor.apply_transcription_request(
            audio=str(audio_path),
        ).to(self.model.device, self.model.dtype)

        with torch.inference_mode():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=self._max_new_tokens,
                do_sample=False,
            )
        generated_ids = output_ids[:, inputs["input_ids"].shape[1]:]

        result = self.processor.decode(generated_ids, return_format="transcription_only")[0] or ""
        return result.strip()
