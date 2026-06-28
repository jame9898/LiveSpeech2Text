# LiveSpeech2Text — 在线实时语音识别

基于 **Qwen3-ASR-hf**（HuggingFace Transformers 原生版）的中文实时语音识别工具。浏览器采集音频（Chrome 标签页或全屏共享），经 WebSocket 送到本地服务端做 VAD 断句、ASR 识别、说话人分离，识别结果（通过**伪流式**传输）回传前端展示。带 PySide6 桌面管理面板和 Tampermonkey 油猴插件。

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
git clone https://github.com/jame9898/LiveSpeech2Text/tree/hf
# 或 Gitee 镜像
git clone https://gitee.com/linhanduzikai/LiveSpeech2Text
cd LiveSpeech2Text

# 2. 创建虚拟环境（推荐）
python -m venv venv
venv\Scripts\activate

# 3. 安装依赖（必须用 venv 的 pip）
# 注意：本版依赖源码版 transformers（Qwen3-ASR 的 qwen3_asr 架构
# 尚未进入正式 release）。requirements 已配置为 git 安装，
# 若 git clone 失败，见文末「常见问题」的离线安装方法。
pip install -r requirements.txt          # CPU 环境
# 或
pip install -r requirements-gpu.txt      # GPU + CUDA 环境

# 4. 下载模型（HF 原生版，根据需求选一个）
# 已内置 HF_ENDPOINT=hf-mirror 镜像加速，首次运行会自动下载到 HF 缓存。
# 手动预下载（需在 venv 下执行）：
# Qwen3-ASR 0.6B-hf — 轻量，CPU 能跑
venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-0.6B-hf')"
# Qwen3-ASR 1.7B-hf — 精度更高，需 GPU 和更多内存
venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-1.7B-hf')"

# 5.（可选）下载说话人识别模型 CAM++，约 27MB
venv\Scripts\python.exe -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/speech_campplus_sv_zh-cn_16k-common', cache_dir='models')"

# 6. 启动桌面面板（用 venv 的 python；或直接双击 start.bat）
venv\Scripts\python.exe app.py
```

更新已有本地仓库：
```bash
git pull
```

---

## 使用方式

### 方式一：网页控制端（无需安装插件）

1. 双击 `start.bat` 或在终端运行 `python app.py`
2. 在 GUI 面板点击「启动服务」，等待日志显示 "Service ready"
3. 浏览器打开 `http://localhost:8765`
4. 填写视频/直播页面 URL（选填，用于自动识别主播）和 UP 主名（可选）
5. 点击「▶ 标签页」（仅捕获浏览器标签页音频）或「▶ 全屏」（捕获系统全部音频）
6. 识别结果实时显示，统计栏显示累计时长、句数和字数

### 方式二：Tampermonkey 油猴插件（自动注入视频页面）

1. 确保服务端已启动（`python app.py` → 启动服务）
2. 安装 [Tampermonkey](https://www.tampermonkey.net/) 浏览器扩展
3. 导入 `asr_panel.user.js` 脚本
4. 打开视频/直播页面，面板自动出现在右侧
5. 可拖拽面板、可最小化、可开启浮动字幕条

> 插件目前适配平台：B站(bilibili)、斗鱼(douyu)

### 识别模式

两种录音模式共用同一条 WebSocket 连接，服务端统一处理：

- **标签页模式**：`getDisplayMedia({preferCurrentTab:true})`，只捕获浏览器当前标签页的音频
- **全屏模式**：`getDisplayMedia({audio:true,video:true})`，捕获整个屏幕/窗口的音频

流式识别延迟约 0.8s，服务端在静音间隙跳过 VAD 切分、等待下一段有效语音。

---

## 可用模型

| 模型 | 大小 | 用途 | 下载命令（HuggingFace ID） |
|---|---|---|---|
| Qwen3-ASR 0.6B-hf | ~2.0 GB | 语音识别，CPU 能跑 | `Qwen/Qwen3-ASR-0.6B-hf` |
| Qwen3-ASR 1.7B-hf | ~4.4 GB | 语音识别，精度最高，建议 GPU | `Qwen/Qwen3-ASR-1.7B-hf` |
| CAM++ | ~27 MB | 说话人声纹识别 | `iic/speech_campplus_sv_zh-cn_16k-common` |

---

## 关键词管理

系统支持手动添加关键词，用于标记识别内容中的重要术语：

| 功能 | 说明 |
|---|---|
| 关键词标记 | 用户输入关键词 → 自动归类（主讲人/关键词）→ 拼音匹配纠正同音错误 → 在识别结果中标记显示 |

## 项目结构

```
在线实时语音识别/
├── app.py                 # PySide6 桌面 GUI（启动/停止/设置/日志/系统托盘）
├── server.py              # WebSocket 服务端（音频接收/VAD调度/转录/关键词纠正/报告/网页渲染）
├── core.py                # ASR 引擎和模型加载（Qwen3-ASR）
├── vad_processor.py       # 自适应能量阈值 VAD（语速感知静音断句/强制切分/三级兜底）
├── speaker_manager.py     # CAM++ 说话人管理（声纹检测/冷启动三级确认/灰色软更新/质量评估）
├── pinyin_utils.py        # 关键词管理 + 文本相似度比对
├── creator_detector.py    # 创作者识别器（从 B站/斗鱼 URL 提取 UP 主/主播名）
├── report_generator.py    # 报告与日志生成（Markdown 报告 + 结构化 JSON 日志）
├── text_utils.py          # 文本处理工具（去重/格式化）
├── settings_dialog.py     # PySide6 设置对话框（模型/设备/VAD/端口配置）
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
检查以下位置是否有对应的 `-hf` 模型文件夹：
- 项目内 `models/Qwen3-ASR-1.7B-hf/`（需含 `config.json`、`model.safetensors` 等）
- HF 缓存 `~/.cache/huggingface/hub/models--Qwen--Qwen3-ASR-1.7B-hf/`
没有则按上面「快速开始」中的命令下载。注意：浏览器下载的文件若被加了 `_` 后缀
（如 `config.json_`），需重命名去掉后缀，否则加载会报错。

**CPU 模式识别慢**
如有 NVIDIA GPU，在「设置」里设备选 cuda，并选用 Qwen3-ASR 1.7B-hf 可大幅提速。

**说话人一直显示 Speaker0**
需积累一定量的语音样本后才会开始区分不同说话人。此外，少于 3 个中文字的短句会自动继承前一句的说话人标签。

**transformers 源码版 git 安装失败（国内 git clone 超时）**
改用 zip 包离线安装：
```powershell
# 下载 main 分支 zip
python -c "import urllib.request; urllib.request.urlretrieve('https://codeload.github.com/huggingface/transformers/zip/refs/heads/main','transformers-main.zip')"
# 解压后本地安装
Expand-Archive transformers-main.zip
venv\Scripts\pip install .\transformers-main\transformers-main
# 清理
Remove-Item transformers-main.zip, transformers-main -Recurse
```

---

## 卸载

本项目未打包为安装程序，直接删除项目文件夹即可：

```bash
# 删除项目文件夹
Remove-Item -Recurse -Force "C:\path\to\LiveSpeech2Text"

# 删除 ModelScope 自动缓存的模型（可选）
Remove-Item -Recurse -Force "$env:USERPROFILE\.cache\modelscope"
Remove-Item -Recurse -Force "$env:USERPROFILE\.cache\huggingface"  # HF 版 ASR 模型缓存
```

Tampermonkey 插件：在浏览器 Tampermonkey 管理面板中删除 `LiveSpeech2Text V1.0` 脚本。

---

## 许可证

[MIT License](LICENSE)
