# 后训练 Roadmap

## 开发迭代记录（本地持续维护）

> 本记录为**本地持续维护**：每完成一轮需求（含对应 git 提交）后，在此追加一条迭代记录（倒序，最新在上），随代码一起提交。
> 提交清单可用 `git log --format="%ad | %s" --date=format:"%Y-%m-%d"` 核对。

### 2026-08-10 · CPU 推理加速调查 + int8 量化开关（需求：CPU 利用率低、本地处理慢）
- 实测排查根因：0.6B fp32 CPU 每生成一个 token 需全量读 2.4GB 权重（DDR4 内存带宽 ~25GB/s 为物理瓶颈），CPU 利用率 28% 属正常（带宽吃满，计算单元空闲），实时率 ~1x 是 0.6B CPU 硬件极限
- 实测无效方案（不采用）：torchao int8 量化（无 VNNI 指令集时反量化开销大，实测 0.75x 变慢）、int4（需 Intel mslk 库）、torch.compile（CPU 无 triton 后端，无收益）、加大 batch（权重读取与 batch 无关，带宽共享）
- 新增设置项"CPU int8 量化"（设置→设备，默认关，仅 CPU 生效）：torchao int8 weight-only 把权重 2.4GB→0.6GB，支持 VNNI/AVX512 的较新 CPU（11 代酷睿+）可开，失败自动回退 fp32
- 硬件建议（真正解决慢）：内存双通道（16GB 单条→2×8GB，带宽翻倍，ASR 预计提速 1.5-2x）；GPU 机器（434 段 15.2s vs CPU 163 段 11 分钟，快约 100 倍）

### 2026-08-10 · 本地模式性能报告开关 + 阶段化进度条 + 声纹批量修复（需求：性能报告默认不输出、勾选后自动输出并带版本；本地进度条几乎不动；说话人批量提取报 numpy truthiness）
- 性能报告默认关闭（设置→本地模式勾选后输出）：阶段耗时/占比 + 采样汇总 + git 分支/commit/远端（GitHub/Gitee）版本信息，便于对照远端最新提交做测试与回退
- 本地进度条阶段化：VAD 0-10% / ASR 10-65% / 说话人 65-80% / 逐段 80-100%，ASR 组间与声纹提取实时上报（此前 ASR 占 86% 但无进度回调，进度条卡 0% 直到结束跳 100%）
- 修复 `extract_embeddings` 中 `result.get('embs') or []` 对 numpy 数组 truthiness 必然崩溃——此前批量声纹提取全部段失败（实时模式被 except 兜底静默吞掉），本次连根修复
- 批量声纹提取并行化：每 worker 克隆独立 pipeline 实例 + torch 线程数按 worker 均分（CPU 上提速）
- Silero VAD CPU 用 1536 大窗口（前向次数降 1/3，提速约 3 倍）；requirements 新增 psutil（CPU 物理核数检测）
- 提交：`441f34f`

### 2026-08-09 · 设备/模型默认自适应 + 文案与面板按设备区分（需求：笔记本打开默认 1.7B+cuda；退出提示写死 GPU 显存；CPU 机不该显示 GPU）
- `dict/asr_config.json` 默认改回 `auto`/`auto`（此前写死开发机的 1.7B/cuda，笔记本同步后即继承）；`core.py` auto 模型按设备选择——GPU 优先 1.7B、CPU 优先 0.6B（省内存快）
- 退出/重启弹窗与卸载日志按实际设备显示"释放 GPU 显存"或"释放内存"（`_mem_kind()`）；设置对话框新增实际检测提示行
- 性能面板 CPU 环境整行隐藏 GPU（无 GPU 时只显示 CPU/内存）；修复启动期 torch 预导入高峰导致 GPU 探测失败被永久判定为 CPU 的问题（每秒重试）

### 2026-08-09 · 性能采样不弹 cmd 窗口（需求：监测时老闪命令行窗口）
- 接入 `nvidia-ml-py==13.610.43`（pynvml，NVIDIA 官方库）：直读驱动采样 GPU 利用率/显存/温度，零子进程、零窗口
- nvidia-smi 回退路径加 `CREATE_NO_WINDOW` 隐藏控制台窗口（Windows）
- requirements-gpu.txt 新增可选依赖（缺失时自动回退，不影响功能）
- 提交：`fd6c2ba`

### 2026-08-09 · 实时性能监测面板（需求：GPU/CPU 监测要实时、独立板块放控制台上方、完整报告也放进去）
- 控制台上方新增性能监测面板：GPU/CPU 利用率进度条 + 显存/温度 + 设备名/内存详情，1s 刷新
- `PerfSampler` 后台线程实时采样（均值/峰值统计）；本地处理启动时重置统计、全程采样，任务结束输出 `[LOCAL-TASK]` 汇总
- `process_audio_file` 拆外层（perf/sampler 托管）+ 内层实现；性能小结新增实时负载行
- 提交：`4d7029c`

### 2026-08-09 · 本地处理性能优化（需求：本地处理总时长看不到、任务管理器才能看到 GPU 是否工作）
- 音频加载改 soundfile 直读（wav 提速约 800 倍，加载占比 36%→0%）；ASR 批量参数按设备自适应（GPU 8×30s/6x，实测再提速约 27%）
- 提交：`dd5fd5b`

### 2026-08-09 · 本地处理性能检测（同上轮需求）
- 新增 `perf_utils.py`（零新依赖）：VAD/ASR/说话人/音频加载阶段计时与占比、实时率、GPU 利用率/显存/温度采样；batch_transcribe 同步
- 提交：`d2b0965`

### 2026-08-09 · README 完善（需求：环境问题进 FAQ、英文版同步、开发环境写明确）
- 常见问题扩充环境/依赖故障排查 + AI 工具排障建议；英文 README 与中文完全同步；新增开发测试环境小节（Python 3.12.8 / RTX 4070 SUPER / CUDA 12.6 / torch 2.12.0+cu126 锁定组合）
- 提交：`78a5819`, `e06691c`, `87398d9`, `eb7a6eb`, `36b113b`

### 2026-08-09 · 说话人模型依赖链修复（需求：排查 modelscope 说话人 pipeline 隐藏依赖）
- 干净环境实测补齐硬依赖：`torchvision==0.27.0`、`simplejson==4.1.1`、`sortedcontainers==2.4.0`、`datasets==4.8.5`
- ERes2Net base 下载分支落盘项目 models/ 并修补 configuration.json（embed_dim=512/channels=32，模型自校验）
- 提交：`dcff6a0`, `2b31ab6`, `7239028`, `3fb8070`

### 2026-08-08~09 · 安装与模型下载基础设施
- `install.py`：自动测速选择最快 pip 镜像源 + PyTorch 源，安装后自动验证核心依赖并自动重试；requirements 加 UTF-8 BOM 修复中文系统 pip 解码失败；依赖锁定开发机验证组合；模型下载顺序与国内外源说明；Silero VAD 支持 LFS 直下 + `[SPEAKER]` 过滤器修复
- 提交：`ce67989`, `693907e`, `02e1608`, `fc014ec`, `951703d`, `af512cb`, `757c532`, `e5c1359`

### 2026-08-08 · 全量审查修复 + 本地处理/数据集模式（需求：Silero 流式 VAD 实时支持）
- Silero 流式 VAD 实时支持、全量代码审查修复、本地处理与后训练数据集模式；README 精简拆分 docs/
- 提交：`f4b2e26`, `c730204`, `4dff455`

### 2026-06-08 ~ 07-10 · 历史迭代（早期开发）
| 日期 | 内容 | 提交 |
|------|------|------|
| 07-10 | English README；start.bat 虚拟环境启动说明；OBS 浏览器源字幕 + 网页配置页 + 说话人同步 + AI 角标；实时识别面板与批量转录脚本 | `0c4311b`, `2ce1f86`, `3ee7c29`, `c778ebf` |
| 06-28 | 全量代码审查发现的 P0/P1 bug 修复 | `dae2fd9` |
| 06-12 | 默认配置改 auto（无 GPU 也能启动）；管线简化、关键词拼音纠错、话题移除 | `4136b94`, `f94aaa8` |
| 06-11 | 代码清理与纠错系统优化：死代码/冗余移除、stop 录制/资源泄漏修复、报告时间戳与断句合并、字典缓存 | `0e58b04` |
| 06-09 | FlashAttention2 加速 + 并发上限 3；partial 互斥锁改递增序号；CS2 纠错体系统一；去重与强制切分调整；漏字修复；README 重写；合规性修复 | `ffaca30`, `2d33893`, `c387c86`, `06deac0`, `2259f52`, `4a50c17`, `87d8f8d`, `0e08f9a`, `a696666`, `42fba5c` |
| 06-08 | 斗鱼主播名 API 优先；README 更新章节（git pull）；模型下载到 models/；gitignore 排除 PROJECT_RULES；qwen-asr 版本修正 + modelscope 依赖 | `9930b29`, `36cd601`, `da082b0`, `75099a5`, `ee39a67`, `981444d`, `12d5201`, `c19ade8`, `8943e50` |
| 06-08 之前 | 早期重构/纠错体系文档/声纹安全与训练优化/B 站插件修复/合规与命名统一（详见 `git log`） | `e617bed` 及更早 |

---

## 总体方向

围绕 Qwen3-ASR 模型优化，主攻**路径 A（热词表 + 解码 Bias）** 与 **路径 C（LoRA / QLoRA 微调）** 两条路线。

- **路径 A**：零训练成本，热词表可热更新，立即可做，作为主用方案。
- **路径 C**：模型真正学会领域术语和说话人特征，作为长期主攻方向。
- **已排除**：外部重排序 / RAG 纠错等机械规则纠错（静态、无动态更新、收益有限，不纳入路线）。

数据基础已就绪：`BackTrain/` 下四级模式（audience / streamer / meeting / local）的**分段存储 + 完整连续录音 + 分段索引**双存储模式已完成，为后续 LoRA 微调提供原始语料。

---

## 阶段 1：词云 + 热词表 + 解码 Bias（路径 A）

### 目标

在不微调模型的前提下，通过**热词表 + 解码端 Bias** 提升 Qwen3-ASR 对专有名词、领域术语的识别准确率。

### 关键产物

1. **词云可视化**：MD 报告中新增 Keyword Section，按主题着色展示高频 / 关键术语，一眼看出"这篇讲什么"。
2. **热词表**：动态维护的术语库，覆盖 AI / 编程 / 大模型等领域，可热更新。
3. **解码 Bias 接入**：Qwen3-ASR 解码时对热词 token logits 加 bias 分数。

### 实施步骤

1. **词云信号源**
   - 转录文本 → jieba 分词 + 自定义术语词典
   - TF-IDF / TextRank 提取通用关键词
   - 规则匹配已知专有名词
   - 变体聚类（拼音 + 编辑距离）发现"疑似识别错的专有名词"
   - 产出：词云图 + 高频术语列表 + 疑似错词映射表

2. **热词表工程**
   - 热词表存储格式：JSON，含 `word` / `weight` / `domain` / `enabled`
   - 初始热词来源：词云聚合 + 人工标注 + 现有 `PinyinCorrector` 画像库
   - 热更新接口：运行时增删热词，无需重启服务
   - 与 `BackTrain/` 的关系：词云聚合的多场会话高频词自动入候选库

3. **解码 Bias 验证与接入**
   - 验证 Qwen3-ASR `generate()` 是否支持 `LogitsProcessor` 挂载（Whisper 系支持，Qwen3-ASR 基于 transformers，理论可行）
   - 实现 `HotwordBiasProcessor`：对热词的 token 序列加 `λ * bias_score`
   - 调参：bias 分数过大导致强制插入，过小无效，需 A/B 测试
   - 失败回退：若 LogitsProcessor 不可用，退化为后处理替换（仅对高置信度错词映射）

4. **MD 报告 Keyword Section**
   - 词云图嵌入（`wordcloud` 库生成 PNG，按主题着色）
   - 关键词表格：词 / 频次 / TF-IDF 权重 / 是否热词 / 疑似错词映射
   - 篇章主题标签（基于关键词聚类推断）

### 验证标准

- 同一段测试音频，启用热词 Bias 后，已知专有名词识别准确率提升 ≥ 30%
- 词云能正确反映篇章主题（人工抽检 10 场会话）
- 热词表热更新延迟 < 1 秒，不影响实时转录

### 风险点

- **LogitsProcessor 兼容性**：Qwen3-ASR 的具体实现需实测，若不兼容则阶段 1 降级为"词云 + 后处理替换"。
- **Bias 调参敏感**：bias 分数需精细调参，否则可能误触发。
- **专有名词切分**：BPE tokenizer 可能把热词切成多个 subword，bias 需作用到完整 token 序列。

---

## 阶段 2：LoRA / QLoRA 微调（路径 C）

### 目标

用后训练数据集的 `(音频, 修正后文本)` 对做监督微调，让 Qwen3-ASR 真正学会领域术语和说话人特征，从模型层面提升识别能力。

### 前置条件

- **数据量**：保守估计 ≥ 10 小时高质量标注音频（修正后文本）
- **数据质量**：必须经过 `update_correction(seg_id, text)` 人工修正或 LLM 辅助修正，脏数据会带偏模型
- **算力**：单卡 GPU，0.6B 模型 QLoRA 需 ≥ 8GB 显存（现有 CUDA 环境满足）

### 关键产物

1. **LoRA Adapter**：rank=8~16 的低秩适配器，挂载在 Qwen3-ASR 的 attention 投影层。
2. **微调数据流水线**：从 `BackTrain/` 到 HuggingFace dataset 的自动转换。
3. **修正闭环工具**：人工修正或 LLM 辅助修正 ASR 输出，回写 `corrected_text` 字段。

### 实施步骤

1. **修正闭环工具（前置必做）**
   - 基于 `BackTrain/` 的 `full_xxx.json` 分段索引 + `seg_xxx.flac` 分段音频
   - 提供 GUI 修正界面：播放分段音频 → 显示原始文本 → 修正 → 保存
   - 修正后文本回写 `seg_xxx.json` 的 `corrected_text` 字段
   - 同步更新 `manifest.json` 中对应条目的 `status: corrected`
   - **无此工具则阶段 2 无法启动**：用未修正的 ASR 输出做微调 = "用错误答案训练模型"

2. **伪标签数据增强**
   - 复用"本地模式再识别一次"思路：同一音频两次识别不一致处，自动标记为高优先级 review 样本
   - 本地模式 vs 实时模式识别差异 → 自动入修正队列
   - 目的：降低人工修正成本，把人工注意力集中到最有价值的样本上

3. **数据格式转换流水线**
   - 输入：`BackTrain/[mode]/YYYYMMDD/HHMM/` 下的 `seg_xxx.flac` + `seg_xxx.json`（含 `corrected_text`）
   - 质量过滤：复用现有 `score_audio` + `is_high_quality`，仅保留综合评分 ≥ 阈值且削波 < 5% 的样本
   - 输出：HuggingFace `Dataset` 格式，字段 `{audio, text, sample_rate, speaker}`
   - 训练 / 验证集划分：按会话划分（避免同会话泄露），比例 8:2

4. **LoRA 微调训练**
   - 框架：HuggingFace `peft` + `transformers` + `accelerate`
   - 挂载点：Qwen3-ASR 的 attention 投影层（`q_proj` / `v_proj` / `o_proj`）
   - 超参起点：rank=16, alpha=32, dropout=0.05, lr=1e-4, batch=4, grad_accum=4
   - 训练监控：loss 曲线 + 验证集 CER（字符错误率）
   - 早停：验证集 CER 连续 3 轮无下降则停止

5. **Adapter 加载与切换**
   - 训练产出的 LoRA Adapter 独立保存为 `models/lora/[task_name]/`
   - 运行时通过 `peft.PeftModel.from_pretrained()` 动态加载
   - 支持多 Adapter 切换：默认模型 / 领域 Adapter / 说话人 Adapter
   - 集成到 UI：模型加载区新增"加载 LoRA Adapter"按钮

6. **效果评估**
   - 测试集 CER 对比（基线 vs LoRA）
   - 专有名词识别准确率对比（重点指标）
   - A/B 测试：同一会话，启用 / 不启用 LoRA 的识别结果差异

### 验证标准

- 测试集 CER 较基线下降 ≥ 15%
- 专有名词识别准确率提升 ≥ 40%
- LoRA Adapter 加载耗时 < 2 秒，推理延迟增加 < 10%
- 单卡训练 10 小时音频数据，总训练时间 ≤ 4 小时

### 风险点

- **数据质量风险**：未充分修正的数据会带偏模型，修正闭环是硬前置。
- **过拟合风险**：LoRA rank 过高或数据量不足时易过拟合，需严格验证集监控。
- **领域漂移**：训练数据领域过窄（如全是 AI 编程），可能导致通用识别能力下降，需保留通用数据混合训练。
- **显存风险**：1.7B 模型 QLoRA 显存需求高于 0.6B，需实测。

---

## 数据基础（已完成）

后训练数据集的双存储模式已就绪，为两个阶段提供数据支撑：

### 存储结构

```
BackTrain/
  [audience | streamer | meeting | local]/   # 模式
    YYYYMMDD/                                # 日期
      YYYYMMDDHHMM/                          # 会话标识（录音/处理开始时间）
        full_YYYYMMDDHHMM.flac              # 完整连续录音（整场会话）
        full_YYYYMMDDHHMM.json              # 完整录音元数据 + 分段索引
        seg_YYYYMMDD_HHMMSS_xxxxxx.flac     # 分段音频
        seg_YYYYMMDD_HHMMSS_xxxxxx.json     # 分段文字标注（与音频同名）
  manifest.json                             # 全局清单（含 mode/source/quality/status）
```

### 接入点

| 模式 | 接入文件 | 说明 |
|------|---------|------|
| 观众 / 主播 / 会议 | `server.py` | 共用 `RealtimeASRServer`，录音 start / 音频块 / stop 三处接入会话管理 |
| 本地 | `local_processor.py` | `LocalProcessThread`，音频加载后一次性追加全量，处理完成后 end_session |

### 预留接口

- `update_correction(seg_id, text)`：供阶段 2 修正闭环工具调用，回写 `corrected_text`。
- `get_stats()`：数据集统计接口，用于阶段 2 数据量评估。

### 双存储价值

- **分段存储**：服务于阶段 2 的 LoRA 微调（按段训练样本）。
- **完整连续录音**：服务于阶段 2 的伪标签数据增强（本地模式再识别 + 比对）和阶段 1 的词云信号源（整场会话语料）。

---

## 不纳入路线的方向

以下方向经评估后**不纳入**本 Roadmap，记录于此供后续复盘：

- **外部重排序 / RAG 纠错**：静态规则纠错，无动态更新能力，机械且收益有限。
- **领域 LM 浅融合（Shallow Fusion）**：需训练独立 LM，工程量大，收益不显著优于路径 A。
- **扩展词表 + 联合训练**：BPE tokenizer 重新训练 merge 规则复杂度过高，性价比低。
- **全量微调**：成本过高，LoRA 已能覆盖大部分收益。

---

## 演进路线图

```
[已完成] 数据基础：双存储模式 + 修正接口预留
    │
    ▼
[阶段 1] 词云 + 热词表 + 解码 Bias（路径 A）
    │   ├─ 词云信号源
    │   ├─ 热词表工程
    │   ├─ 解码 Bias 验证与接入
    │   └─ MD 报告 Keyword Section
    │
    ▼
[阶段 2] LoRA / QLoRA 微调（路径 C）
        ├─ 修正闭环工具（前置必做）
        ├─ 伪标签数据增强
        ├─ 数据格式转换流水线
        ├─ LoRA 微调训练
        ├─ Adapter 加载与切换
        └─ 效果评估
```

阶段 1 与阶段 2 非强依赖关系：阶段 1 可独立上线产出价值；阶段 2 的前置条件是数据修正闭环，而非阶段 1 完成。但阶段 1 的词云产出的热词表，可作为阶段 2 微调数据的质量评估参考（识别错的专有名词优先 review）。
