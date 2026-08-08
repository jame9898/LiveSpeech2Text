# LiveSpeech2Text — 在线实时语音识别

基于 **Qwen3-ASR** 的中文实时语音识别工具。浏览器采集音频（Chrome 标签页或全屏共享），经 WebSocket 送到本地服务端做 VAD 断句、ASR 识别、说话人分离，识别结果（通过**伪流式**传输）回传前端展示。带 PySide6 桌面管理面板和 Tampermonkey 油猴插件。

> **架构说明**：所有模式（观众模式、主播模式、会议模式、本地模式）统一采用**伪流式处理**。
> - Qwen3-ASR 模型本身基于 Transformers 架构，不支持真流式推理
> - 本项目通过 **VAD 分段 + 段级快速 partial + 段尾 final 修正** 实现伪流式效果
> - 实时在线模式（观众/主播/会议）：边采集边识别，段尾输出最终文本
> - 本地处理模式：批量读入文件后，按 VAD 段逐段识别，段尾输出最终文本
> - 不存在"整体一次 ASR"模式，因 Qwen3-ASR 单次输出受 `max_new_tokens` 限制，长音频无法一次输出完整文本

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

# 5. 下载说话人识别模型 CAM++，约 27MB
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/speech_campplus_sv_zh-cn_16k-common', cache_dir='models')"

# 6. 启动桌面面板
python app.py
```

> **关于虚拟环境**：第 2 步是可选的。不创建虚拟环境，依赖装在系统里，双击 `start.bat` 或运行 `python app.py` 即可启动。
>
> 如果第 2 步创建了虚拟环境（依赖装在 venv 里），每次启动前必须先激活虚拟环境：
> ```bash
> cd LiveSpeech2Text
> venv\Scripts\activate
> python app.py
> ```

更新已有本地仓库：
```bash
git pull
```

---

## 使用方式

桌面面板（`python app.py`）提供四种识别模式，顶部单选切换：

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
4. 实时字幕展示在右侧滚动区；底部「字幕页」「设置页」两栏会显示对应 URL（含复制按钮），未启动时显示提示文字，启动后显示真实地址
5. 可在字幕展示区点击「导出 MD 文档」保存字幕文本

### OBS 浏览器源配置（直播字幕）

字幕条通过 OBS 浏览器源（Browser Source）接入，透明背景叠加在画面上，可拖动、可缩放。这是直播字幕的主流方案，比窗口采集更干净（无黑底、无窗口边框、可任意缩放）。

#### 接入步骤

1. 打开桌面面板，选择「主播模式」，点击「启动服务」
2. 在桌面面板复制「字幕页」地址，浏览器打开可预览字幕效果（`http://localhost:8765/subtitle`）
3. 在桌面面板复制「设置页」地址，浏览器打开进入「字幕页设置」面板（`http://localhost:8765/subtitle?settings=1`）
4. （可选）在设置页调整字幕样式，可配置项见下表。不调整则使用默认配置
5. 复制设置页底部的 **「OBS 浏览器源地址（已含配置）」**（该地址已把当前所有配置编码进 URL）
6. 打开 OBS →「来源」面板点击 **＋** → 选择 **浏览器（Browser）** → URL 粘贴上一步复制的地址 → 宽高自定（如 800×120）→ 勾选「刷新浏览器激活时」→ 确定
7. 该源在 OBS 画布中可自由拖动、缩放；透明背景，只显示字幕文字

> 关键：粘贴到 OBS 的必须是设置页里生成的「已含配置」URL（带 `#` 后缀），不是裸地址。原因见下方说明。

#### 可配置项

所有字幕样式都在网页设置页调整，不在桌面客户端：

| 配置项 | 说明 |
|---|---|
| 当前字幕字号 | 滑块调整（16–72px） |
| 历史记录字号 | 滑块调整（12–48px） |
| 历史保留句数 | 0–5 句（0 = 只显示当前句） |
| 字幕条背景 | 启用/关闭、颜色、透明度（关闭=透明，OBS 推荐） |
| 强制文字颜色 | 所有字幕统一使用此颜色 |
| 显示讲话人 | 开启后字幕前显示 Speaker 编号 |
| AI 角标 | 显示开关 + 角标比例（角标字号 = 正文字号 × 比例，默认 35%） |

#### 为什么 URL 里要带配置

设置页生成的 OBS 地址长这样：

```
http://localhost:8765/subtitle#bar=36&hist=20&histCount=3&bg=0&color=%23ffffff&badge=1&badgeScale=0.35&...
```

`#` 后面的一串是当前所有配置项的编码。**OBS 内置的浏览器与系统浏览器的 localStorage 是隔离的**，直接在 OBS 里打开裸地址 `http://localhost:8765/subtitle` 不会读取到你在 Chrome 里设置的配置。所以必须用设置页生成的「已含配置」URL 填入 OBS，配置才会生效。

每次在设置页修改配置后，该地址会自动更新，需在 OBS 浏览器源属性里重新粘贴一次。

#### 说话人名字同步

说话人自定义名字（如把 Speaker0 改成「主持人」）在桌面客户端设置，服务端会广播给所有连接的客户端（含 OBS 字幕页），实时同步显示。

### 会议模式

同时拾取麦克风和系统音频（远程会议、双人对话等）。

1. 选择「会议模式」，分别选择麦克风（本地说话人）和系统音频（远端参会者）
2. 说话人命名、字幕条、测试、导出功能同主播模式
3. 当服务端检测到新说话人（如 Speaker1）时，下拉框自动新增该项，可选择后命名

#### 系统音频回环采集（WASAPI）

会议模式通过 WASAPI loopback 采集系统输出设备（喇叭）播放的音频，喇叭正常发声的同时拿到音频流，无需虚拟声卡。该功能依赖 `PyAudioWPatch`（已在 requirements 中）。

#### 半双工模式（避免回声重复）

会议模式采用半双工策略，解决麦克风采集到喇叭声音导致重复识别的问题：

- **远端说话时**（系统音频电平超过阈值）→ 麦克风自动静音
- **远端安静后** 300ms → 麦克风恢复

这样对方说话时不会被麦克风重复采集，但代价是双方不能同时说话（接话开头可能丢几个字）。如果双方都戴耳机使用，可以避免这个问题，但半双工作为默认保护仍然有效。

### 本地模式

伪流式处理本地视频/音频文件，提取语音内容并生成 Markdown 报告。适合从本地短视频、录音文件中提取文字内容。

> **处理方式**：与实时在线模式一致，采用**伪流式处理**——文件读入后按 VAD 分段，逐段做 ASR + 说话人分离，段尾输出最终文本。不提供"整体一次 ASR"模式（Qwen3-ASR 单次输出受 `max_new_tokens` 限制，长音频无法一次输出完整文本）。

1. 选择「本地模式」，在输入源区选择「选文件」或「选文件夹」（包含视频或音频文件）
2. 可选：修改「输出目录」（默认与输入文件夹相同，MD 报告输出到此目录）
3. 可选：勾选「同时存入后训练数据集」(需先在设置→后训练中启用)
4. 点击「启动服务」加载 ASR 模型（模型加载后按钮变为「运行中」）
5. 模型就绪后点击「开始处理」，系统会：
   - 自动遍历文件夹下所有视频/音频文件（含子目录）
   - 视频文件用 ffmpeg 提取音频为 16kHz mono wav
   - **伪流式处理**：VAD 切分 + 段级 ASR 识别 + 说话人分离
   - 为每个文件生成一份 Markdown 报告
6. 处理进度显示在进度条和控制台日志中
7. 处理完成后点击「停止服务」卸载模型并释放 GPU 显存

#### 支持的文件格式

| 类型 | 扩展名 |
|---|---|
| 视频 | .mp4 .mkv .avi .mov .flv .wmv .webm .m4v .ts .mpg .mpeg |
| 音频 | .wav .mp3 .flac .m4a .ogg .aac .wma .opus |

#### ffmpeg 配置

视频文件需要 ffmpeg 提取音频。ffmpeg 查找顺序：

1. 设置→本地模式→ffmpeg 路径 中指定的路径
2. 项目模型文件夹下的 ffmpeg（`models/ffmpeg/ffmpeg.exe`）
3. 系统 PATH 中的 ffmpeg
4. 项目根目录下的 `ffmpeg.exe`（Windows）

推荐将 ffmpeg.exe 放到 `models/ffmpeg/` 目录下，便于统一管理。未安装 ffmpeg 时，仅能处理音频文件，视频文件会被跳过并提示。

#### VAD 引擎

本地模式的 VAD 引擎和参数跟随「音频/VAD」选项卡的全局设置，不再独立配置。三种引擎说明见下方「VAD 引擎选择」章节。

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

延迟说明（伪流式）：
- **字幕条（实时预览）**：每 0.3s 触发一次，对最近 ≤3s 音频做 ASR，跟手显示，长句由最终文本修正
- **右侧记录（最终文本）**：VAD 检测到句尾静音（默认 ≥0.8s）后切段，对整段做最终 ASR 后输出

### VAD 引擎选择

在「设置 → 音频/VAD」中选择 VAD 引擎，三种引擎可选：

> **作用范围**：Silero 与能量阈值两种引擎在**实时模式和本地模式**都可用；FSMN 为批处理接口，仅对「本地模式」生效（实时模式会自动回退到能量阈值）。

| 引擎 | 说明 | 特点 |
|---|---|---|
| Silero（推荐） | 基于 STFT 频谱的神经网络 VAD，实时模式走流式 VADIterator | 多语言鲁棒、精度高；对静音敏感，多人对话时可能切分过细 |
| 能量阈值 | 基于 RMS 能量阈值 + 时间强制切分 | 速度快、无额外依赖、段长均匀；按时间切分可能切断语义 |
| FSMN | 达摩院 FunASR 框架的 VAD（仅本地模式） | 中文优化、语义连贯性最好、段数最少；需安装 funasr |

**引擎专属参数**：

| 引擎 | 专属参数 | 说明 |
|---|---|---|
| 能量阈值 | 缓冲区上限、强制切分开关 | 控制最大缓冲时长和是否强制切分 |
| Silero | 语音概率阈值（0.20~0.80） | 检测语音/非语音的概率分界线，越低越敏感 |
| FSMN | 语音噪声阈值（0.30~0.90） | 区分语音和噪声的阈值，越低越严格 |

**通用参数**（三种引擎都生效）：

| 参数 | 默认值 | 说明 |
|---|---|---|
| 静音断句阈值 | 0.50 秒 | 静音超过此时长则断句，越小定稿越快（语速快时易切碎） |
| 强制切分时长 | 6.0 秒 | 单段最大时长，超过则强制切分 |
| 最小语音段 | 0.12 秒 | 短于此的语音段会被丢弃 |

> **推荐**：默认使用能量阈值引擎。如需更好的语义连贯性，可切换到 FSMN 引擎。Silero 引擎适合单人清晰语音场景。

---

## 可用模型

| 模型 | 大小 | 用途 | 下载命令（ModelScope ID） |
|---|---|---|---|
| Qwen3-ASR 0.6B | ~2.0 GB | 语音识别，CPU 能跑 | `Qwen/Qwen3-ASR-0.6B` |
| Qwen3-ASR 1.7B | ~4.4 GB | 语音识别，精度最高，建议 GPU | `Qwen/Qwen3-ASR-1.7B` |
| CAM++ | ~27 MB | 说话人声纹识别 | `iic/speech_campplus_sv_zh-cn_16k-common` |
| FSMN-VAD | ~4 MB | 语音活动检测（选择 FSMN 引擎时自动加载） | `iic/speech_fsmn_vad_zh-cn-16k-common-pytorch` |
| Silero-VAD | ~2 MB | 语音活动检测（选择 Silero 引擎时自动下载） | GitHub: `snakers4/silero-vad` |
| ffmpeg | ~80 MB | 视频音频提取（本地模式） | 放到 `models/ffmpeg/ffmpeg.exe` |

---

## 关键词管理

系统支持手动添加关键词，用于标记识别内容中的重要术语：

| 功能 | 说明 |
|---|---|
| 关键词标记 | 用户输入关键词 → 自动归类（主讲人/关键词）→ 拼音匹配纠正同音错误 → 在识别结果中标记显示 |

---

## 后训练数据集

后训练数据集是一个**人在回路**（Human-in-the-loop）系统：系统自动切分语音段并评分，用户对识别文本做人工修正，积累「一段音频 + 一段修正后文字」的高质量配对数据，为后期 LoRA 微调或说话人自适应训练提供数据基础。

> **默认不启用**，需在「设置 → 后训练」中手动开启。

### 数据组织

每条记录 = 一个音频片段 + 对应的修正文本。文件按三级目录组织，音频和文字标注同目录同名一一对应：

```
BackTrain/
├── audience/                       # 模式：audience(观众)
│   └── YYYYMMDD/                   # 日期
│       └── 202607111230/           # 来源名称=处理开始时间(YYYYMMDDHHMM)
│           ├── full_202607111230.flac         # 完整连续录音
│           ├── full_202607111230.json         # 完整录音元数据 + 分段索引
│           ├── seg_20260711_143022_123456.flac   # 音频片段
│           └── seg_20260711_143022_123456.json   # 同名文字标注
├── streamer/                       # 模式：streamer(主播)
│   └── YYYYMMDD/
│       └── 202607111230/
│           ├── seg_...flac
│           └── seg_...json
├── meeting/                        # 模式：meeting(会议)
│   └── YYYYMMDD/
│       └── 202607111430/
│           ├── seg_...flac
│           └── seg_...json
├── local/                          # 模式：local(本地)
│   └── YYYYMMDD/
│       └── 202607111500/
│           ├── seg_...flac
│           └── seg_...json
├── manifest.json                   # 全部片段元数据清单
└── manifest.example.json           # 清单模板（仅参考结构）
```

> 第三级目录用「来源名称」（本地模式=处理开始时间，实时模式=录音开始时间），而非说话人：CAM++ 可能把单人音频误判为多人，用会话标识归集更稳定。说话人标签仍记录在每条 JSON 标注的 `speaker` 字段，供后期筛选。

### 字段说明

每条记录的 JSON 字段：

| 字段 | 说明 |
|---|---|
| `id` | 片段唯一 ID（`seg_YYYYMMDD_HHMMSS_xxxxxx`） |
| `mode` | 数据来源模式：`audience` / `streamer` / `meeting` / `local` |
| `audio_path` | 音频文件相对路径 |
| `corrected_path` | 同目录标注 JSON 路径（与音频同名） |
| `raw_text` | 模型原始识别文本 |
| `text` | 经后处理的识别文本（去重/格式化） |
| `corrected_text` | 人工修正后的文本（初始为 `null`，待人工修正后填入） |
| `speaker` | 说话人标签 |
| `duration` | 片段时长（秒） |
| `quality` | 质量评分（见下表） |
| `status` | `pending`（待修正）/ `corrected`（已修正）/ `rejected`（已弃用） |

### 质量评分

系统在存储时自动对每段语音打分，用于筛选优质训练数据：

| 维度 | 说明 |
|---|---|
| `snr` | 信噪比估计（纯净度，0.0~1.0，越高越干净） |
| `rms` | 音量电平（0.0~1.0，过低=太轻，过高=可能削波） |
| `clipping` | 削波比例（0.0~1.0，越低越好） |
| `spectral_flatness` | 频谱平坦度（越低=语音特征越明显，越高=噪声/嗡嗡声） |
| `overall` | 综合评分（0.0~1.0，加权组合） |

### 启用与配置

在「设置 → 后训练」选项卡中：

| 配置 | 默认值 | 说明 |
|---|---|---|
| 启用后训练数据集收集 | 关闭 | 设置页勾选=全局默认（所有模式生效）；各模式页面还有独立复选框，勾选=仅对该次会话生效 |
| 质量评分阈值 | 0.60 | 综合评分低于此值的片段不落盘 |
| 多维度自动筛选 | 开启 | 综合评分 + 削波 + 频谱平坦度多维判断，关闭则仅按综合评分过滤 |

### 使用流程

1. 在「设置 → 后训练」勾选「启用后训练数据集收集」，保存配置
2. 重启服务，使用任意模式（主播/会议/本地）进行识别
3. 系统自动将符合质量阈值的语音段存入 `BackTrain/[mode]/YYYYMMDD/[speaker]/`
4. 每段音频对应一个同目录同名的 `seg_xxx.json` 标注文件，其中 `corrected_text` 初始为 `null`
5. 人工审听音频，对照 `raw_text` 修正为 `corrected_text`（通过 `DatasetManager.update_correction(id, text)` 接口或直接编辑 JSON）
6. 修正完成的记录 `status` 改为 `corrected`，可作为后期模型微调的训练样本

### 隐私与安全

- 数据集目录含个人声纹数据，`.gitignore` 已配置过滤 `BackTrain/audience/`、`BackTrain/streamer/`、`BackTrain/meeting/`、`BackTrain/local/`、`*.flac`
- 仓库仅保留 `BackTrain/.gitkeep` 和 `BackTrain/manifest.example.json`（模板）
- 实际音频和标注不会上传到远程仓库

## 项目结构

```
在线实时语音识别/
├── app.py                 # PySide6 桌面 GUI（四模式切换/启动停止/字幕展示/日志/系统托盘）
├── realtime_panel.py      # 实时面板组件（字幕展示区/麦克风采集线程/WS客户端/系统音频回环采集）
├── server.py              # WebSocket 服务端（音频接收/VAD调度/转录/说话人分离/报告/网页渲染/后训练数据集接入）
├── core.py                # ASR 引擎和模型加载（Qwen3-ASR）+ 配置管理（model/dataset/local 三组设置）
├── vad_processor.py       # 自适应 VAD 语音活动检测（静音断句/强制切分/音乐噪声检测）
├── speaker_manager.py     # CAM++ 说话人管理（声纹检测/冷启动三级确认/灰色软更新/质量评估）
├── pinyin_utils.py        # 关键词管理 + 文本相似度比对
├── creator_detector.py    # 创作者识别器（从 B站/斗鱼 URL 提取 UP 主/主播名）
├── report_generator.py    # 报告与日志生成（Markdown 报告 + 结构化 JSON 日志）
├── text_utils.py          # 文本处理工具（去重/格式化）
├── settings_dialog.py     # PySide6 设置对话框（模型/设备/VAD/端口/后训练/本地模式配置）
├── local_processor.py     # 本地模式批量处理（ffmpeg提取+VAD+ASR+报告+数据集接入）
├── audio_quality.py       # 语音质量评分（SNR/RMS/削波/频谱平坦度/综合评分）
├── dataset_manager.py     # 后训练数据集管理器（三级目录存储/manifest/人工修正接口）
├── batch_transcribe.py    # 批量音频转录脚本（命令行版，复用 VAD/ASR/说话人/报告管线）
├── asr_panel.user.js      # Tampermonkey 用户脚本（多平台视频页面内嵌面板+字幕条）
├── __init__.py            # 包导出
├── requirements.txt       # Python 依赖 (CPU)
├── requirements-gpu.txt   # Python 依赖 (GPU + CUDA)
├── start.bat              # 一键启动
├── .gitignore
├── LICENSE
├── dict/
│   └── asr_config.json    # ASR 运行时配置（模型/设备/VAD/后训练/本地模式参数）
├── BackTrain/             # 后训练数据集（.gitignore 已过滤实际数据）
│   ├── .gitkeep
│   └── manifest.example.json  # 清单模板
└── static/
    ├── index.html         # 控制面板主页
    └── subtitle.html      # OBS 浏览器源字幕页（透明背景）
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

本项目基于 [MIT License](LICENSE) 开源，可商用。

### 第三方依赖许可证

#### Python 库

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

#### 模型

| 模型 | 许可证 | 商用兼容性 | 说明 |
|------|--------|-----------|------|
| Qwen3-ASR (0.6B / 1.7B) | Apache 2.0 | 完全兼容 | 语音识别模型 |
| CAM++ | Apache 2.0 | 完全兼容 | 说话人声纹识别 |
| FSMN-VAD | Apache 2.0 | 完全兼容 | 语音活动检测 |
| Silero VAD | MIT | 完全兼容 | 语音活动检测 |

> 所有模型均采用宽松开源许可证，允许商业使用、修改和分发。
