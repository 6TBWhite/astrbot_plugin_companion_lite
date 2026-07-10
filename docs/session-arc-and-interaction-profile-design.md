# CompanionLite 会话弧线与互动画像重构设计

> 状态：实施基准。
> 日期：2026-07-10
> 目标：用可验证的会话轨迹替代每日建议摘要，并把风格设置升级为带证据的互动画像。

## 1. 问题定义

旧 `daily_arc` 将多次周期反思输出的 mood、trend 和 guidance 按自然日累积，再额外调用 LLM 压缩为次日建议。它存在四个根本问题：

1. 最后一次 trend 覆盖日内轨迹，无法表达“靠近 -> 拉扯 -> 修复”。
2. 弧线由 LLM 文案定义，没有状态前后差、峰值和可验证转折点。
3. 自然日不是互动边界，跨午夜的连续会话会被错误切开。
4. 日终 LLM 只压缩先前 LLM 的输出，信息增益低且增加调用成本。

现有 `StyleProfile` 也只是三个回复偏好开关，不是用户画像；它没有来源、证据、置信度或冲突处理。

## 2. 分层职责

```text
即时状态层
  当前事件、连续动力学、四轴姿态

会话弧线层
  一段互动从哪里开始、经过哪些转折、最后如何结束

互动画像层
  多段会话后，哪些相处偏好和关系反应模式有稳定证据

LivingMemory
  用户事实、经历、兴趣和外部世界信息
```

CompanionLite 不生成性格诊断，也不复制 LivingMemory 的事实记忆。画像只描述“怎样与该用户相处”和“双方互动通常如何发展”。

## 3. 会话边界

会话按互动间隔划分，不按日期划分：

- 当前无开放会话时，用户消息创建新会话。
- 距开放会话最后活动超过 60 分钟时，先结束旧会话，再创建新会话。
- 40 分钟静默反思可以更新会话摘要，但不强制结束会话。
- 后台任务发现开放会话静默超过 60 分钟时，规则化结束会话。

60 分钟是第一版代码常量，验证后再决定是否开放配置。

## 4. 数据契约

### 4.1 SessionArc

```json
{
  "id": 1,
  "user_id": "u1",
  "started_at": 0,
  "last_activity_at": 0,
  "ended_at": 0,
  "status": "open",
  "start_snapshot": {},
  "end_snapshot": {},
  "peak_boundary_pressure": 0,
  "peak_negative_trend": 0,
  "peak_positive_trend": 0,
  "min_energy": 60,
  "message_count": 0,
  "turning_points": [],
  "outcome": "ongoing",
  "summary": "",
  "reflection_count": 0
}
```

快照只保存弧线判定需要的字段：familiarity、closeness、safety、boundary pressure、energy 及三种短期趋势。

### 4.2 TurningPoint

```json
{
  "at": 0,
  "kind": "boundary_escalation",
  "event_type": "boundary_push",
  "event_class": "boundary_violation",
  "intensity": 1.5,
  "reason": "用户明确表达拒绝",
  "changes": {"boundary_pressure": 12.0},
  "posture": "cautious"
}
```

只记录真正改变轨迹的节点：

- `boundary_escalation`：明确越界或压力显著上升。
- `repair_attempt`：存在冲突背景下的修复行为。
- `warming`：正向趋势跨过 warm 阈值。
- `energy_drop`：energy 首次进入低能区。
- `energy_recovery`：energy 从低能恢复到正常区。
- `relationship_shift`：closeness 或 safety 单次发生显著变化。

相邻同类节点在短时间内合并，单会话保留最近 12 个节点。

### 4.3 Outcome

会话结果由本地状态差和转折点计算，不由 LLM 自由决定：

```text
stable_warm
stable_neutral
warming
cooling
boundary_escalation
unresolved_tension
partial_repair
recovered
energy_exhaustion
mixed
```

LLM 可以补充一句摘要，但不能覆盖规则 outcome。

### 4.4 InteractionProfileEvidence

```json
{
  "key": "follow_up_questions",
  "value": "avoid",
  "source": "explicit",
  "positive_evidence": 2,
  "negative_evidence": 0,
  "confidence": 1.0,
  "first_observed_at": 0,
  "last_observed_at": 0,
  "active": true
}
```

第一版只落地明示偏好证据：

- `reply_length = short|long`
- `tone = soft|direct`
- `follow_up_questions = avoid`

明示偏好置信度为 1，可被相反明示指令覆盖。观察性画像和关系反应模式先建立数据接口，必须达到样本阈值后才允许注入。

## 5. 采集流程

```text
用户消息到达
  -> 结束超时会话或打开新会话
  -> 保存事件前快照
  -> 应用事件和动力学
  -> 保存事件后快照、峰值和转折点
  -> 更新明示画像证据

Bot 最终回复
  -> 记录回复工作量
  -> 更新会话活动时间和最低能量

周期反思完成
  -> 更新会话 summary/reflection_count
  -> 不覆盖 outcome，不写第二份关系数值

会话超时
  -> 保存 end_snapshot
  -> 本地计算 outcome
  -> 关闭会话
```

## 6. 连续性注入

新连续性只注入仍有效的信息：

1. 最近一次已结束会话的 outcome 与关键转折。
2. 最近 7 次会话的规则聚合模式。
3. 高置信、active 的互动偏好。

示例：

```text
连续性：上次会话有边界压力，之后仅部分修复；本次先保持克制，少追问。用户明确偏好简短回复。
```

当前即时 boundary/energy 姿态始终优先于历史连续性。

## 7. 数据切换策略

- 高速迭代阶段不承担旧 `daily_arc` 兼容负担；代码、配置和 API 直接切换到新结构。
- 旧 SQLite 文件中即使残留 `daily_arc` 表，也不会再读取或写入，可由用户按需删除数据库重新初始化。
- 不将旧文案自动转换为结构化转折点，避免制造伪证据。

## 8. LLM 职责调整

周期反思继续负责语义校正和会话摘要候选，但不再输出或维护 `tomorrow_guidance` 作为控制主源。日终二次 LLM finalize 从新链路移除。

规则负责：会话边界、快照、峰值、转折点、outcome 和画像证据计数。

LLM 负责：规则无法表达的语义原因、简短摘要、低置信画像候选。候选必须经过本地证据门槛才能激活。

## 9. 第一阶段验收

1. 跨午夜但间隔不足 60 分钟的互动属于同一会话。
2. 静默超过 60 分钟后，新消息先关闭旧会话并创建新会话。
3. “友善 -> 越界 -> 修复”保留三个阶段，不被最后结果覆盖。
4. 会话 outcome 可由状态和转折点重复计算，不依赖 LLM 文案。
5. 新连续性在已有 session arc 时不读取旧 daily guidance。
6. “短点”“别追问”等明示偏好带来源、时间和置信度持久化。
7. 未达到证据阈值的观察性画像不注入。
8. 不新增逐消息或日终 LLM 调用。
