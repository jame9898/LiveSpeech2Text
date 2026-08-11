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
| Python | 3.10 ~ 3.12（推荐 3.12.x） |
| 内存 | 8 GB 以上（1.7B 模型需 6GB+） |
| 文件占用空间 | 约 6 GB（含模型下载） |
| 显卡 | CPU 可用；GPU 加速需 NVIDIA + CUDA |

## 开发测试环境

项目依赖版本均已锁定为下列开发环境实测通过的组合（见 `requirements.txt` / `requirements-gpu.txt`），请尽量对齐，避免版本漂移导致不可复现的问题：

| 项目 | 开发机实际配置 |
|---|---|
| 操作系统 | Windows 11 64-bit |
| Python | 3.12.8 |
| 显卡 | NVIDIA GeForce RTX 4070 SUPER（12 GB，驱动 610.74，算力 8.9） |
| CUDA | 12.6（cu126 轮子） |
| torch / torchaudio / torchvision | 2.12.0+cu126 / 2.11.0+cu126 / 0.27.0+cu126 |
| modelscope | 1.37.1 |
| funasr | 1.3.0 |
| qwen-asr | 0.0.6 |
| datasets / addict | 4.8.5 / 2.4.0 |
| PySide6 | 6.11.1 |

> CPU 版开发机：相同版本组合，仅 torch 三件套为 CPU 轮子（`torch==2.12.0`、`torchaudio==2.11.0`、`torchvision==0.27.0`，无 `+cu126` 后缀）。

## 快速开始

```bash
# 1. 克隆仓库（GitHub 或 Gitee）
git clone https://github.com/jame9898/LiveSpeech2Text
# 或 Gitee 镜像
git clone https://gitee.com/linhanduzikai/LiveSpeech2Text

# 2. 进入文件夹
cd LiveSpeech2Text

# 3. 虚拟环境（建议使用；如使用系统环境，可跳过这一步）
python -m venv venv 
venv\Scripts\activate

# 4. 安装依赖（自动测速选择最快镜像源，CPU 专用）
python install.py
# 或（GPU + CUDA 专用）
python install.py --gpu
# 或手动指定镜像源（跳过自动测速）：
# python install.py --index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 5. 下载模型（自动保存到 models/）
# qwen3-ASR模型 下载平台：魔搭 ModelScope 
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-0.6B', cache_dir='models')"
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-1.7B', cache_dir='models')"

# qwen3-ASR模型 下载平台：Hugging Face（目录名与项目约定一致，下载后程序可自动发现）
python -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-0.6B', local_dir='models/hub/models/Qwen/Qwen3-ASR-0___6B')"
python -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-1.7B', local_dir='models/hub/models/Qwen/Qwen3-ASR-1___7B')"
# 模型页面：https://huggingface.co/Qwen/Qwen3-ASR-0.6B | https://huggingface.co/Qwen/Qwen3-ASR-1.7B

# 说话人模型（可选，在设置中选择使用；CAM++ 为默认，ERes2NetV2 精度更高，ERes2Net base 为 3D-Speaker 版本）：
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/speech_campplus_sv_zh-cn_16k-common', cache_dir='models')"
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/speech_eres2netv2_sv_zh-cn_16k-common', cache_dir='models')"
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/speech_eres2net_base_sv_zh-cn_3dspeaker_16k', cache_dir='models')"

# FireRedVAD（可选，设置中选择使用；DFSMN 多语言 SOTA，FLEURS-102 F1 97.57 vs Silero 95.95，误报率低约 3.5 倍，约 7MB）：
# 下载后把 models/xukaituo/FireRedVAD 复制为 models/firered-vad（含 VAD/Stream-VAD/AED 三个子目录）
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('xukaituo/FireRedVAD', cache_dir='models')"

# 6. 启动桌面面板
python app.py
```

> 也可以双击 `start.vbs`（无命令行窗口启动，优先使用项目虚拟环境，其次系统 Python 环境）。

**安装慢或超时？** `install.py` 会自动对官方 PyPI、清华、阿里云、腾讯云、中科大镜像测速（约 5 秒），选择最快的源下载，国内外网络均可自适应；国内用户通常会命中阿里云/清华镜像。也可直接使用原始方式 `pip install -r requirements.txt`（需自行配置国内镜像，否则可能因访问 PyPI 官方源过慢而超时）。

**更新代码**：`git pull` 后依赖可能变化，需重新安装：

```bash
git pull
python -m venv venv # 虚拟环境下（非虚拟环境可跳过）
venv\Scripts\activate  # 虚拟环境下（非虚拟环境可跳过）
python install.py   # CPU 专用
python install.py --gpu # GPU + CUDA 专用  
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

### 环境与依赖

**`python install.py` 后说话人模型（CAM++/ERes2Net）加载失败** — 多为 modelscope 的隐藏依赖缺失。本项目已把实测确认的硬依赖全部锁定进 `requirements.txt`（含 addict / datasets / torchvision / simplejson / sortedcontainers 等）。`git pull` 后**必须重新运行 `python install.py`**；`install.py` 结尾会打印核心包验证清单，可对照 `pip list` 排查是否漏装。

**Silero VAD 加载失败** — 程序启动时会自动从 GitHub 直下真实模型文件修复（GitHub zipball 里的 .jit 只是 LFS 指针）；仍失败说明无法访问 `raw.githubusercontent.com`，可在设置中切换 FSMN VAD。

**pip 安装超时/慢** — `install.py` 会自动对官方 PyPI、清华、阿里云、腾讯云、中科大镜像测速（约 5 秒）并选用最快源；也可 `python install.py --index-url <镜像地址>` 手动指定。

**模型下载中断** — 重跑「快速开始」中对应的下载命令即可断点续传，无需删缓存。

**报错 `No module named 'xxx'`** — 依次执行 `git pull` → `python install.py` → 重启；若仍缺失，对照 `install.py` 的验证清单与 `pip list` 找出差异。

### 使用问题

**说话人一直显示 Speaker0** — 先在日志里找 `[SPEAKER] ... load failed`：有则说明说话人模型未加载，按上方依赖问题处理；无则需积累一定语音样本后才区分说话人，少于 3 个中文字的短句自动继承上一句说话人。

**CPU 模式识别慢** — 已优化：本地批处理自动批量转录（实测约 6 倍提速）、实时模式 partial 自适应节流、说话人检测冷却、torch 物理核线程。追求最佳性能仍建议使用 NVIDIA GPU。

**OBS 字幕不生效** — 必须使用设置页生成的「已含配置」URL（带 `#` 后缀），见 [docs/OBS_SUBTITLE.md](docs/OBS_SUBTITLE.md)。

### 用 AI 工具排查故障（推荐）

遇到报错时，建议直接交给 AI 工具（opencode、Claude、ChatGPT 等）排查，比搜索引擎更快：

1. **贴全日志**：把完整日志（含 `[SPEAKER]`、`[LOAD]`、`Traceback` 行）复制给 AI，不要只贴最后一行
2. **附带环境信息**：`python --version` 与 `pip list`（或 `python install.py` 验证清单输出）
3. **说明复现步骤**：做什么操作触发的（启动 app.py / 本地模式 / 实时模式）
4. 本项目修复过的同类环境问题（modelscope 隐藏依赖、Silero LFS 指针等）均可直接套用此流程

## 许可证

[MIT License](LICENSE)，可商用。第三方依赖与模型许可证明细见 [docs/LICENSE_DETAILS.md](docs/LICENSE_DETAILS.md)。
