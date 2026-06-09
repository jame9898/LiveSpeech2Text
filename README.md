# LiveSpeech2Text — 在线实时语音识别

基于 Qwen3-ASR 的中文实时语音识别工具。浏览器采集音频（Chrome 标签页或全屏共享），经 WebSocket 送到本地服务端做 VAD 断句、ASR 识别、说话人分离和拼音纠正，结果实时回传前端展示。带 PySide6 桌面管理面板和 Tampermonkey 油猴插件。

## 它能做什么

- 浏览器取音频，WebSocket 传本地服务端，延迟约 0.8s
- Qwen3-ASR 实时转写（0.6B CPU 可用 / 1.7B 需 GPU），支持中文、英语、粤语、日语等 30 种语言
- VAD 自适应静音断句，根据语调动态调整切分阈值，支持强制切分长句
- CAM++ 声纹说话人分离：相同人 >0.60 归并，不同人 <0.25 新建，中间灰色地带软更新不浪费数据。前 2 分钟宽松阈值快速适应，越久区分越准
- 拼音 + 实体 + 文本三步纠正：先将已知别名替换为规范名，再按拼音词典纠正，最后做英文/数字 Token 直接替换
- 手动添加关键词（主讲人/话题/关键词三类），系统自动转拼音后匹配纠正
- 手动输入话题名（如 `CS`），服务端自动匹配话题别名并加载该领域的拼音/文本/实体词典
- 自动识别 B站（视频 API + 直播 API）、斗鱼（betard API + HTML 标题 fallback）、虎牙（HTML 提取）的 UP 主/主播名
- 会话结束时生成 Markdown 格式识别报告和结构化 JSON 日志
- 油猴插件端支持浮动字幕条，叠加在视频播放器上方
- PySide6 桌面 GUI：启动/停止服务、模型/设备/端口/VAD 参数配置、系统托盘最小化

## 目前不支持（已知局限）

- 语音翻译：外文语音只能输出该语种原文，不自动翻译
- 说话人声纹跨会话持久化（每次启动重头积累）
- 关键词的 LLM 联想扩展（`keyword_expander.py` 目前只有分类常量）
- 独立安装包（须有 Python 环境，手动 pip install）

---

## 系统要求

项目在 Windows 10/11 下开发测试，其他系统未验证。

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 10/11 64-bit |
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

> 插件目前适配平台：B站(bilibili)、斗鱼(douyu)、虎牙(huya)

### 识别模式

两种录音模式共用同一条 WebSocket 连接，服务端统一处理：

- **标签页模式**：`getDisplayMedia({preferCurrentTab:true})`，只捕获浏览器当前标签页的音频
- **全屏模式**：`getDisplayMedia({audio:true,video:true})`，捕获整个屏幕/窗口的音频

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

## 纠正体系

系统内置三步纠错管线，与前端「主讲人/话题/关键词」三类输入对应：

| 步骤 | 机制 | 对应输入 | 说明 |
|---|---|---|---|
| 1 | 实体别名归一化 + 模糊匹配 | 话题 | 将已知别名替换为规范名（如 `faze` → `FaZe`），未知 Token 模糊查找知识库 |
| 2 | 拼音词典纠正 | 话题 + 关键词 | 用户输入词 → 自动转拼音 → 匹配 `dict/pinyin_corrections/` 下对应话题的 `.json` 词典。通用词典 (`general.json`) 始终加载，话题词典仅在用户手动输入话题名后加载 |
| 3 | 文本直接替换 | 话题 | 英文/数字 Token 的整词替换（大小写不敏感），词典位于 `dict/text_corrections/` |

词典目录：
```
dict/
├── asr_config.json             # 运行时可改的配置（模型/设备/VAD端口）
├── topic_keywords.json         # 话题→关键词映射库
├── pinyin_corrections/
│   ├── general.json            # 通用拼音纠正（始终加载）
│   ├── cs2.json                # CS2 专用拼音纠正
│   └── datacom.json            # 网络/通信术语拼音纠正
├── text_corrections/
│   ├── general.json            # 通用英文文本纠正
│   └── cs2.json                # CS2 专用文本纠正
└── entities/
    └── cs2.json                # CS2 实体知识库（战队/选手/地图/武器）
```

---

## 项目结构

```
在线实时语音识别/
├── app.py                 # PySide6 桌面 GUI（启动/停止/设置/日志/系统托盘）
├── server.py              # WebSocket 服务端（音频接收/VAD调度/转录/纠正/报告/网页渲染）
├── core.py                # ASR 引擎和模型加载（Qwen3-ASR）
├── vad_processor.py       # 自适应 VAD 语音活动检测（静音断句/强制切分/音乐噪声检测）
├── speaker_manager.py     # CAM++ 说话人管理（声纹检测/冷启动三级确认/灰色软更新/质量评估）
├── correction_engine.py   # 纠错引擎（实体纠正 → 拼音纠正 → 文本纠正 三步管线）
├── pinyin_utils.py        # 拼音纠正工具（拼音相似度计算/词典加载/关键词纠正）
├── topic_manager.py       # 话题关键词管理器（匹配标签→加载词典）
├── report_generator.py    # 报告与日志生成（Markdown 报告 + 结构化 JSON 日志）
├── keyword_expander.py    # 关键词分类常量（主讲人/话题/关键词的标签和图标）
├── text_utils.py          # 文本处理工具（去重/编辑距离/标题关键词提取）
├── merge_pinyin_dict.py   # 词典格式转换工具（一次性脚本，生成 general.json 等）
├── settings_dialog.py     # PySide6 设置对话框（模型/设备/VAD/端口配置）
├── asr_panel.user.js      # Tampermonkey 用户脚本（多平台视频页面内嵌面板+字幕条）
├── __init__.py            # 包导出
├── requirements.txt       # Python 依赖 (CPU)
├── requirements-gpu.txt   # Python 依赖 (GPU + CUDA)
├── start.bat              # 一键启动
├── .gitignore
├── LICENSE
├── dict/                  # 词典和配置（见上文纠正体系）
├── temp/                  # 临时音频文件（自动创建和清理）
└── models/                # 下载的模型文件（自动创建）
```

---

## 常见问题

**端口 8765 被占用**
系统启动时会自动检测并用 `taskkill` 释放。如果持续冲突，重启电脑或手动改 `dict/asr_config.json` 中的 `ws_port`。

**模型加载失败**
检查 `models/` 目录下是否有对应的模型文件夹。没有则按上面「快速开始」中的命令下载。

**CPU 模式识别慢**
Qwen3-ASR 0.6B 在 CPU 上每次识别约 2-5 秒。如有 NVIDIA GPU，改用 1.7B + CUDA 可大幅提速。

**说话人一直显示 Speaker0**
前 2 分钟为预热期（阈值较宽松），需积累一定量的语音样本后才会开始区分不同说话人。此外，少于 3 个中文字的短句会自动继承前一句的说话人标签。

**如何添加领域专属纠错词典**
在 `dict/pinyin_corrections/` 下新建 `{名称}.json`，格式与 `general.json` 相同（拼音键→正确文本值）。同时在 `dict/topic_keywords.json` 中添加对应话题别名。

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
