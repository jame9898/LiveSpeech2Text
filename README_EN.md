# LiveSpeech2Text — Real-time Speech Recognition

A Chinese real-time speech recognition tool based on **Qwen3-ASR**. Audio is captured via browser (Chrome tab or full-screen sharing), sent to a local server via WebSocket for VAD segmentation, ASR recognition, and speaker diarization. Results are streamed back to the frontend (**pseudo-streaming**). Includes a PySide6 desktop panel and a Tampermonkey userscript.

---

## System Requirements

Developed and tested on Windows 11. Other systems are not verified.

| Item | Requirement |
|---|---|
| OS | Windows 11 64-bit |
| Python | 3.10 ~ 3.12 |
| RAM | 8 GB+ (1.7B model requires 6GB+) |
| Disk | ~6 GB (including model downloads) |
| GPU | CPU works; GPU acceleration requires NVIDIA + CUDA |

---

## Quick Start

```bash
# 1. Clone the repository (GitHub or Gitee, choose one)
git clone https://github.com/jame9898/LiveSpeech2Text
# or Gitee mirror
git clone https://gitee.com/linhanduzikai/LiveSpeech2Text
cd LiveSpeech2Text

# 2. Create a virtual environment (recommended)
python -m venv venv
venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt          # CPU environment
# or
pip install -r requirements-gpu.txt      # GPU + CUDA environment

# 4. Download a model (choose one, auto-saved to models/)
# Qwen3-ASR 0.6B — lightweight, runs on CPU
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-0.6B', cache_dir='models')"
# Qwen3-ASR 1.7B — higher accuracy, requires GPU and more memory
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-1.7B', cache_dir='models')"

# 5. Download the speaker recognition model CAM++ (~27MB)
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/speech_campplus_sv_zh-cn_16k-common', cache_dir='models')"

# 6. Launch the desktop panel
python app.py
```

> **About Virtual Environments**: Step 2 is optional. If you skip it, dependencies are installed in the system Python — just double-click `start.bat` or run `python app.py` to launch.
>
> If you created a virtual environment in Step 2 (dependencies installed in venv), you must activate it before each launch:
> ```bash
> cd LiveSpeech2Text
> venv\Scripts\activate
> python app.py
> ```

Update an existing local repository:
```bash
git pull
```

---

## Usage

The desktop panel (`python app.py`) provides three recognition modes, switchable via radio buttons at the top:

### Audience Mode (Default)

Recognizes audio played by web pages (Bilibili/Douyu live streams or videos).

1. Double-click `start.bat` or run `python app.py`
2. Select "Audience Mode", click "Start Service"
3. Open `http://localhost:8765` in your browser, or install the Tampermonkey script for auto-injection
4. Click "Tab Capture" or "Full Screen" to start capturing
5. Recognition results are displayed in real-time in the subtitle area

### Streamer Mode

Captures local microphone audio (solo streaming, voice-over, etc.).

1. Select "Streamer Mode", choose a microphone device from the dropdown (auto-detects local input devices)
2. Optional: In the "Speaker" dropdown, select Speaker0, enter a name and press Enter to rename
3. Click "Start Service" — microphone capture starts automatically once the service is ready
4. Real-time subtitles appear in the scrolling area on the right; the bottom "Subtitle Page" and "Settings Page" rows show their respective URLs (with copy buttons) — placeholder text when not running, real addresses when running
5. Click "Test Microphone" to capture 5 seconds and verify recognition; afterwards you can "Export" the subtitle text

### OBS Browser Source Configuration (Live Subtitles)

The subtitle bar is integrated via OBS Browser Source, with a transparent background overlaid on the video. It can be dragged and resized. This is the mainstream solution for live subtitles — cleaner than window capture (no black background, no window borders, freely scalable).

#### Setup Steps

1. Open the desktop panel, select "Streamer Mode", click "Start Service"
2. Copy the "Subtitle Page" URL from the desktop panel and open it in a browser to preview subtitles (`http://localhost:8765/subtitle`)
3. Copy the "Settings Page" URL from the desktop panel and open it in a browser to enter the subtitle settings panel (`http://localhost:8765/subtitle?settings=1`)
4. (Optional) Adjust subtitle styles on the settings page — see the table below for configurable options. Skip to use defaults
5. Copy the **"OBS Browser Source URL (with config)"** at the bottom of the settings page (this URL encodes all current settings into the URL)
6. Open OBS → "Sources" panel, click **＋** → select **Browser** → paste the URL from the previous step → set custom width/height (e.g. 800×120) → check "Refresh browser when scene becomes active" → OK
7. The source can be freely dragged and resized on the OBS canvas; transparent background, only subtitle text is shown

> Key: The URL pasted into OBS must be the "with config" URL generated by the settings page (with a `#` suffix), not the bare address. See the explanation below.

#### Configurable Options

All subtitle styles are adjusted on the web settings page, not in the desktop client:

| Option | Description |
|---|---|
| Current subtitle font size | Slider (16–72px) |
| History font size | Slider (12–48px) |
| History line count | 0–5 lines (0 = show only current line) |
| Subtitle bar background | Enable/disable, color, opacity (disabled = transparent, recommended for OBS) |
| Force text color | All subtitles use this color uniformly |
| Show speaker | When enabled, shows Speaker ID before subtitle text |
| AI badge | Show toggle + scale ratio (badge font size = body font size × ratio, default 35%) |

#### Why the URL Must Include Configuration

The OBS URL generated by the settings page looks like this:

```
http://localhost:8765/subtitle#bar=36&hist=20&histCount=3&bg=0&color=%23ffffff&badge=1&badgeScale=0.35&...
```

The string after `#` is the encoded form of all current settings. **OBS's built-in browser and your system browser have isolated localStorage** — opening the bare URL `http://localhost:8765/subtitle` directly in OBS will not read the settings you configured in Chrome. Therefore, you must use the "with config" URL generated by the settings page in OBS for the configuration to take effect.

Each time you modify settings on the settings page, the URL updates automatically — you need to re-paste it in the OBS browser source properties.

#### Speaker Name Sync

Custom speaker names (e.g. renaming Speaker0 to "Host") are set in the desktop client. The server broadcasts these to all connected clients (including the OBS subtitle page) for real-time synchronization.

### Meeting Mode

Captures both microphone and system audio simultaneously (remote meetings, two-way conversations, etc.).

1. Select "Meeting Mode", choose microphone (local speaker) and system audio (remote participant, requires virtual sound card) separately
2. Speaker naming, subtitle bar, test, and export functions work the same as Streamer Mode
3. When the server detects a new speaker (e.g. Speaker1), the dropdown automatically adds the item for naming

### Tampermonkey Userscript (Audience Mode Enhancement)

1. Install the [Tampermonkey](https://www.tampermonkey.net/) browser extension
2. Import the `asr_panel.user.js` script
3. Open a video/live stream page — the panel appears automatically on the right
4. Panel can be dragged, minimized, and a floating subtitle bar can be enabled

> Currently supported platforms: Bilibili, Douyu

### Technical Notes on Recognition Modes

All three modes share the same WebSocket connection (`ws://localhost:8765`), handled uniformly by the server:

- **Audience Mode**: Browser `getDisplayMedia` captures tab/full-screen audio, pushed via Tampermonkey script or web frontend
- **Streamer/Meeting Mode**: Local `sounddevice` captures microphone (48kHz/mono/float32), forwarded by the desktop panel's built-in WS client

Streaming recognition latency is approximately 0.8s. The server skips VAD segmentation during silence and waits for the next valid speech segment.

---

## Available Models

| Model | Size | Purpose | Download Command (ModelScope ID) |
|---|---|---|---|
| Qwen3-ASR 0.6B | ~2.0 GB | Speech recognition, runs on CPU | `Qwen/Qwen3-ASR-0.6B` |
| Qwen3-ASR 1.7B | ~4.4 GB | Speech recognition, highest accuracy, GPU recommended | `Qwen/Qwen3-ASR-1.7B` |
| CAM++ | ~27 MB | Speaker voiceprint recognition | `iic/speech_campplus_sv_zh-cn_16k-common` |
| FSMN-VAD | ~4 MB | Voice activity detection (auto-loaded with modelscope) | `iic/speech_fsmn_vad_zh-cn-16k-common-pytorch` |

---

## Keyword Management

The system supports manual keyword addition for marking important terms in recognition content:

| Feature | Description |
|---|---|
| Keyword tagging | User enters keyword → auto-categorization (speaker/keyword) → pinyin matching for homophone correction → highlighted in recognition results |

## Project Structure

```
LiveSpeech2Text/
├── app.py                 # PySide6 desktop GUI (mode switching/start-stop/subtitle display/log/system tray)
├── realtime_panel.py      # Realtime panel components (subtitle view/mic capture thread/WS client)
├── server.py              # WebSocket server (audio receive/VAD scheduling/transcription/speaker diarization/report/web)
├── core.py                # ASR engine and model loading (Qwen3-ASR)
├── vad_processor.py       # Adaptive VAD voice activity detection (silence segmentation/forced cut/music noise detection)
├── speaker_manager.py     # CAM++ speaker management (voiceprint detection/cold-start 3-level confirmation/soft update/quality assessment)
├── pinyin_utils.py        # Keyword management + text similarity matching
├── creator_detector.py    # Creator detector (extracts UP/streamer names from Bilibili/Douyu URLs)
├── report_generator.py    # Report and log generation (Markdown report + structured JSON log)
├── text_utils.py          # Text processing utilities (dedup/formatting)
├── settings_dialog.py     # PySide6 settings dialog (model/device/VAD/port config)
├── batch_transcribe.py    # Batch audio transcription script (reuses VAD/ASR/speaker/report pipeline)
├── asr_panel.user.js      # Tampermonkey userscript (multi-platform in-page panel + subtitle bar)
├── __init__.py            # Package exports
├── requirements.txt       # Python dependencies (CPU)
├── requirements-gpu.txt   # Python dependencies (GPU + CUDA)
├── start.bat              # One-click launcher
├── .gitignore
├── LICENSE
├── dict/
│   └── asr_config.json    # ASR runtime config (model/device/VAD params)
└── static/
    ├── index.html         # Control panel homepage
    └── subtitle.html      # OBS browser source subtitle page (transparent background)
```

---

## FAQ

**Model loading failed**
Check if the corresponding model folder exists in the `models/` directory. If not, download it using the command from "Quick Start" above.

**CPU mode is slow**
If you have an NVIDIA GPU, switching to 1.7B + CUDA can significantly speed up recognition.

**Speaker always shows Speaker0**
A certain amount of voice samples must be accumulated before different speakers can be distinguished. Additionally, short sentences with fewer than 3 Chinese characters automatically inherit the previous sentence's speaker label.

---

## Uninstall

This project is not packaged as an installer. Simply delete the project folder:

```bash
# Delete the project folder
Remove-Item -Recurse -Force "C:\path\to\LiveSpeech2Text"

# Delete ModelScope cached models (optional)
Remove-Item -Recurse -Force "$env:USERPROFILE\.cache\modelscope"
```

Tampermonkey plugin: Delete the `LiveSpeech2Text V1.0` script in the browser's Tampermonkey management panel.

---

## License

[MIT License](LICENSE)
