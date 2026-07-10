# CompanionLite 瘦身执行计划（Slim Execution Plan）

> 状态：历史执行记录。P3 每日弧线已被 `docs/session-arc-and-interaction-profile-design.md` 完全替代；当前动力学以 `docs/math_model.md` 和 `docs/lightweight-dynamics-evolution-plan.md` 为准。
> 决策日期：2026-07-08
> 项目定位：纯个人实验。
> 路线结论：P2/2.5 减法冻结 → 瘦身 P3 → 瘦身 P4（待 P3 验证通过）→ P5 无限期搁置。

本文档保留用于追溯早期瘦身决策，不再作为当前实现说明。`docs/oldplan/` 同样仅供历史参考。

> 2026-07-10 补充决策：状态层仍不做无边界扩张，但允许修复确定性缺陷；未来动力学升级以 `docs/lightweight-dynamics-evolution-plan.md` 为评审基准，不视为对本计划的默认解冻。

---

## 一、背景与决策记录

### 1.1 当前现状（2026-07-08 盘点）

- 代码约 2050 行，P1 / P2 / P2.5 已实现且与文档一致。
- `CompanionState` 共 38 个字段，其中周期态势 14 个字段。
- 注入侧存在三套模板（LLM 周期策略 / 规则完整指导 / 规则简化提醒）+ 固定块。
- P3 / P4 / P5 只有文档（约 1020 行），未实现。
- `state.py` 中存在约 100 行死代码（旧 `RuleEngine`、旧 `CompanionState.apply_event()`），已被 `events.py` / `state_engine.py` 取代，`main.py` 不再调用。

### 1.2 核心判断

外部评估（"其他模型的建议"）与代码盘点得出一致结论：

1. **结构化会话弧线 + 跨会话连续性是本插件不可替代的部分。** LLM 上下文和长期记忆能提供聊过什么，但不负责记录关系状态差、峰值、转折和规则 outcome；当前实施基准见 `docs/session-arc-and-interaction-profile-design.md`。
2. **P2 / P2.5 是基础设施，且已经过重。** 状态引擎属于"可被别人做掉的公共地"，不值得继续加厚。
3. **面板的价值在调参验证，不在展示。** 可调面太大反而看不过来，需要收窄。

### 1.3 SylannEngine 评估结论：不集成，只当参照物

SylannEngine（`plugins/SylannEngine-main`）是一个从陪伴 bot 剥离出来的情感动力学计算 SDK（约 1.9 万行核心代码、650+ 测试、mypy strict），它做的事恰好是 P2/P2.5 的"公理化加强版"：状态惯性、时间衰减、相变表达、不可逆伤疤、人格漂移。

**不集成的理由：**

| 顾虑 | 具体 |
|---|---|
| 依赖风险 | 单人项目、正在剧烈重构（v2.5 刚删除了原核心的 Kuramoto 共振机制），API 随时可能变 |
| 成本模型不符 | 其语义评估器需要每条消息一次 LLM 调用（降级只有关键词规则）；本插件是每条 ~1ms 正则 + 低频反思 |
| 哲学不符 | 其伤疤不可逆（公理保证"回不去"）；本插件是"原谅要慢但可修复"，陪伴场景更合适 |
| 许可证 | AGPL-3.0，且作者声明不希望商用 |
| 复杂度倒挂 | 用 1.9 万行引擎替换 400 行的 state_engine 去支撑一个 Lite 插件，方向相反 |

**关键佐证：** SylannEngine 自己也不做 P3/P4 的事——它只输出数值化 Surface，"拿到状态之后怎么指导回复"留给消费方。这恰好验证了弧线→连续性→自然语言姿态注入这一层是真正的空白。

**可借鉴的设计思想（后续调参时参考，不引入代码）：**

- 时间衰减曲线的分档设计（其人格漂移用双速率 EMA + 恒稳态回复力）。
- 演化安全机制：震荡检测冻结、速率上限、深层约束表层。本插件如果未来做长期偏好演化，应对标这套防护。
- "虚空计算"思想：把沉默 / 缺席当作主动信号。本插件的 `time_decay` 已有雏形，未来 DailyArc 可考虑记录"今天没聊"也是一种弧线。

---

## 二、第一步：P2 / P2.5 减法与冻结

预计工作量：半天到一天。目标：删死代码、收窄调参面、冻结状态层。

### 2.1 删除死代码

删除前置检查（已于 2026-07-08 确认，执行时建议复查一遍）：

```text
grep "RuleEngine" main.py     -> 无引用
grep "apply_event" main.py    -> 只有 state_engine.apply_event（main.py:326）
```

删除内容：

1. `state.py:283-329`：旧 `RuleEngine` 类整体删除。
   - 已确认：`EventEngine`（`events.py:62`）有自己的 `apply_style_update`，`main.py:327` 调用的是 `EventEngine` 版本，旧 `RuleEngine` 无任何引用，可整体删除。
2. `state.py:72-133`：旧 `CompanionState.apply_event()` 方法（已由 `state_engine.py:89` 的 `StateEngine.apply_event()` 取代）。
3. 删除后运行插件冒烟验证：加载 → 发消息 → 触发注入 → Debug 页面正常。

### 2.2 收窄调参面（改角色，不删字段）

原则：**不动数据结构、不做存储迁移**，只改变字段在决策逻辑中的角色。

| 角色 | 字段 | 含义 |
|---|---|---|
| 活跃三维 | `closeness`、`boundary_pressure`、`energy` | 继续参与门控、周期权重、姿态判定；调参只盯这三个 |
| 只读底色 | `familiarity` | 保留（它是过早亲密门控的输入），但不再为它调参、不再调整其衰减曲线 |
| 降级观测 | `safety`、`mood` | 保留展示与事件更新，但从姿态判定条件中移出 |

具体改动点：

1. `state_engine.py:370-383` `explain_posture()`：

```python
# 改动前
if state.boundary_pressure >= 65 or state.safety <= 25:
    return "强收敛：极少追问，不主动延展，优先尊重边界。"
...
if state.safety >= 72 and state.closeness >= 45:
    return "放松亲近：可以自然接话，允许轻微主动延伸。"

# 改动后（safety 移出判定，由 boundary_pressure / closeness 单独承担）
if state.boundary_pressure >= 65:
    return "强收敛：极少追问，不主动延展，优先尊重边界。"
...
if state.closeness >= 45 and state.boundary_pressure < 15:
    return "放松亲近：可以自然接话，允许轻微主动延伸。"
```

2. `state.py` `relationship_label()`（135-150 行）：同理移除 `safety <= 25`、`safety >= 70` 条件，改用 `boundary_pressure` / `closeness` 表达。

3. `state.py` `boundary_stance()`（152-165 行）：移除三处 safety 条件（`safety <= 25`、`safety <= 40`、`safety >= 72`），阈值由 `boundary_pressure` 分档承担：

```python
# 改动后建议分档
closeness <= -35            -> STRONG
closeness < 0               -> DEFENSIVE
boundary_pressure >= 65     -> STRONG
boundary_pressure >= 40     -> DEFENSIVE
boundary_pressure >= 22     -> CAUTIOUS
closeness >= 45 且 boundary_pressure < 10 -> RELAXED
其他                        -> NORMAL
```

4. `state_engine.py` 的 `EVENT_DELTAS`、时间衰减中的 safety 逻辑**保持不动**（safety 继续被事件更新和衰减，只是不参与决策）。这样未来如果想恢复 safety 参与决策，数据是连续的。

5. Debug 面板（`pages/debug/index.html`）：在 safety 和 mood 的展示位置标注"观测量（不参与姿态判定）"。

### 2.3 调参后回归口径

改完 2.2 后，用以下场景手动回归，确认行为不劣化：

- 低熟悉度突然表白 -> 仍进入 premature_intimacy 门控（此路径不依赖 safety）。
- 连续 boundary_push -> 姿态进入强收敛（现在由 `boundary_pressure >= 65` 单独触发）。
- 长期正常互动 -> 能到达"放松亲近"（新条件 `closeness >= 45 且 boundary_pressure < 15`）。
- 道歉 / 修复 -> 边界压力下降、姿态回落（不依赖 safety）。

### 2.4 可信度强化（2026-07-08 追加）

在冻结前对现有逻辑做最后一轮"拟真可信"修正。原则：**不加新功能、不加新模板、不加 LLM 调用**，只修正分类器盲区和动力学不对称性。每项都对应一个可复现的失真场景。合计约 60-80 行改动。

#### 2.4.1 输入层：分类器可信度（`events.py`）

分类错一次，状态、周期、注入整条管线都在放大错误，所以这层优先级最高。

**A. 否定前缀防误判（最重要）。**

失真场景："我不喜欢你这样" -> 命中"喜欢" -> affection；"别说抱歉了" -> apology；"我没生气，不用走开" -> boundary_push。

实现：`classify` 中命中关键词后，检查关键词在原文中位置的前 3 个字符是否含否定词，命中则跳过该关键词继续匹配：

```python
NEGATION_PREFIXES = ("不", "别", "没", "无", "非", "莫", "勿", "不要", "不是", "没有", "别说")

@staticmethod
def _negated(lower: str, keyword: str) -> bool:
    idx = lower.find(keyword)
    while idx != -1:
        prefix = lower[max(0, idx - 3): idx]
        if not any(prefix.endswith(neg) for neg in NEGATION_PREFIXES):
            return False  # 存在一处非否定命中，按命中处理
        idx = lower.find(keyword, idx + 1)
    return True  # 所有命中位置都被否定
```

`any(keyword in lower ...)` 改为 `any(keyword in lower and not cls._negated(lower, keyword) ...)`。
注意：boundary_push 类保持从严——"不想聊"本身就在关键词表里且以"不"开头，`find` 定位的是整个关键词，不会被自己的首字误伤；但需在回归中验证"没有不想聊"这类双重否定按保守方向（不触发）处理即可，不追求完美。

**B. 清理过敏关键词。**

- BOREDOM 删除"哎"（"哎对了"日常转折词，误伤率极高），保留"无聊/没意思/好闲/好闷"。
- STYLE_DIRECT 删除"直接"（"我直接去睡了"误判），删除死键 `" blunt"`；保留"直说/别绕/实诚"，新增"打直球"。
- POSITIVE_CLOSURE 的"晚安"保留，但 AFFECTION 与 POSITIVE_CLOSURE 同时命中时（如"爱你晚安"）优先 positive_closure（调整 checks 顺序：positive_closure 提到 affection 之前）。

**C. deep_sharing 收紧。**

失真场景：贴 200 字代码/日志/链接 = "深度分享"白拿熟悉度。

实现：长度达标后追加内容启发式——中文字符占比 < 40%，或包含 "```"、"http://"、"https://"、行数 >= 8 时，降级为 neutral：

```python
@staticmethod
def _looks_like_paste(text: str) -> bool:
    if "```" in text or "http://" in text or "https://" in text:
        return True
    if text.count("\n") >= 8:
        return True
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk / max(1, len(text)) < 0.4
```

**D. confidence 参与折算。**

`InteractionEvent.confidence` 目前是摆设。在 `StateEngine.apply_event` 中，正向 delta 乘以 `event.confidence`（负向不打折，从严原则）：低置信事件（deep_sharing 0.8、active_chat 0.7）收益相应缩水，1 行改动让已有字段真正生效。

#### 2.4.2 状态层：动力学不对称性（`state_engine.py` + `state.py`）

心理学依据：重复刺激习惯化（正向递减）、威胁敏化（负向递增）、信任重建慢于破坏（修复限速）。现有实现三者都缺或只做了一半。

**E. 修复限速补到 EVENT_DELTAS（bug 级，必修）。**

失真场景：连发 10 次"对不起" = 边界压力 -60，一次严重越界被机械道歉洗白。`_repair_multiplier` 目前只作用于周期权重，不作用于状态 delta。

实现：`_shape_event_deltas` 中，`event_class == "repair"` 时，将 `boundary_pressure` 的负向 delta 乘以 `self._repair_multiplier(state.cycle_negative_weight)`，并叠加下述习惯化因子。gate_reason 更新为"修复收益受周期负向权重与重复度限速"。

**F. 正向习惯化（重复刺激递减）。**

失真场景：连说 5 次"谢谢"线性叠加 5 次收益。

实现：新增 1 个内部字段 `CompanionState.last_event_streak: int = 0`（连续同类型事件计数；事件类型变化时归零）。`_shape_event_deltas` 末尾，对正向 delta 乘以习惯化因子：

```python
HABITUATION = (1.0, 0.6, 0.35, 0.2)  # 第1/2/3/4+次连续同类事件

factor = HABITUATION[min(state.last_event_streak, 3)]
```

只作用于 prosocial / intimacy / repair 类的正向收益；neutral 和 preference 不受影响。

**G. 负向敏化（越踩越敏感）。**

失真场景：周期内第 3 次 boundary_push 与第 1 次扣得一样重。

实现：boundary_violation 类事件的 `boundary_pressure` 正向 delta 乘以 `1.0 + 0.3 * min(state.cycle_boundary_hits, 3)`（第 2 次 x1.3、第 3 次 x1.6、封顶 x1.9）。使用已有的 `cycle_boundary_hits` 字段，无需新字段。注意在 `_update_cycle_state` 计数自增**之前**读取。

**H. 边界压力分层衰减（严重的留痕更久）。**

失真场景：一句"滚"带来的压力按 3.0/小时衰减，3 小时后如同未发生。

实现：`apply_time_decay` 中衰减速率按当前压力水平分档——低压区快消、高压区慢消，模拟"小摩擦易忘、大冲突留痕"：

```python
if state.boundary_pressure > 50:
    bp_decay_rate = 1.0   # 高压慢消：50 以上部分约 2 天消化
elif state.boundary_pressure > 25:
    bp_decay_rate = 2.0
else:
    bp_decay_rate = 3.5   # 低压快消，维持现有体感
```

**I. energy 下限硬编码复查（顺手项）。**

`clamp()` 中 `energy` 下限为 20，而 silence 触发条件是 `energy < 25`，可用区间只有 5，实际很难触发低能量沉默。将下限改为 10（或将 silence 阈值同步复核），确保"低能量"是可达状态。执行时以 `silence.py` 实际阈值为准对齐。

#### 2.4.3 表达层：负值语义（`context_builder.py`）

**J. `_level()` 对负 closeness 失语。**

失真场景：closeness = -40（强排斥）被描述为"亲近度很低"，主模型读到的语义与实际状态严重不符。

实现：closeness 单独走一个带负值分支的描述函数：

```python
@staticmethod
def _closeness_text(value: float) -> str:
    if value <= -35:
        return "明显排斥"
    if value < 0:
        return "有些疏离"
    if value <= 20:
        return "很低"
    if value <= 45:
        return "一般"
    if value <= 70:
        return "较高"
    return "很高"
```

#### 2.4.4 回归场景（在 2.3 基础上追加）

- "我不喜欢你这样" -> 不判 affection（否定防误判生效）。
- "哎对了，帮我看个东西" -> neutral，不扣能量。
- 贴 300 字代码 -> neutral，不加熟悉度。
- 连发 3 次"谢谢" -> 第 3 次收益明显小于第 1 次（Debug 面板 gate_reason 可见）。
- 严重越界后连发 3 次"对不起" -> 边界压力缓慢下降，未被清零；姿态仍为谨慎/冷却。
- 周期内第 3 次"别烦" -> 边界压力增幅大于第 1 次。
- closeness 为负时注入文本出现"疏离/排斥"字样而非"亲近度很低"。

#### 2.4.5 实施顺序

E（bug 级）> A（误判源头）> F/G（对称性）> H > B/C/D > I/J。全部完成后才进入 2.5 冻结。

### 2.5 冻结声明

自 2.4 可信度强化完成起，P2 / P2.5 层冻结：

- **不再新增**状态字段、周期字段、事件类型、注入模板（2.4 的 `last_event_streak` 是冻结前最后一个新增字段）。
- 只允许 bug 修复和第 2.2 节描述的收窄改动。
- 后续所有新能力都建立在 P3 弧线层，不回头加厚状态层。

### 2.6 验收标准

- 死代码删除后插件正常加载运行，无 import / 属性错误。
- `explain_posture` / `relationship_label` / `boundary_stance` 不再引用 safety。
- 2.3 的四个回归场景 + 2.4.4 的七个可信度回归场景行为符合预期。
- Debug 页面 safety / mood 标注为观测量。

---

## 三、第二步：瘦身版 P3（每日情感弧线与连续性）

预计工作量：两到三天。这是本插件的核心壁垒，也是"到底有没有用"的验证对象。

### 3.1 与原 phase3 计划的裁剪对照

| 原计划（phase3-continuity-plan.md） | 瘦身版 |
|---|---|
| DailyArc 约 15 个字段 | 6 个字段 |
| ContinuitySummary 独立表 + 约 10 字段 | 第一版不建表，注入时现算 |
| 7 天权重数组（1.00 / 0.75 / 0.55 / ...） | 只看昨天 + 近 3 天 trend 序列 |
| 四源融合权重（50% / 30% / 15% / 5%） | 不做数值融合，注入顺序即优先级 |
| 新增 2-3 个模块（arc.py / continuity.py / models.py） | 只新增 1 个文件 `arc.py` |
| 反思输出改嵌套结构（state_delta + daily_arc + style_updates） | 保持扁平，追加 3 个键 |

裁剪原则：先用最小实现验证"连续性注入是否真实改变回复姿态"，验证通过后再考虑加回 ContinuitySummary 表和权重融合。

### 3.2 数据模型

`storage.py` 新增 1 张表：

```sql
CREATE TABLE IF NOT EXISTS daily_arc (
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,              -- 'YYYY-MM-DD'（本地时区）
    overall_mood TEXT DEFAULT '',    -- 当天整体情绪走势，一句话
    relationship_trend TEXT DEFAULT '',  -- 靠近/稳定/疲惫/拉扯/恢复 等短语
    important_interactions TEXT DEFAULT '[]',  -- JSON 数组，最多 3 条短句
    tomorrow_guidance TEXT DEFAULT '',   -- 明天相处建议，一句话
    updated_at REAL DEFAULT 0,
    PRIMARY KEY (user_id, date)
);
```

约束：

- `overall_mood` / `relationship_trend` 各截断 60 字。
- `important_interactions` 每条截断 60 字，最多 3 条。
- `tomorrow_guidance` 截断 120 字。
- 不保存对话原文，只保存提炼后的短句。

Storage 新增方法（3 个）：

```python
def upsert_daily_arc(self, user_id: str, date: str, arc: dict) -> None: ...
def get_daily_arc(self, user_id: str, date: str) -> dict | None: ...
def get_recent_arcs(self, user_id: str, days: int = 3) -> list[dict]: ...
    # 返回按日期降序、不含今天的最近 N 天弧线
```

### 3.3 新文件 `arc.py`（约 150 行）

```python
class ArcEngine:
    """每日情感弧线：由反思结果逐步完善，供次日连续性注入使用。"""

    def __init__(self, storage: Storage): ...

    def update_from_reflection(self, user_id: str, result: dict, state: CompanionState) -> None:
        """反思成功后调用。提取 arc_mood / arc_trend / tomorrow_guidance /
        arc_highlights，upsert 到当天的 daily_arc。
        - 同一天多次反思：字段非空则覆盖，highlights 合并去重后保留最新 3 条。
        - result 中缺少 arc 字段时（旧格式/LLM 未按要求输出）：静默跳过，不报错。
        """

    def build_continuity_text(self, user_id: str, today: str) -> str:
        """读取昨天的 arc + 近 3 天 trend 序列，现算一段连续性提示。
        - 昨天有 arc：'昨天整体{overall_mood}，{tomorrow_guidance}'
        - 近 3 天 trend 非空：追加一句趋势描述（见 3.6 规则）
        - 昨天无 arc（没聊/未反思）：返回空字符串，注入侧跳过该块。
        输出总长控制在 150 字以内。
        """

    def get_today_arc(self, user_id: str) -> dict | None:
        """供 Debug 面板展示今日弧线。"""
```

不做的事：不单独调 LLM（完全复用反思管线）、不建 ContinuitySummary 表、不做跨用户逻辑。

### 3.4 反思输出扩展（`reflection.py`）

在现有扁平 JSON 输出上**追加 3 + 1 个键**，不改嵌套结构：

```json
{
  "familiarity_delta": 0.5,
  "...现有键保持不变...": "...",

  "arc_mood": "白天压力较高，晚上缓和",
  "arc_trend": "轻微靠近",
  "arc_highlights": ["下午主动分享工作压力", "晚上要求短回复"],
  "tomorrow_guidance": "明天开场轻柔，先承接情绪，不要追问细节。"
}
```

Prompt 追加要求（写入反思 system prompt）：

- `arc_mood`：今天到目前为止的整体情绪走势，一句话，不超过 30 字。
- `arc_trend`：从"靠近/稳定/疲惫/拉扯/恢复/冷淡"中选一个词，可加简短修饰。
- `arc_highlights`：最多 3 条重要互动短句，每条不超过 30 字，没有就给空数组。
- `tomorrow_guidance`：给明天的自己一句相处建议，不超过 60 字。

向后兼容处理：

- 这 4 个键全部可选。LLM 未输出时 `ArcEngine.update_from_reflection` 静默跳过。
- 现有 `sanitize_reflection_result`（`state_engine.py:338`）不需要处理 arc 键；但 `tomorrow_guidance` 需做一层消毒：出现"表白/亲密/恋人"类词且当前 `familiarity < 8` 时丢弃该条 guidance（防止 LLM 在过早亲密场景下写出"明天更亲近一点"）。这段消毒放在 `ArcEngine.update_from_reflection` 内。

调用点接线（`main.py` 反思成功回调处）：

```text
反思成功
  -> state_engine.apply_reflection_delta(...)   （现有）
  -> arc_engine.update_from_reflection(...)      （新增，放在 delta 之后）
  -> state_engine.reset_cycle_after_reflection(...) （现有）
  -> storage 持久化
```

arc 更新失败（异常）不影响状态更新和周期重置，try/except 包裹并记日志。

### 3.5 注入扩展（`context_builder.py`）

新增 `<continuity>` 块，位置在 `<cycle_strategy>` / `<cycle_posture>` 之后、`<relationship_posture>` 之前：

```xml
<continuity>
昨天整体白天压力较高、晚上缓和。今天开场保持轻柔，先承接情绪，不要追问细节。近三天趋势：疲惫 -> 疲惫 -> 轻微靠近，正在缓慢恢复。
</continuity>
```

注入规则：

- 仅当 `enable_continuity_injection = true`（新配置）且 `build_continuity_text` 返回非空时注入。
- **每天首次注入必带**；当天后续请求继续携带（内容短，无需做"只注入一次"的复杂判定，保持实现简单）。
- 优先级语义：连续性提示是"背景色"，周期策略是"当前指令"。两者冲突时（如昨天建议温和、今天用户越界触发 cooldown），注入顺序保证周期策略在前，并在 `<continuity>` 文案生成时加一条规则：当 `cycle_dominant_class` 为 `cooldown` 或 `cautious` 时，跳过 guidance 中的"靠近/主动"类语句，只保留情绪承接部分。

不做四源数值融合。注入优先级完全由块顺序和上述跳过规则表达。

### 3.6 近 3 天趋势的现算规则（`build_continuity_text` 内，约 30 行）

```text
取近 3 天（不含今天）的 relationship_trend 列表 trends（按时间正序）
- len == 0: 不输出趋势句
- 全部相同: "近几天持续{trend}"
- 最后一天与之前不同: "近几天从{旧}转向{新}"
- 其他: "近三天：{t1} -> {t2} -> {t3}"
额外风险提示（简单规则，不引入新字段）:
- trends 中"疲惫"出现 >= 2 次: 追加 "注意近几天能量偏低，整体收着点。"
- trends 中"拉扯"出现 >= 2 次: 追加 "最近反复拉扯，避免主动推进关系。"
```

### 3.7 配置与面板

`_conf_schema.json` / `config.py` 新增（只加 2 项，克制）：

- `enable_continuity_injection`（bool，默认 true）：连续性注入总开关，也是 A/B 验证开关。
- `continuity_lookback_days`（int，默认 3，范围 1-7）：趋势回看天数。

Debug 面板新增一栏"连续性"：

- 今日弧线：`overall_mood` / `relationship_trend` / `important_interactions` / `updated_at`。
- 昨日 `tomorrow_guidance` 原文。
- 当前实际生成的 `<continuity>` 注入文本（与现有"实时注入上下文窗口"打通即可）。
- 注入开关当前状态。

### 3.8 验收标准

- 每天反思后能生成 / 更新一条 `daily_arc`，同日多次反思逐步完善。
- 第二天首次对话的注入中带上昨天的延续建议。
- LLM 未输出 arc 键时一切正常（弧线不更新、注入优雅缺省）。
- `cooldown` / `cautious` 周期下，guidance 中的靠近类语句被跳过。
- 关闭 `enable_continuity_injection` 后 `<continuity>` 块消失，其余注入不变。
- Debug 面板能看到今日弧线、昨日 guidance、实际注入文本。
- 插件仍不保存对话原文到 arc，不写入 LivingMemory。

---

## 四、第三步：验证机制（回答"这真的有用吗"）

P3 落地后先验证，再决定 P4。方法：

### 4.1 A/B 对照

- 开关：`enable_continuity_injection`。
- 对照方式：同样是"新一天的第一轮对话"，分别在开 / 关状态下观察 bot 的开场姿态（是否承接昨天的情绪、是否避免了 guidance 里提示要避免的行为）。
- Debug 面板并排展示"昨日 guidance"与"今日实际注入"，肉眼核对因果链。

### 4.2 一周观察记录

建议在 `docs/` 下随手维护一个 `continuity-log.md`（手工记录，不做成功能）：

```markdown
## 2026-07-15
- 昨日 guidance: 开场轻柔，先承接情绪
- 今日开场（开）: bot 第一句 "昨天睡得还好吗？今天不聊工作了" —— 命中
- 今日开场（关，重roll对照）: bot 第一句 "早上好！今天有什么计划？" —— 无延续
- 判定: 有效 / 无差别 / 反效果
```

### 4.3 判定标准

- **一周内"有效"占多数** -> P3 成立，推进瘦身版 P4。
- **多数"无差别"** -> 用最小代价证伪了核心假设，止损：冻结整个项目或转向重新设计注入文案，不继续投 P4/P5。
- **出现"反效果"**（如 guidance 过时导致 bot 答非所问）-> 优先调整 guidance 消毒和过期规则（例如昨天的 arc 超过 48 小时未更新则不注入），而不是加机制。

---

## 五、第四阶段：瘦身版 P4（LivingMemory 只读增强）

**前置条件：P3 验证判定为"有效"后才启动。** 原 phase4-livingmemory-plan.md 保留为完整参考，实际按以下瘦身版执行。

### 5.1 与原 phase4 计划的裁剪对照

| 原计划 | 瘦身版 |
|---|---|
| 4 种 adapter 候选能力探测 | 先只实现 1-2 种（探测 `search_memories` 与 `memory_engine.search_memories`），探测不到就降级 |
| 结果规范化支持 4 种返回结构、3 组字段提取优先级 | 只提取 `content` / `text` / `summary` 三个键，都没有就丢弃该条 |
| 6 个观测指标 + 降级矩阵 7 种场景 | 内存状态 4 个字段：`available` / `adapter` / `last_read_at` / `last_error`；所有失败统一"静默降级 + 记录 last_error" |
| 4 个新配置项 | 1 个：`enable_livingmemory_read`（bool，默认 false） |
| 读取近 1-3 天 | 固定近 1 天（只为补当天弧线） |

### 5.2 职责与用途（与原计划一致，不变）

- **只读，不写入。** 不调用任何 `add_memory` / `save_memory` 类方法。
- LM 内容**只作为反思输入**：在触发反思时，若可读则把 LM 近 1 天摘要（截断后总量 <= 500 字）附加到反思 prompt 的参考资料区，帮 LLM 写出更完整的 `arc_mood` / `arc_highlights`。
- **不直接注入主对话。** 最终注入的仍然只有 CompanionLite 自己的 `<continuity>` 等块。
- `daily_arc` 增加来源标记：本地缓冲为主时 `source='local'`，混入了 LM 摘要则 `source='mixed'`（表加一列 `source TEXT DEFAULT 'local'`，建表时一并加上，P3 阶段就写 `local`）。

### 5.3 实现要点

- 新文件 `livingmemory_reader.py`（目标 <= 150 行）：在现有 `livingmemory_integration.py`（detect）之上加 `read_recent(user_id, max_chars=500) -> str`，内部 try/except 全包裹，失败返回空字符串。
- 读取时机：仅在反思任务启动时读一次，不在消息路径上读（不给每条消息加延迟）。
- Debug 面板加一行：LM 可读状态 / adapter / 最近读取时间 / 最近错误。

### 5.4 验收标准

- LM 可用时，反思 prompt 带上近 1 天摘要，弧线 `source` 变为 `mixed`。
- LM 不可用 / 关闭开关 / 读取异常时，P3 全功能不受影响。
- 消息处理路径延迟无变化（读取只发生在反思任务内）。
- 不产生任何对 LM 的写入调用。

---

## 六、明确不做的事（负面清单）

防止范围回涨，以下事项在本计划内明确不做：

1. **不集成 SylannEngine**（理由见 1.3；仅借鉴设计思想）。
2. **不做 P5 知识收获**（14 字段表 + 审查流 + 8 个 API，离核心命题最远）。无限期搁置，等 P3/P4 稳定运行一个月以上再重新评估是否需要。
3. **不做 ContinuitySummary 独立表**、7 天权重数组、四源数值融合（P3 验证有效且觉得"只看 3 天不够"时再考虑）。
4. **不给 P2/P2.5 加新字段 / 新模板 / 新事件类型**（冻结声明见 2.5；2.4 可信度强化是冻结前的最后一轮改动）。
5. **不做人格演化 / persona 候选生成**（design.md 第八节的远期方向，与当前命题无关）。
6. **不做多用户差异化策略、主动问候、群聊支持**。
7. **不在消息路径上增加任何 LLM 调用**（保持"正则即时 + 反思低频"的成本模型）。

---

## 七、执行顺序与里程碑

```text
里程碑 1（1-2天）：减法、可信度强化与冻结
  删死代码 -> 收窄决策条件 -> 可信度强化（2.4：修复限速 E > 否定防误判 A > 习惯化/敏化 F/G > 分层衰减 H > 关键词清理 B/C/D > I/J）
  -> 回归 2.3 四场景 + 2.4.4 七场景 -> 面板标注 -> changelog 记录 -> 冻结

里程碑 2（2-3天）：瘦身 P3
  daily_arc 表 + storage 方法（建表时带 source 列）
  -> arc.py（update_from_reflection / build_continuity_text）
  -> reflection.py prompt 追加 4 键 + guidance 消毒
  -> main.py 接线（反思成功回调）
  -> context_builder.py <continuity> 块 + 冲突跳过规则
  -> 配置 2 项 + Debug 面板连续性栏

里程碑 3（1周，无编码）：验证
  A/B 对照 + continuity-log.md 手工记录 -> 按 4.3 判定

里程碑 4（1-2天，条件触发）：瘦身 P4
  livingmemory_reader.py -> 反思 prompt 附加 LM 摘要 -> source=mixed -> 面板状态行

搁置：P5
```

每完成一个里程碑，在 `docs/changelog.md` 追加记录后再进入下一个。
