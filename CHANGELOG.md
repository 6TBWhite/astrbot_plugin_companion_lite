# Changelog

## 1.0.1 - 2026-07-10

### 提示词优化：减总量 + 结构清理

**注入文本瘦身（584 → 238 字，-59%）**：
- 删除状态来源 `last_event_reason` 和反思摘要 `last_reflection_summary`——给 debug 看的，不该给 LLM 看。
- relationship_posture 只报非默认维度：默认值"一般/很低"不再报，只有偏离默认时才出现。
- style_preference 只在有非默认偏好时才注入：全新用户默认值不再占 token。
- priority 说明和尾部说明各压缩到一行。

**标签格式从 XML 对改为 `---` 分隔**：
- 5 对 `<tag>...</tag>` 替换为单行内容 + `---` 分隔，去掉全部闭合标签开销。
- silence 指令去掉 `<silence_intent>` 包裹，纯指令行直接追加。
- LLM 不做 XML 解析，标签只是视觉边界，`---` 同样清晰但更省。

**silence.py 四个 mode 文本压缩 ~50%**：
- 去掉解释性语句（"不要冷嘲、不要赌气、也不要解释自己为什么话少"→"不冷嘲不赌气"）。
- 保留核心指令语义不变。

**reflection system_prompt 从 67 行压到 ~38 行**：
- 合并重复规则（"用户困了不要降 energy"出现两次 → 一次）。
- JSON 模板从多行缩进格式压为单行带引号的紧凑格式。
- 保留所有关键语义约束，去掉冗余展开。

涉及文件：`context_builder.py`（build 重写 + `_relationship_details` + `_style_line` + `_energy_text` 精简）、`silence.py`（4 mode 压缩 + 去标签）、`reflection.py`（system_prompt 压缩）、`main.py`（`continuity_injected` 检测改为 `"连续性：" in combined`）、`README.md`（示例和架构图同步）。

## 1.0.0 - 2026-07-09

首个正式版。核心定位不变：填补私聊场景的关系感知空白，让 bot 有连续性、有累的权利、有自然演化的关系状态。

### 精力非线性演化：bot 有累的权利

旧版精力是线性恢复（每小时 +6、目标 75），只要不聊天就永远朝满血爬，bot "总是不累"。本版改为四段非线性模型：

- 高能区（>70）：精神好但活跃消耗大，朝 65 自然下滑（-3/时）——满血不再恒定。
- 中高区（55-70）：稳态微恢复（+2/时，目标 70）。
- 中低区（30-55）：开始累，慢恢复（+1.5/时，目标 55）。
- 开摆区（<30）：几乎持平，恢复极慢（+0.5/时，目标 30）——累了不会被迫快速回血。

事件消耗也按当前精力分段：高能时 `active_chat` 消耗 ×2（话多耗神），低能时 ×0.3（开摆了几乎不再多耗）。正向回血分段双向：高能区（>70）回血归零（已经够精神不该再被推高），低能区全额回血（累了就该被哄回来）。精力档位传导同步强化：`_energy_text` 从三档扩为五档，`explain_posture` 新增 42 档"微疲"。精力 ≤42 即让 LLM 感知疲态并自然收短回复。

**高频聊天微消耗**：距上一条消息 <2 分钟时，每条额外随机扣精力 `uniform(0.30, 0.60)`（期望 ≈0.45/条）。24 条密集消息期望掉约 11 点，40 条掉约 18 点。开摆区（≤30）豁免——累了就不追着扣了。补上纯时间衰减在高频聊天时体感不足的缺口。

**活跃回血冷却**：自然回血在活跃聊天期间被冻结，15 分钟（`ENERGY_RECOVERY_COOLDOWN_SECONDS`）没人继续缠着才开始恢复——你在聊天不在休息，不该边聊边回血。只有正向 delta 被冻结，高能区下滑不受影响。实测 24 轮 40 分钟从 70 降到 ~59，而非旧版的只降到 65。

**修复能量冻住 bug**：`apply_time_decay` 的 `hours < 0.05`（3分钟）防抖门槛原本把能量也一起挡了，高频聊天时能量一动不动。修复后能量非线性 delta 在门槛之前计算、永远执行，其余慢变量保持防抖。另修复高能区感谢反而加精力的 bug：正向回血原只对负向分段，现双向分段，高能区回血归零。

**修复反思路径绕过分段调制的 bug**：`apply_reflection_delta` 原只调 `_shape_reflection_deltas`（只处理 familiarity/closeness），energy delta 原样生效——LLM 反思返回 +10 时即使 energy=74 也会加到 84，高能区回血归零的设计被完全绕过。修复后反思路径在 `_shape_reflection_deltas` 之前先调 `_apply_energy_tier_to_consumption`，与事件路径走完全相同的分段双向调制。

**反思正向 energy delta 上限 +2**：消耗是累加的（15 轮 × -1 = -15），负向 -10 合理；恢复是时间函数不是瞬间事件，正向不该像"喝红牛"一口气跳 +6。新增 `REFLECTION_ENERGY_POSITIVE_CAP = 2.0`，正向 delta 先被钳到 +2 再进分段调制。配合高能区 ×0.0，高能时反思正向回血双重归零。

**传导档位阈值对齐实际可达范围**：稳态天花板 70、事件推高峰值 ~71，旧阈值 >75"很有精神"是死代码。`_energy_text` 和 `explain_posture` 阈值调整为 ≤30/≤42/≤55/≤68/≥69，让峰值状态短暂可见但不持续，与"喝红牛"体感一致。

涉及文件：`state_engine.py`（`apply_time_decay` 重写 + `_energy_natural_delta` + `_apply_energy_tier_to_consumption` 双向分段 + `_apply_active_chat_drain` + `_clamp_reflection_energy_delta` + `apply_reflection_delta` 补分段 + `explain_posture`）、`context_builder.py`（`_energy_text`）、`pages/debug/index.html`（WebUI 阈值同步）。数学建模详见 `docs/math_model.md`。

### /bond 语义修复：陪伴模式，不再洗脑

旧版 `/bond` 把熟悉度/亲近度/边界压力/精力四项一次性抬到高值（65/72/8/55），等于剥夺了 bot 累的权利——bond 一下突然精神。本版改为：

- 新增 `bonded` 布尔标记位，区分"自然发展到亲近"和"手动进入陪伴模式"。
- `/bond` 只抬关系档位（熟悉度 ≥55、亲近度 ≥50、边界压力 ≤15），**完全不碰精力**——累了照样累。
- 起步值从"亲密"调低到"熟人起步"，给后续演化留空间；四项底线均可在配置中调整。
- `/unbond` 只清标记，不再强行压低亲近度/抬高边界压力，数值保留由对话演化接管。
- 回执明确告知"精力不干涉，后续关系值和精力都会随对话自然变化"。

涉及文件：`state.py`（+`bonded` 字段及序列化）、`main.py`（`/bond` `/unbond` 重写 + `cp_status` 显示陪伴模式）、`config.py` + `_conf_schema.json`（+3 个 bond 配置项）。

### 今日弧线：日终压缩版

旧版 `tomorrow_guidance` 是覆盖式——每 12 条反思就盖掉前一次建议，最后一次的盖掉前面的，不够"总结性"。本版改为累积 + 跨天压缩：

数据层（`storage.py`）：

- `daily_arc` 表新增 `guidance_segments`（累积的建议片段列表）、`finalized`（是否已日终收尾）、`cycle_count`（今日反思次数）。
- 含老库迁移：启动时自动 `ALTER TABLE` 补字段，旧数据默认空片段/未收尾/0 次。
- 新增 `get_unfinalized_arc_before`：查指定日期前最近一条未收尾弧线，用于跨天补生成。

弧线引擎（`arc.py` 重写）：

- `update_from_reflection`：guidance 改为 append 到 `guidance_segments`（每段 ≤60 字），不再覆盖 `tomorrow_guidance`；mood/trend/highlights 仍增量更新。
- 日中压缩：一天内片段累积到阈值（默认 4 条）先做一次中间压缩，防聊太多 token 涨；无 LLM 时本地兜底保留首尾两条。
- `finalize_arc_for_date`：把当天的 segments + mood + trend 喂给反思 LLM 压缩成一条 ≤120 字的正式 `tomorrow_guidance`，置 `finalized=1`。
- `build_continuity_text`：加 finalized 守卫，未收尾的弧线不注入 guidance（避免答非所问），但 mood/trend 仍可注入。
- `build_today_arc_brief`：给反思 LLM 看的今日弧线背景摘要（定长 ~80 字），让反思知道今天整体走向、避免弧线建议跑偏。

触发与注入（`main.py` + `reflection.py`）：

- 反思流程开头加 `_maybe_finalize_yesterday_arc`：新一天首次反思时，先把昨天（或更早）未收尾的弧线补生成。不用定时任务，跟着用户活跃走。
- `DeepReflection.reflect` 新增 `arc_brief` 参数，注入到 user_prompt 末尾；system_prompt 加一句说明"今日弧线"字段的含义。
- 完整弧线只给反思 LLM 当背景看（零成本影响今天基调），回复 LLM 只看昨天的精简连续性文本（已限 150 字）。
- 周期指导 vs 连续性优先级不变：周期指导优先（即时纠偏），连续性是基线。

配置（`config.py` + `_conf_schema.json`）：

- `Continuity_Settings` 新增 `enable_arc_finalization`（默认 true）、`arc_midday_compress_threshold`（默认 4，0 禁用日中压缩）、`arc_max_segments`（默认 5）。

回归：存储迁移、片段累积、日中压缩、finalize（有/无 LLM/幂等）、连续性守卫（未收尾不注入 guidance / 收尾后注入）共 9 项测试通过。

### WebUI 优化

可视化条重做（解决"数字堆一起丑"）：

- 每个指标一行：左侧标签 + 右侧大数字，下方进度条占满宽，范围用小灰字单独一行——不再把 `min..max` 挤进数值位。
- 颜色按语义重映射，不再用百分比套用 success/warning/danger：
  - 熟悉度：>70 绿（很高）/ 45-70 蓝（较高）/ 20-45 黄（一般）/ <20 灰（很低）。
  - 亲近度：>45 粉（亲近）/ 0-45 蓝（一般）/ <0 紫（疏离）/ <-35 红（排斥）。
  - 边界压力：反转色——<15 绿（放松）/ 15-35 黄 / 35-60 橙 / >60 红（很高，高值=危险）。
  - 精力：≤30 红（已经累了）/ ≤42 橙（有点累）/ ≤55 黄 / ≤68 蓝 / >68 绿，对齐五档传导。
- 亲近度双向条用 flex 重做，中线 2px 实色，负轴紫色填充、正轴粉色渐变。

字段清理：

- 移除/降级：`last_decay_hours`（移到系统页）、周期负向/正向/修复三个权重（中间计算量，`周期主导`已是结论）、`last_event_class` 与 `last_event` 合并为一行。
- 新增：`bonded` 陪伴模式 badge、`mood` 当前心情行、反思进度 `n/12`、`last_deep_reflection_at`（per-user，替换进程级的 `_last_reflection_ts`）。
- 弧线页新增：finalized 状态 badge（已收尾/进行中）、累积片段列表、第几次反思、日终收尾开关状态。

label 全部改写成人话：

- "关系阶段"→"当前关系"、"边界姿态"→"相处姿态"、"已观察消息"→"累计消息数"、"周期主导"→"本周期基调"、"LLM周期策略基调"→"下周期语气（LLM建议）"、"规则完整指导"→"当前周期策略（规则）"、"沉默注入"→"沉默意图已注入"、"连续性注入"→"连续性背景已注入"、"缓冲消息数"→"待反思消息数"等。
- hint 文本：核心指标页"精力会自然起伏——精神好时话多但消耗快，累了会话少想休息，这是正常的"；注入上下文页"以下是最近一次发给模型的完整上下文，模型回复时会看到这些"；风格页"这三项会根据你的聊天习惯慢慢调整，每次反思后可能更新"。
- 侧栏导航："连续性（弧线）"→"今日弧线与连续性"、"指导与注入"→"回复指导与注入"、"系统信息"→"系统与插件状态"。
- 消息缓冲标题加"达 12 条触发反思"提示。

修复：陪伴模式 badge 的 HTML 不再被 `rows()` 的 `esc()` 当文本转义显示。

### 测试

新增三个测试文件共 22 项：

- `test_energy_nonlinear.py`（10 项）：高能衰减、中高/中低/开摆区恢复、事件消耗分段（高能加倍/低能减轻/正向不分段）、五档能量文本、45 档姿态。
- `test_bond.py`（3 项）：`bonded` 默认值、序列化往返、旧数据兼容。
- `test_arc_finalization.py`（9 项）：片段累积不覆盖、日中压缩、finalize（无 LLM 兜底/有 LLM 压缩/幂等）、连续性守卫（未收尾不注入 guidance / 收尾后注入）、老库迁移、`get_unfinalized_before` 查询。

`python -m compileall` 通过，`pytest` 22 项全部通过。

---

## 0.1.0-alpha1 - 2026-07-08

首个 alpha 版。确立了规则 + LLM 双轨学习架构、4 状态周期系统、沉默机制、LivingMemory 只读协同。详见下方各里程碑记录。

### 路线决策（2026-07-08）

- 评估外部项目 SylannEngine：结论为不集成，仅作设计参照（理由与可借鉴点见 `execution-plan-slim.md` 第 1.3 节）。
- 确定瘦身路线：阶段 2/2.5 减法冻结 -> 瘦身版阶段 3 -> 验证一周 -> 瘦身版阶段 4，阶段 5 无限期搁置。
- 新增 `docs/execution-plan-slim.md` 作为后续实现的对照基准，取代 phase3/4/5 原计划的执行地位（原文档保留为参考）。

### 里程碑 1：减法、可信度强化与冻结（2026-07-08，对应 execution-plan-slim.md 第二节）

减法与收窄：

- 删除 `state.py` 死代码：旧 `RuleEngine` 类与旧 `CompanionState.apply_event()`（约 100 行，已被 `events.py` / `state_engine.py` 取代）。
- safety 与 mood 降级为观测量：从 `explain_posture` / `relationship_label` / `boundary_stance` / 沉默触发条件中移除 safety 判定，改由 boundary_pressure 与 closeness 承担；数值仍被事件更新和衰减，Debug 面板标注"观测量"。
- 调参面收窄为三个活跃维度：closeness、boundary_pressure、energy。

可信度强化（2.4 节，冻结前最后一轮逻辑修正）：

- [E] 修复限速补到状态 delta：道歉/修复的边界压力收益乘以周期负向权重降权系数，堵住"连发道歉洗白越界"漏洞。
- [A] 否定前缀防误判："我不喜欢你这样"不再判为 affection；自带否定首字的关键词（如"不想聊"）豁免。
- [F] 正向习惯化：连续同类正向事件收益按 1.0/0.6/0.35/0.2 递减（新增字段 `last_event_streak`，冻结前最后一个新增字段）。
- [G] 负向敏化：周期内重复越界的边界压力增幅按 x1.0/x1.3/x1.6/x1.9 递增（复用 `cycle_boundary_hits`）。
- [H] 边界压力分层衰减：高压(>50)按 1.0/时慢消、中压 2.0/时、低压 3.5/时快消，大冲突留痕更久。
- [B] 关键词清理：BOREDOM 删除"哎"，STYLE_DIRECT 删除"直接"与死键 " blunt"、新增"打直球"；positive_closure 检查提前到 affection 之前并真正接入分类器。
- [C] deep_sharing 收紧：含代码块/链接/多行/中文占比低的长文本降级为 neutral。
- [D] `InteractionEvent.confidence` 参与正向收益折算（负向不打折）。
- [I] energy 下限从 20 改为 10，低能量沉默成为可达状态；强边界沉默改由更高压力阈值触发（不再依赖 safety）。
- [J] closeness 负值语义修复：注入文本中负亲近度描述为"有些疏离/明显排斥"，不再是"亲近度很低"。
- 回归验证：2.3 四场景 + 2.4.4 七场景 + 序列化往返共 25 项全部通过。

冻结声明生效：P2/P2.5 层自此不再新增状态字段、周期字段、事件类型、注入模板。

### 文本层审计：词表命中率与注入语义（2026-07-08，里程碑 1 补充）

目标：确保关键词能命中真实说话方式、注入 prompt 能真正指导 LLM、多层注入不互相矛盾。

词表精修（events.py）：

- affection 改为方向性关键词："喜欢你/想你了/好想你"替代裸词"喜欢/想你"——"我喜欢吃火锅""想你帮我看看"不再误判亲密。
- 强词守卫机制（GUARDED_KEYWORDS）："滚""够了"只在整句为该词本身或出现方向性变体（"你滚/滚开/真够了"）时命中——"滚动条""睡够了"不再误判越界。
- APOLOGY 删除"不好意思"（中文礼貌填充语，且是道歉刷分新入口）；REPAIR 删除"继续聊"（无冲突时是普通话题延续）。
- 风格词表改为指令式表达："详细说说/展开讲讲"替代裸词"详细/深入/温柔"——"帮我详细分析代码""她很温柔"不再永久改写 StyleProfile。
- "不想聊"从 boundary_push（bp+8）移到 rest_request（bp+2、能量恢复、少追问）——礼貌收束不再按越界惩罚。

逻辑与解释一致性（state_engine.py）：

- 无冲突背景（bp<5 且周期无负向）下的道歉按礼貌用语处理：无修复收益，gate_reason 如实说明——修掉"明明没有压力却宣称缓解了压力"的自相矛盾。

注入文本精修（context_builder.py / silence.py）：

- 注入开头新增优先级声明：周期策略/即时指导 > 总体回复基调 > 表达偏好——多层指导冲突时 LLM 不再自行猜测。
- 注入文本移除"安全感"描述，观测量彻底退出表达层（此前只退出了决策层）。
- 末尾指令改写：从"不要直接输出这些状态描述，除非用户主动询问"改为"不复述数值和术语；被问感受时用自然日常语言表达"——避免被问感受时倾倒机械术语。
- silence 文案："不要表现冷淡攻击"改为"平静克制、不冷嘲、不赌气、不解释话少"；删除裸数值"能量12"暴露。

回归：新增真实场景误触案例 32 项 + 旧回归抽核心 25 项，共 57 项全部通过。

### 里程碑 2：瘦身版 P3——每日情感弧线与连续性（2026-07-08，对应 execution-plan-slim.md 第三节）

数据层（storage.py）：

- 新增 `daily_arc` 表：`(user_id, date)` 主键，4 个内容字段 + `source` 列（P4 预留，当前恒为 `local`）。
- 新增 `upsert_daily_arc` / `get_daily_arc` / `get_recent_arcs`（支持 `before_date` 排除当天）。不保存对话原文，只存提炼短句。

弧线引擎（新文件 arc.py，约 170 行）：

- `update_from_reflection`：提取 `arc_mood` / `arc_trend` / `arc_highlights` / `tomorrow_guidance` 写入当日弧线；同日多次反思非空覆盖、highlights 合并去重保留最新 3 条；4 键全缺时静默跳过。
- guidance 消毒：`familiarity < 8` 且 guidance 含"表白/亲密/恋人/更亲近/撒娇/亲昵"时丢弃该条建议。
- 截断约束：mood/trend 60 字、highlights 3x60 字、guidance 120 字、连续性输出 150 字。
- `build_continuity_text`：昨日 mood + guidance + 近 N 天趋势现算（持续/转向/序列三种句式；疲惫x2 追加收敛提示、拉扯x2 追加不推进提示）。
- 过期规则：最近弧线超过 48 小时未更新则整块不注入（防过时 guidance 答非所问）。
- 冲突规则：`cycle_dominant_class` 为 cooldown/cautious 时，按句剔除 guidance 中含"靠近/主动/推进/亲近/热情/撒娇"的语句，只保留情绪承接部分。

反思扩展（reflection.py）：

- 输出 JSON 追加 4 个可选键（保持扁平结构），prompt 明确：arc_mood 写走势不写瞬间情绪、guidance 写相处方式不写用户评价、当天有越界/过早亲密时 guidance 不得建议靠近。

注入（context_builder.py / main.py）：

- 新增 `<continuity>` 块，位置在周期块之后、`<style_preference>` 之前；优先级声明更新为"周期策略 > 总体基调 > 连续性背景 > 表达偏好"。
- 接线：反思成功回调中 `arc_engine.update_from_reflection`（try/except 包裹，失败不影响状态更新与周期重置）；注入路径生成 continuity 文本失败时静默跳过该块。
- `max_context_chars` 默认 700 -> 900（容纳连续性块，避免截断末尾指令）。

配置与面板：

- 新增 `Continuity_Settings`：`enable_continuity_injection`（默认 true，兼 A/B 验证开关）、`continuity_lookback_days`（默认 3，钳制 1-7）。
- WebUI 重构为侧栏布局：状态总览 / 连续性（弧线）/ 指导与注入 / 风格画像 / 消息缓冲 / 系统信息 六栏切换；侧栏底部常驻 LM/沉默/今日弧线三个徽章。
- 连续性栏展示：注入预览（实际生成文本 + 开关状态）、今日弧线、近 7 天弧线卡片。
- 新增 `/arc` API；注入记录增加 `continuity_injected` 标记。

回归：存储往返、同日合并、消毒、截断、趋势句式、过期缺省、cooldown 跳过、注入位置与开关、配置钳制共 38 项全部通过。

### 面板与系统命令过滤修正（2026-07-08）

- Debug WebUI 去除瘦身后不再参与活跃决策的 `safety` / `mood` 展示与条形图，风格画像去除当前不会被事件更新或注入使用的 `emotion_intensity` / `formality`。
- Debug WebUI 明确活跃决策面：`familiarity` / `closeness` / `boundary_pressure` / `energy`；风格画像只展示长度、语气、主动程度三项。
- 亲近度命令行画像修正为 `-50..100`，不再显示成 `/100`。
- 私聊系统命令过滤扩展为自然检测：文本中出现 `/命令` 形态（如 `/sid`、`/reset`）时，不捕获、不注入、不记录 bot 命令结果到消息缓冲，避免进入深度反思与每日弧线总结样本。
- 消息缓冲 API 与手动触发反思路径追加兜底过滤，历史残留的 `/命令` 消息不再显示，也不会进入新的反思样本。
- Debug WebUI 改为 LivingMemory 风格的浅色优先界面，并增加深/浅色切换（localStorage 记忆主题）。
- Debug WebUI 修复主题按钮与加载卡死：按钮文案显示目标主题（浅色时 Dark、深色时 Light），各 API 请求加 5 秒超时与局部降级，避免某个分区接口卡住导致主界面一直停在加载中。

### 消息捕获链路对齐 LivingMemory（2026-07-08）

问题背景：

- 仅按文本撞库过滤系统命令不可靠。AstrBot 可能把 `/reset` 归一成用户文本 `reset`，同时 bot 侧系统结果可能表现为 `Conversation reset successfully.`；继续追加裸词黑名单会误伤真实对话。
- LivingMemory 的做法不是维护命令词表，而是主要在 `on_llm_request` / `on_llm_response` 链路记录真实对话；系统命令不进入普通 LLM 请求，因此天然不会进入会话样本。

已调整：

- 用户消息捕获改为 LLM 请求链路：`inject_companion_context` 中先捕获本轮用户消息，再构建关系上下文并注入。
- 关闭原私聊事件捕获写库：该入口会收到 AstrBot 命令归一后的纯文本（如 `/reset` -> `reset`），不能作为真实对话来源。
- 助手消息捕获从 `after_message_sent` 迁到 `on_llm_response`，只记录真实 LLM assistant 回复，并跳过工具调用中间轮与工具总结轮；系统命令结果不再进入 assistant 缓冲。
- 移除临时的裸词命令撞库（如 `reset` / `sid` / `Conversation reset successfully.`），避免误伤用户正常提到这些词的对话。
- 保留通用命令形态兜底：以 `/命令`、`!命令`、`#命令` 形态出现的文本仍跳过；消息缓冲 API 和反思样本读取也继续过滤这些历史残留。

当前状态与待验证：

- `python -m py_compile astrbot_plugin_companion_lite/main.py` 通过。
- 本地过滤样例：`/reset`、`/sid` 会兜底过滤；`reset`、`sid`、`Conversation reset successfully.`、`http://x/y` 不再被词库硬过滤。
- 需要真机验证：AstrBot 系统命令是否完全不触发 `on_llm_request` / `on_llm_response`；如果仍出现残留，应继续从事件元信息判断命令来源，而不是恢复裸词黑名单。

### 调试操作补充：弧线重置与运行期绑定（2026-07-08）

- Debug WebUI 连续性栏新增“刷新弧线”和“重置弧线”按钮，便于测试每日弧线生成、过期、注入预览与清空后的缺省行为。
- 新增 `/bond` 私聊命令：仅对已配置主用户生效，将当前关系直接拉到亲密调试档（熟悉度至少 65、亲近度至少 72、边界压力不高于 8、能量至少 55），并记录 `manual_bond` 事件。
- 新增 `/unbond` 私聊命令：仅对已配置主用户生效，解除手动亲密关系并回到自然积累档（亲近度不高于 10、边界压力至少 12），清除最近注入预览，并记录 `manual_unbond` 事件。
- `/bond` / `/unbond` 参考 `astrbot_plugin_sylanne-main` 的手动亲密关系绑定语义，不再用于修改 `main_user_ids` 或运行期用户许可；用户许可仍由配置负责。

### Debug WebUI 状态徽章与主题按钮调整（2026-07-08）

- 侧栏策略徽章从“回复正常/收敛中”改为“普通策略/收敛策略”；普通策略显示绿灯，收敛策略显示红灯，避免误解为系统在线状态。
- LivingMemory 徽章改为全名显示：“LivingMemory运行中/未运行”；后端 `page/health` 每次请求实时调用 `livingmemory.detect()`，不再只依赖初始化时检测结果。
- 深/浅色切换从侧栏菜单项移到品牌区右侧的小圆按钮，按钮使用月亮/太阳字符提示可切换目标主题。

### Debug WebUI 主题按钮改用 SVG 图标（2026-07-08）

- 将 Unicode 图标 `☀` / `☾` 替换为内联 SVG，消除字体 glyph 偏移导致的视觉居中偏差。
- 按钮保持 `36x36`，内部图标盒 `20x20`，用 `inline-flex` + `align-items: center` + `justify-content: center` 做几何居中。
- 浅色模式显示月亮 SVG（表示可切换到深色），深色模式显示太阳 SVG（表示可切换到浅色）。
- 图标设计：月亮为月牙形，太阳为带放射线的圆形，`viewBox="0 0 24 24"`，`stroke="currentColor"` 跟随主题色。

### 阶段 1：稳定地基

- 新增显式 `main_user_ids` 绑定；未绑定时不捕获、不注入、不学习。
- 增加消息缓冲上限、活跃聊天统计窗口、反思任务按用户去重。
- Debug 页面支持未绑定提示、健康状态和基础消息缓冲展示。

### 阶段 2：关系状态重构

- 新增 `EventEngine`、`StateEngine`、`ContextBuilder`。
- 增加恢复类事件、时间衰减、能量恢复、边界压力下降。
- `closeness` 与 `familiarity` 解耦，并允许 `-50..100` 的负亲近度。
- 增加事件类别、门控原因、亲近度负正分段 UI。
- LLM 深度反思可以修改关系数值，并记录反思摘要。

### 阶段 2.5：周期态势与社交惯性

- 新增周期态势字段：周期权重、主导类别、完整规则指导、简化规则提醒、LLM 周期策略。
- 周期内正则负责即时控场，修复事件受负向周期权重降权。
- LLM 反思输出 `next_cycle_tone` / `next_cycle_instruction`，反思成功后成为当前周期策略。
- 上下文注入改为：无 LLM 策略时注入完整规则指导；有 LLM 策略时由 LLM 策略接管，正则只追加简化提醒。
- Debug 页面新增实时注入上下文窗口，展示实际注入给主模型的内容。
