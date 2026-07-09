# 阶段 4 技术开发计划：LivingMemory 只读增强

## 一、阶段目标

阶段 4 的目标是在不破坏职责边界的前提下，让 CompanionLite 只读使用 LivingMemory 的近期摘要或检索结果，增强每日情感弧线和跨日连续性。

阶段 3 已经让 CompanionLite 能基于本地消息缓冲生成 DailyArc 和 ContinuitySummary。阶段 4 只做增强：如果 LivingMemory 可读，就把它作为弧线构建输入；如果不可读，插件必须完全降级，继续依靠本地消息缓冲工作。

必须达成的技术目标：

- 新增 `LivingMemoryReader`，弱依赖探测 LivingMemory 可读接口。
- 只读取绑定 UID 相关、最近 1-3 天、数量和字符数受限的内容。
- 不写入 LivingMemory。
- 不直接把 LivingMemory 原文大量注入 LLM。
- LivingMemory 内容只作为 DailyArc/Continuity 的输入，由 CompanionLite 提炼关系和情绪走势。
- Debug 页面展示 LivingMemory 读取状态、最近读取时间、读取数量、降级原因。
- 所有读取失败都不阻塞消息捕获、反思和 LLM 注入。

## 二、设计边界

必须遵守：

- LivingMemory 是事实记忆层，CompanionLite 是关系连续性层。
- CompanionLite 不调用任何写入类方法，例如 `add_memory`、`save_memory`、`create_memory`。
- CompanionLite 不持久化 LivingMemory 原文，只保存压缩后的弧线和相处建议。
- LivingMemory 接口不稳定时，优先降级，不做硬失败。
- 读取结果必须经过字符数和条数限制。
- 注入给 LLM 的仍然是 CompanionLite 生成的 `companion_context`，不是 LM 原始记忆列表。

## 三、可读接口策略

由于 LivingMemory 可能存在不同版本，`LivingMemoryReader` 应使用“能力探测”而不是写死单一 API。

探测顺序建议：

```text
LivingMemoryIntegration.detect()
  -> 获取 star.instance 或 star.star_cls 实例
  -> 探测公开/半公开只读接口
  -> 包装成统一 read_recent(user_id, days, limit) 输出
```

可能的只读来源类型：

- `search_memories(query, ...)`：按 query 检索。
- `memory_engine.search_memories(...)`：内部检索接口。
- `conversation_manager` / `conversation_mgr`：近期会话摘要。
- `get_recent_memories(...)`：如果插件版本提供。
- `query(...)` / `search(...)`：通用查询方法。

实现原则：

- 每种接口都放在独立 adapter 方法中。
- 每次调用都 try/except。
- 一旦找到可用接口，记录 adapter 名称。
- 如果接口返回结构未知，尽量提取 `content`、`text`、`summary`、`memory`、`metadata`。
- 不假设 LivingMemory 内部对象一定存在。

## 四、数据模型

### 1. LivingMemoryReadResult

建议新增 dataclass：

```python
@dataclass
class LivingMemoryReadResult:
    ok: bool
    items: list[dict]
    adapter: str = ""
    error: str = ""
    read_at: float = 0.0
    degraded: bool = False
```

`items` 统一结构：

```json
{
  "content": "用户最近提到工作压力较大，晚上希望短回复。",
  "timestamp": 1783440000.0,
  "score": 0.82,
  "source": "livingmemory.search_memories",
  "metadata": {
    "raw_type": "memory"
  }
}
```

注意：

- `content` 必须被截断，例如单条最多 300 字。
- `items` 总数默认最多 5-10 条。
- `metadata` 只保留非敏感、调试需要的信息。

### 2. LM 读取状态

建议在内存中维护状态，阶段 4 不强制入库：

```python
self._lm_read_status = {
    "available": false,
    "adapter": "",
    "last_read_at": 0.0,
    "last_count": 0,
    "last_error": "",
    "degraded": false
}
```

如果希望跨重启保留，可后续加 `integration_status` 表。本阶段不必增加。

### 3. DailyArc source 扩展

阶段 3 的 `daily_arc.source` 在阶段 4 扩展：

- `local`：只使用本地消息缓冲。
- `livingmemory`：只使用 LM 读取结果。
- `mixed`：本地消息缓冲 + LM 读取结果。

推荐实际使用 `mixed`，除非本地缓冲为空而 LM 有内容。

## 五、结构拓扑

阶段 4 后推荐结构：

```text
CompanionLitePlugin
├── LivingMemoryIntegration
│   └── 检测插件是否存在和激活
│
├── LivingMemoryReader
│   ├── detect_read_adapter(...)
│   ├── read_recent(user_id, days, limit)
│   ├── normalize_items(raw)
│   ├── trim_items(items)
│   └── read_status
│
├── ArcEngine
│   ├── build_local_input(messages, events)
│   ├── build_lm_input(lm_items)
│   ├── build_mixed_input(local, lm)
│   └── save DailyArc(source=mixed)
│
├── ReflectionEngine
│   ├── reflect_daily_arc(local_context, lm_context)
│   └── 强约束：LM 内容只用于情绪/关系弧线
│
├── ContinuityEngine
│   └── 使用 mixed DailyArc 生成趋势
│
└── DebugPanel
    ├── LM active
    ├── LM readable
    ├── adapter
    ├── last_read_at
    ├── last_count
    └── last_error/degraded
```

建议新增文件：

- `livingmemory_reader.py`

保留现有：

- `livingmemory_integration.py` 继续只负责插件检测。
- `LivingMemoryReader` 负责读接口探测和结果规范化。

## 六、技术实现

### 1. LivingMemoryReader 初始化

建议构造：

```python
class LivingMemoryReader:
    def __init__(self, integration: LivingMemoryIntegration, max_items: int = 8, max_chars: int = 1200) -> None:
        self.integration = integration
        self.max_items = max_items
        self.max_chars = max_chars
        self._adapter_name = ""
        self._status = {...}
```

`read_recent()` 入口：

```python
async def read_recent(self, user_id: str, days: int = 3, limit: int = 8) -> LivingMemoryReadResult:
    if not self.integration.active:
        return degraded result
    instance = self.integration.instance
    adapter = self._resolve_adapter(instance)
    if not adapter:
        return degraded result
    raw = await adapter(user_id=user_id, days=days, limit=limit)
    items = self._normalize_items(raw)
    return ok result
```

### 2. Adapter 探测

推荐 adapter 顺序：

1. 显式公开方法。
2. `memory_engine` 只读检索。
3. 通用 search/query。
4. 无可用接口则降级。

伪代码：

```python
def _resolve_adapter(self, instance):
    candidates = [
        self._adapter_get_recent_memories,
        self._adapter_search_memories,
        self._adapter_memory_engine_search,
        self._adapter_generic_search,
    ]
    for candidate in candidates:
        if candidate.supports(instance):
            return candidate
    return None
```

不要在 supports 阶段执行昂贵调用，只检查属性和 callable。

### 3. 查询构造

LM 查询应该引导其返回近期相关内容，而不是泛泛检索。

建议 query：

```text
用户 {user_id} 最近 1-3 天的对话摘要、情绪变化、表达偏好、关系互动、边界或疲惫状态
```

注意：

- 不要求 LM 做关系判断，关系判断由 CompanionLite 做。
- 如果 LM 检索不支持 user_id 过滤，则 query 中包含 user_id，但仍需限制结果数量。

### 4. 结果规范化

`_normalize_items(raw)` 应支持：

- list[str]
- list[dict]
- dict with `results` / `memories` / `items`
- object with `content` / `text` / `summary`

提取字段优先级：

```text
content > text > summary > memory > description > str(item)
```

timestamp 提取优先级：

```text
timestamp > created_at > updated_at > time
```

score 提取优先级：

```text
score > relevance > similarity > confidence
```

安全处理：

- 空内容丢弃。
- 单条内容截断到 300 字。
- 总字符数截断到配置上限。
- 去重相同 content。

### 5. 反思输入融合

阶段 4 的 `_run_reflection()` 流程：

```text
本地消息缓冲 messages
  + 可选 LM read_recent(user_id)
  -> build reflection input
  -> DeepReflection.reflect(..., lm_items=...)
  -> DailyArc source = mixed/local/livingmemory
```

Reflection prompt 中 LM 区块建议：

```text
以下是 LivingMemory 只读提供的近期事实/摘要。它们只用于辅助判断情绪弧线和相处建议。
不要逐条复述，不要把事实内容保存到 CompanionLite，只总结它们对关系、能量、边界和明日姿态的影响。
```

### 6. 调用时机

推荐只在以下时机读取 LM：

- 深度反思触发时。
- 手动触发反思时。
- Debug 页面手动刷新 LM 状态时，可选。

不建议每次 LLM 请求都读取 LM，原因：

- 增加延迟。
- 和 LM 自己的注入重复。
- 读接口不稳定会影响回复链路。

### 7. 配置项

建议新增到 `LivingMemory_Settings`：

- `enable_livingmemory_read`: 默认 `true`。
- `livingmemory_read_days`: 默认 `3`。
- `livingmemory_read_limit`: 默认 `8`。
- `livingmemory_read_max_chars`: 默认 `1200`。

如果阶段 4 初版希望最小改动，可以先只在代码内给默认值，后续再暴露到配置面板。但推荐直接加 schema，便于调试。

### 8. Debug API

新增或扩展：

- `GET page/livingmemory_status`
- `GET page/health` 增加 LM 读取状态。

返回示例：

```json
{
  "active": true,
  "readable": true,
  "adapter": "memory_engine.search_memories",
  "last_read_at": 1783440000.0,
  "last_count": 5,
  "last_error": "",
  "degraded": false
}
```

Debug 页面新增卡片：

- LivingMemory 插件状态。
- 只读接口状态。
- Adapter 名称。
- 最近读取数量和时间。
- 降级原因。

## 七、失败与降级策略

必须覆盖：

- LivingMemory 未安装：`active=false`，正常降级。
- LivingMemory 未激活：`active=false`，正常降级。
- 找不到只读接口：`readable=false`，正常降级。
- 接口调用超时：记录 warning，正常降级。
- 返回结构未知：尽力解析，解析不到则空结果。
- 返回内容过长：截断。
- LLM 反思失败：不清空本地缓冲。

建议超时：

- 单次 LM 读取 2-3 秒。
- 超时后本轮反思继续使用本地消息。

## 八、测试方法

### 1. 单元测试建议

建议用 fake LivingMemory instance 覆盖：

- 未激活时返回 degraded。
- 有 `search_memories` 方法时能读取。
- 有 `memory_engine.search_memories` 时能读取。
- 返回 list[str] 能规范化。
- 返回 list[dict] 能规范化。
- 返回 dict.results 能规范化。
- 单条和总字符数能截断。
- 重复内容能去重。
- 接口异常时不抛出到主流程。

### 2. 手动验证场景

场景 A：无 LivingMemory。

步骤：

1. 禁用或移除 LivingMemory。
2. 触发 CompanionLite 反思。

期望：

- 反思仍然基于本地消息完成。
- Debug 显示 LM 不可用或降级。
- 无异常中断。

场景 B：LivingMemory 可检测但不可读。

步骤：

1. 模拟 LM 激活但没有可识别只读接口。
2. 触发反思。

期望：

- Debug 显示 active=true, readable=false。
- DailyArc source 仍为 local。

场景 C：LivingMemory 可读。

步骤：

1. 提供 fake 或真实 LM 检索结果。
2. 触发反思。

期望：

- DailyArc source 为 mixed。
- 弧线中体现 LM 内容对情绪/关系的影响。
- 注入内容不直接复述 LM 原文。

场景 D：LM 读取超时。

步骤：

1. 模拟只读接口 sleep 超过超时。

期望：

- 日志 warning。
- 本地反思继续。
- Debug 显示 degraded 和 last_error。

### 3. 回归验证

确认阶段 1-3 能力不退化：

- 显式 UID 绑定仍生效。
- 反思任务仍去重。
- DailyArc 本地生成仍可用。
- ContinuitySummary 仍可生成。
- 未配置 UID 不读取 LM。
- LM 不可用时 LLM 注入仍正常。

## 九、调试与观测

建议日志点：

- LM reader adapter resolved。
- LM read success: count, adapter, elapsed_ms。
- LM read degraded: reason。
- LM content trimmed: original_chars, final_chars。
- DailyArc source=mixed 写入。

建议指标：

- `lm_read_attempts`
- `lm_read_success`
- `lm_read_failures`
- `lm_read_timeout`
- `lm_items_count`
- `lm_read_elapsed_ms`

初版可以只放在 health/debug，不必引入完整 metrics。

## 十、完成标准

阶段 4 完成后，应满足：

- CompanionLite 能检测并只读使用 LivingMemory 的近期内容。
- LivingMemory 可用时，DailyArc 能使用 mixed source。
- LivingMemory 不可用、不可读、超时时，插件完全降级。
- 插件不写入 LivingMemory。
- LLM 注入不直接搬运 LM 原文。
- Debug 页面能清楚说明 LM 读取是否成功、用的哪个 adapter、最近读到了多少内容。
- 阶段 3 的每日弧线和连续性在无 LM 情况下仍稳定可用。
