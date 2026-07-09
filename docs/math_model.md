# CompanionLite 关系状态数学建模

> 本文档把精力、熟悉度、亲近度、边界压力四个核心指标的完整数学模型从代码中抽象出来，作为独立的分析与升级基准。
> 代码实现以 `state_engine.py` 为准；本文档与之对齐，参数有变动时两边同步。

## 总览

四个指标各有三个驱动来源，叠加后经 `clamp()` 钳制到取值范围：

```
状态值(t) = clamp( 状态值(t-1) + 事件delta + 时间衰减 + LLM反思delta )
```

| 指标 | 范围 | 事件驱动 | 时间演化 | LLM反思 |
|------|------|---------|---------|---------|
| 精力 energy | [10, 90] | 聊天消耗/休息恢复 | 非线性四段自然演化 | 可调 |
| 熟悉度 familiarity | [0, 100] | 互动积累 | 随熟悉度分档衰减 | 可调 |
| 亲近度 closeness | [-50, 100] | 关系事件升降 | 朝下限衰减 | 可调 |
| 边界压力 boundary_pressure | [0, 100] | 越界升高/修复降低 | 分档衰减 | 可调 |

另有 safety（[0,100]）和 mood（枚举），已降级为观测量，不直接参与姿态/边界/沉默决策，但仍被事件更新和衰减。

---

## 1. 精力 energy

### 1.1 取值范围与钳制

`clamp(energy, 10, 90)`

下限 10 保证 bot 永远能产出极简回复（不会完全失能）；上限 90 留出"非常精神"的头部空间。

### 1.2 事件驱动

每个事件类型对精力的基础 delta（`EVENT_DELTAS`）：

| 事件类型 | energy 基础 delta | 方向 |
|---------|------------------|------|
| gratitude | +1.0 | 正向 |
| comfort | +1.0 | 正向 |
| positive_closure | +2.0 | 正向 |
| rest_request | +3.0 | 正向（最大回血） |
| active_chat | -1.0 | 负向 |
| deep_sharing | -1.0 | 负向 |
| boredom | -3.0 | 负向（最大消耗） |
| boundary_push | -2.0 | 负向 |

事件 delta 进入 `_shape_event_deltas` 后依次经过三道调制：

**调制 A：习惯化 habituation**

对 prosocial / intimacy / repair 三类事件生效。连续同类事件按重复次数衰减：

```
factor = HABITUATION[min(repeat_index, 3)]
HABITUATION = (1.0, 0.6, 0.35, 0.2)
```

- 第 1 次：×1.0（全额）
- 第 2 次：×0.6
- 第 3 次：×0.35
- 第 4 次及以后：×0.2

对 energy 的效果：正向回血被习惯化削弱（连续感谢越来越不回血），负向消耗不受 habituation 影响（边界压力的负向 delta 才参与 habituation，energy 的负向不参与）。

**调制 B：置信度折算**

`event.confidence < 1.0` 时，正向 delta 乘以 confidence（长文本/粘贴类降权 0.8、active_chat 降权 0.7）；负向 delta 不打折。

**调制 C：能量分段双向调制**（`_apply_energy_tier_to_consumption`）

按当前 energy 所在区间，对最终 energy delta 乘以系数，**正负向都生效**：

| energy 区间 | 负向 delta 系数（消耗） | 正向 delta 系数（回血） | 语义 |
|------------|----------------------|----------------------|------|
| >70 高能 | ×2.0 | ×0.0 | 活跃消耗大，且不再被推高 |
| 55-70 中高 | ×1.0 | ×0.3 | 正常消耗，回血已大幅削减 |
| 30-55 中低 | ×0.6 | ×0.8 | 累了消耗减轻，回血接近全额 |
| <30 开摆 | ×0.3 | ×1.0 | 几乎不再多耗，回血全额 |

设计意图：高能区只升不降被堵死——负向消耗加倍、正向回血归零，配合自然下滑确保能量不会恒定在高位。

**调制 D：高频聊天微消耗**（`_apply_active_chat_drain`）

在调制 A-C 之后、`_apply_deltas` 之前注入。距上一条消息 <2 分钟时视为密集对话，每条额外随机扣精力：

```
if energy > 30 and (now - last_state_updated_at) < 120秒:
    drain = random.uniform(0.30, 0.60)   # 期望 ≈0.45/条
    energy_delta -= drain
```

- 期望：24 条密集消息掉约 11 点（范围 7-14），40 条掉约 18 点（范围 12-24）。
- 开摆区（energy ≤ 30）豁免——累了就不追着扣了。
- 与事件本身的 energy delta 叠加（active_chat 事件还有 -1 × 分段系数），二者独立。
- 随机性让消耗有自然波动，不机械。

**为什么需要调制 D**：时间衰减（调制外的 `_energy_natural_delta`）在高频聊天时单条影响极小（间隔 30 秒时仅 -0.025），即使修了防抖门槛冻住的 bug，纯靠时间衰减 20 轮也才掉 0.5 点。高频微消耗补上这个体感缺口，让密集聊天能真实地"耗神"。

**调制 E：活跃回血冷却**（`apply_time_decay` 内）

自然回血在活跃聊天期间被冻结——你在聊天不在休息，不该边聊边回血：

```
chat_gap = now - last_state_updated_at
if energy_delta > 0 and chat_gap < 900秒(15分钟):
    energy_delta = 0.0
```

- 15 分钟冷却期：哪怕中间停了几分钟，只要还没静下来够久就不回血。
- 只有正向 delta 被冻结；高能区下滑（负向）不受影响，该掉还是掉。
- 实测效果：24 轮 40 分钟从 70 降到 ~59（微消耗 10.8 + 事件消耗，无回血补偿），而非旧版的只降到 65。

### 1.3 时间演化（非线性四段模型）

`apply_time_decay` 在每次状态加载时调用，计算自上次更新以来的自然变化：

```
hours = (now - last_state_updated_at) / 3600
```

能量非线性 delta 不受 `hours < 0.05`（3分钟）防抖门槛限制——高频聊天时恰恰是最该消耗的场景：

```
           energy > 70:  delta = -3.0 * hours,  target = 65  (高能下滑)
 55 < energy <= 70:      delta = +2.0 * hours,  target = 70  (中高微恢复)
 30 < energy <= 55:      delta = +1.5 * hours,  target = 55  (中低慢恢复)
      energy <= 30:      delta = +0.5 * hours,  target = 30  (开摆稳态)
```

收敛规则（不冲过 target）：
- 若 delta > 0：`delta = min(delta, max(0, target - energy))`
- 若 delta < 0：`delta = max(delta, min(0, target - energy))`

边界高压修正：若 `boundary_pressure > 60` 且 delta > 0（恢复中），`delta *= 0.5`——高压状态下恢复减半。

### 1.4 LLM 反思驱动

深度反思返回 `energy_delta`（-10 到 +10），经两层处理：

**消毒层**（`sanitize_reflection_result`）：
- 若反思摘要含"用户困/累/想睡"但不含"Bot/bot/机器人/助手"，且 energy_delta < 0，则强制改为 0（用户累不该让 bot 累）。

**正向上限**（`_clamp_reflection_energy_delta`）：
- 正向 energy delta 硬上限 +2（`REFLECTION_ENERGY_POSITIVE_CAP`）。
- 语义：消耗是累加的（15 轮 × -1 = -15），负向 -10 合理；恢复是时间函数，不是瞬间事件，正向不该像"喝红牛"一口气跳 +6。
- 一个体贴的周期应让后续自然恢复速率变快，而不是瞬间加一大截。

**分段调制**（`_apply_energy_tier_to_consumption`）：
- 与事件路径走**完全相同的分段双向调制**（调制 C），确保反思路径不会绕过高能区回血归零的设计。
- 高能区（>70）反思正向回血 ×0.0 → 配合 +2 上限，双重堵死。

### 1.5 传导到回复

**`_energy_text`（注入 LLM 的文字描述）**：

阈值与实际可达范围对齐。稳态天花板 70，事件推高峰值 ~71，密集聊天谷底 ~30：

| energy | 文字 | 回复效果 |
|--------|------|---------|
| ≤30 | 很低，已经累了，话会变少、想收着聊 | 沉默机制强制简短 |
| 31-42 | 偏低，有点累，倾向简短回应 | LLM 自然收短 |
| 43-55 | 普通，可以正常聊 | 正常 |
| 56-68 | 稳定，状态不错 | 正常偏活跃 |
| ≥69 | 充足，很有精神 | 活跃（短暂峰值，不持续） |

**`explain_posture`（总体回复基调）**：

| 条件 | 基调 |
|------|------|
| energy ≤ 30 | 低能量：温和简短，可以结束话题，不要开启新话题 |
| energy ≤ 42 | 微疲：回复保持自然但偏短，少追问，不主动展开新话题 |

**`SilenceMechanism.check`（硬阈值沉默）**：

| 条件 | 模式 |
|------|------|
| energy < 25 且 mood ∈ {疲惫, 低落} | tired_low（温柔简短） |
| energy < 25 | low_energy（简短，暗示想休息） |

---

## 2. 熟悉度 familiarity

### 2.1 取值范围

`clamp(familiarity, 0, 100)`，恒非负。

### 2.2 事件驱动

| 事件类型 | familiarity 基础 delta |
|---------|----------------------|
| deep_sharing | +1.5 |
| affection | +0.3 |
| gratitude | +0.2 |
| active_chat | +0.08 |
| neutral | +0.08 |
| 低熟悉度 affection（<8） | max(0.2, ...) |

调制链（正向 familiarity 才走）：

**调制 A：日增长乘数**

```
growth_multiplier = 1.0 + min(today_messages, 100) / 500.0
```

当天聊得越多，单次增长越快（最多 ×1.2），模拟"聊得多关系升温快"。

**调制 B：饱和乘数**（`_saturation_multiplier`）

| familiarity | 乘数 |
|------------|------|
| <0（不可能，恒非负） | 1.0 |
| <30 | 1.0 |
| 30-60 | 0.65 |
| 60-80 | 0.35 |
| ≥80 | 0.15 |

越高越难涨——防止 familiarity 线性冲顶。

**调制 C：日上限**

```
familiarity_delta = min(delta, DAILY_FAMILIARITY_CAP - today_familiarity_gain)
DAILY_FAMILIARITY_CAP = 15.0
```

每天最多涨 15 点，无论聊多少。`today_familiarity_gain` 每天重置（`_roll_active_day`）。

### 2.3 时间演化（衰减）

```
familiarity_delta = -(hours/24) * familiarity_decay_per_day
```

衰减速率按当前熟悉度分档（越熟悉衰减越慢——熟人不会因为几天没聊就变陌生人）：

| familiarity | 每日衰减 |
|------------|---------|
| <15 | 1.2 |
| 15-35 | 0.7 |
| 35-65 | 0.25 |
| ≥65 | 0.08 |

衰减受 `hours < 0.05` 防抖门槛保护，短间隔不反复扣。

### 2.4 LLM 反思

返回 `familiarity_delta`（0-5），经 `_shape_reflection_deltas`：
```
delta = min(delta * saturation_multiplier(familiarity), DAILY_FAMILIARITY_CAP - today_familiarity_gain)
```
与事件驱动共享饱和乘数和日上限。

---

## 3. 亲近度 closeness

### 3.1 取值范围

`clamp(closeness, -50, 100)`。允许负值，负值表示疏离/排斥，区别于"不熟悉"。

### 3.2 事件驱动

| 事件类型 | closeness 基础 delta |
|---------|---------------------|
| affection | +2.0 |
| deep_sharing | +1.2 |
| gratitude | +1.2 |
| comfort | +0.8 |
| apology / repair | +0.6 |
| boundary_push | -2.0 |
| 低熟悉度 affection（familiarity<8） | -1.5（过早亲近反而疏离） |
| 有压力/疏离时的 affection | min(原值, -0.8)（门控为压力） |

特殊门控逻辑（`_shape_event_deltas`）：

- **低熟悉度亲密**（familiarity < 8）：affection 的 closeness 强制为 -1.5，safety -1.0，boundary_pressure ≥4.0——"刚认识就说喜欢"被视为越界。
- **有压力时的亲密**（boundary_pressure > 25 或 closeness < 0）：affection 的 closeness 强制 ≤ -0.8——已有冲突时亲密表达被当作压力。
- **修复限速**（apology/repair）：
  - 无冲突背景（bp<5 且周期无负向 且 closeness≥0）：按礼貌用语，closeness ≤0.2，不产生修复收益。
  - 有冲突背景：boundary_pressure 负向 delta 乘以 `_repair_multiplier`：
    - cycle_negative_weight ≥3.0：×0.25
    - cycle_negative_weight ≥1.0：×0.4
    - 否则：×1.0
  - closeness < 0 时修复最多 +1.0（疏离只能逐步恢复）。

正向 closeness 调制：

**调制 A：低熟悉度+高压封顶**

```
if familiarity < 10 and boundary_pressure > 25:
    closeness_delta = min(delta, 0.3)
```

**调制 B：饱和乘数**（同 familiarity 的 `_saturation_multiplier`）

**调制 C：日上限**

```
closeness_delta = min(delta, DAILY_CLOSENESS_CAP - today_closeness_gain)
DAILY_CLOSENESS_CAP = 18.0
```

### 3.3 时间演化

```
closeness_floor = min(20.0, familiarity * 0.35)
```

closeness 的下限随 familiarity 上升——越熟悉的人，亲近度的自然下限越高（不会因为没聊就降到陌生人水平）。

- **正亲近度衰减**：`delta = -(hours/24) * closeness_decay_per_day`，衰减到 `closeness_floor` 为止。
- **负亲近度恢复**：`delta = +(hours/24) * 0.8`，朝 0 缓慢恢复（疏离会随时间淡化）。

衰减速率按 familiarity 分档：

| familiarity | closeness 每日衰减 |
|------------|-------------------|
| <15 | 3.5 |
| 15-35 | 2.2 |
| 35-65 | 1.0 |
| ≥65 | 0.35 |

### 3.4 传导到回复

**`relationship_label`**：

| 条件 | 关系标签 |
|------|---------|
| closeness ≤ -35 | 强排斥 |
| closense < 0 | 疏离 |
| boundary_pressure ≥ 65 | 防御 |
| boundary_pressure ≥ 40 | 紧张 |
| closeness ≥ 70 且 bp < 15 | 亲近 |
| familiarity ≥ 55 | 熟人 |
| familiarity ≥ 25 | 认识 |
| else | 刚认识 |

**`boundary_stance`**：

| 条件 | 相处姿态 |
|------|---------|
| closeness ≤ -35 | 强边界 |
| closeness < 0 | 防御 |
| boundary_pressure ≥ 65 | 强边界 |
| boundary_pressure ≥ 40 | 防御 |
| boundary_pressure ≥ 22 | 谨慎 |
| closeness ≥ 45 且 bp < 10 | 放松 |
| else | 正常 |

**`explain_posture`**（closeness 相关部分）：

| 条件 | 基调 |
|------|------|
| closeness ≤ -35 | 强排斥：不要主动靠近，不开玩笑，不暧昧，不追问；只做必要回应 |
| closeness < 0 | 疏离收敛：保持礼貌距离，避免亲昵称呼和主动延展 |
| closeness ≥ 45 且 bp < 15 | 放松亲近：可以自然接话，允许轻微主动延伸 |

---

## 4. 边界压力 boundary_pressure

### 4.1 取值范围

`clamp(boundary_pressure, 0, 100)`，恒非负。

### 4.2 事件驱动

| 事件类型 | boundary_pressure 基础 delta |
|---------|------------------------------|
| boundary_push | +8.0 |
| rest_request | +2.0（礼貌收束也微增压力） |
| apology | -6.0 |
| repair | -4.0 |
| positive_closure | -2.0 |
| 低熟悉度 affection（<8） | max(4.0, ...) |
| 有压力时的 affection | max(2.0, ...) |

特殊调制：

**负向敏化**（重复越界加重）：

```
sensitization = 1.0 + 0.3 * min(cycle_boundary_hits, 3)
boundary_pressure_delta *= sensitization
```

周期内重复越界：第 2 次 ×1.3，第 3 次 ×1.6，第 4 次+ ×1.9。

**修复限速**（见 3.2）：负向 delta 乘以 `_repair_multiplier`，防止连发道歉快速洗白。

### 4.3 时间演化（分档衰减）

```
boundary_pressure_delta = -hours * boundary_decay_rate
```

衰减速率按当前压力分档（高压留痕更久）：

| boundary_pressure | 每小时衰减 |
|-------------------|-----------|
| >50 | 1.0 |
| 25-50 | 2.0 |
| <25 | 3.5 |

### 4.4 传导到回复

见 3.4 的 `boundary_stance` 和 `explain_posture`。

**`SilenceMechanism.check`**：

| 条件 | 模式 |
|------|------|
| bp ≥ max(75, threshold+15) | strong_boundary（极简克制） |
| bp ≥ threshold（默认60） | defensive（简短不延伸） |

---

## 5. 周期系统（影响事件调制）

周期是"最近一批消息"的滚动窗口，反思后重置。周期状态影响事件调制和即时指导。

### 5.1 周期权重累积（`_update_cycle_state`）

每条消息按事件类别累积周期权重：

| 事件 | 负向权重 | 正向权重 | 修复权重 | hits |
|------|---------|---------|---------|------|
| boundary_violation | +3.0 | - | - | boundary+1 |
| 低熟悉度/有压力的 affection | +2.0/+1.5 | - | - | boundary+1 |
| prosocial | - | +0.8 | - | - |
| repair | - | - | +0.6×repair_multiplier | repair+1 |
| rest_request/low_energy_share | - | +0.2 | - | - |
| 其他 withdrawal | +0.5 | - | - | - |
| neutral | - | +0.05 | - | - |

修复时负向权重同步下降：`negative -= repair_gain * 0.4`

### 5.2 周期主导判定（`_refresh_cycle_instruction`）

| 条件 | dominant | 指导基调 |
|------|----------|---------|
| negative ≥ 3.0 | cooldown | 礼貌距离，不接暧昧 |
| negative ≥ 1.5 | cautious | 礼貌简短，少追问 |
| repair > 0 且 boundary_hits > 0 | repairing | 谨慎接受，不立即亲近 |
| positive ≥ 2.0 且 negative ≤ 0.1 | warm | 自然接话，略微柔和 |
| else | normal | 自然回应 |

### 5.3 习惯化

连续同类正向事件衰减：

| repeat_index | factor | 适用类别 |
|-------------|--------|---------|
| 0（首次） | 1.0 | prosocial / intimacy / repair |
| 1 | 0.6 | |
| 2 | 0.35 | |
| 3+ | 0.2 | |

---

## 6. 陪伴模式 /bond

一次性抬底，不锁死，后续仍可自然演化：

```
bonded = True
familiarity = max(familiarity, bond_familiarity_floor)       # 默认 55
closeness = max(closeness, bond_closeness_floor)             # 默认 50
boundary_pressure = min(boundary_pressure, bond_boundary_ceiling)  # 默认 15
# energy 完全不碰
```

`/unbond` 只清 `bonded = False`，不压任何值。

---

## 7. 已知设计张力与可调点

以下是需要持续观察或可升级的方向：

**精力**：
- 高能区衰减 -3/h 在高频聊天（间隔秒级）时单条影响极小，已由高频微消耗（调制 D）补上体感缺口；若仍觉得"掉太慢"，可提高 `ACTIVE_CHAT_ENERGY_MAX` 或缩小 `ACTIVE_CHAT_WINDOW_SECONDS`。
- 正向回血在 >70 归零，意味着高能时休息/感谢完全不能回血——如果希望"温和的关心仍能维持高能"，可把系数从 0.0 改为 0.1。
- 开摆区 target=30 意味着 energy 不会自然跌破 30；若想让 bot 有"彻底累垮"的状态，可降低 target 或引入连续聊天时的额外下推。
- 高频微消耗 uniform(0.30, 0.60) 的随机范围可调；若想让消耗更可预测，可改为固定值或收窄区间。
- 活跃回血冷却 `ENERGY_RECOVERY_COOLDOWN_SECONDS = 900`（15分钟）：若觉得"停 5 分钟就该开始恢复"，可缩短；若觉得"短暂沉默不该回血"，可延长。
- 反思正向 energy delta 上限 +2（`REFLECTION_ENERGY_POSITIVE_CAP`）：若觉得"体贴的周期该恢复更多"，可调到 +3，但不宜超过单条 rest_request 的 +3，否则反思比明确休息还猛。
- 传导档位阈值（≤42/≤55/≤68/≥69）对齐实际可达范围 30-71；若调整了稳态 target 使可达范围变化，这些阈值要同步复核。

**熟悉度**：
- 日上限 15 配合饱和乘数，高熟悉度（>80）时几乎停滞；若觉得"老朋友也该有缓慢增长"，可放宽 >80 的饱和乘数。
- 衰减在 ≥65 时仅 0.08/天，几乎不衰减；这是有意为之（熟人不会忘），但长期不聊的关系完全不降温可能不符合预期。

**亲近度**：
- 负亲近度恢复速率 0.8/天 是恒定的，不随疏离程度调整；若希望"强排斥恢复更慢"，可对 closeness ≤ -35 降速。
- closeness_floor = familiarity × 0.35 意味着高熟悉度必然有较高亲近度下限；若想允许"很熟但很疏"的组合，需要解耦这个 floor。

**边界压力**：
- 高压衰减 1.0/h 意味着大冲突约 50 小时自然消退；若觉得"记仇太久"或"忘太快"，调这个分档。
- 敏化上限 ×1.9 在 cycle_boundary_hits ≥3 时封顶；若希望重复越界更严厉，提高 0.3 系数或提高 min 上限。

**周期**：
- 周期权重在反思后重置，意味着"一次反思清零所有周期累积"；若希望周期有惯性，重置时只衰减而非清零。
