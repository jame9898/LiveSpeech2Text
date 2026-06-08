# 在线实时语音识别系统 v1.0

基于 Qwen3-ASR 的实时语音识别桌面应用，支持浏览器端音频采集、说话人识别、拼音纠正、关键词高亮和**流式字幕叠加**。

## 核心特性

- **🎬 流式字幕条** — 识别文字实时叠加在视频播放器上方（半透明黑底白字，宽度 = 播放器 × 0.618）
- **⚡ 流式识别** — 毫秒级实时输出，静音时自动跳过推理降低GPU消耗
- **👤 说话人分离** — CAM++ 说话人识别，会话内越用越精确，区分不同说话人
- **📝 拼音纠正** — 内置通用 + 场景专属拼音纠正词库（CS2、游戏、直播等多场景）
- **🏷 话题关键词** — 自动匹配话题标签加载专用词库，提升领域术语识别准确率
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
# 1. 克隆仓库
git clone https://ghfast.top/https://github.com/jame9898/LiveSpeech2Text
cd LiveSpeech2Text

# 2. 创建虚拟环境（推荐）
python -m venv venv
venv\Scripts\activate

# 3. 安装依赖（二选一）
# CPU 环境
pip install -r requirements.txt
# GPU + CUDA 环境
pip install -r requirements-gpu.txt

# 4. 下载语音识别模型（根据需要选一个或多个，自动保存到 models/ 目录）
# Qwen3-ASR 0.6B — 轻量，CPU 也能跑
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-0.6B', cache_dir='models')"
# Qwen3-ASR 1.7B — 最高精度，需 GPU
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-1.7B', cache_dir='models')"

# 5. 可选：下载说话人识别模型
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/speech_campplus_sv_zh-cn_16k-common', cache_dir='models')"

# 6. 启动
python app.py
```

---

## 更新

有新版本时，在项目目录下运行：

```bash
git pull
```

---

## 可用模型

| 模型 | 大小 | 精度 | 速度 | 场景 | ModelScope ID |
|---|---|---|---|---|---|
| Qwen3-ASR 0.6B | ~2.0 GB | ★★★ | ★★★ | 轻量，CPU 也能跑 | `Qwen/Qwen3-ASR-0.6B` |
| Qwen3-ASR 1.7B | ~4.4 GB | ★★★★★ | ★★ | 最高精度，需 GPU | `Qwen/Qwen3-ASR-1.7B` |
| CAM++ | ~27 MB | — | — | 说话人识别 | `iic/speech_campplus_sv_zh-cn_16k-common` |

---

## 使用流程

### 方式一：独立网页控制端（推荐，无需安装任何插件）

1. 运行 `python app.py` 或双击 `start.bat`，打开 GUI 面板
2. 在 GUI 面板中点击 **启动服务** 按钮，等待日志显示服务启动完成
3. 浏览器打开 `http://localhost:8765`，进入完整控制面板
4. 填写视频/直播页面URL和UP主名称（选填，用于自动加载关键词）
5. 点击 **▶ 标签页**（仅捕获浏览器声音）或 **▶ 全屏**（捕获所有系统声音）
6. 实时识别结果实时显示，流式字幕条叠加在视频上方

### 识别模式

流式模式：延迟约 0.8s，实时显示识别结果和字幕条。静音时自动跳过ASR推理，降低CPU/GPU消耗。

适用于直播字幕、实时会议、视频转录等所有场景。

### 方式二：Tampermonkey 插件（可选，自动注入视频页面）

1. 运行 `python app.py` 或双击 `start.bat`，打开 GUI 面板
2. 安装 [Tampermonkey](https://www.tampermonkey.net/) 浏览器扩展
3. 在 Tampermonkey 中导入 `asr_panel.user.js` 脚本
4. 打开视频/直播页面，面板自动出现在右边
5. 点击「开始」即可

> 支持平台：B站(bilibili)、斗鱼(douyu)

---

## 关键词与纠正体系

系统内置三层纠正机制，与插件端「主讲人 / 话题 / 关键词」对应：

| 层级 | 机制 | 对应插件字段 | 说明 |
|------|------|:--:|------|
| 1 | 拼音纠正词典 | — | 普遍适用，纠正口音和常见词语的ASR识别错误（`general.json` + 场景专属词库），支持声调匹配 |
| 2 | 关键词拼音纠正 | 关键词 | 手动输入的关键词，系统自动拼音化后进行拼音相似度纠正（≥90%），修正ASR近音错误 |
| 3 | 词典知识库 | 话题 | 按话题标签（如CS2）统一加载文本纠正词典（`text_corrections/`）+ 实体知识库（`entities/`）+ 英文/数字匹配，一体化领域知识纠正 |

---

## 项目结构

```
在线实时语音识别/
├── app.py                 # 主 GUI（PySide6，双击启动）
├── server.py              # WebSocket 服务端（实时推理 + 纠正 + 声纹）
├── core.py                # ASR 引擎加载 + 模型管理
├── correction_engine.py   # 智能纠错引擎（实体识别/模糊匹配/语法检查/置信度）
├── settings_dialog.py     # 设置对话框（VAD/模型/端口/模式配置）
├── keyword_expander.py    # 关键词分类标签定义
├── speaker_manager.py     # 说话人管理（CAM++ 声纹识别 + 说话人标注）
├── speaker_profile.py     # 话题关键词管理器
├── pinyin_utils.py        # 拼音纠正引擎
├── text_utils.py          # 文本处理工具（去重/相似度/英文匹配）
├── report_generator.py    # 报告/日志生成
├── vad_processor.py       # VAD 语音活动检测
├── asr_panel.user.js      # 浏览器增强脚本（Tampermonkey，含流式字幕条）
├── __init__.py            # 包导出
├── requirements.txt       # Python 依赖（CPU）
├── requirements-gpu.txt   # Python 依赖（GPU + CUDA）
├── start.bat              # 一键启动脚本
├── dict/
│   ├── asr_config.json             # ASR 配置文件（VAD/模型/端口/模式）
│   ├── topic_keywords.json         # 话题关键词库（自动匹配加载）
│   ├── pinyin_corrections/
│   │   ├── general.json            # 通用拼音纠正词库
│   │   └── cs2.json                # CS2 场景专属拼音纠正词库
│   ├── text_corrections/
│   │   └── cs2.json                # CS2 文本纠正词库
│   └── entities/
│       └── cs2.json                # CS2 实体知识库
├── temp/                  # 临时音频文件（自动清理）
└── models/                # 下载的模型文件（自动创建）
```

---

## 常见问题

### Q: 依赖安装
（CPU 环境）运行 `pip install -r requirements.txt` 

（GPU+CUDA 环境）运行 `pip install -r requirements-gpu.txt` 确保所有依赖已安装。

### Q: 端口 8765 被占用
系统会自动尝试释放端口，无需手动处理。如果持续占用，重启电脑即可。

### Q: 模型加载失败
检查 `models/` 目录下是否有对应的模型文件夹。如果没有，按上面「快速开始」中的命令下载。

### Q: CPU 模式很慢
Qwen3-ASR 0.6B 在 CPU 上每次识别约 2-5 秒。如果太慢，考虑：
- 使用 GPU 加速（Qwen3-ASR 1.7B + CUDA torch）

### Q: 如何添加场景专属词库？
在 `dict/pinyin_corrections/` 目录下创建 `{场景名}.json` 文件，格式参照 `cs2.json`。系统会根据话题标签自动加载对应词库。

### Q: 说话人声纹会保存吗？
不会。声纹仅在当前直播会话中缓存，用于越来越精确地区分不同说话人。直播结束后声纹自动清除，不保留到下次。

---

## 卸载

### 移除应用程序

本项目无需安装，直接删除克隆的项目文件夹即可。

```bash
# 1. 停用虚拟环境（如使用）
deactivate

# 2. 删除项目文件夹 — 找到名为 LiveSpeech2Text 的文件夹，直接删除即可

# 3. 删除自动缓存的模型文件
rmdir /s "%USERPROFILE%\.cache\modelscope\hub\Qwen"
rmdir /s "%USERPROFILE%\.cache\modelscope\hub\iic"
```

### 移除 Tampermonkey 插件

1. 浏览器打开 Tampermonkey 管理面板
2. 找到 `LiveSpeech2Text V1.0` 脚本，点击删除

### 移除 Python 依赖（可选）

如果不再需要这些 Python 包：

```bash
pip uninstall torch torchaudio modelscope qwen-asr PySide6 websockets pypinyin soundfile scipy librosa numpy -y
```

---

## 许可证

[MIT License](LICENSE)
