# 在线实时语音识别 — 项目需求清单

## 1. ASR 流式语音识别系统

基于 qwen3-asr 模型的在线语音识别，支持流式传输文字结果。

## 2. 双前端功能对等

油猴插件（`asr_panel.user.js`）和网页端（`http://localhost:8765`）功能完全相等。

## 3. PySide6 服务端管理界面

使用 PySide6 构建 UI 服务端/后端管理界面，不依赖外部 GUI 工具。

## 4. 报告与日志导出

支持语音识别报告导出及日志导出。

## 5. 说话人记录体系

- **斜体文本** 与 **字幕条** 内容相同（即时识别结果）
- **Speaker 言语记录条** 相当于对斜体文本和字幕条的持久化记录

### 5.1 CAM++ 声纹说话人分离
- 基于达摩院 3D-Speaker CAM++ 模型，输出 192 维声纹向量
- 余弦相似度区分说话人：同一人 0.60–0.95，不同人 0.05–0.30
- 支持多说话人自动区分与命名

### 5.2 声纹越用越灵敏
- **滚动平均精炼**：每次识别成功，声纹 embedding 用加权平均更新（新样本不断精炼声纹）
- **动态阈值自适应**：前 5 分钟宽松（SAME=0.50），逐步收紧到 30 分钟后标准（SAME=0.60），越久区分越准
- **灰色地带软更新**：相似度 0.30–0.60 之间按比例部分更新声纹，不浪费边界数据
- **新人冷启动**：需连续 3 次确认才创建新 speaker，确认后取均值作为初始声纹
- **质量里程碑**：5 分钟快速评估 + 30 分钟完整评估

## 6. 智能识别与拼音纠正

### 6.1 插件智能识别
- 自动识别短视频 UP 主和直播间主播

### 6.2 话题纠正
- 话题用于 ASR 文字纠正
- 话题词典内置但不默认加载（目前仅有 CS 话题）
- 用户需在话题输入框手动输入话题名（如 `CS`）才会启用该话题的拼音纠正
- 话题不输入则不启用话题纠错

### 6.3 关键词纠正
- 关键词用于 ASR 文字纠正
- 关键词由用户手动输入
- 原理：程序将关键词转为拼音，将对应的错别字纠正回来

## 7. 服务端默认设置

| 配置项 | 默认值 |
|--------|--------|
| 设备（device） | `auto` |
| 模型（model） | `auto` |

---

## 8. 已完成优化（2026-06-09）

### 8.1 纠错引擎简化
- 从 6 步管线简化为 3 步：实体纠正 → 拼音纠正 → 文本纠正
- 移除未使用的 `GrammarChecker`、`ConfidenceScorer`、`suggest()`、`get_stats()`
- `correct()` 返回简化格式 `(corrected_text, [(old, new), ...])`，前端直接可用
- 精简 ~290 行代码（581 → 291 行）

### 8.2 漏词修复
- **Bug 1 - 并发满载丢音频**：`transcribe_buffer` 返回 `True`/`False`，`process_audio` 仅在提交成功后才更新缓冲区，并发满时保留音频待下次 VAD 重试
- **Bug 2 - 音乐检测误杀**：仅对 `>= 3s` 长段检测，阈值 `0.25 → 0.18`
- **Bug 3 - 轻声被丢弃**：desperate cut 移除 RMS 检查，统一交给 ASR 判断

### 8.3 音频处理修复
- 下采样增加抗混叠滤波（scipy `resample_poly`，无 scipy 时用移动平均）
- 移除 `_do_streaming_partial` 和 `transcribe_buffer` 中的裸 `is_music_like` 调用

### 8.4 GUI 启动修复
- 修复 `_append_log_label()` 参数不匹配导致的 GUI 无法启动（移除多余的 `"dim"` 参数）

### 8.5 合规性修复 (2026-06-09)
- **6.2 话题纠正手动输入**：移除用户脚本中 `detectTags()` 自动页面标签检测及 `topic_keywords_load` 自动发送。话题纠错现在仅在前端通过 `keyword_add` + category=`topic` 手动触发。
- **模块重命名**：`speaker_profile.py` → `topic_manager.py`，与文件实际内容（`TopicKeywordManager`）一致。
- **死代码清理**：`keyword_expander.py` 移除未使用的 `import json` / `from core import DICT_DIR`，文档字符串与实际功能对齐。

---

## 9. 合规性现状

### 9.1 双前端功能对等
- 网页端 (`STATUS_PAGE`) 与用户脚本 (`asr_panel.user.js`) 核心功能完全一致：录音控制（标签页/全屏）、清除、报告、保存、日志导出、关键词/话题/主讲人的增删。
- 字幕叠加为插件独有（需嵌入视频页面 DOM），不在对等范围内。

### 9.2 话题纠正
- 话题词典内置但不默认加载（当前仅有 CS 话题）。
- 用户通过任一前端的 `keyword_add` + category=`topic` 手动输入话题名，服务端自动匹配话题别名并加载对应的拼音/文本/实体纠正词典。
- `topic_keywords_load` 消息仅用于配合手动输入 — 服务端保留此 handler，前端仅在用户主动操作时调用。

### 9.3 模块文件清单
| 文件名 | 职责 |
|---|---|
| `core.py` | ASR 引擎、配置管理、设备解析 |
| `server.py` | WebSocket 服务、音频缓冲、VAD 调度、前端页面渲染 |
| `vad_processor.py` | 自适应 VAD 断句、音乐/噪声检测 |
| `speaker_manager.py` | CAM++ 声纹说话人分离、命名、质量评估 |
| `topic_manager.py` | 话题关键词匹配与加载 |
| `correction_engine.py` | 三步纠错管线（实体 → 拼音 → 文本） |
| `pinyin_utils.py` | 拼音纠错词典、相似度计算 |
| `report_generator.py` | Markdown 报告与结构化 JSON 日志生成 |
| `keyword_expander.py` | 关键词分类常量和图标 |
| `text_utils.py` | 文本去重、编辑距离、标题关键词提取 |
| `merge_pinyin_dict.py` | 词典格式转换工具（一次性运行） |
| `app.py` | PySide6 桌面 GUI |
| `settings_dialog.py` | PySide6 设置对话框 |
| `asr_panel.user.js` | 用户脚本（多平台视频页面内嵌面板） |

---

## 10. 模型能力边界

### 10.1 Qwen3-ASR 不支持跨语种翻译
- **来源**: 模型 README (`models/models/iic/Qwen3-ASR-1___7B/README.md`)
- **结论**: Qwen3-ASR 是纯 ASR（语音识别）模型，`pipeline_tag: automatic-speech-recognition`，不支持 S2TT（语音到文本翻译）。
- **行为**: 英语输入→英语文本，粤语输入→粤语文本，日语输入→日语文本。`language` 参数仅控制**检测**目标语种，不能改变输出语种。
- **README 原文**: "support language identification and ASR for 52 languages"，全文无 translate/translation 关键词。
- **如需实现跨语种翻译输出**（如英语语音→中文文本），可选方案：

| 方案 | 模型 | 说明 |
|---|---|---|
| A - 两步管线 | Qwen3-ASR + 翻译模型 | ASR 先转写原文，再调用翻译（LLM/MT 引擎）翻成中文 |
| B - 原生 S2TT | SeamlessM4T | 单一模型支持语音输入→不同语种文本输出 |
| C - 多模态模型 | Qwen3-Omni | 同系列更高阶模型，原生支持音频理解和翻译 |

### 10.3 推荐翻译小模型
- **首选: Qwen2.5-0.5B-Instruct**
  - 0.5B 参数，~1GB，CPU 可用
  - 通过指令提示即可翻译：`"把以下{源语言}翻译成中文: {text}"`
  - 与 Qwen3-ASR 同 ModelScope 生态，`transformers` 栈直接复用
  - 额外可复用为关键词联想扩展（`keyword_expander.py` 原计划功能）
  - 下载: `modelscope download --model Qwen/Qwen2.5-0.5B-Instruct --local_dir ./models/Qwen2.5-0.5B-Instruct`
- **备选: Qwen3-0.6B**
  - 0.6B 参数，~1.2GB，稍新但体积略大，其余一致
- **不推荐: NLLB-200-600M** — 专业翻译模型但不在 ModelScope 上，需额外依赖，无法复用

### 10.2 已支持语种
- 30 种语言 + 22 种中文方言 + 多国英语口音
- 含中文、英语、粤语、日语、韩语、德语、法语、西班牙语等
（完整列表见模型 README Released Models Description 表格）
