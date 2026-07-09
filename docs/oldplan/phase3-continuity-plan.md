# 阶段 3 技术开发计划：每日情感弧线与连续性

## 一、阶段目标

阶段 3 的目标是让 CompanionLite 从“即时关系状态插件”升级为“私聊关系连续性插件”。

阶段 1 解决稳定性和显式绑定问题，阶段 2 让即时关系状态具备恢复和衰减。阶段 3 在此基础上新增每日情感弧线和跨日连续性摘要，使 bot 能记得昨天/今天的相处走势，并用来指导明天、后天的回复姿态。

必须达成的技术目标：

- 新增 `daily_arc` 数据层，每个绑定 UID 每天一条情感弧线。
- 新增 `continuity_summary` 数据层，基于最近几天 `DailyArc` 加权生成连续性提示。
- 让深度反思同时产出即时状态 delta、今日弧线、明日建议和反思摘要。
- LLM 注入升级为“当前关系状态 + 今日弧线 + 近几天延续建议”。
- Debug 页面展示今日情感弧线、跨日趋势、来源、更新时间和最近一次反思摘要。
- 所有连续性能力只保存关系/情绪/相处建议，不保存事实记忆原文。

本阶段不接入 LivingMemory 数据读取。DailyArc 的输入先来自 CompanionLite 自己的消息缓冲、事件结果和 bot 回复记录。LivingMemory 只读增强留到阶段 4。

## 二、核心概念

### 1. DailyArc

`DailyArc` 是某个绑定用户在某一天的情感与关系走势摘要。

它回答这些问题：

- 今天整体聊得轻松、疲惫、紧张、靠近，还是恢复？
- 一天中能量是如何变化的？
- 有没有出现明显边界压力？有没有修复？
- 用户今天的表达偏好是否有变化？
- 明天应该以什么姿态继续？

`DailyArc` 不是事实记忆，不记录“用户今天做了什么”的完整事实链。它只记录这些事实对相处状态的影响。

### 2. ContinuitySummary

`ContinuitySummary` 是最近几天 DailyArc 的加权总结。

它回答这些问题：

- 最近几天关系是在靠近、稳定、疲惫、拉扯还是疏远？
- 有哪些重复出现的风险，例如连续低能量、反复要求少追问？
- 今天/明天回复时应该延续什么姿态？
- 哪些提示应该短期保留，哪些已经过期？

### 3. Reply Posture

`ReplyPosture` 是给 LLM 的最终相处姿态提示，不一定单独入库。

它由以下内容融合得到：

```text
当前回复姿态 =
  即时关系状态
+ 今日情感弧线
+ 昨天/前天延续建议
+ 近几天趋势
+ 长期关系底色
```

默认权重建议：

- 即时关系状态：50%。
- 今天/昨天弧线：30%。
- 近 3 天趋势：15%。
- 长期关系底色：5%。

## 三、数据模型

### 1. daily_arc 表

建议新增 SQLite 表：

```sql
CREATE TABLE IF NOT EXISTS daily_arc (
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    arc TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL DEFAULT 'local',
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_id, date)
);

CREATE INDEX IF NOT EXISTS idx_daily_arc_user_date
ON daily_arc(user_id, date);
```

`arc` JSON 建议字段：

```json
{
  "user_id": "123456",
  "date": "2026-07-07",
  "overall_mood": "低落后缓和",
  "relationship_trend": "轻微靠近",
  "energy_curve": "下午较活跃，晚上明显疲惫",
  "boundary_curve": "晚上出现轻微边界压力，随后缓和",
  "important_interactions": [
    "用户主动分享压力",
    "用户要求回复短一点",
    "最后对话以平和结束"
  ],
  "style_observations": [
    "今天更偏好短回复",
    "不希望连续追问"
  ],
  "tomorrow_guidance": "明天开场保持轻柔，不要太主动追问，优先承接情绪。",
  "risk_flags": ["夜间能量偏低"],
  "confidence": 0.78,
  "source": "local",
  "message_count": 18,
  "reflection_count": 2,
  "updated_at": 1783440000.0
}
```

字段说明：

- `overall_mood`：当天整体情绪走势，短语即可。
- `relationship_trend`：关系方向，例如靠近、稳定、疲惫、拉扯、恢复、疏远。
- `energy_curve`：能量变化，不要求精确时间序列。
- `boundary_curve`：边界压力变化和是否修复。
- `important_interactions`：只保存对关系有影响的互动摘要，不保存大段原文。
- `style_observations`：当天观察到的表达偏好，不等于长期偏好。
- `tomorrow_guidance`：明日相处建议，是注入层的重要输入。
- `risk_flags`：短期风险，例如“连续低能量”“边界压力未修复”。
- `confidence`：本次弧线可信度。
- `source`：阶段 3 固定为 `local`，阶段 4 可为 `mixed`。

### 2. continuity_summary 表

建议新增 SQLite 表：

```sql
CREATE TABLE IF NOT EXISTS continuity_summary (
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '{}',
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_id, date)
);

CREATE INDEX IF NOT EXISTS idx_continuity_summary_user_date
ON continuity_summary(user_id, date);
```

`summary` JSON 建议字段：

```json
{
  "user_id": "123456",
  "date": "2026-07-07",
  "recent_emotional_direction": "整体疲惫但关系稳定",
  "relationship_momentum": "缓慢靠近",
  "recommended_posture": "温和、短句、少连续追问",
  "carry_over_notes": [
    "昨天最后对话以疲惫结束，今天不要突然开启复杂话题",
    "近三天用户多次偏好短回复"
  ],
  "risk_flags": [
    "连续两天夜间低能量",
    "多次要求少追问"
  ],
  "stable_preferences": [
    "短回复",
    "直接表达"
  ],
  "source_days": ["2026-07-05", "2026-07-06", "2026-07-07"],
  "confidence": 0.72,
  "updated_at": 1783440000.0
}
```

### 3. 可选 event_digest

阶段 3 不强制新增事件表。如果阶段 2 已经把事件和 reason 写入状态，可以先从消息缓冲和反思结果生成弧线。

如果后续调试需要更强可解释性，可新增 `event_digest` 表：

```sql
CREATE TABLE IF NOT EXISTS event_digest (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    deltas TEXT NOT NULL DEFAULT '{}',
    timestamp REAL NOT NULL
);
```

建议阶段 3 先不强依赖该表，避免实现面扩大。

## 四、结构拓扑

阶段 3 后推荐结构：

```text
CompanionLitePlugin
├── StateEngine
│   └── 当前关系状态、边界、能量、恢复/衰减
│
├── ReflectionEngine
│   ├── reflect_state(...)
│   ├── reflect_daily_arc(...)
│   └── parse structured result
│
├── ArcEngine
│   ├── build_today_arc_input(...)
│   ├── merge_arc(existing, new_result)
│   ├── save_daily_arc(...)
│   └── get_recent_arcs(user_id, days=N)
│
├── ContinuityEngine
│   ├── weight_recent_arcs(...)
│   ├── build_continuity_summary(...)
│   ├── save_summary(...)
│   └── get_today_summary(...)
│
├── ContextBuilder
│   ├── build_state_context(...)
│   ├── build_arc_context(...)
│   ├── build_continuity_context(...)
│   └── build_companion_context(...)
│
├── Storage
│   ├── companion_state
│   ├── style_profile
│   ├── message_buffer
│   ├── daily_arc
│   └── continuity_summary
│
└── DebugPanel
    ├── 今日弧线
    ├── 近几天趋势
    ├── 最近反思摘要
    └── 数据来源/更新时间
```

建议新增文件：

- `arc.py`：`DailyArc` dataclass 和 `ArcEngine`。
- `continuity.py`：`ContinuitySummary` dataclass 和 `ContinuityEngine`。
- `context_builder.py`：统一构建 LLM 注入文本。

可选新增：

- `models.py`：集中放 dataclass，避免 `state.py` 继续膨胀。

## 五、技术实现

### 1. Storage 扩展

文件：`storage.py`

新增方法：

```python
def save_daily_arc(self, user_id: str, date: str, arc: dict, source: str = "local") -> None: ...

def get_daily_arc(self, user_id: str, date: str) -> dict | None: ...

def get_recent_daily_arcs(self, user_id: str, limit: int = 7) -> list[dict]: ...

def save_continuity_summary(self, user_id: str, date: str, summary: dict) -> None: ...

def get_continuity_summary(self, user_id: str, date: str) -> dict | None: ...
```

日期格式统一使用本地日期 `YYYY-MM-DD`。

注意：

- 写入时 JSON 使用 `ensure_ascii=False`。
- `get_recent_daily_arcs` 按 date 降序取，再按时间正序返回给 LLM 更自然。
- `source` 阶段 3 先写 `local`。

### 2. DeepReflection 输出扩展

文件：`reflection.py`

阶段 3 的反思输出建议：

```json
{
  "state_delta": {
    "familiarity_delta": 0.5,
    "closeness_delta": 1.0,
    "safety_delta": 0.0,
    "energy_delta": -2.0,
    "boundary_pressure_delta": 0.0,
    "mood": "平静"
  },
  "style_updates": {
    "preferred_length": "简短",
    "preferred_tone": "自然",
    "preferred_initiative": "少追问"
  },
  "daily_arc": {
    "overall_mood": "疲惫但平和",
    "relationship_trend": "稳定",
    "energy_curve": "对话后半段能量下降",
    "boundary_curve": "无明显边界压力",
    "important_interactions": ["用户表达疲惫，随后自然结束对话"],
    "style_observations": ["更适合短回复"],
    "tomorrow_guidance": "明天先轻柔承接，不要主动追问太多。",
    "risk_flags": ["夜间低能量"],
    "confidence": 0.76
  },
  "reflection_summary": "本轮对话整体平和，但用户后半段疲惫，后续应短句承接。"
}
```

兼容策略：

- `apply_result()` 需要兼容阶段 1/2 的扁平 delta 字段。
- 优先读取 `state_delta`，没有时读取旧字段。
- `daily_arc` 缺失时只更新状态，不写弧线。

### 3. ArcEngine

建议接口：

```python
class ArcEngine:
    def today(self) -> str: ...

    def normalize_arc(self, user_id: str, date: str, raw: dict, source: str) -> dict: ...

    def merge_arc(self, existing: dict | None, incoming: dict) -> dict: ...

    def build_arc_context(self, arc: dict | None) -> str: ...
```

合并规则：

- `overall_mood`、`relationship_trend` 使用新反思覆盖旧值，除非新值为空。
- `important_interactions` 追加去重，最多保留 6 条。
- `style_observations` 追加去重，最多保留 5 条。
- `risk_flags` 追加去重，最多保留 5 条。
- `tomorrow_guidance` 使用最新高置信度结果。
- `reflection_count` 自增。
- `message_count` 使用本次反思消息数累加或覆盖为当天累计估计。

### 4. ContinuityEngine

建议接口：

```python
class ContinuityEngine:
    def build_summary(self, user_id: str, arcs: list[dict]) -> dict: ...

    def build_context(self, summary: dict | None) -> str: ...
```

初版可使用规则聚合，不必每次调用 LLM：

- 收集最近 7 天 `relationship_trend`。
- 收集最近 7 天 `risk_flags` 和 `style_observations`。
- 最近天数按权重排序。
- 用模板生成 `recommended_posture`。

如果要使用 LLM 总结，建议低频触发：

- DailyArc 更新成功后触发。
- 每天最多 1-2 次。
- LLM 失败时使用规则 fallback。

推荐权重：

```python
WEIGHTS = [1.0, 0.75, 0.55, 0.4, 0.35, 0.3, 0.25]
```

规则示例：

- 最近两天出现“低能量”风险：`recommended_posture` 加入“短句、少追问”。
- 最近两天关系趋势为“靠近/恢复”：加入“可以自然亲近，但不要过度主动”。
- 最近出现“边界压力”：加入“避免连续追问和强行延伸”。
- 多天出现“短回复”偏好：加入 `stable_preferences`。

### 5. 反思触发后的写入流程

当前 `_run_reflection()` 应改为：

```text
LLM reflect
  -> apply state/style result
  -> extract daily_arc result
  -> merge and save DailyArc
  -> rebuild ContinuitySummary
  -> save state/style
  -> clear processed message buffer
```

失败策略：

- LLM 返回空：不写状态，不清空缓冲。
- state_delta 有效但 daily_arc 缺失：可更新状态，但不写弧线。
- daily_arc 解析失败：保留状态更新，记录 warning。
- continuity 生成失败：不影响状态和 DailyArc。

### 6. ContextBuilder 注入升级

阶段 3 注入结构建议：

```xml
<companion_context>
当前关系：熟人偏亲近，信任稳定。
当前相处姿态：温和自然，少连续追问。
今日情绪弧线：用户白天压力较高，晚上能量偏低，但整体愿意交流。
连续性提示：昨天最后对话以疲惫结束，今天先轻柔承接，不要突然开启复杂话题。
表达偏好：最近更偏好短回复和直接表达。
回应建议：先承接用户当前内容，不要直接输出这些状态描述。
</companion_context>
```

注入控制：

- 仍遵守 `max_context_chars`。
- 优先保留当前关系、连续性提示、回应建议。
- DailyArc 和 ContinuitySummary 为空时自动降级为阶段 2 的当前状态上下文。
- 不注入 `confidence`、`source`、内部字段名。

### 7. Debug API 扩展

建议新增 API：

- `GET page/daily_arc`
- `GET page/continuity`
- `GET page/arc_history?limit=7`

返回示例：

```json
{
  "arc": {...},
  "exists": true,
  "date": "2026-07-07"
}
```

Health 增加：

- `daily_arc_exists`
- `continuity_exists`
- `last_arc_update`
- `arc_source`

Debug 页面新增卡片：

- 今日情感弧线。
- 明日建议。
- 近几天连续性。
- 风险提示。
- 数据来源与更新时间。

## 六、反思 Prompt 设计

阶段 3 的系统 prompt 应强调：

- 不记录事实流水账。
- 只总结关系、情绪走势、能量、边界、表达偏好。
- 输出 JSON，不要输出额外文本。
- 不把用户一次性情绪当作长期偏好。
- 明日建议必须具体、可指导回复姿态。

关键约束示例：

```text
你不是事实记忆系统。不要总结用户今天具体做了什么，除非这件事明显影响相处方式。
你的任务是总结这段对话对关系状态、边界、能量和明日回复姿态的影响。
```

## 七、测试方法

### 1. 单元测试建议

建议覆盖：

- `Storage.save_daily_arc()` / `get_daily_arc()`。
- `Storage.get_recent_daily_arcs()` 按日期返回正确。
- `ArcEngine.merge_arc()` 能追加去重并限制条数。
- `ContinuityEngine.build_summary()` 能按权重生成风险和姿态。
- `DeepReflection.apply_result()` 兼容旧扁平字段和新 `state_delta`。
- `ContextBuilder` 在 DailyArc 缺失时能降级。
- `ContextBuilder` 不输出内部字段名和裸数值。

### 2. 手动验证场景

场景 A：生成今日弧线。

步骤：

1. 配置绑定 UID。
2. 连续进行一段私聊，达到反思阈值。
3. 触发深度反思。
4. 打开 Debug 页面。

期望：

- `daily_arc` 有当天记录。
- 今日弧线包含整体走势、重要互动、明日建议。
- 消息缓冲在成功后清空。

场景 B：第二天延续。

步骤：

1. 手动构造昨天 DailyArc，或跨日测试。
2. 第二天触发 LLM 请求。

期望：

- 注入内容包含昨天延续提示。
- 不重复搬运昨天事实原文。

场景 C：近几天趋势。

步骤：

1. 插入最近 3 天 DailyArc。
2. 触发 continuity 构建。

期望：

- `ContinuitySummary` 包含关系动量、风险提示、推荐姿态。
- 最近一天的风险权重更高。

场景 D：反思部分失败。

步骤：

1. 模拟 LLM 返回只有 state_delta，没有 daily_arc。

期望：

- 状态可更新。
- DailyArc 不写入。
- 日志提示缺失但不报 fatal。

场景 E：注入降级。

步骤：

1. 删除 DailyArc 和 ContinuitySummary。
2. 触发 LLM 请求。

期望：

- 仍能注入当前关系状态。
- 不出现空字段或 JSON 泄露。

### 3. 回归验证

确认阶段 1/2 能力不退化：

- 未绑定 UID 不处理。
- 缓冲上限仍生效。
- 反思任务仍去重。
- 反思失败不清空缓冲。
- 能量恢复和边界恢复仍生效。
- 沉默/收敛意图仍能注入。

## 八、调试与观测

建议日志点：

- DailyArc 写入成功：user、date、source、confidence。
- ContinuitySummary 写入成功：user、date、source_days。
- DailyArc 缺失降级：debug 级别。
- LLM 反思 JSON 解析失败：warning。
- Continuity 规则 fallback：info 或 debug。

建议 Debug 页面显示：

- 今日弧线是否存在。
- 今日弧线更新时间。
- 弧线来源。
- 明日建议。
- 最近 7 天 source_days。
- 风险 flags。
- 推荐姿态。

## 九、完成标准

阶段 3 完成后，应满足：

- 每个绑定 UID 每天可以生成并更新一条 DailyArc。
- 最近几天 DailyArc 可以生成 ContinuitySummary。
- LLM 注入包含当前状态、今日弧线和近几天延续建议。
- 第二天/后天的回复姿态能受最近情感走势影响。
- Debug 页面能看懂“为什么今天应该更短、更温柔或更收敛”。
- 失败时能安全降级到阶段 2 的当前状态上下文。
- 插件仍不保存事实记忆原文，不写入 LivingMemory。
