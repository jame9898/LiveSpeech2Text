# LiveSpeech2Text — 在线实时语音识别

基于 **Qwen3-ASR** 的中文实时语音识别工具。浏览器采集音频（Chrome 标签页或全屏共享），经 WebSocket 送到本地服务端做 VAD 断句、ASR 识别、说话人分离，识别结果（通过**伪流式**传输）回传前端展示。带 PySide6 桌面管理面板和 Tampermonkey 油猴插件。

---

## 系统要求

项目在 Windows 11 下开发测试，其他系统未验证。

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 11 64-bit |
| Python | 3.10 ~ 3.12 |
| 内存 | 8 GB 以上（1.7B 模型需 6GB+） |
| 硬盘 | 约 6 GB（含模型下载） |
| 显卡 | CPU 可用；GPU 加速需 NVIDIA + CUDA |

---

## 快速开始

```bash
# 1. 克隆仓库（GitHub 或 Gitee，二选一）
git clone https://github.com/jame9898/LiveSpeech2Text
# 或 Gitee 镜像
git clone https://gitee.com/linhanduzikai/LiveSpeech2Text
cd LiveSpeech2Text

# 2. 创建虚拟环境（推荐）
python -m venv venv
venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt          # CPU 环境
# 或
pip install -r requirements-gpu.txt      # GPU + CUDA 环境

# 4. 下载模型（根据需求选一个，自动保存到 models/）
# Qwen3-ASR 0.6B — 轻量，CPU 能跑
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-0.6B', cache_dir='models')"
# Qwen3-ASR 1.7B — 精度更高，需 GPU 和更多内存
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-1.7B', cache_dir='models')"

# 5.（可选）下载说话人识别模型 CAM++，约 27MB
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/speech_campplus_sv_zh-cn_16k-common', cache_dir='models')"

# 6. 启动桌面面板
python app.py
```

更新已有本地仓库：
```bash
git pull
```

---

## 使用方式

桌面面板（`python app.py`）提供三种识别模式，顶部单选切换：

### 观众模式（默认）

识别网页播放的声音（B站/斗鱼等直播或视频）。

1. 双击 `start.bat` 或运行 `python app.py`
2. 选择「观众模式」，点击「启动服务」
3. 浏览器打开 `http://localhost:8765`，或安装油猴脚本自动注入页面
4. 点击「▶ 标签页」或「▶ 全屏」开始捕获
5. 识别结果实时显示在字幕展示区

### 主播模式

拾取本地麦克风声音（单人直播、配音等）。

1. 选择「主播模式」，下拉框选择麦克风设备（自动检测本地输入设备）
2. 可选：在「说话人」下拉框选择 Speaker0，输入名字并回车命名
3. 点击「启动服务」，服务就绪后自动开始采集麦克风音频
4. 实时字幕展示在右侧滚动区，同时可开启独立字幕条悬浮窗（可被 OBS 捕获）
5. 字幕条支持拖拽移动、滚轮调字号、右下角拖拽调整大小、双击切换宽窄
6. 可点击「测试麦克风」采集 5 秒验证识别是否正常，结束后可「导出」字幕文本

### 会议模式

同时拾取麦克风和系统音频（远程会议、双人对话等）。

1. 选择「会议模式」，分别选择麦克风（本地说话人）和系统音频（远端参会者，需虚拟声卡）
2. 说话人命名、字幕条、测试、导出功能同主播模式
3. 当服务端检测到新说话人（如 Speaker1）时，下拉框自动新增该项，可选择后命名

### Tampermonkey 油猴插件（观众模式增强）

1. 安装 [Tampermonkey](https://www.tampermonkey.net/) 浏览器扩展
2. 导入 `asr_panel.user.js` 脚本
3. 打开视频/直播页面，面板自动出现在右侧
4. 可拖拽面板、可最小化、可开启浮动字幕条

> 插件目前适配平台：B站(bilibili)、斗鱼(douyu)

### 识别模式技术说明

三种模式共用同一条 WebSocket 连接（`ws://localhost:8765`），服务端统一处理：

- **观众模式**：浏览器 `getDisplayMedia` 捕获标签页/全屏音频，通过油猴脚本或网页前端推送
- **主播/会议模式**：本地 `sounddevice` 采集麦克风（48kHz/mono/float32），桌面面板内置 WS 客户端转发

流式识别延迟约 0.8s，服务端在静音间隙跳过 VAD 切分、等待下一段有效语音。

---

## 可用模型

| 模型 | 大小 | 用途 | 下载命令（ModelScope ID） |
|---|---|---|---|
| Qwen3-ASR 0.6B | ~2.0 GB | 语音识别，CPU 能跑 | `Qwen/Qwen3-ASR-0.6B` |
| Qwen3-ASR 1.7B | ~4.4 GB | 语音识别，精度最高，建议 GPU | `Qwen/Qwen3-ASR-1.7B` |
| CAM++ | ~27 MB | 说话人声纹识别 | `iic/speech_campplus_sv_zh-cn_16k-common` |
| FSMN-VAD | ~4 MB | 语音活动检测（自动随 modelscope 加载） | `iic/speech_fsmn_vad_zh-cn-16k-common-pytorch` |

---

## 关键词管理

系统支持手动添加关键词，用于标记识别内容中的重要术语：

| 功能 | 说明 |
|---|---|
| 关键词标记 | 用户输入关键词 → 自动归类（主讲人/关键词）→ 拼音匹配纠正同音错误 → 在识别结果中标记显示 |

## 项目结构

```
在线实时语音识别/
├── app.py                 # PySide6 桌面 GUI（三模式切换/启动停止/字幕展示/日志/系统托盘）
├── realtime_panel.py      # 实时面板组件（字幕条悬浮窗/字幕展示区/麦克风采集线程/WS客户端）
├── server.py              # WebSocket 服务端（音频接收/VAD调度/转录/说话人分离/报告/网页渲染）
├── core.py                # ASR 引擎和模型加载（Qwen3-ASR）
├── vad_processor.py       # 自适应 VAD 语音活动检测（静音断句/强制切分/音乐噪声检测）
├── speaker_manager.py     # CAM++ 说话人管理（声纹检测/冷启动三级确认/灰色软更新/质量评估）
├── pinyin_utils.py        # 关键词管理 + 文本相似度比对
├── creator_detector.py    # 创作者识别器（从 B站/斗鱼 URL 提取 UP 主/主播名）
├── report_generator.py    # 报告与日志生成（Markdown 报告 + 结构化 JSON 日志）
├── text_utils.py          # 文本处理工具（去重/格式化）
├── settings_dialog.py     # PySide6 设置对话框（模型/设备/VAD/端口配置）
├── batch_transcribe.py    # 批量音频转录脚本（复用 VAD/ASR/说话人/报告管线）
├── make_upload_zip.py     # 打包上传 ZIP 脚本（排除大文件/缓存/敏感数据）
├── asr_panel.user.js      # Tampermonkey 用户脚本（多平台视频页面内嵌面板+字幕条）
├── __init__.py            # 包导出
├── requirements.txt       # Python 依赖 (CPU)
├── requirements-gpu.txt   # Python 依赖 (GPU + CUDA)
├── start.bat              # 一键启动
├── .gitignore
├── LICENSE
├── dict/
│   └── asr_config.json    # ASR 运行时配置（模型/设备/VAD参数）
└── static/
    └── index.html         # 网页前端
```

---

## 常见问题

**模型加载失败**
检查 `models/` 目录下是否有对应的模型文件夹。没有则按上面「快速开始」中的命令下载。

**CPU 模式识别慢**
如有 NVIDIA GPU，改用 1.7B + CUDA 可大幅提速。

**说话人一直显示 Speaker0**
需积累一定量的语音样本后才会开始区分不同说话人。此外，少于 3 个中文字的短句会自动继承前一句的说话人标签。

---

## 卸载

本项目未打包为安装程序，直接删除项目文件夹即可：

```bash
# 删除项目文件夹
Remove-Item -Recurse -Force "C:\path\to\LiveSpeech2Text"

# 删除 ModelScope 自动缓存的模型（可选）
Remove-Item -Recurse -Force "$env:USERPROFILE\.cache\modelscope"
```

Tampermonkey 插件：在浏览器 Tampermonkey 管理面板中删除 `LiveSpeech2Text V1.0` 脚本。

---

## 许可证

[MIT License](LICENSE)
