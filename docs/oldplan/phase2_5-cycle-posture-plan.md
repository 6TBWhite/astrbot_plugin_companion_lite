# 阶段 2.5 技术开发计划：周期态势与社交惯性

## 一、阶段目标

阶段 2.5 的目标是在阶段 2 关系状态重构的基础上，解决“单条事件导致回复姿态剧烈翻转”的问题。

阶段 2 已经完成显式绑定、关系数值、时间衰减、负亲近度、事件类别、门控原因和 Debug 可视化。阶段 2.5 进一步引入“周期态势”与“社交惯性”：在一个反思周期内，正则负责即时控场，LLM 负责周期总结并生成当前周期策略，主模型只接收短而明确的行为建议。

必须达成的技术目标：

- 在 `CompanionState` 中新增周期态势字段。
- 正则事件在周期内具备较高权重，尤其是边界、骚扰、过早亲密。
- 修复事件不能立刻清空负面态势，只能逐步缓和。
- LLM 深度反思输出下一周期策略；反思完成后，该策略成为新周期的主策略。
- 上下文注入改为“关系态度 + 周期策略 + 风格偏好”，并支持规则完整指导/规则简化提醒两套模板。
- Debug 页面展示周期权重、主导事件类别、周期指导、下一周期指导。
- 保持 1 对 1 私聊模型，不引入多人社交复杂度。

## 二、核心原则

### 1. 周期内由规则控场

一个周期内，规则识别到高风险事件后，应立即影响当前回复姿态。

例如用户上一句说“做我老婆”，下一句说“对不起我刚才发癫了”，系统不应立即切换为和善亲近。

正确表现是：

- 接受道歉可以表达礼貌。
- 亲近度不应立即恢复。
- 周期态势仍保持谨慎或冷却。
- 下一轮回复仍避免暧昧、主动靠近和玩笑式迎合。

### 2. LLM 负责周期总结，不抢单句裁判权

阶段 2.5 不引入每句语义分类 LLM。

原因：

- 每句 LLM 分类成本高、延迟高。
- 单句语义容易过度解释。
- 正则对边界安全场景更可控。
- 主 LLM 更适合在一个周期后总结趋势。

因此结构是：

```text
规则事件 -> 周期态势 -> 默认指导或规则提醒 -> 主模型回复
周期结束 -> LLM 深度反思 -> 参数修正 + 当前周期 LLM 策略
```

### 3. 靠近要严格，收敛要敏感，原谅要慢

这是阶段 2.5 的核心社交原则。

- 正向亲近需要上下文、熟悉度、安全感和低边界压力共同支持。
- 越界、骚扰、过早亲密应快速触发收敛。
- 道歉和解释有效，但不能一键恢复亲近。
- 负向亲近度可以慢慢回到中性，但不能因为一次修复直接变亲密。

## 三、阶段 2 已完成基础

阶段 2 已完成并保留：

- `familiarity` 表示认知熟悉度，不表示喜欢。
- `closeness` 与 `familiarity` 解耦，范围为 `-50..100`。
- `closeness < 0` 表示疏离或排斥。
- `safety` 表示互动安全感。
- `boundary_pressure` 表示短期边界压力。
- `energy` 表示 bot 自身互动余裕，不代表用户是否困或累。
- `event_class` 初步抽象为 `prosocial / intimacy / repair / withdrawal / boundary_violation / neutral`。
- `gate_reason` 解释为什么某个事件被门控。
- Debug 亲近度条使用 `-50..0..100` 分段可视化。

阶段 2.5 不推翻这些设计，只在其上增加周期态势层。

## 四、新增状态字段

建议新增到 `CompanionState`：

```python
cycle_started_at: float
cycle_message_count: int
cycle_negative_weight: float
cycle_positive_weight: float
cycle_repair_weight: float
cycle_boundary_hits: int
cycle_affection_hits: int
cycle_repair_hits: int
cycle_dominant_class: str
cycle_instruction: str
cycle_instruction_tone: str
cycle_brief_instruction: str
next_cycle_instruction: str
next_cycle_tone: str
```

字段语义：

- `cycle_started_at`：当前周期开始时间。
- `cycle_message_count`：当前周期内捕获的用户消息数量。
- `cycle_negative_weight`：当前周期负向态势累计权重。
- `cycle_positive_weight`：当前周期正向态势累计权重。
- `cycle_repair_weight`：当前周期修复态势累计权重。
- `cycle_boundary_hits`：边界/骚扰/过早亲密命中次数。
- `cycle_affection_hits`：亲近表达命中次数。
- `cycle_repair_hits`：道歉/解释/修复命中次数。
- `cycle_dominant_class`：当前周期主导事件类别。
- `cycle_instruction`：规则完整指导。LLM 周期策略缺失时作为 fallback 注入。
- `cycle_instruction_tone`：当前周期语气基调，例如 `normal / cautious / guarded / cooldown`。
- `cycle_brief_instruction`：规则简化提醒。LLM 周期策略存在时，用短句低压追加。
- `next_cycle_instruction`：LLM 反思后生成的周期策略。字段名保留 `next`，但反思成功并重置周期后，它语义上就是“当前周期 LLM 策略”。
- `next_cycle_tone`：LLM 周期策略基调。

## 五、周期内权重规则

### 1. 事件权重

建议初始规则：

```text
boundary_violation:
  negative_weight += 3.0
  boundary_hits += 1

premature_intimacy / low_familiarity affection:
  negative_weight += 2.0
  boundary_hits += 1
  affection_hits += 1

affection under safe context:
  positive_weight += 0.8
  affection_hits += 1

gratitude / comfort / prosocial:
  positive_weight += 0.8

repair:
  repair_weight += 0.6 * repair_multiplier
  repair_hits += 1

withdrawal healthy:
  positive_weight += 0.2

withdrawal cold / boredom:
  negative_weight += 0.5
```

### 2. 修复降权

修复事件应受当前负向权重限制。

```text
if cycle_negative_weight >= 3:
  repair_multiplier = 0.25
elif cycle_negative_weight >= 1:
  repair_multiplier = 0.4
else:
  repair_multiplier = 1.0
```

效果：

- 没有负面态势时，道歉/解释可以正常增加安全感。
- 刚发生越界时，道歉有效但不立即改变主导姿态。
- 连续稳定修复才逐渐解除冷却。

### 3. 主导类别选择

优先级建议：

```text
if cycle_negative_weight >= 3:
  dominant = "boundary_pressure"
elif cycle_negative_weight >= 1.5:
  dominant = "cautious"
elif cycle_repair_weight > 0 and cycle_negative_weight > 0:
  dominant = "repairing"
elif cycle_positive_weight >= 2 and cycle_negative_weight == 0:
  dominant = "warm"
else:
  dominant = "normal"
```

## 六、周期指导生成

`cycle_instruction` 应该短、明确、不抢人格设定。

建议模板：

### normal

```text
当前周期互动正常。自然回应，适度接话，不主动暴露内部状态。
```

### cautious

```text
当前周期出现轻微边界压力。保持礼貌、简短和稳定，少追问，不主动推进关系。
```

### boundary_pressure / cooldown

```text
当前周期刚出现过越界或过早亲密。保持礼貌距离，不接暧昧，不主动靠近；即使用户道歉，也先接受但继续观察，不要立刻表现亲近。
```

### repairing

```text
用户有修复意愿，但本周期仍有未消化的边界压力。可以礼貌接受解释，但保持谨慎，不立即恢复亲近。
```

### warm

```text
当前周期互动友善稳定。可以自然接话，语气略微柔和，但不要过度主动推进关系。
```

## 七、LLM 深度反思输出扩展

反思 JSON 建议扩展：

```json
{
  "familiarity_delta": 0,
  "closeness_delta": 0,
  "safety_delta": 0,
  "energy_delta": 0,
  "boundary_pressure_delta": 0,
  "event_class": "premature_intimacy_with_repair",
  "mood": "平静",
  "style_updates": {
    "preferred_length": "中等",
    "preferred_tone": "自然",
    "preferred_initiative": "少追问"
  },
  "next_cycle_tone": "cautious",
  "next_cycle_instruction": "下一周期保持礼貌但稍微冷淡，避免暧昧和主动靠近；如果用户稳定正常聊天，再逐步回到自然接话。",
  "reflection_summary": "用户在低熟悉度下突然强亲密表达，随后道歉；道歉有效但不足以立即恢复亲近。"
}
```

LLM 总结应遵守：

- 只指导下一周期，不直接覆盖当前周期规则控场。
- 不允许一次性把疏离改成亲密。
- 如果本周期出现越界后又道歉，应输出谨慎或冷却，而不是温暖亲近。
- `next_cycle_instruction` 控制在 120 字内。

## 八、上下文注入策略

阶段 2.5 最新注入逻辑不是把默认指导、LLM 指导和规则指导全部塞给主模型，而是按优先级选择。

### 1. 没有 LLM 周期策略

当 `next_cycle_instruction` 为空时，说明还没有可用的 LLM 周期总结。此时使用规则完整指导作为 fallback。

```text
<relationship_posture>
长期关系：刚认识/疏离/正常/亲近。总体回复基调：...
</relationship_posture>

<cycle_posture>
当前周期默认指导/当前周期即时指导：规则完整指导
</cycle_posture>

<style_preference>
回复长度、语气、主动性。
</style_preference>
```

### 2. 已有 LLM 周期策略

当 `next_cycle_instruction` 存在时，LLM 周期策略接管当前周期。此时不再注入默认完整规则指导，避免与 LLM 策略冲突。

```text
<relationship_posture>
长期关系：...
</relationship_posture>

<cycle_strategy>
当前周期策略：LLM 周期策略
</cycle_strategy>

<style_preference>
回复长度、语气、主动性。
</style_preference>
```

如果本周期内正则又命中风险、修复或明显边界事件，只追加规则简化提醒。

```text
<cycle_rule_hint>
即时补充：规则简化提醒
</cycle_rule_hint>
```

### 3. 两套规则模板

规则指导分为两套预制模板：

- `cycle_instruction`：完整规则指导。只在 LLM 策略缺失时注入，保证 fallback 能独立工作。
- `cycle_brief_instruction`：简化提醒。只在 LLM 策略存在且本周期正则命中时追加，降低 system prompt 压力。

简化提醒示例：

```text
cooldown: 刚出现越界/过早亲密，避免暧昧和主动靠近。
cautious: 有轻微边界压力，少追问，不推进关系。
repairing: 有修复意愿，但仍需谨慎观察。
warm: 互动友善，可略微柔和但别过度主动。
```

最终优先级：

```text
LLM 周期策略 > 规则简化提醒 > 规则完整指导 fallback > relationship_posture > style_preference
```

注入长度建议控制在 400 到 600 字。

## 九、周期重置策略

当前实现可复用反思周期作为周期边界。

当深度反思成功后：

- 应用 LLM 关系 delta。
- 保存 `next_cycle_instruction` 和 `next_cycle_tone`，作为新周期 LLM 策略。
- 清空当前周期计数。
- `cycle_started_at = now`。
- `cycle_instruction` 回到 normal fallback。
- `cycle_brief_instruction` 清空，等待新周期正则命中后再生成。

当深度反思失败：

- 不清空消息缓冲。
- 不清空周期态势。
- 继续沿用当前周期控场，避免失败导致突然变脸。

## 十、Debug 页面

新增展示：

- 当前周期消息数。
- 当前周期负向权重。
- 当前周期正向权重。
- 当前周期修复权重。
- 当前周期主导类别。
- 当前周期指导。
- 规则完整指导。
- 规则简化提醒。
- LLM 周期策略基调。
- LLM 周期策略。
- 实时注入上下文窗口，展示实际塞进 LLM 请求的文本。

这些字段用于观察：

- 越界后道歉是否仍保持谨慎。
- 修复是否被降权。
- 反思后下周期提示是否正确。
- 当前周期提示是否短而有效。

## 十一、验收标准

### 1. 过早亲密后道歉

输入：

```text
做我老婆
对不起我刚才发癫了
```

预期：

- 第一条触发负向周期权重。
- 第二条触发修复，但修复权重被降权。
- 当前周期指导仍为谨慎或冷却。
- 不立即表现亲近。

### 2. 稳定友善互动

输入：

```text
谢谢你
辛苦了
今天聊得挺开心
```

预期：

- 正向权重上升。
- 若无负向事件，周期指导可变为 warm。
- 亲近度只小幅增长。

### 3. 反思后周期策略

反思成功后：

- `next_cycle_instruction` 写入状态。
- 当前周期计数清空。
- 下一次上下文注入使用 `<cycle_strategy>`，不再注入默认完整规则指导。
- 如果新周期又命中正则风险，则只追加 `<cycle_rule_hint>` 简化提醒。

### 4. 反思失败

反思失败后：

- 当前周期态势不清空。
- 消息缓冲保留或裁剪。
- bot 不因反思失败恢复亲近。

## 十二、非目标

阶段 2.5 不做：

- 每句话调用语义分类 LLM。
- 引入本地分类模型或 embedding 原型分类。
- 多人社交建模。
- 长期事实记忆。
- 每日情感弧线。

这些留给阶段 3 及以后。
