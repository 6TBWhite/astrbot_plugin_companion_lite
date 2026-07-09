# 阶段 2/2.5 总体流程图：关系状态、周期态势与注入

## 一、总览

阶段 2 和阶段 2.5 共同构成 CompanionLite 的即时关系状态层。

目标不是保存事实记忆，而是回答这些问题：

- 这个用户和 bot 当前是什么相处状态？
- 最近是否出现边界压力、过早亲密、修复、友善或冷淡？
- 当前周期该如何指导主模型回复？
- 周期结束后，LLM 是否需要调整下个周期的回复策略？

总体流程：

```text
私聊消息
  -> 显式绑定检查
  -> 文本过滤
  -> 规则事件识别 EventEngine
  -> 时间衰减 StateEngine.apply_time_decay
  -> 事件门控 StateEngine.apply_event
  -> 周期态势更新 Cycle Posture
  -> 保存状态与消息缓冲
  -> 达到条件后触发 DeepReflection

LLM 请求
  -> 加载状态并应用时间衰减
  -> ContextBuilder 生成注入上下文
  -> 可选 SilenceMechanism 注入收敛提示
  -> 写入 req.extra_user_content_parts 或 prompt fallback
```

## 二、消息捕获流程

```text
capture_private_message(event)
  ├─ initialized / enable_message_capture 检查
  ├─ 只处理私聊
  ├─ 文本长度和命令前缀过滤
  ├─ BindingManager.is_bound(user_id)
  ├─ Storage.count_recent_user_messages -> recent_rate
  ├─ EventEngine.classify(text, recent_rate)
  │    └─ 输出 InteractionEvent(type, event_class, reason, confidence)
  ├─ _load_state_with_decay(user_id)
  │    └─ StateEngine.apply_time_decay
  ├─ StateEngine.apply_event(state, event)
  │    ├─ 基础 delta
  │    ├─ 状态门控
  │    ├─ 负亲近度 / 边界压力 / 安全感更新
  │    ├─ 周期权重更新
  │    └─ 生成 last_posture / gate_reason
  ├─ EventEngine.apply_style_update(style, event.type)
  ├─ Storage.save_state / save_style_profile
  ├─ Storage.append_message(user, text)
  └─ _maybe_trigger_reflection
```

## 三、事件层

### 1. InteractionEvent

```python
InteractionEvent(
    type="affection",
    event_class="intimacy",
    reason="用户表达亲近或喜欢",
    confidence=1.0,
)
```

### 2. 事件类型和类别

```text
gratitude          -> prosocial
comfort            -> prosocial
affection          -> intimacy
boundary_push      -> boundary_violation
apology            -> repair
repair             -> repair
rest_request       -> withdrawal
low_energy_share   -> withdrawal
boredom            -> withdrawal
deep_sharing       -> prosocial
active_chat        -> neutral
neutral            -> neutral
```

### 3. 关键原则

```text
同一个 type 不直接等于最终 delta。
StateEngine 会根据 familiarity、closeness、safety、boundary_pressure 和周期态势进行门控。
```

例如 `affection`：

```text
低熟悉度 -> 过早亲密，closeness 下降，boundary_pressure 上升。
高熟悉度且安全 -> 自然亲近，closeness 小幅上升。
已有边界压力 -> 被门控为压力，避免误加好感。
```

## 四、状态层

### 1. 基础关系状态

```text
familiarity: 0..100
认知熟悉度。知道这个人是什么样，不代表喜欢。

closeness: -50..100
关系亲近取向。负数代表疏离/排斥，0 代表中性，正数代表愿意靠近。

safety: 0..100
互动安全感。表示 bot 是否觉得对方稳定、尊重、可预测。

boundary_pressure: 0..100
短期边界压力。表示当前是否需要收敛、保持距离、减少主动性。

energy: 20..90
bot 自身互动余裕，不代表用户是否困、累、难过。
```

### 2. 事件解释状态

```text
last_event
last_event_class
last_event_reason
last_gate_reason
last_posture
last_reflection_summary
```

这些字段用于 Debug 和上下文解释，不是事实记忆。

## 五、时间衰减

每次加载状态时应用：

```text
StateEngine.apply_time_decay(state, now)
```

衰减规则：

```text
energy:
  随时间恢复到目标值附近，高边界压力时恢复变慢。

boundary_pressure:
  随时间下降，是短期压力。

closeness:
  正值会缓慢冷却，熟悉度越高越稳定。
  负值会缓慢向 0 恢复，但不会自动转正。

familiarity:
  也会轻微衰减，新人掉得更快，熟人更稳定。

safety:
  缓慢回归中性基线。
```

## 六、增长阻尼和每日上限

增长不是无限叠加。

```text
DAILY_FAMILIARITY_CAP = 15
DAILY_CLOSENESS_CAP = 18
```

当天消息越多，熟悉度增长略有加成，但最多约 20%。

数值越高，增长越慢：

```text
0..30: 正常增长
30..60: 65% 增长
60..80: 35% 增长
80..100: 15% 增长
```

## 七、周期态势层

阶段 2.5 增加周期态势，用来避免单句事件导致回复姿态剧烈翻转。

### 1. 周期字段

```text
cycle_started_at
cycle_message_count
cycle_negative_weight
cycle_positive_weight
cycle_repair_weight
cycle_boundary_hits
cycle_affection_hits
cycle_repair_hits
cycle_dominant_class
cycle_instruction
cycle_brief_instruction
next_cycle_instruction
next_cycle_tone
```

### 2. 周期内权重

```text
boundary_violation: negative += 3
low familiarity affection: negative += 2
affection under pressure: negative += 1.5
prosocial: positive += 0.8
repair: repair += 0.6 * repair_multiplier
healthy withdrawal: positive += 0.2
cold withdrawal: negative += 0.5
neutral: positive += 0.05
```

修复降权：

```text
negative >= 3: repair_multiplier = 0.25
negative >= 1: repair_multiplier = 0.4
else: repair_multiplier = 1.0
```

## 八、周期指导双模板

规则指导分两套：

```text
cycle_instruction
完整规则指导。没有 LLM 周期策略时使用，保证 fallback 可独立工作。

cycle_brief_instruction
简化规则提醒。有 LLM 周期策略时才追加，降低 prompt 压力。
```

LLM 周期策略：

```text
next_cycle_instruction
字段名保留 next，但反思成功并重置周期后，它是当前周期的 LLM 策略。
```

注入优先级：

```text
if next_cycle_instruction exists:
  inject cycle_strategy
  if rule hit in current cycle:
    inject cycle_rule_hint
else:
  inject cycle_posture with full rule instruction
```

## 九、上下文注入流程

```text
inject_companion_context(event, req)
  ├─ 加载 state/style
  ├─ apply_time_decay(save=True)
  ├─ resolve bot_name from persona_manager if possible
  ├─ ContextBuilder.build(state, style, max_chars, bot_name)
  │    ├─ relationship_posture
  │    ├─ cycle_strategy 或 cycle_posture
  │    ├─ cycle_rule_hint 可选
  │    └─ style_preference
  ├─ SilenceMechanism.should_inject_silence(state)
  ├─ 缓存 last_injected_context 给 Debug
  └─ append_extra_user_content 或 prompt fallback
```

注入示例：

```text
<relationship_posture>
长期关系：刚认识；熟悉度很低，亲近度一般，安全感较高，边界压力很低。当前Para状态：平静；相处姿态：正常；能量：稳定。总体回复基调：稳定自然...
</relationship_posture>

<cycle_strategy>
当前周期策略(cautious)：保持礼貌但稍微冷淡，避免暧昧和主动靠近。
</cycle_strategy>

<cycle_rule_hint>
即时补充：刚出现越界/过早亲密，避免暧昧和主动靠近。
</cycle_rule_hint>

<style_preference>
表达偏好：回复长度偏中等，语气偏自然，主动程度为少追问。
</style_preference>
```

## 十、深度反思流程

```text
_maybe_trigger_reflection
  ├─ 消息数达到 reflection_message_interval
  ├─ 距离上次反思达到 reflection_time_interval_minutes
  ├─ 标记 last_deep_reflection_at
  └─ queue _run_reflection

_run_reflection
  ├─ DeepReflection.reflect(state, style, messages)
  ├─ DeepReflection.apply_result
  │    ├─ apply_reflection_delta
  │    ├─ 写 last_reflection_summary
  │    ├─ 写 next_cycle_tone / next_cycle_instruction
  │    └─ 更新 style profile
  ├─ StateEngine.reset_cycle_after_reflection
  ├─ save state/style
  └─ clear message buffer
```

反思失败：

```text
不清空消息缓冲。
不重置周期态势。
只裁剪缓冲到上限。
```

## 十一、Debug 页面

Debug 分为几类：

```text
用户状态卡:
  数值和短状态。避免塞入大段说明。

数值可视化:
  familiarity / closeness(-50..0..100) / safety / boundary / energy。

实时注入上下文:
  展示说明性文字、规则指导、LLM 策略和实际注入给主模型的完整文本。

消息缓冲:
  展示最近待反思消息。
```

“debug 文档/Debug”在这里指的是插件内置 WebUI 调试页，不是另一个文档文件。

路径：

```text
pages/debug/index.html
```

## 十二、当前非目标

阶段 2/2.5 不做：

- LivingMemory 读取。
- 每日情感弧线。
- 每句 LLM 语义分类。
- 多人社交模型。
- 长期事实记忆。

这些分别进入阶段 3、4、5。
