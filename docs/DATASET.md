# 后训练数据集

后训练数据集是一个**人在回路**（Human-in-the-loop）系统：系统自动切分语音段并评分，用户对识别文本做人工修正，积累「一段音频 + 一段修正后文字」的高质量配对数据，为后期 LoRA 微调或说话人自适应训练提供数据基础。

> **默认不启用**，需在「设置 → 后训练」中手动开启。

## 数据组织

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
├── meeting/                        # 模式：meeting(会议)
├── local/                          # 模式：local(本地)
├── manifest.json                   # 全部片段元数据清单
└── manifest.example.json           # 清单模板（仅参考结构）
```

> 第三级目录用「来源名称」（本地模式=处理开始时间，实时模式=录音开始时间），而非说话人：CAM++ 可能把单人音频误判为多人，用会话标识归集更稳定。说话人标签仍记录在每条 JSON 标注的 `speaker` 字段，供后期筛选。

## 字段说明

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

## 质量评分

系统在存储时自动对每段语音打分，用于筛选优质训练数据：

| 维度 | 说明 |
|---|---|
| `snr` | 信噪比估计（纯净度，0.0~1.0，越高越干净） |
| `rms` | 音量电平（0.0~1.0，过低=太轻，过高=可能削波） |
| `clipping` | 削波比例（0.0~1.0，越低越好） |
| `spectral_flatness` | 频谱平坦度（越低=语音特征越明显，越高=噪声/嗡嗡声） |
| `overall` | 综合评分（0.0~1.0，加权组合） |

## 启用与配置

在「设置 → 后训练」选项卡中：

| 配置 | 默认值 | 说明 |
|---|---|---|
| 启用后训练数据集收集 | 关闭 | 设置页勾选=全局默认（所有模式生效）；各模式页面还有独立复选框，勾选=仅对该次会话生效 |
| 质量评分阈值 | 0.60 | 综合评分低于此值的片段不落盘 |
| 多维度自动筛选 | 开启 | 综合评分 + 削波 + 频谱平坦度多维判断，关闭则仅按综合评分过滤 |

## 使用流程

1. 在「设置 → 后训练」勾选「启用后训练数据集收集」，保存配置
2. 重启服务，使用任意模式（主播/会议/本地）进行识别
3. 系统自动将符合质量阈值的语音段存入 `BackTrain/[mode]/YYYYMMDD/[speaker]/`
4. 每段音频对应一个同目录同名的 `seg_xxx.json` 标注文件，其中 `corrected_text` 初始为 `null`
5. 人工审听音频，对照 `raw_text` 修正为 `corrected_text`（通过 `DatasetManager.update_correction(id, text)` 接口或直接编辑 JSON）
6. 修正完成的记录 `status` 改为 `corrected`，可作为后期模型微调的训练样本

## 隐私与安全

- 数据集目录含个人声纹数据，`.gitignore` 已配置过滤 `BackTrain/audience/`、`BackTrain/streamer/`、`BackTrain/meeting/`、`BackTrain/local/`、`*.flac`、`BackTrain/manifest.json`
- 仓库仅保留 `BackTrain/.gitkeep` 和 `BackTrain/manifest.example.json`（模板）
- 实际音频和标注不会上传到远程仓库
