# -*- coding: utf-8 -*-
"""
在线实时语音识别系统 - 核心模块
支持模型: Qwen3-ASR, SenseVoice, Paraformer, Whisper
"""
import logging
for _bad_logger in ["transformers", "diffusers", "huggingface_hub",
                     "datasets", "accelerate", "tokenizers", "modelscope"]:
    _lg = logging.getLogger(_bad_logger)
    _lg.handlers.clear()
    _lg.addHandler(logging.NullHandler())
    _lg.propagate = False

import torch
import json
from pathlib import Path

import os as _os

BASE_DIR = Path(__file__).parent
DICT_DIR = BASE_DIR / "dict"
TEMP_DIR = BASE_DIR / "temp"
MODELS_DIR = BASE_DIR / "models"
CONFIG_FILE = DICT_DIR / "asr_config.json"

for d in [TEMP_DIR, MODELS_DIR]:
    d.mkdir(exist_ok=True)

_os.environ.setdefault('MODELSCOPE_CACHE', str(MODELS_DIR))

OLD_MODELSCOPE_CACHE = Path.home() / '.cache' / 'modelscope'

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "current_model": "auto",
        "device": "auto",
        "model_settings": {}
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
                import json
                with open(self.correction_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
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
        self.processor = None
        self.language = "zh"
        self._config = config if config is not None else load_config()
        self._device = device if device is not None else resolve_device(self._config)
        self._settings = self._config.get("model_settings", {})

    def load_model(self, preferred=None):
        if preferred is None:
            preferred = self._config.get("current_model", "auto")
        if preferred == 'whisper':
            return self._try_load('_load_whisper', 'OpenAI Whisper')
        elif preferred in ('whisper-tiny', 'whisper-base', 'whisper-small',
                           'whisper-medium', 'whisper-large'):
            size = preferred.split('-', 1)[1]
            return self._try_load('_load_whisper', f'OpenAI Whisper ({size})', size=size)
        elif preferred == 'paraformer':
            return self._try_load('_load_paraformer', 'Paraformer')
        elif preferred in ('qwen3-asr-1.7b', 'qwen3-asr-0.6b'):
            size = preferred.split('-', 2)[2]
            return self._try_load('_load_qwen3_asr', f'Qwen3-ASR {size.upper()}', size=size.upper())
        elif preferred in ('qwen3-asr',):
            return self._try_load('_load_qwen3_asr', 'Qwen3-ASR')
        elif preferred == 'sensevoice':
            return self._try_load('_load_sensevoice', 'SenseVoice')
        else:
            order = [
                ('_load_qwen3_asr', 'Qwen3-ASR', '1.7B'),
                ('_load_qwen3_asr', 'Qwen3-ASR', '0.6B'),
                ('_load_sensevoice', 'SenseVoice', None),
                ('_load_paraformer', 'Paraformer', None),
                ('_load_whisper', 'OpenAI Whisper', None),
            ]
            for method, name, size in order:
                extra = {'size': size} if size else {}
                if self._try_load(method, name, **extra):
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
    
    def _load_whisper(self, size=None):
        """加载OpenAI Whisper模型"""
        try:
            import whisper
            
            model_size = size if size else self._settings.get("whisper_size", "base")
            print(f"[LOAD] Loading OpenAI Whisper: {model_size} (device={self._device})")

            self.model = whisper.load_model(model_size, device=self._device)
            self.model_name = f"whisper-{model_size}"
            self.language = "zh"
            
            print("[OK] Whisper loaded successfully")
            return True
            
        except Exception as e:
            print(f"[WARN] Whisper load failed: {e}")
            return False
    
    def _load_paraformer(self):
        """加载Paraformer模型（FunASR，中文识别效果最好）"""
        try:
            import os
            os.environ['FUNASR_DEVICE'] = self._device
            print(f"[INFO] ModelScope cache: {MODELS_DIR}")

            from funasr import AutoModel

            print(f"[LOAD] Loading Paraformer model ({self._device.upper()})...")

            self.model = AutoModel(
                model="paraformer-zh",
                model_revision="v2.0.4",
                disable_update=True,
                disable_log=True,
                local_files_only=True,
                vad_model="fsmn-vad",
                vad_model_revision="v2.0.4",
                punc_model="ct-punc-c",
                punc_model_revision="v2.0.4",
                device=self._device
            )
            
            self.model_name = "paraformer"
            print("[OK] Paraformer loaded successfully")
            return True
            
        except Exception as e:
            print(f"[ERROR] Paraformer load failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _load_qwen3_asr(self, size=None):
        """Qwen3-ASR  --  1.7B / 0.6B, GPU / CPU"""
        try:
            import os, sys

            import logging
            for _name in ["transformers", "diffusers", "huggingface_hub",
                          "datasets", "accelerate", "tokenizers", "modelscope"]:
                _lg = logging.getLogger(_name)
                _lg.handlers.clear()
                _lg.addHandler(logging.NullHandler())
                _lg.propagate = False

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
                    OLD_MODELSCOPE_CACHE / 'hub' / 'models' / 'Qwen' / folder_name,
                ]
                for candidate in list(MODELS_DIR.glob(f'**/{folder_name}')):
                    if candidate.is_dir() and candidate not in search_paths:
                        search_paths.insert(0, candidate)
                for p in search_paths:
                    if p.is_dir():
                        model_path = str(p)
                        model_variant = (folder_name, size_label, ms_id, hf_id)
                        tag = 'project' if str(p).startswith(str(MODELS_DIR)) else 'user-cache'
                        print(f"[LOAD] Qwen3-ASR {size_label} from {tag}: {model_path}", flush=True)
                        break
                if model_path:
                    break

            if not model_path:
                for folder_name, size_label, ms_id, hf_id in model_variants:
                    try:
                        from modelscope import snapshot_download
                        model_path = snapshot_download(ms_id)
                        model_variant = (folder_name, size_label, ms_id, hf_id)
                        print(f"[LOAD] Qwen3-ASR {size_label} from ModelScope: {model_path}", flush=True)
                        break
                    except Exception:
                        continue

            if not model_path or not os.path.isdir(model_path):
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

            print("[LOAD] Qwen3-ASR step3: from_pretrained...", flush=True)
            self.model = Qwen3ASRModel.from_pretrained(
                model_path,
                dtype=dtype,
                device_map=device_map,
                max_new_tokens=96,
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

    def _load_sensevoice(self):
        """加载SenseVoice模型（FunASR，比Paraformer更新）"""
        try:
            import os
            os.environ['FUNASR_DEVICE'] = DEVICE

            from funasr import AutoModel
            print(f"[LOAD] SenseVoice via FunASR ({DEVICE.upper()})...")
            self.model = AutoModel(
                model="iic/SenseVoiceSmall",
                disable_update=True,
                disable_log=True,
                device=DEVICE
            )
            self.model_name = "sensevoice"
            print("[OK] SenseVoice loaded")
            return True
        except Exception as e:
            print(f"[WARN] SenseVoice failed: {e}")
            return False
    
    def transcribe(self, audio_path):
        """转录音频文件"""
        if self.model is None:
            raise RuntimeError("ASR model not loaded")
        
        import time
        start = time.time()
        
        if self.model_name == "whisper":
            result = self._transcribe_whisper(audio_path)
        elif self.model_name == "qwen3-asr":
            result = self._transcribe_qwen(audio_path)
        elif self.model_name == "sensevoice":
            result = self._transcribe_paraformer(audio_path)
        else:
            result = self._transcribe_paraformer(audio_path)
        
        elapsed = time.time() - start
        print(f"[OK] Transcription done ({len(result)} chars, {elapsed:.1f}s)")
        return result
    
    def _transcribe_whisper(self, audio_path):
        """OpenAI Whisper识别"""
        result = self.model.transcribe(
            str(audio_path),
            language=self.language,
            fp16=(DEVICE == "cuda")
        )
        return result.get("text", "").strip()
    
    def _transcribe_qwen(self, audio_path):
        """Qwen3-ASR 官方 qwen-asr 转录"""
        results = self.model.transcribe(
            audio=str(audio_path),
            language=None,
        )
        return results[0].text.strip()
    
    def _transcribe_paraformer(self, audio_path):
        """Paraformer识别 - 用 numpy 数组传入，避免 ffmpeg 依赖"""
        import soundfile as sf
        import numpy as np
        
        # 用 soundfile 加载音频数据（绕过 ffmpeg）
        audio_data, sr = sf.read(str(audio_path), dtype='float32')
        
        # 如果是立体声，转单声道
        if len(audio_data.shape) > 1:
            audio_data = np.mean(audio_data, axis=1)
        
        # 如果采样率不是 16kHz，需要重采样
        if sr != 16000:
            import librosa
            audio_data = librosa.resample(audio_data, orig_sr=sr, target_sr=16000)
        
        # 直接传入 numpy 数组（绕过 FunASR 的 ffmpeg 调用）
        result = self.model.generate(input=audio_data)
        
        if result and len(result) > 0:
            return result[0].get("text", "")
        return ""
