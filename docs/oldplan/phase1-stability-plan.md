# 阶段 1 技术开发计划：稳定地基

## 一、阶段目标

阶段 1 的目标是把 CompanionLite 从概念 alpha 调整为稳定、可配置、不会误学习的基础版本。

本阶段不引入每日情感弧线、不做 LivingMemory 数据读取、不做知识收获。重点是修正当前运行风险，建立后续阶段可复用的模块边界。

必须达成的技术目标：

- 去掉自动绑定，只处理后台明确配置的 `main_user_ids`。
- 修复配置读取，兼容 AstrBot 分组配置和当前扁平配置。
- 未配置 UID 时进入未绑定状态，不捕获、不注入、不反思。
- 消息缓冲有上限，不会无限增长。
- 深度反思失败时不清空消息缓冲。
- 同一用户不会并发运行多个反思任务。
- `active_chat` 能基于最近消息频率真实触发。
- 清理 `memory_worthy` / `memory_content`，避免和 LivingMemory 职责混淆。

## 二、当前问题

现有实现的主要问题：

- `main.py` 中 `_auto_main_user_id` 会自动绑定首个私聊用户，重启后可能错绑。
- `config.py` 只读取扁平字段，但 `_conf_schema.json` 是分组结构，WebUI 配置可能不生效。
- `state.py` 的 `RuleEngine.classify()` 支持 `recent_rate`，但 `main.py` 固定传入 `0.0`。
- `storage.py` 的 `message_buffer` 没有裁剪策略。
- `_run_reflection()` 即使 LLM 返回空结果，也会清空消息缓冲。
- 自动反思和 Debug 手动反思都能创建任务，没有按用户去重。
- 反思提示词要求 `memory_worthy`，但实现不处理该字段。

## 三、结构拓扑

阶段 1 后的推荐结构：

```text
CompanionLitePlugin
├── BindingManager
│   ├── 从 CLConfig 读取 main_user_ids
│   ├── 判断当前 user_id 是否绑定
│   └── 暴露绑定状态给命令和 Debug API
│
├── ConfigLoader
│   ├── 兼容分组配置
│   ├── 兼容扁平配置
│   └── 规范化 UID 列表和数值配置
│
├── Storage
│   ├── companion_state
│   ├── style_profile
│   ├── message_buffer
│   ├── append_message(..., max_messages=N)
│   ├── count_recent_user_messages(...)
│   └── trim_messages(...)
│
├── RuleEngine
│   └── classify(text, recent_rate)
│
├── ReflectionTaskManager
│   ├── per-user task 去重
│   ├── 自动反思触发
│   └── 手动反思触发
│
├── DeepReflection
│   ├── 只返回关系和风格更新
│   └── 不输出 memory_worthy
│
└── Debug API
    ├── health 显示绑定状态
    ├── messages 显示缓冲数量
    └── trigger_reflection 复用任务管理
```

最小实现可以不单独拆出所有类，但代码组织应朝这个拓扑靠拢。阶段 1 如果为了降低改动风险，可以先新增 `binding.py`，其他能力在现有 `config.py`、`storage.py`、`main.py` 中完成。

## 四、技术实现

### 1. 配置读取重构

文件：`config.py`

实现目标：

- 支持 `_conf_schema.json` 的分组配置。
- 支持旧的扁平配置。
- `main_user_ids` 支持列表和逗号字符串。
- 对数值项做安全转换和下限保护。

建议实现：

```python
def _read_group(raw, group_name):
    group = raw.get(group_name, {})
    return group if isinstance(group, dict) else {}

def _get(raw, group, key, default):
    return group.get(key, raw.get(key, default))
```

需要兼容的分组名：

- `Basic_Settings`
- `Reflection_Settings`
- `Silence_Settings`
- `LivingMemory_Settings`
- `LLM_Settings`

新增配置建议：

- `max_buffer_messages`: 默认 `120`。
- `recent_rate_window_seconds`: 默认 `60`。

如果不想马上修改 `_conf_schema.json`，可以先在 dataclass 中提供默认值，并在后续补配置面板。

### 2. 去掉自动绑定

文件：`main.py`，建议新增 `binding.py`

删除或停用：

- `_auto_main_user_id`
- `default_main_user_from_private`
- `_is_main_user()` 中的自动绑定逻辑

建议新增：

```python
class BindingManager:
    def __init__(self, user_ids: list[str]) -> None:
        self._user_ids = tuple(str(x).strip() for x in user_ids if str(x).strip())

    @property
    def configured(self) -> bool:
        return bool(self._user_ids)

    def is_bound(self, user_id: str) -> bool:
        return bool(user_id) and user_id in self._user_ids

    def primary_user_id(self) -> str:
        return self._user_ids[0] if self._user_ids else ""
```

行为要求：

- `capture_private_message()` 未绑定时直接 return。
- `inject_companion_context()` 未绑定时直接 return。
- `after_bot_reply()` 未绑定时直接 return。
- `/cp_status` 等命令可以查看当前发送者状态，但 Debug API 默认使用第一个绑定 UID。
- Debug health 显示 `bound_user_ids` 和 `binding_configured`。

### 3. 消息缓冲上限

文件：`storage.py`

新增能力：

- `trim_messages(user_id, max_messages)`
- `append_message(user_id, role, content, max_messages=None)`
- `count_recent_user_messages(user_id, window_seconds)`

推荐 SQL：

```sql
DELETE FROM message_buffer
WHERE user_id = ?
  AND id NOT IN (
    SELECT id FROM message_buffer
    WHERE user_id = ?
    ORDER BY timestamp DESC
    LIMIT ?
  )
```

注意：

- 裁剪按用户隔离。
- 裁剪时保留最新 N 条。
- `count_recent_user_messages` 只统计 `role = 'user'`。

### 4. 活跃聊天频率

文件：`main.py`、`storage.py`

实现方式：

- 在 `capture_private_message()` 中分类前查询最近 60 秒用户消息数。
- 将每分钟消息数传给 `RuleEngine.classify(text, recent_rate)`。
- 当前消息尚未写入缓冲时，计算结果可以加 1，避免第 N 条才滞后触发。

示例：

```python
recent_count = self.storage.count_recent_user_messages(user_id, window_seconds=60)
rate = recent_count + 1
event_type = RuleEngine.classify(text, rate) or "neutral"
```

### 5. 反思任务去重

文件：`main.py`

替换当前 `_background_tasks: set[asyncio.Task]` 的裸集合逻辑。

建议结构：

```python
self._background_tasks: set[asyncio.Task] = set()
self._reflection_tasks_by_user: dict[str, asyncio.Task] = {}
```

新增方法：

```python
def _queue_reflection(self, user_id, state, style, messages) -> bool:
    existing = self._reflection_tasks_by_user.get(user_id)
    if existing and not existing.done():
        return False
    task = asyncio.create_task(self._run_reflection(user_id, state, style, messages))
    self._background_tasks.add(task)
    self._reflection_tasks_by_user[user_id] = task
    task.add_done_callback(lambda t: self._on_reflection_done(user_id, t))
    return True
```

完成回调需要：

- 从 `_background_tasks` 移除。
- 如果当前 task 仍是该用户记录的 task，从 `_reflection_tasks_by_user` 移除。
- 记录异常日志，避免 silent failure。

### 6. 反思失败不清空缓冲

文件：`main.py`、`reflection.py`

当前 `_run_reflection()` 无论 `result` 是否为空都会 `clear_messages()`。

改为：

- `result` 有效且 apply 成功后清空或裁剪。
- `result` 为空时保留缓冲。
- 如果 LLM 调用失败，更新日志和 health，但不丢消息。

建议返回值：

```python
success = bool(result)
if success:
    apply_result(...)
    clear_messages(...)
else:
    trim_messages(user_id, max_buffer_messages)
```

### 7. 清理反思提示词

文件：`reflection.py`

删除输出字段：

- `memory_worthy`
- `memory_content`

替换为阶段 1 可保留的字段：

- `reflection_summary`
- `style_updates`

如果暂不改 `CompanionState` 结构，可以先解析但不落库；阶段 2 或 3 再持久化 `last_reflection_summary`。

### 8. Debug API 调整

文件：`main.py`、`pages/debug/index.html`

阶段 1 必做：

- `_resolve_user_id()` 不再使用 `_auto_main_user_id`。
- 未配置 UID 返回 `{"error": "no_bound_user"}`。
- `_api_health()` 增加绑定状态。
- `buffer_count` 使用主绑定 UID。
- `background_tasks` 增加 per-user reflection 任务数。

阶段 1 可选：

- reset、clear、trigger 从 GET 改 POST。若担心 AstrBot page bridge 支持不确定，可先保留 GET，并在阶段 3 Debug 重构时处理。

## 五、测试方法

### 1. 单元测试建议

如果当前插件没有测试框架，可以先新增轻量 pytest 测试；如果暂不引入测试目录，至少通过手动脚本验证核心纯函数。

建议覆盖：

- `load_config()` 能读取分组配置。
- `load_config()` 能读取扁平配置。
- `main_user_ids` 字符串可解析成列表。
- `BindingManager.is_bound()` 只允许配置 UID。
- `Storage.trim_messages()` 保留最新 N 条。
- `Storage.count_recent_user_messages()` 只统计窗口内 user 消息。
- `RuleEngine.classify()` 在 `recent_rate >= 5` 时返回 `active_chat`。

### 2. 手动验证场景

场景 A：未配置 UID。

步骤：

1. 清空 `main_user_ids`。
2. 启动插件。
3. 私聊发送普通消息。
4. 触发一次 LLM 回复。
5. 打开 Debug 页面。

期望：

- 不保存消息。
- 不注入 companion context。
- Debug health 显示未绑定。
- 日志不出现自动绑定。

场景 B：配置 UID。

步骤：

1. 配置 `main_user_ids` 为当前账号。
2. 私聊发送普通消息。
3. 触发 LLM 回复。

期望：

- `message_buffer` 增长。
- `companion_state.messages_seen` 增长。
- LLM 请求注入 `<companion_context>`。

场景 C：非绑定 UID。

步骤：

1. 配置 UID A。
2. 用 UID B 私聊。

期望：

- 不捕获 UID B 消息。
- 不为 UID B 注入上下文。

场景 D：反思失败。

步骤：

1. 配置无效 provider 或临时让 `_llm_generate()` 返回空。
2. 积累达到反思阈值。
3. 触发反思。

期望：

- 反思失败有日志。
- `message_buffer` 不被清空。
- 后续 provider 恢复后还能再次反思。

场景 E：任务去重。

步骤：

1. 积累足够消息。
2. 连续点击 Debug 触发反思多次。

期望：

- 同一用户只有一个反思任务。
- Debug health 中任务数不会无限增加。

场景 F：缓冲裁剪。

步骤：

1. 设置 `max_buffer_messages = 5`。
2. 连续发送 8 条消息。

期望：

- `message_buffer` 最多保留 5 条最新消息。

### 3. 回归验证

需要确认以下旧功能仍可用：

- `/cp_status`
- `/cp_profile`
- `/cp_reset`
- `/cp_silent`
- LLM 上下文注入
- 沉默意图注入
- Debug 页面基础加载

## 六、完成标准

阶段 1 完成后，应满足：

- 插件不再存在自动绑定行为。
- 配置读取稳定，WebUI 配置能生效。
- 未绑定时安全静默。
- 绑定用户的消息学习和上下文注入正常。
- 反思失败不会丢数据。
- 消息缓冲有明确上限。
- 活跃聊天事件可触发。
- 代码结构为阶段 2 的状态恢复和衰减留出接口。
