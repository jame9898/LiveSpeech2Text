# LiveSpeech2Text — 在线实时语音识别

基于 **Qwen3-ASR** 的中文实时语音识别工具。浏览器/麦克风/系统音频采集 → WebSocket 送到本地服务端 → **VAD 断句 + ASR 识别 + 说话人分离** → 实时字幕与 Markdown 报告。带 PySide6 桌面面板和 Tampermonkey 油猴插件。

## 特性

- **四种模式**：观众（网页声音）、主播（麦克风）、会议（麦克风+系统音频）、本地（音视频文件批处理）
- **实时字幕**：字幕条实时预览（GPU 0.3s / CPU 自适应节流）+ VAD 段尾定稿，可接入 OBS 浏览器源
- **说话人分离**：CAM++ / ERes2NetV2 声纹识别，自动区分说话人
- **关键词纠错**：拼音匹配纠正 ASR 同音错误，可实时增删关键词

## 系统要求

项目在 Windows 11 下开发测试，其他系统未验证。

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 11 64-bit |
| Python | 3.10 ~ 3.12 |
| 内存 | 8 GB 以上（1.7B 模型需 6GB+） |
| 文件占用空间 | 约 6 GB（含模型下载） |
| 显卡 | CPU 可用；GPU 加速需 NVIDIA + CUDA |

## 快速开始

```bash
# 1. 克隆仓库（GitHub 或 Gitee，二选一）
git clone https://github.com/jame9898/LiveSpeech2Text
# 或 Gitee 镜像
git clone https://gitee.com/linhanduzikai/LiveSpeech2Text
cd LiveSpeech2Text

# 2. 安装依赖（CPU 专用）
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
# 或（GPU + CUDA 专用）
pip install -r requirements-gpu.txt

# 3. 下载模型（自动保存到 models/）
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-0.6B', cache_dir='models')"
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/speech_campplus_sv_zh-cn_16k-common', cache_dir='models')"

# 4. 启动桌面面板
python app.py
```

> 也可以双击 `start.bat`（使用系统 Python 环境）。1.7B 模型精度更高但需 GPU 和更多内存：`snapshot_download('Qwen/Qwen3-ASR-1.7B', cache_dir='models')`。

**更新代码**：`git pull` 后依赖可能变化，需重新安装：

```bash
git pull
pip install -r requirements.txt   # CPU 专用（GPU + CUDA 用 requirements-gpu.txt）
```

## 卸载

本项目未打包为安装程序，直接删除项目文件夹即可：

```bash
Remove-Item -Recurse -Force "C:\path\to\LiveSpeech2Text"
# 可选：清理 ModelScope 模型缓存
Remove-Item -Recurse -Force "$env:USERPROFILE\.cache\modelscope"
```

Tampermonkey 插件：在浏览器 Tampermonkey 管理面板中删除 `LiveSpeech2Text V1.0` 脚本。

## 使用

| 模式 | 用法 |
|---|---|
| **观众模式**（默认） | 启动服务 → 浏览器打开 `http://localhost:8765` → 点击「标签页/全屏」捕获网页声音（B站/斗鱼等） |
| **主播模式** | 选麦克风 → 启动服务自动采集。字幕页 `http://localhost:8765/subtitle` 可接 OBS |
| **会议模式** | 麦克风 + 系统音频双采集（WASAPI 回环 + 半双工防回声），适合双人对话 |
| **本地模式** | 选文件/文件夹 → 开始处理 → 为每个文件生成 Markdown 报告（需 ffmpeg 提取视频音频） |
| **油猴插件** | 导入 `asr_panel.user.js`，B站/斗鱼视频页面内嵌识别面板（适配：B站、斗鱼） |

## 文档

| 文档 | 内容 |
|---|---|
| [docs/OBS_SUBTITLE.md](docs/OBS_SUBTITLE.md) | OBS 字幕条接入、字幕样式配置 |
| [docs/VAD.md](docs/VAD.md) | VAD 引擎对比与参数说明 |
| [docs/DATASET.md](docs/DATASET.md) | 后训练数据集（组织/评分/人工修正流程） |
| [docs/LICENSE_DETAILS.md](docs/LICENSE_DETAILS.md) | 第三方依赖与模型许可证明细 |

## 项目结构

```
├── app.py                 # PySide6 桌面 GUI（四模式切换/启动停止/字幕/系统托盘）
├── server.py              # WebSocket 服务端（音频接收/VAD/转录/说话人分离/网页渲染）
├── core.py                # ASR 引擎与模型加载 + 配置管理
├── vad_processor.py       # VAD 引擎（能量/Silero 流式/FSMN 批处理）
├── local_processor.py     # 本地模式批量处理（ffmpeg+VAD+ASR+报告）
├── dataset_manager.py     # 后训练数据集管理器
├── realtime_panel.py      # 实时面板组件（字幕区/采集线程/WS客户端）
├── speaker_manager.py     # 说话人管理（声纹检测/命名/档案）
├── pinyin_utils.py        # 关键词管理 + 拼音纠错
├── report_generator.py    # Markdown 报告生成
├── batch_transcribe.py    # 命令行批量转录脚本
├── asr_panel.user.js      # 油猴插件
├── dict/                  # 运行时配置（asr_config.json）
└── static/                # 控制页 + OBS 字幕页
```

## 常见问题

**模型加载失败** — 检查 `models/` 目录，按「快速开始」第 3 步命令下载。

**CPU 模式识别慢** — 已优化：本地批处理自动批量转录（实测约 6 倍提速）、实时模式 partial 自适应节流、说话人检测冷却、torch 物理核线程。追求最佳性能仍建议使用 NVIDIA GPU。

**说话人一直显示 Speaker0** — 需积累一定语音样本后才会区分说话人；少于 3 个中文字的短句自动继承上一句说话人。

**OBS 字幕不生效** — 必须使用设置页生成的「已含配置」URL（带 `#` 后缀），见 [docs/OBS_SUBTITLE.md](docs/OBS_SUBTITLE.md)。

## 许可证

[MIT License](LICENSE)，可商用。第三方依赖与模型许可证明细见 [docs/LICENSE_DETAILS.md](docs/LICENSE_DETAILS.md)。
