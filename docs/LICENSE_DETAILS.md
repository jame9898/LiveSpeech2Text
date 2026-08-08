# 第三方依赖与模型许可证

## Python 库

| 依赖 | 许可证 | 商用兼容性 | 说明 |
|------|--------|-----------|------|
| torch / torchaudio | BSD 3-Clause | 完全兼容 | 深度学习引擎 |
| qwen-asr | Apache 2.0 | 完全兼容 | Qwen3-ASR 模型推理 |
| funasr | MIT | 完全兼容 | FSMN VAD 引擎 |
| modelscope | Apache 2.0 | 完全兼容 | 模型下载 |
| transformers | Apache 2.0 | 完全兼容 | 模型加载 |
| accelerate | Apache 2.0 | 完全兼容 | 模型加速 |
| websockets | BSD 3-Clause | 完全兼容 | WebSocket 通信 |
| soundfile | BSD 3-Clause | 完全兼容 | 音频文件读写 |
| librosa | ISC | 完全兼容 | 音频处理 |
| sounddevice | MIT | 完全兼容 | 麦克风采集 |
| PyAudioWPatch | MIT | 完全兼容 | WASAPI 回环采集 |
| pypinyin | MIT | 完全兼容 | 拼音转换 |
| numpy | BSD 3-Clause | 完全兼容 | 科学计算 |
| scipy | BSD 3-Clause | 完全兼容 | 科学计算 |
| PySide6 | LGPL 3.0 | 兼容（动态链接） | GUI 框架，动态链接使用，LGPL 允许闭源软件动态链接 |
| ffmpeg | LGPL 2.1+ | 兼容（独立调用） | 视频音频提取，通过 subprocess 调用可执行文件，属独立程序调用 |

> **PySide6 使用说明**：本项目以动态链接方式（`import PySide6`）使用 PySide6，符合 LGPL 3.0 的动态链接豁免条款，不触发许可证传染。分发时需提供 PySide6 源码获取方式（可从 [官方仓库](https://code.qt.io/cgit/pyside/pyside-setup.git/) 获取）。
>
> **FFmpeg 使用说明**：本项目通过 `subprocess` 调用 ffmpeg 可执行文件，属于独立程序调用，不涉及动态/静态链接，LGPL 2.1+ 下完全合法。请勿使用 `--enable-gpl` 编译版本的 ffmpeg（会变为 GPL 许可证，触发传染）。推荐使用 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 提供的 LGPL 编译版本。

## 模型

| 模型 | 许可证 | 商用兼容性 | 说明 |
|------|--------|-----------|------|
| Qwen3-ASR (0.6B / 1.7B) | Apache 2.0 | 完全兼容 | 语音识别模型 |
| CAM++ | Apache 2.0 | 完全兼容 | 说话人声纹识别 |
| FSMN-VAD | Apache 2.0 | 完全兼容 | 语音活动检测 |
| Silero VAD | MIT | 完全兼容 | 语音活动检测 |

> 所有模型均采用宽松开源许可证，允许商业使用、修改和分发。
