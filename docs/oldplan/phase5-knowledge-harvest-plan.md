# 阶段 5 技术开发计划：知识收获与受控自学习

## 一、阶段目标

阶段 5 的目标是让 CompanionLite 具备受控的“知识收获”能力，让 bot 能从长期私聊中沉淀可复用知识，而不仅仅学习关系状态、情感弧线和表达偏好。

这个阶段实现的不是模型微调，不是人格自动覆盖，也不是无限制自由笔记。它是一个结构化、可审查、可去重、可回滚的知识蒸馏系统。

必须达成的技术目标：

- 新增 `knowledge_harvest` 数据层，保存结构化知识收获。
- 从本地消息缓冲和可选 LivingMemory 摘要中提取候选知识。
- 对候选知识做去重、冲突检查、置信度评分和范围标注。
- 支持 pending / approved / rejected / superseded 状态。
- Debug 页面支持查看、批准、拒绝、删除、改写知识。
- LLM 请求前只检索并注入少量相关 approved 知识。
- 不保存大段私聊原文，不写入 LivingMemory。

## 二、设计边界

必须遵守：

- 不让 LLM 任意写自由文本笔记。
- 不让 bot 自己决定所有内容永久有效。
- 不保存未经压缩的大段私聊原文。
- 不把事实记忆、关系状态、人格改写混在同一张表。
- 不把低置信度猜测直接注入后续对话。
- 不替代 LivingMemory 的事实记忆职责。
- 不自动修改 AstrBot 人格或 system prompt。

知识收获保存的是：

- 用户明确教给 bot 的概念、规则、工具用法。
- 用户项目或协作中的稳定约定。
- 用户反复确认的个人偏好。
- 和该用户协作时可复用的经验。
- 能帮助未来回答或协作的抽象结论。

知识收获不保存：

- 一次性情绪话。
- 未确认猜测。
- 流水账事实。
- 大段原始对话。
- 敏感信息原文。
- 与后续无复用价值的闲聊。

## 三、知识类型与范围

### 1. scope

建议 `scope` 取值：

- `user_only`：只适用于当前绑定用户。
- `project`：适用于用户某个项目或工作流。
- `relationship`：相处和协作经验。
- `general`：通用知识，但需要谨慎批准。

默认范围建议：

- 用户偏好、协作习惯：`user_only`。
- 项目约定：`project`。
- 相处经验：`relationship`。
- 通用知识：默认 pending，需要人工批准。

### 2. knowledge_type

建议 `knowledge_type` 取值：

- `concept`：概念解释。
- `procedure`：步骤、流程、操作方法。
- `preference`：用户稳定偏好。
- `project_rule`：项目规则或约定。
- `collaboration_rule`：协作经验。
- `correction`：用户纠正过的错误。

### 3. status

建议状态：

- `pending`：候选知识，等待自动或人工审查。
- `approved`：可用于后续检索注入。
- `rejected`：拒绝，不再使用。
- `superseded`：被更新知识取代。

## 四、数据模型

### 1. knowledge_harvest 表

建议新增 SQLite 表：

```sql
CREATE TABLE IF NOT EXISTS knowledge_harvest (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    claim TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '',
    knowledge_type TEXT NOT NULL DEFAULT 'concept',
    scope TEXT NOT NULL DEFAULT 'user_only',
    confidence REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'pending',
    source TEXT NOT NULL DEFAULT 'local',
    tags TEXT NOT NULL DEFAULT '[]',
    supersedes_id INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_knowledge_user_status
ON knowledge_harvest(user_id, status);

CREATE INDEX IF NOT EXISTS idx_knowledge_user_topic
ON knowledge_harvest(user_id, topic);
```

字段说明：

- `topic`：主题，例如“用户开发习惯”“某项目部署规则”。
- `claim`：学到的内容，必须短、明确、可复用。
- `evidence`：简短证据摘要，不保存大段原文。
- `knowledge_type`：知识类型。
- `scope`：适用范围。
- `confidence`：置信度。
- `status`：审查状态。
- `source`：local、livingmemory、mixed、manual。
- `tags`：JSON list，用于检索和过滤。
- `supersedes_id`：如果该知识替代旧知识，记录旧记录 ID。

示例：

```json
{
  "id": 12,
  "user_id": "123456",
  "topic": "用户的开发协作偏好",
  "claim": "用户更喜欢先对齐最终愿景，再拆分阶段开发计划。",
  "evidence": "用户多次要求先讨论愿景和阶段计划，再开始实现。",
  "knowledge_type": "collaboration_rule",
  "scope": "user_only",
  "confidence": 0.86,
  "status": "approved",
  "source": "local",
  "tags": ["协作", "开发计划", "偏好"]
}
```

### 2. knowledge_review_log 表（可选）

如果需要审查历史，可新增：

```sql
CREATE TABLE IF NOT EXISTS knowledge_review_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    knowledge_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    before_status TEXT NOT NULL DEFAULT '',
    after_status TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    timestamp REAL NOT NULL
);
```

阶段 5 初版可以不做该表，但 Debug 审查功能若要可追溯，建议加入。

## 五、结构拓扑

阶段 5 后推荐结构：

```text
CompanionLitePlugin
├── KnowledgeHarvestEngine
│   ├── extract_candidates(local_messages, lm_items)
│   ├── normalize_candidate(raw)
│   ├── score_candidate(candidate)
│   ├── classify_scope(candidate)
│   ├── dedupe_and_conflict_check(candidate)
│   └── save_candidate(candidate)
│
├── KnowledgeRepository / Storage
│   ├── save_knowledge(...)
│   ├── list_knowledge(...)
│   ├── update_status(...)
│   ├── supersede(...)
│   └── search_knowledge(...)
│
├── KnowledgeReviewService
│   ├── approve(id)
│   ├── reject(id)
│   ├── delete(id)
│   ├── edit(id, patch)
│   └── log_review(...)
│
├── KnowledgeRetriever
│   ├── lexical_search(prompt, approved)
│   ├── rank_by_overlap(...)
│   ├── optional_embedding_search(...)
│   └── build_injection(...)
│
├── ContextBuilder
│   ├── build_companion_context(...)
│   └── append_knowledge_context(...)
│
└── DebugPanel
    ├── pending knowledge
    ├── approved knowledge
    ├── reject/edit/delete
    ├── source/confidence/scope
    └── injection preview
```

建议新增文件：

- `knowledge.py`：dataclass、候选提取、评分、去重。
- `knowledge_retriever.py`：相关性检索和注入构建。
- `knowledge_review.py`：审查动作封装，可选。

## 六、候选知识提取

### 1. 触发时机

推荐触发：

- 深度反思成功后。
- DailyArc 更新成功后。
- 手动 Debug “提取知识”按钮。

不推荐每条消息都触发 LLM 提取，成本高且容易污染。

### 2. 输入来源

来源：

- 本地消息缓冲。
- 最近 bot 回复。
- 阶段 4 的 LivingMemory 只读摘要。
- 今日 DailyArc 和 ContinuitySummary。

输入组装原则：

- 原始对话最多 20 条。
- LM 摘要最多 5 条。
- 只给 LLM 最近上下文，不给全历史。
- 明确要求只提取“可复用知识”。

### 3. LLM 输出格式

建议 prompt 要求：

```json
{
  "candidates": [
    {
      "topic": "用户的开发协作偏好",
      "claim": "用户更喜欢先对齐最终愿景，再拆阶段计划。",
      "evidence": "用户明确要求先把最终实现愿景和阶段计划写成文档。",
      "knowledge_type": "collaboration_rule",
      "scope": "user_only",
      "confidence": 0.86,
      "tags": ["协作", "规划", "偏好"]
    }
  ]
}
```

约束：

- 最多返回 3 条候选。
- 不确定就返回空列表。
- `claim` 不超过 80 字。
- `evidence` 不超过 120 字。
- 不要保存敏感原文。
- 不要把一次闲聊当作稳定知识。

### 4. 规则预筛

在调用 LLM 前可以用规则判断是否值得提取：

- 出现“记住”“以后”“我一般”“我的习惯”“规则是”“你要知道”。
- 用户纠正 bot：“不是 X，是 Y”。
- 用户明确教授概念：“这个东西是指...”。
- 对话中多次重复同一偏好。

如果没有任何信号，可以跳过知识提取，降低噪声。

## 七、去重与冲突检查

### 1. 去重策略

初版用词面相似即可：

- topic 相同或高度相似。
- claim 字符重叠率高。
- tags 有明显重叠。

可选：

- 如果项目已有 embedding，可后续加入向量相似度。

处理规则：

- 高相似且不冲突：合并 evidence，提高 confidence，更新时间。
- 高相似但新 claim 更具体：新记录 supersede 旧记录。
- 高相似但冲突：新记录 pending，标记冲突原因。

### 2. 冲突示例

旧知识：

```text
用户喜欢所有回复详细解释。
```

新知识：

```text
用户最近明确要求开发讨论先简短给结论。
```

处理：

- 不直接覆盖。
- 新记录 pending 或 supersede 旧记录，视 confidence 和用户明确程度决定。
- Debug 页面展示冲突。

### 3. 状态决策

建议默认策略：

- `confidence >= 0.85` 且 scope 非 `general`：可自动 approved。
- `0.6 <= confidence < 0.85`：pending。
- `< 0.6`：丢弃或 pending_low_confidence，初版建议丢弃。
- `scope == general`：默认 pending，避免错误通用知识污染。

配置项可控制：

- `auto_approve_knowledge`: 默认 `false` 或仅高置信开启。
- `knowledge_auto_approve_threshold`: 默认 `0.85`。

## 八、知识检索与注入

### 1. 检索时机

在 `on_llm_request` 阶段，构建 companion context 后，检索当前 prompt 相关 approved 知识。

注意：

- 未绑定 UID 不检索。
- 知识检索失败不影响回复。
- 每次最多注入 3 条。

### 2. 初版检索算法

无需一开始做向量检索，可用轻量词面匹配：

```text
score = topic overlap + claim overlap + tag overlap + recency bonus + confidence bonus
```

过滤：

- status 必须 approved。
- user_id 必须当前绑定 UID，除非 scope 为 general 且已批准。
- score 低于阈值不注入。

### 3. 注入格式

建议和关系上下文分开：

```xml
<companion_knowledge>
可能相关的已批准知识：
1. 用户更喜欢先对齐最终愿景，再拆阶段开发计划。
2. 当前项目讨论中，文档应先写设计目标和验收标准。
这些知识只用于辅助回答；如果和用户当前表达冲突，以用户当前表达为准。
</companion_knowledge>
```

注入原则：

- 不注入 evidence，除非用户问“你为什么这么认为”。
- 不注入 confidence。
- 不注入 pending/rejected。
- 每条尽量短。
- 当前用户表达优先于历史知识。

## 九、配置项

建议新增 `Knowledge_Settings`：

```json
{
  "enable_knowledge_harvest": true,
  "enable_knowledge_injection": true,
  "auto_approve_knowledge": false,
  "knowledge_auto_approve_threshold": 0.85,
  "knowledge_trigger_message_interval": 20,
  "knowledge_min_interval_minutes": 60,
  "knowledge_max_candidates_per_run": 3,
  "knowledge_injection_limit": 3,
  "knowledge_injection_max_chars": 600
}
```

默认建议：

- `enable_knowledge_harvest`: true。
- `auto_approve_knowledge`: false，初期更安全。
- `enable_knowledge_injection`: true，但只注入 approved。

## 十、Debug API 与页面

建议新增 API：

- `GET page/knowledge?status=pending&limit=20`
- `GET page/knowledge?status=approved&limit=20`
- `GET page/knowledge/search?q=...`
- `POST page/knowledge/approve`
- `POST page/knowledge/reject`
- `POST page/knowledge/delete`
- `POST page/knowledge/edit`
- `POST page/knowledge/extract`

如果 AstrBot bridge 对 POST 支持不稳定，可初版保留 GET + query，但破坏性操作最终应迁移 POST。

Debug 页面新增：

- Pending 知识候选列表。
- Approved 知识列表。
- 每条显示 topic、claim、scope、type、confidence、source。
- 操作按钮：批准、拒绝、删除、编辑。
- 当前 prompt 的知识注入预览，可选。
- 最近一次知识提取状态。

## 十一、失败与安全策略

必须覆盖：

- LLM 提取失败：不影响反思和注入。
- JSON 解析失败：记录 warning，不写入。
- 候选为空：正常跳过。
- 低置信度：不写入或 pending。
- 冲突：不自动覆盖。
- 审查操作失败：返回明确错误。
- 注入检索失败：跳过知识注入。
- 知识内容过长：截断或拒绝。

敏感内容策略：

- evidence 只保存摘要。
- 默认不保存包含明显密钥、密码、token 的内容。
- 可加简单敏感模式过滤：`api_key`、`token`、`password`、`secret`、长串密钥样式。
- 命中敏感模式时 status=pending 或直接丢弃。

## 十二、测试方法

### 1. 单元测试建议

建议覆盖：

- `KnowledgeHarvestEngine.normalize_candidate()` 字段缺失处理。
- `score_candidate()` 对高/低置信候选处理正确。
- `dedupe_and_conflict_check()` 能合并重复。
- 冲突候选不会自动覆盖 approved。
- `Storage.save_knowledge()` / `list_knowledge()` / `update_status()`。
- `KnowledgeRetriever.search()` 只返回 approved。
- 检索结果按相关性排序。
- 注入构建不包含 pending、rejected、evidence、confidence。
- 敏感内容过滤生效。

### 2. 手动验证场景

场景 A：明确教学。

步骤：

1. 用户说“以后我们做开发，先对齐愿景，再拆阶段计划”。
2. 触发知识提取。

期望：

- 生成 pending 或 approved 候选。
- topic 和 claim 清晰。
- evidence 是摘要，不是大段原文。

场景 B：低价值闲聊。

步骤：

1. 用户普通闲聊几句。
2. 触发知识提取。

期望：

- 不生成候选，或候选为空。

场景 C：知识注入。

步骤：

1. 批准一条“开发偏好”知识。
2. 用户问“接下来怎么推进这个插件”。

期望：

- LLM 注入包含相关已批准知识。
- 不注入无关知识。

场景 D：冲突更新。

步骤：

1. 已有 approved：“用户喜欢详细解释”。
2. 用户明确说“以后先短结论，别展开太多”。

期望：

- 新候选 pending 或 supersede，不静默覆盖。
- Debug 页面能看到冲突。

场景 E：敏感内容。

步骤：

1. 用户发送类似 token/password 的内容。
2. 触发知识提取。

期望：

- 不保存为 approved。
- 最好直接丢弃或 pending。

### 3. 回归验证

确认阶段 1-4 能力不退化：

- 显式 UID 绑定仍生效。
- DailyArc 和 ContinuitySummary 仍正常。
- LivingMemory 只读失败仍降级。
- 知识提取失败不影响反思。
- 知识注入失败不影响 companion context。

## 十三、调试与观测

建议日志点：

- 知识提取开始：user、message_count、source。
- 候选数量。
- 每条候选的 status 决策。
- 去重/冲突处理结果。
- 注入知识数量。
- 审查操作。

建议 health 字段：

- `knowledge_harvest_enabled`
- `knowledge_injection_enabled`
- `pending_knowledge_count`
- `approved_knowledge_count`
- `last_knowledge_extract_at`
- `last_knowledge_extract_count`
- `last_knowledge_extract_error`

## 十四、完成标准

阶段 5 完成后，应满足：

- bot 能从明确教学或反复确认的对话中生成结构化知识候选。
- 候选知识具备 topic、claim、evidence、type、scope、confidence、status。
- 低置信度和冲突知识不会静默长期生效。
- 管理员能在 Debug 页面审查、批准、拒绝、删除和编辑知识。
- approved 知识能在相关问题中被少量注入。
- 知识注入不覆盖当前用户表达，不污染人格。
- 插件仍不写入 LivingMemory，不保存大段私聊原文。
- 整个知识收获链路失败时能安全降级，不影响关系连续性能力。
