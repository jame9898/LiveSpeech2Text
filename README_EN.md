# LiveSpeech2Text — Real-time Speech Recognition

A Chinese real-time speech recognition tool based on **Qwen3-ASR**. Audio is captured from the browser/microphone/system output, sent to a local server via WebSocket for **VAD segmentation + ASR recognition + speaker diarization**, producing real-time subtitles and Markdown reports. Includes a PySide6 desktop panel and a Tampermonkey userscript.

## Features

- **Four modes**: Audience (web audio), Streamer (microphone), Meeting (microphone + system audio), Local (batch audio/video files)
- **Real-time subtitles**: live preview bar (0.3s on GPU, adaptive throttling on CPU) + final text at VAD segment ends; OBS browser source supported
- **Speaker diarization**: CAM++ / ERes2NetV2 voiceprint recognition
- **Keyword correction**: pinyin-based homophone error correction, add/remove keywords on the fly

## System Requirements

Developed and tested on Windows 11. Other systems are not verified.

| Item | Requirement |
|---|---|
| OS | Windows 11 64-bit |
| Python | 3.10 ~ 3.12 |
| RAM | 8 GB+ (1.7B model requires 6GB+) |
| Storage usage | ~6 GB (including model downloads) |
| GPU | CPU works; GPU acceleration requires NVIDIA + CUDA |

## Quick Start

```bash
# 1. Clone the repository (GitHub or Gitee, choose one)
git clone https://github.com/jame9898/LiveSpeech2Text
# or Gitee mirror
git clone https://gitee.com/linhanduzikai/LiveSpeech2Text

# 2. Enter the folder
cd LiveSpeech2Text

# 3. Virtual environment (recommended; skip if using the system environment)
python -m venv venv
venv\Scripts\activate

# 4. Install dependencies (auto-benchmarks mirrors and picks the fastest, CPU only)
python install.py
# or (GPU + CUDA only)
python install.py --gpu
# or specify a mirror manually (skips auto-benchmark):
# python install.py --index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 5. Download models (auto-saved to models/)
# qwen3-ASR models: ModelScope
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-0.6B', cache_dir='models')"
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-1.7B', cache_dir='models')"

# qwen3-ASR models: Hugging Face (project-compatible directory names, auto-discovered)
python -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-0.6B', local_dir='models/hub/models/Qwen/Qwen3-ASR-0___6B')"
python -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-1.7B', local_dir='models/hub/models/Qwen/Qwen3-ASR-1___7B')"
# Model pages: https://huggingface.co/Qwen/Qwen3-ASR-0.6B | https://huggingface.co/Qwen/Qwen3-ASR-1.7B

# Speaker models (optional, select in Settings; CAM++ is default, ERes2NetV2 is more accurate, ERes2Net base is the 3D-Speaker version):
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/speech_campplus_sv_zh-cn_16k-common', cache_dir='models')"
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/speech_eres2netv2_sv_zh-cn_16k-common', cache_dir='models')"
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/speech_eres2net_base_sv_zh-cn_3dspeaker_16k', cache_dir='models')"

# 6. Launch the desktop panel
python app.py
```

> You can also double-click `start.bat` (uses system Python).

**Install slow or timing out?** `install.py` auto-benchmarks official PyPI, Tsinghua, Aliyun, Tencent, and USTC mirrors (~5s) and picks the fastest source, adapting to networks both in and out of China; domestic users usually hit the Aliyun/Tsinghua mirror. You can also fall back to `pip install -r requirements.txt` directly (you need to configure a domestic mirror yourself, otherwise the official PyPI may be too slow and time out).

**Updating**: after `git pull`, dependencies may have changed — reinstall them:

```bash
git pull
python -m venv venv  # if using a virtual environment (skip otherwise)
venv\Scripts\activate  # if using a virtual environment (skip otherwise)
python install.py   # CPU only
python install.py --gpu # GPU + CUDA only
```

## Uninstall

This project is not packaged as an installer. Simply delete the project folder:

```bash
Remove-Item -Recurse -Force "C:\path\to\LiveSpeech2Text"
# Optional: clear ModelScope model cache
Remove-Item -Recurse -Force "$env:USERPROFILE\.cache\modelscope"
```

Tampermonkey plugin: delete the `LiveSpeech2Text V1.0` script in the Tampermonkey management panel.

## Usage

| Mode | How to use |
|---|---|
| **Audience** (default) | Start service → open `http://localhost:8765` → click "Tab/Fullscreen" to capture web audio (Bilibili/Douyu etc.) |
| **Streamer** | Pick a microphone → start service, capture begins automatically. Subtitle page `http://localhost:8765/subtitle` works with OBS |
| **Meeting** | Microphone + system audio (WASAPI loopback + half-duplex anti-echo), for two-way conversations |
| **Local** | Select files/folder → start processing → Markdown report per file (ffmpeg required for video files) |
| **Tampermonkey** | Import `asr_panel.user.js` for an in-page recognition panel on Bilibili/Douyu |

## Documentation

| Doc | Content |
|---|---|
| [docs/OBS_SUBTITLE.md](docs/OBS_SUBTITLE.md) | OBS subtitle bar setup, subtitle style configuration |
| [docs/VAD.md](docs/VAD.md) | VAD engine comparison and parameters |
| [docs/DATASET.md](docs/DATASET.md) | Fine-tuning dataset (layout/scoring/manual correction flow) |
| [docs/LICENSE_DETAILS.md](docs/LICENSE_DETAILS.md) | Third-party dependency and model license details |

## Project Structure

```
├── app.py                 # PySide6 desktop GUI (mode switching/start-stop/subtitles/system tray)
├── server.py              # WebSocket server (audio receive/VAD/transcription/speaker/web pages)
├── core.py                # ASR engine and model loading + config management
├── vad_processor.py       # VAD engines (energy/Silero streaming/FSMN batch)
├── local_processor.py     # Local mode batch processing (ffmpeg+VAD+ASR+report)
├── dataset_manager.py     # Fine-tuning dataset manager
├── realtime_panel.py      # Realtime panel components (subtitle view/capture threads/WS client)
├── speaker_manager.py     # Speaker management (voiceprint/naming/profiles)
├── pinyin_utils.py        # Keyword management + pinyin correction
├── report_generator.py    # Markdown report generation
├── batch_transcribe.py    # CLI batch transcription script
├── asr_panel.user.js      # Tampermonkey userscript
├── dict/                  # Runtime config (asr_config.json)
└── static/                # Control page + OBS subtitle page
```

## FAQ

### Environment & dependencies

**Speaker model (CAM++/ERes2Net) fails to load after `python install.py`** — Usually caused by missing hidden dependencies of modelscope. This project has pinned all verified hard dependencies in `requirements.txt` (including addict / datasets / torchvision / simplejson / sortedcontainers). After `git pull`, you **must re-run `python install.py`**. It prints a core-package verification list at the end — compare it with `pip list` to find what's missing.

**Silero VAD fails to load** — The program auto-downloads the real model file from GitHub on startup (the .jit in the GitHub zipball is just an LFS pointer). If it still fails, `raw.githubusercontent.com` is unreachable — switch to FSMN VAD in settings.

**pip install timeouts / slow** — `install.py` benchmarks official PyPI, Tsinghua, Aliyun, Tencent, and USTC mirrors (~5s) and picks the fastest; or use `python install.py --index-url <mirror>` manually.

**Model download interrupted** — Re-run the corresponding download command from Quick Start; it resumes automatically, no need to clear cache.

**Error `No module named 'xxx'`** — Run `git pull` → `python install.py` → restart. If still missing, compare the verification list from `install.py` with `pip list`.

### Usage

**Speaker always shows Speaker0** — First check the logs for `[SPEAKER] ... load failed`: if present, the speaker model did not load — see the dependency issues above. Otherwise, voice samples must accumulate before speakers are distinguished; sentences with fewer than 3 Chinese characters inherit the previous sentence's speaker.

**CPU mode is slow** — Optimized: automatic batch transcription for local mode (measured ~6x speedup), adaptive partial throttling and speaker detection cooldown in realtime mode, physical-core thread count for torch. An NVIDIA GPU is still recommended for best performance.

**OBS subtitles not working** — You must use the "with config" URL (with `#` suffix) generated by the settings page, see [docs/OBS_SUBTITLE.md](docs/OBS_SUBTITLE.md).

### Troubleshooting with AI tools (recommended)

When you hit an error, hand it to an AI assistant (opencode, Claude, ChatGPT, etc.) instead of searching the web:

1. **Paste the full log** — the complete log (including `[SPEAKER]`, `[LOAD]`, and `Traceback` lines), not just the last line
2. **Include environment info** — `python --version` and `pip list` (or the verification list from `python install.py`)
3. **Describe how to reproduce** — what triggered it (starting app.py / local mode / realtime mode)
4. This project's previously fixed environment issues (modelscope hidden dependencies, Silero LFS pointers, etc.) can all be diagnosed with this same workflow

## License

[MIT License](LICENSE), free for commercial use. Third-party dependency and model license details: [docs/LICENSE_DETAILS.md](docs/LICENSE_DETAILS.md).
