# 阶段 2 技术开发计划：关系状态重构

## 一、阶段目标

阶段 2 的目标是让 CompanionLite 的关系状态从“简单加减分”升级为更自然的长期相处状态机。

本阶段不做每日情感弧线，也不接入 LivingMemory 数据读取。重点是让即时状态具备恢复、衰减、边界修复和更自然的沉默/收敛表达。

必须达成的技术目标：

- 明确 `mood` 是 bot 的当前相处状态，不代表用户真实心情。
- 增加恢复类事件：道歉、缓和、安慰、重新邀请、良好结束。
- 增加时间恢复/衰减：能量恢复、边界压力下降、亲近度轻微冷却。
- 重构事件应用逻辑，使状态变化可解释、可测试。
- 调整沉默机制，从“冷淡疏离”改为“收敛、少追问、降低主动性”。
- 上下文注入从数值描述进一步转向自然相处建议。
- Debug 页面和命令能解释当前姿态来源。

## 二、状态语义

### 1. CompanionState

`CompanionState` 表示 bot 和绑定用户此刻的相处状态。

字段语义：

- `familiarity`：熟悉度，长期底色，主要随互动积累增长，不轻易下降。
- `closeness`：亲近度，表示当前关系亲近程度，可缓慢冷却。
- `safety`：安全感，表示 bot 对当前互动是否感到稳定、安全、可自然回应。
- `boundary_pressure`：边界压力，表示当前是否需要收敛、保持距离、减少主动性。
- `energy`：互动能量，表示 bot 当前愿意继续互动的程度，会随密集聊天下降、随时间恢复。
- `mood`：bot 当前相处状态，例如平静、开心、疲惫、低落、烦躁、好奇。
- `last_event`：最近一次事件。
- `last_event_reason`：最近一次事件的简短原因，可选新增。
- `last_state_updated_at`：最近状态更新时间，建议新增。
- `last_reflection_summary`：最近反思摘要，可选新增，若阶段 1 未落地则本阶段补。

### 2. 状态边界

建议 clamp：

- `familiarity`: 0 到 100。
- `closeness`: 0 到 100。
- `safety`: 0 到 100。
- `boundary_pressure`: 0 到 100。
- `energy`: 10 到 95。

当前实现能量最低为 20。阶段 2 可保留 20，也可调整到 10。建议先保留 20，降低行为变化幅度。

## 三、结构拓扑

阶段 2 后推荐结构：

```text
CompanionLitePlugin
├── EventEngine
│   ├── classify(text, recent_rate)
│   ├── detect_style_preference(text)
│   └── build_event(reason, confidence)
│
├── StateEngine
│   ├── apply_time_decay(state, now)
│   ├── apply_event(state, event)
│   ├── apply_reflection_delta(state, result)
│   └── explain_posture(state)
│
├── StyleEngine
│   ├── apply_style_event(style, event)
│   └── update_confidence(style, explicit_signal)
│
├── SilenceMechanism
│   ├── check(state)
│   ├── mode: mild / defensive / rest
│   └── build_guidance(state, mode)
│
├── ContextBuilder
│   ├── relationship_text(state)
│   ├── posture_text(state)
│   ├── style_text(style)
│   └── build_context(state, style)
│
└── Debug API
    ├── state explanation
    ├── recent event reason
    └── decay/recovery status
```

为了控制改动量，阶段 2 可先新增：

- `events.py`：事件类型和规则识别。
- `state_engine.py`：状态衰减和事件应用。
- `context_builder.py`：上下文构建。

`state.py` 可以继续保留 dataclass，但逐步把逻辑从 `CompanionState.apply_event()` 移到 `StateEngine`。

## 四、事件模型

### 1. 事件结构

建议新增轻量事件结构：

```python
@dataclass
class InteractionEvent:
    type: str
    reason: str = ""
    confidence: float = 1.0
```

阶段 2 不需要复杂事件溯源表，但可以先把 reason 存进 `state.last_event_reason`。

### 2. 事件类型

保留现有：

- `gratitude`
- `boundary_push`
- `affection`
- `boredom`
- `deep_sharing`
- `active_chat`
- `style_length_short`
- `style_length_long`
- `style_tone_soft`
- `style_tone_direct`
- `neutral`

新增恢复类：

- `apology`：用户道歉，例如“抱歉”“对不起”“刚才语气不好”。
- `repair`：用户解释或重新靠近，例如“我不是那个意思”“继续聊吧”。
- `comfort`：用户安慰或表达理解，例如“辛苦了”“你也休息下”。
- `positive_closure`：自然结束且氛围良好，例如“今天先这样，晚安”“谢谢，早点休息”。
- `rest_request`：用户明确希望 bot 休息或对话停下，例如“你休息吧”“先不聊了”。
- `low_energy_share`：用户表达自己很累、状态差，例如“我好累”“撑不住了”。

### 3. 规则识别建议

新增关键词集合：

```python
APOLOGY_KEYWORDS = ["抱歉", "对不起", "不好意思", "刚才语气", "我错了"]
REPAIR_KEYWORDS = ["不是那个意思", "继续聊", "别误会", "我解释一下"]
COMFORT_KEYWORDS = ["辛苦了", "你也休息", "别太累", "慢慢来"]
POSITIVE_CLOSURE_KEYWORDS = ["晚安", "今天先这样", "早点休息", "谢谢你陪我"]
REST_REQUEST_KEYWORDS = ["你休息吧", "先不聊", "别回了", "到这吧"]
LOW_ENERGY_KEYWORDS = ["我好累", "累死", "撑不住", "没力气", "心累"]
```

优先级建议：

1. 明确边界类：`boundary_push`、`rest_request`。
2. 修复类：`apology`、`repair`。
3. 亲近/感谢类：`affection`、`gratitude`、`comfort`。
4. 风格偏好类。
5. 状态表达类：`low_energy_share`、`boredom`。
6. 长消息和活跃聊天。

## 五、状态变化规则

建议把所有 delta 放进一个表驱动结构，便于测试和调参。

示例：

```python
EVENT_DELTAS = {
    "gratitude": {"safety": 3, "closeness": 2, "energy": 1, "mood": "开心"},
    "boundary_push": {"boundary_pressure": 8, "safety": -3, "energy": -2, "mood": "烦躁"},
    "apology": {"boundary_pressure": -6, "safety": 3, "closeness": 1, "mood": "平静"},
    "repair": {"boundary_pressure": -4, "safety": 2, "closeness": 1, "mood": "平静"},
    "comfort": {"safety": 3, "closeness": 1, "energy": 1, "mood": "平静"},
    "positive_closure": {"boundary_pressure": -2, "energy": 2, "mood": "平静"},
    "rest_request": {"boundary_pressure": 2, "energy": 3, "mood": "平静"},
    "low_energy_share": {"energy": -1, "safety": 1, "mood": "低落"},
}
```

注意：

- `rest_request` 不应被理解为负面拒绝。它更多是降低主动性、尊重结束。
- `low_energy_share` 是用户低能量，不应直接让 bot 防御。
- `apology` 不应一次性清空所有边界压力，应逐步恢复。

## 六、时间恢复和衰减

### 1. 触发时机

建议在每次加载状态后、应用新事件前调用：

```python
state_engine.apply_time_decay(state, now=time.time())
```

适用入口：

- `capture_private_message()`
- `inject_companion_context()`
- `/cp_status`
- Debug API state

为了避免只查看状态就频繁写库，可以：

- capture 时一定保存 decay 后状态。
- inject 时如果变化超过阈值再保存。
- command/debug 可只展示计算后的状态，或保存也可以接受。

### 2. 能量恢复

建议规则：

- 每小时恢复 4 到 8 点。
- 上限 70 或 80，不自动恢复到极高。
- 如果边界压力很高，能量恢复速度降低。

示例：

```text
hours = elapsed_seconds / 3600
recovery = hours * 6
if boundary_pressure > 60:
    recovery *= 0.5
energy = min(80, energy + recovery)
```

### 3. 边界压力下降

建议规则：

- 每小时下降 1 到 2 点。
- 正向事件可额外下降。
- 如果安全感低于 25，下降速度降低。

示例：

```text
boundary_pressure -= hours * 1.5
```

### 4. 亲近度冷却

建议规则：

- 24 小时内不冷却。
- 超过 3 天未互动，每天下降 0.2 到 0.5。
- 不低于由熟悉度决定的关系底色。

阶段 2 可先实现极轻量版本：超过 7 天无互动时，closeness 每天下降 0.3。

## 七、沉默机制重构

### 1. 模式定义

替换当前强烈的模式文案，保留分级：

- `mild_conserve`：能量偏低，回复短一点，少追问。
- `defensive_conserve`：边界压力高，礼貌、短、不主动延伸。
- `rest_closure`：能量很低或用户要求结束，允许一句话结束对话。

### 2. 触发条件

建议：

```python
if state.energy < 22:
    return "rest_closure"
if state.boundary_pressure >= boundary_threshold:
    return "defensive_conserve"
if state.energy < energy_threshold:
    return "mild_conserve"
```

如果最近事件是 `rest_request` 或 `positive_closure`，也可以进入 `rest_closure`。

### 3. 注入文案

示例：

```xml
<companion_boundary>
当前互动能量偏低。请明显缩短回复，少追问，不主动开启新话题。
如果用户没有明确要求继续，可以用一句温和的话自然收束。
</companion_boundary>
```

避免使用：

- “安全感极低”。
- “冷淡、疏离”。
- “1-2 个字即可”。

这些词容易造成突兀人格变化。

## 八、上下文构建重构

文件：建议新增 `context_builder.py`

目标：把 `main.py._build_context_text()` 移出主类，降低主类复杂度。

建议输出结构：

```xml
<companion_context>
当前关系：熟人偏亲近，信任稳定。
当前相处姿态：温和自然，保持适度主动。
当前状态：互动能量正常，边界压力低。
表达偏好：回复偏简短，语气自然，少连续追问。
回应建议：先承接用户当前内容，不要直接暴露这些状态描述。
</companion_context>
```

设计原则：

- 数值只用于内部判断，不直接注入。
- 优先注入行为建议，而不是抽象标签。
- 不把状态写成命令式人格覆盖。
- 控制长度，遵守 `max_context_chars`。

## 九、存储迁移

阶段 2 建议给 `companion_state` JSON 增加字段，而不是改表结构。

新增字段：

- `last_state_updated_at`
- `last_event_reason`
- `last_reflection_summary`

兼容策略：

- `from_dict()` 对缺失字段使用默认值。
- `to_dict()` 写出新字段。
- 不需要 SQL migration。

## 十、测试方法

### 1. 单元测试建议

建议新增或扩展 pytest 覆盖：

- `EventEngine.classify()` 能识别 apology、repair、comfort、rest_request、low_energy_share。
- `StateEngine.apply_event()` 对每种事件产生预期 delta。
- `StateEngine.apply_time_decay()` 会恢复 energy。
- `StateEngine.apply_time_decay()` 会降低 boundary_pressure。
- 长时间不互动时 closeness 轻微冷却。
- `SilenceMechanism.check()` 返回正确模式。
- `ContextBuilder.build()` 不包含裸数值和内部字段名。

### 2. 手动验证场景

场景 A：边界压力恢复。

步骤：

1. 发送“别烦”。
2. 查看边界压力上升。
3. 发送“抱歉，刚才语气不好”。
4. 查看边界压力下降、安全感回升。

期望：

- 不会一直防御。
- 最近事件显示 apology。

场景 B：能量恢复。

步骤：

1. 连续快速发送多条消息，让 `active_chat` 触发。
2. 查看 energy 下降。
3. 手动修改 `last_state_updated_at` 为一小时前，或等待足够时间。
4. 再查看状态。

期望：

- energy 自动恢复一部分。

场景 C：用户要求结束。

步骤：

1. 发送“今天先不聊了，你休息吧”。
2. 触发 LLM 回复。

期望：

- 注入 `companion_boundary`。
- 建议短回复、自然收束。
- 不把该事件判定为强负面边界冲突。

场景 D：沉默文案自然性。

步骤：

1. `/cp_silent` 进入低能量。
2. 触发 LLM 回复。

期望：

- 注入文案是“收敛、少追问、可自然结束”。
- 不出现“冷淡疏离”“安全感极低”等突兀指令。

场景 E：上下文不暴露数值。

步骤：

1. 打开 debug 或日志查看注入文本。

期望：

- 不包含 `familiarity=xx`、`boundary_pressure=xx` 这类裸数值。
- 只包含自然语言关系和相处建议。

### 3. 回归验证

确认阶段 1 能力不退化：

- 未绑定 UID 不处理。
- 绑定 UID 正常捕获和注入。
- 缓冲上限仍生效。
- 反思失败不清空缓冲。
- 反思任务仍按用户去重。

## 十一、完成标准

阶段 2 完成后，应满足：

- 状态变化具备恢复路径，不再只涨不降。
- 时间经过会自然恢复能量和降低边界压力。
- 用户道歉、缓和、安慰能影响状态。
- 沉默机制表达更自然，默认只做软收敛。
- LLM 上下文注入更像相处建议，而不是内部状态报告。
- Debug 和命令能解释当前姿态来源。
- 代码结构为阶段 3 的每日情感弧线提供清晰输入：事件、状态、原因、更新时间。
