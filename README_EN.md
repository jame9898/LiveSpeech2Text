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
cd LiveSpeech2Text

# 2. Install dependencies (CPU only)
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
# or (GPU + CUDA only)
pip install -r requirements-gpu.txt

# 3. Download models (auto-saved to models/)
# China: ModelScope
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-0.6B', cache_dir='models')"
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/speech_campplus_sv_zh-cn_16k-common', cache_dir='models')"
# 1.7B offers higher accuracy; requires a GPU and more RAM:
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-1.7B', cache_dir='models')"

# Overseas: Hugging Face (use project-compatible directory names, auto-discovered)
# python -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-0.6B', local_dir='models/hub/models/Qwen/Qwen3-ASR-0___6B')"
# python -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-1.7B', local_dir='models/hub/models/Qwen/Qwen3-ASR-1___7B')"
# Model pages: https://huggingface.co/Qwen/Qwen3-ASR-0.6B | https://huggingface.co/Qwen/Qwen3-ASR-1.7B

# 4. Launch the desktop panel
python app.py
```

> You can also double-click `start.bat` (uses system Python).

**Updating**: after `git pull`, dependencies may have changed — reinstall them:

```bash
git pull
pip install -r requirements.txt   # CPU only (GPU + CUDA: requirements-gpu.txt)
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

**Model loading failed** — Check the `models/` directory; download using the Quick Start step 3 commands.

**CPU mode is slow** — Optimized: automatic batch transcription for local mode (measured ~6x speedup), adaptive partial throttling and speaker detection cooldown in realtime mode, physical-core thread count for torch. An NVIDIA GPU is still recommended for best performance.

**Speaker always shows Speaker0** — Voice samples must accumulate before speakers are distinguished; sentences with fewer than 3 Chinese characters inherit the previous sentence's speaker.

**OBS subtitles not working** — You must use the "with config" URL (with `#` suffix) generated by the settings page, see [docs/OBS_SUBTITLE.md](docs/OBS_SUBTITLE.md).

## License

[MIT License](LICENSE), free for commercial use. Third-party dependency and model license details: [docs/LICENSE_DETAILS.md](docs/LICENSE_DETAILS.md).
