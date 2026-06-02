# 在线实时语音识别系统 v1.0

基于 Qwen3-ASR / Paraformer / SenseVoice / Whisper 的实时语音识别桌面应用，支持浏览器端音频采集、说话人识别、拼音纠正、关键词高亮、口音矫正、歌词匹配和**流式字幕叠加**。

## 核心特性

- **🎬 流式字幕条** — 识别文字实时叠加在视频播放器上方（半透明黑底白字，宽度 = 播放器 × 0.618）
- **⚡ 双模式切换** — 默认为流式模式（毫秒级实时输出），可选整句模式（VAD断句后一次性输出）
- **👤 声纹识别** — CAM++ 说话人分离 + 声纹-创作者绑定，跨会话自动恢复，越用越灵敏
- **🗣 口音矫正** — 根据说话人籍贯方言特征（平翘舌/前后鼻音/n-l/h-f/r-l等）自动纠正ASR错字
- **📝 拼音纠正** — 内置通用 + 场景专属拼音纠正词库（CS2、游戏、直播等多场景）
- **🏷 话题关键词** — 自动匹配话题标签加载专用词库，提升领域术语识别准确率
- **🎵 歌词匹配** — 状态机连续匹配歌曲歌词，锁定后高效修正同音错字
- **📊 结构化报告** — 自动生成四板块报告（对话正文 + 关键词 + 纠正明细 + 技术附录）
- **🔄 多端同步** — 网页端与 Tampermonkey 插件端状态实时同步

---

## 系统要求

| 项目 | 最低 | 推荐 |
|---|---|---|
| 操作系统 | Windows 10 64-bit | Windows 11 |
| Python | 3.10 | **3.12**（开发环境） |
| 内存 | 8 GB | 16 GB |
| 硬盘 | 5 GB（含模型） | 10 GB |
| 显卡 | 无（CPU 模式） | NVIDIA 6GB+ VRAM（GPU 模式） |

---

## 快速开始

```bash
# 1. 克隆仓库（GitHub / Gitee 二选一）
git clone https://github.com/jame9898/LiveSpeech2Text.git
# 或 Gitee 镜像
git clone https://gitee.com/linhanduzikai/LiveSpeech2Text.git
cd LiveSpeech2Text

# 2. 创建虚拟环境（推荐）
python -m venv venv
venv\Scripts\activate

# 3. 安装依赖（二选一）
# CPU 环境
pip install -r requirements.txt
# GPU + CUDA 环境
pip install -r requirements-gpu.txt

# 4. 下载语音识别模型（根据需要选一个或多个）
# Qwen3-ASR 0.6B — 轻量，CPU 也能跑
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-0.6B')"
# Qwen3-ASR 1.7B — 最高精度，需 GPU
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-1.7B')"
# Paraformer — 纯中文，最快
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch')"
# SenseVoice — 多语言，轻量
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/SenseVoiceSmall')"
# Whisper（OpenAI）— 使用系统自带 pip 安装即可，无需手动下载模型

# 5. 可选：下载说话人识别模型
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/speech_campplus_sv_zh-cn_16k-common')"

# 6. 启动
python app.py
```

---

## 开发环境（已验证）

| 组件 | 版本 |
|---|---|
| Python | **3.12.8** |
| torch | 2.6.0+cu124 |
| torchaudio | 2.6.0+cu124 |
| modelscope | 1.37.1 |
| qwen-asr | 0.0.6 |
| PySide6 | 6.11.1 |
| websockets | 15.0.1 |
| pypinyin | 0.55.0 |
| numpy | 2.3.5 |
| funasr | 1.3.0（可选） |

---

## GPU 加速（可选）

如果你有 NVIDIA 显卡，卸载 CPU 版 torch 换 GPU 版：

```bash
pip uninstall torch torchaudio -y
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
```

---

## 可选依赖

```bash
# FunASR — 支持 Paraformer / SenseVoice / VAD 模型
pip install funasr

# 关键词扩展功能
pip install scikit-learn
```

---

## 可用模型

| 模型 | 大小 | 精度 | 速度 | 场景 | ModelScope ID |
|---|---|---|---|---|---|
| Qwen3-ASR 0.6B | ~2.0 GB | ★★★ | ★★★ | 轻量，CPU 也能跑 | `Qwen/Qwen3-ASR-0.6B` |
| Qwen3-ASR 1.7B | ~4.4 GB | ★★★★★ | ★★ | 最高精度，需 GPU | `Qwen/Qwen3-ASR-1.7B` |
| Paraformer | ~1.5 GB | ★★★ | ★★★★★ | 纯中文，最快 | `iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch` |
| SenseVoice | ~1.0 GB | ★★ | ★★★★ | 多语言 | `iic/SenseVoiceSmall` |
| Whisper tiny | ~1.0 GB | ★ | ★★★ | 最小 Whisper | `openai/whisper-tiny` |
| Whisper base | ~1.4 GB | ★★ | ★★★ | 基础 Whisper | `openai/whisper-base` |
| Whisper small | ~2.4 GB | ★★★ | ★★ | 均衡 Whisper | `openai/whisper-small` |
| Whisper medium | ~5.7 GB | ★★★★ | ★ | 中等精度 | `openai/whisper-medium` |
| Whisper large | ~8.3 GB | ★★★★★ | ★ | 最高精度 | `openai/whisper-large` |
| CAM++ | ~27 MB | — | — | 说话人识别 | `iic/speech_campplus_sv_zh-cn_16k-common` |

---

## 使用流程

### 方式一：独立网页控制端（推荐，无需安装任何插件）

1. 运行 `python app.py` 或双击 `start.bat`，打开 GUI 面板
2. 在 GUI 面板中点击 **启动服务** 按钮，等待日志显示服务启动完成
3. 浏览器打开 `http://localhost:8765`，进入完整控制面板
4. 填写视频/直播页面URL和UP主名称（选填，用于自动加载关键词）
5. 点击 **▶ 开始** → 在浏览器弹出的共享对话框中选择目标页面
6. 实时识别结果实时显示，流式字幕条叠加在视频上方
7. 右上角「整句 | 流式」按钮可切换模式；GUI设置中也可配置

### 转录模式说明

| 模式 | 延迟 | 准确率 | 字幕条 | 适用场景 |
|------|:---:|:---:|:---:|------|
| **流式**（默认） | 0.8s | ★★★★ | ✅ 显示 | 直播字幕、实时会议 |
| 整句 | VAD断句后 | ★★★★★ | ❌ 不显示 | 视频转录、事后整理 |

> 流式模式做了性能优化：静音时跳过ASR推理、降低推理token数、加大间隔至0.8s，尽量减少CPU/GPU消耗。

### 方式二：Tampermonkey 插件（可选，自动注入视频页面）

1. 运行 `python app.py` 或双击 `start.bat`，打开 GUI 面板
2. 安装 [Tampermonkey](https://www.tampermonkey.net/) 浏览器扩展
3. 在 Tampermonkey 中导入 `asr_panel.user.js` 脚本
4. 打开视频/直播页面，面板自动出现在右边
5. 点击「开始」即可

> 支持平台：B站(bilibili)、斗鱼(douyu)、虎牙(huya)、YouTube、抖音(douyin)、网易CC、腾讯电竞

---

## 关键词与纠正体系

系统内置多层纠错流水线，按优先级依次执行：

| 层级 | 机制 | 说明 |
|------|------|------|
| 1 | 拼音纠正词典 | 精确拼音→正确文本映射，支持声调匹配（`general.json` + 场景专属 `cs2.json`） |
| 2 | 关键词拼音纠正 | 手动添加的关键词通过拼音相似度（≥90%）自动纠正ASR近音错误 |
| 3 | 口音矫正 | 根据说话人画像的方言特征自动纠正 |
| 4 | 英文/数字匹配 | 英文关键词通过编辑距离匹配纠正ASR音译错误 |
| 5 | 音乐/噪声过滤 | 自动检测并丢弃音乐背景音产生的幻听文本 |

---

## 项目结构

```
在线实时语音识别/
├── app.py                 # 主 GUI（PySide6，双击启动）
├── server.py              # WebSocket 服务端（实时推理 + 纠正 + 声纹）
├── core.py                # ASR 引擎 + 模型加载 + 纠正管理器
├── settings_dialog.py     # 设置对话框（VAD/模型/端口/模式配置）
├── keyword_expander.py    # 关键词联想扩展（近音混淆 + 语义关联）
├── speaker_profile.py     # 说话人画像系统（口音/方言/画像库/话题管理）
├── lyrics_matcher.py      # 歌词匹配引擎（状态机连续匹配）
├── asr_panel.user.js      # 浏览器增强脚本（Tampermonkey，含流式字幕条）
├── requirements.txt       # Python 依赖（CPU）
├── requirements-gpu.txt   # Python 依赖（GPU + CUDA）
├── start.bat              # 一键启动脚本
├── push.bat               # Git 推送脚本
├── dict/
│   ├── asr_config.json             # ASR 配置文件（VAD/模型/端口/模式）
│   ├── correction.json             # 全局纠正词
│   ├── keywords.json               # 关键词列表
│   ├── blacklist.json              # 黑名单词汇
│   ├── lyrics.json                 # 歌词库
│   ├── prompts.json                # 提示词模板
│   ├── speaker_profiles.json       # 说话人画像数据（口音特征）
│   ├── topic_keywords.json         # 话题关键词库（自动匹配加载）
│   ├── voice_profile_library.json  # 语音画像库（预置人物口音+口头禅）
│   ├── pinyin_correction.json      # 拼音纠正配置
│   └── pinyin_corrections/
│       ├── general.json            # 通用拼音纠正词库
│       └── cs2.json                # CS2 场景专属拼音纠正词库
├── temp/                  # 临时音频文件（自动清理）
├── models/                # 下载的模型文件（自动创建）
└── voiceprints/           # 声纹保存目录（dict/voiceprints/）
```

---

## 常见问题

### Q: 依赖安装
（CPU 环境）运行 `pip install -r requirements.txt` /（GPU+CUDA 环境）运行 `pip install -r requirements-gpu.txt` 确保所有依赖已安装。

### Q: 端口 8765 被占用
系统会自动尝试释放端口，无需手动处理。如果持续占用，重启电脑即可。

### Q: 模型加载失败
检查 `models/` 目录下是否有对应的模型文件夹。如果没有，按上面「快速开始」中的命令下载。

### Q: CPU 模式很慢
Qwen3-ASR 0.6B 在 CPU 上每次识别约 2-5 秒。如果太慢，考虑：
- 换用更小的模型（如 SenseVoice）
- 使用 GPU 加速（Qwen3-ASR 1.7B + CUDA torch）

### Q: 如何添加场景专属词库？
在 `dict/pinyin_corrections/` 目录下创建 `{场景名}.json` 文件，格式参照 `cs2.json`。系统会根据话题标签自动加载对应词库。

### Q: 口音矫正如何使用？
1. 在关键词面板中添加主讲人姓名
2. 系统自动从画像库查找该人物的口音特征
3. 若未匹配，可手动设置籍贯/方言区域
4. 识别过程中自动纠正口音导致的错字

---

## 许可证

[MIT License](LICENSE)