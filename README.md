# 在线实时语音识别系统 v1.0

基于 Qwen3-ASR / Paraformer / SenseVoice 的实时语音识别桌面应用，支持浏览器端音频采集、说话人识别、拼音纠正词、关键词高亮展开和歌词匹配。

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
# CPU 版（通用，无需显卡）
pip install -r requirements.txt

# 或 GPU 版（NVIDIA 显卡 + CUDA 12.4，推理更快）
pip install -r requirements-gpu.txt

# 4. 下载语音识别模型（根据需要选一个或多个）
# Qwen3-ASR 0.6B — 推荐，CPU 也能跑
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-0.6B')"
# Qwen3-ASR 1.7B — 最高精度，需 GPU
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-1.7B')"
# Paraformer — 纯中文，最快
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch')"
# SenseVoice — 多语言，轻量
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/SenseVoiceSmall')"

# 5. 可选：下载说话人识别模型
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/speech_campplus_sv_zh-cn_16k-common')"

# 6. 启动
python app.py
```

---

## 开发环境（GPU 版 · 已验证）

> ⚠️ 以下为 GPU 加速版开发环境（torch 2.6.0 + CUDA 12.4）。CPU 用户请使用 `pip install -r requirements.txt` 安装通用版依赖。

| 组件 | 版本 |
|---|---|
| Python | **3.12.8** |
| torch (CUDA 12.4) | 2.6.0+cu124 |
| torchaudio (CUDA 12.4) | 2.6.0+cu124 |
| modelscope | 1.37.1 |
| qwen-asr | 0.0.6 |
| PySide6 | 6.11.1 |
| websockets | 15.0.1 |
| pypinyin | 0.55.0 |
| numpy | 2.3.5 |
| funasr | 1.3.0（可选） |

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
| Qwen3-ASR 0.6B | ~2.0 GB | ★★★ | ★★★ | **推荐**，CPU 也能跑 | `Qwen/Qwen3-ASR-0.6B` |
| Qwen3-ASR 1.7B | ~4.4 GB | ★★★★★ | ★★ | 最高精度，需 GPU | `Qwen/Qwen3-ASR-1.7B` |
| Paraformer | ~1.5 GB | ★★★ | ★★★★★ | 纯中文，最快 | `iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch` |
| SenseVoice | ~1.0 GB | ★★ | ★★★★ | 多语言 | `iic/SenseVoiceSmall` |
| CAM++ | ~27 MB | — | — | 说话人识别 | `iic/speech_campplus_sv_zh-cn_16k-common` |

---

## 使用流程

### 方式一：独立网页控制端（推荐，无需安装任何插件）

1. 运行 `python app.py` 或双击 `start.bat`，打开 GUI 面板
2. 在 GUI 面板中点击 **启动服务** 按钮，等待日志显示服务启动完成
3. 浏览器打开 `http://localhost:8765`，进入完整控制面板
4. 点击 **▶ 开始** → 填写录制设置（视频地址、主播名等）→ **✅ 开始录制**
5. 在浏览器弹出的共享对话框中选择目标页面
6. 实时识别结果实时显示，支持清除/报告/保存/日志

### 方式二：Tampermonkey 插件（可选，自动注入视频页面）

1. 安装 [Tampermonkey](https://www.tampermonkey.net/) 浏览器扩展
2. 导入 `asr_panel.user.js` 脚本
3. 打开视频/直播页面，面板自动出现在右边
4. 点击「开始」即可

> 两个端状态自动同步：网页端开始录制 → 插件端自动显示识别中；反之亦然。

---

## 项目结构

```
在线实时语音识别/
├── app.py              # 主 GUI（PySide6，双击启动）
├── server.py           # WebSocket 服务端（实时推理 + 纠正）
├── core.py             # ASR 引擎 + 模型加载 + 纠正管理器
├── settings_dialog.py  # 设置对话框（VAD/模型/端口配置）
├── keyword_expander.py # 关键词提取与展开
├── speaker_profile.py  # 说话人画像（口音/方言）
├── lyrics_matcher.py   # 歌词匹配
├── asr_panel.user.js   # 浏览器增强脚本（Tampermonkey）
├── requirements.txt    # Python 依赖
├── dict/
│   ├── asr_config.json           # ASR 配置文件（VAD/模型/端口）
│   ├── correction.json           # 全局纠正词
│   ├── keywords.json             # 关键词列表
│   ├── blacklist.json            # 黑名单词汇
│   ├── lyrics.json               # 歌词库
│   ├── prompts.json              # 提示词模板
│   ├── speaker_profiles.json     # 说话人画像数据
│   ├── topic_keywords.json       # 话题关键词
│   ├── voice_profile_library.json # 语音画像库
│   └── pinyin_corrections/
│       ├── general.json          # 通用拼音纠正
│       └── cs2.json              # CS 场景专属拼音纠正
└── models/             # 下载的模型文件（自动创建）
```

---

## 常见问题

### Q: `ModuleNotFoundError: No module named 'xxx'`
运行 `pip install -r requirements.txt` 确保所有依赖已安装。

### Q: 端口 8765 被占用
系统会自动尝试释放端口，无需手动处理。如果持续占用，重启电脑即可。

### Q: 模型加载失败
检查 `models/` 目录下是否有对应的模型文件夹。如果没有，按上面「快速开始」中的命令下载。

### Q: CPU 模式很慢
Qwen3-ASR 0.6B 在 CPU 上每次识别约 2-5 秒。如果太慢，考虑：
- 换用更小的模型（如 SenseVoice）
- 使用 GPU 加速（qwen3-asr 1.7B + CUDA torch）

---

## 许可证

[MIT License](LICENSE)
