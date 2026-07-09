# CompanionLite 设计思想

## 一、起源：三兄弟架构的观察

在构建 CompanionLite 之前，我们深入分析了 AstrBot 生态中三个核心插件的协同模式：

```
┌─────────────────────────────────────────────────────────────┐
│  SelfLearning (完整版)          SelfLearning Lite            │
│  ┌─────────────────────┐        ┌────────────────┐        │
│  │ 消息捕获 → 风格学习   │        │ 规则状态跟踪    │        │
│  │ → 人设进化 → 社交   │        │ → LLM注入      │        │
│  │   上下文注入         │        │ (检测LM但未    │        │
│  │                     │        │  实际委托)      │        │
│  │ FeatureDelegation   │        └────────────────┘        │
│  │ ├─ delegate_memory  │                                    │
│  │ │   → LivingMemory │     GroupChatPlus                  │
│  │ └─ delegate_reply   │     ┌──────────────────┐         │
│  │   → GCP            │     │ 概率门控 → 决策AI │         │
│  └─────────────────────┘     │ → 回复AI → 改写   │         │
│         │                    │ MemoryInjector    │         │
│         │                    │ (直接调用LM API)  │         │
│         ▼                    └──────────────────┘         │
│  ┌──────────────────────────────────────────┐             │
│  │  LivingMemory (长期记忆核心)              │             │
│  │  PassiveGroupCapture → ConversationMgr   │             │
│  │  → MemoryReflection(LLM) → MemoryEngine  │             │
│  │  → FAISS + BM25 + Graph + Atom           │             │
│  │  → on_llm_request注入记忆到所有LLM调用    │             │
│  └──────────────────────────────────────────┘             │
└─────────────────────────────────────────────────────────────┘
```

### 关键发现

**交互模式**：三个插件之间，只有 GCP 做了主动读取（`MemoryInjector` 直接调用 `memory_engine.search_memories()`），没有任何插件主动向 LM **写入**数据。

**数据流向**：单向依赖，不调用对方 API。SelfLearning 检测到 LM 活跃后，关闭本地记忆模块；检测到 GCP 活跃后，关闭本地回复生成。这是纯粹的"开关式委托"，不是数据交换。

**分层原则**：每个插件管一层，互不侵入。LM 管事实记忆，SL 管风格/人设，GCP 管回复决策。

---

## 二、空白：私聊陪伴场景的缺失

三兄弟的设计初衷是群聊场景。在私聊场景中，存在一个明显的空白：

| 能力 | LivingMemory | SelfLearning | GroupChatPlus | CompanionLite |
|------|-------------|-------------|--------------|---------------|
| 事实记忆 | ✅ 核心能力 | 可委托 | ❌ | 委托 LM |
| 关系感知 | ❌ | ✅ 好感度 | ❌ | ✅ 核心能力 |
| 回复决策 | ❌ | 可委托 GCP | ✅ 核心能力 | 沉默机制 |
| 风格学习 | ❌ | ✅ 核心能力 | ✅ 部分 | ✅ 轻量版 |
| 私聊优化 | ❌ | ❌ | ❌ | ✅ 唯一目标 |

**CompanionLite 的定位**：填补私聊场景的关系感知空白。管"我们之间的关系"，让 LM 管"发生了什么"。

---

## 三、设计哲学

### 3.1 平行层，非主从

```
LM: "用户上周三提到喜欢猫，对Git感兴趣"
CL: "我和这个用户比较熟了，他今天状态一般，回复短一点比较好"

LLM 同时看到两层的注入，自己做融合：
  "用户喜欢猫 → 可以聊猫"
+ "他今天状态一般 → 简短、温和地聊"
= 简短聊猫，不追问，语气温柔
```

CL 不碰 LM 的数据，LM 不碰 CL 的状态。两者通过同一个 LLM 请求上下文自然融合。

### 3.2 零侵入 LivingMemory

这是从三兄弟架构中学到的最重要的一课：**不主动写入 LM**。

风险清单：
- 数据所有权混乱：LM 的 PassiveGroupCapture 可能同时捕获同一段对话 → 重复记忆
- 重要性冲突：CL 自定 importance，LM 的 MemoryProcessor 有自己的评估 → 两条独立记忆链
- 生命周期不统一：LM 的记忆有 decay_scheduler 管理，CL 写入的记忆可能被错误衰减
- API 耦合：LM 的 `memory_engine` 接口是内部 API，不是稳定契约

CL 的做法：初始化时检测 LM 是否存在且活跃，仅记录状态。信任 LM 自己管理记忆。

### 3.3 规则 + LLM 双轨学习

**Layer 1 - 即时规则（无 LLM 开销）**：

每条约 1ms 完成。关键词匹配 → 事件分类 → 状态加减。

| 事件类型 | 触发词 | 状态变化 |
|---------|--------|---------|
| gratitude | 谢谢/多谢/帮大忙 | safety+3, closeness+2, energy+1 |
| boundary_push | 别烦/走开/不想聊 | boundary_pressure+8, safety-2 |
| affection | 喜欢/爱你/想你 | closeness+5, safety+3 |
| deep_sharing | 长消息 >200字 | familiarity+3, closeness+2 |
| style_length_short | 短点/简短/别太长 | preferred_length→简短 |

**Layer 2 - LLM 深度反思（每 12 条 + 30 分钟触发）**：

将近期消息缓冲发给 LLM，返回关系变化、心情判断、风格偏好更新。这是唯一的 LLM 调用点，用于规则无法覆盖的深层理解。

### 3.4 沉默机制：Bot 有不回复的权利

传统插件都关注"如何让 Bot 回复"。CL 反其道而行之：**Bot 有权不回复**。

触发条件：
- `energy < 25`：低能量沉默
- `boundary_pressure > 60`：防御沉默
- `boundary_pressure > 60` 且 `safety <= 25`：强边界沉默

实现方式：注入 `<silence_intent>` 标签，让 LLM 自然产生简短安抚语。不中断事件流，不阻止其他插件运行。

---

## 四、架构总览

```
CompanionLite 插件
├── 消息捕获层 (on_private_message)
│   ├─ RuleEngine.classify() → 关键词 → 事件类型
│   ├─ state.apply_event() → 即时状态更新
│   ├─ storage.append_message() → 消息缓冲
│   └─ _maybe_trigger_reflection() → 每12条+30min触发LLM分析
│
├── 深度反思层 (LLM辅助)
│   ├─ 将近期消息缓冲发给LLM
│   ├─ LLM返回关系变化、心情判断、风格偏好更新
│   └─ 更新CompanionState + StyleProfile
│
├── 沉默机制层 (on_llm_request)
│   ├─ energy < 25 → 低能量沉默
│   ├─ boundary_pressure > 60 → 防御沉默
│   └─ 注入 <silence_intent> 标签
│
├── 上下文注入层 (on_llm_request)
│   ├─ 注入关系状态（自然语言，无数字）
│   ├─ 注入风格偏好
│   └─ 注入心情/能量/边界姿态
│
└── LivingMemory感知层 (只读)
    └─ 初始化时检测LM是否存在且活跃
```

---

## 五、与三兄弟的关键差异

| 维度 | SelfLearning | SelfLearning Lite | CompanionLite |
|------|-------------|-------------------|---------------|
| 场景 | 群聊 + 多用户 | 私聊 + 单一陪伴 | 私聊 + 单一陪伴 |
| 学习方式 | LLM驱动 | 纯规则 | 规则 + LLM双轨 |
| 记忆 | 自有V2引擎 + 可委托LM | 完全委托LM（仅检测） | 完全委托LM（只读检测） |
| 人设演化 | 人设候选生成→审核→应用 | 无 | 无 |
| 回复控制 | 可委托GCP | 无 | 沉默机制（注入意图） |
| 代码量 | ~15000行 | ~500行 | ~800行 |
| 存储 | PostgreSQL | PostgreSQL | SQLite单文件 |
| 外部依赖 | SQLAlchemy + 多LLM | asyncpg | 零 |

### 为什么不继承 SelfLearning Lite？

SelfLearning Lite 的架构是"为后续 LLM 增强预留接口"，Phase 1 实际只有规则引擎在跑。CompanionLite 从零开始，直接实现"规则 + LLM 双轨"，不需要处理遗留的 7 表 schema 和未完成的 delegation。

---

## 六、数据流

```
用户私聊消息
    │
    ▼
capture_private_message (on_private_message)
    │
    ├─ RuleEngine.classify() → 事件类型
    │
    ├─ state.apply_event() → 即时状态更新
    │   (familiarity+, closeness+, energy-...)
    │
    ├─ storage.append_message() → 存入消息缓冲
    │
    └─ _maybe_trigger_reflection()
            │
            ├─ 消息数 < 12? → 跳过
            ├─ 距上次反思 < 30min? → 跳过
            └─ 满足条件 → asyncio.create_task(_run_reflection)
                    │
                    ▼
                LLM 调用 (provider.text_chat)
                    │
                    ├─ 输入: 当前状态 + 近期对话缓冲
                    ├─ 输出: JSON (deltas + mood + style_updates)
                    └─ apply_result() → 更新 CompanionState + StyleProfile
                            │
                            ▼
                        storage.clear_messages() → 清空缓冲

LLM 请求 (on_llm_request)
    │
    ├─ silence.check() → 应沉默?
    │   └─ 是 → 注入 <silence_intent>
    │
    └─ _build_context_text() → 注入 <companion_context>
        (关系状态 + 风格偏好 + 心情/能量/边界姿态)
            │
            ▼
        LLM 同时看到:
            [LM 注入的事实记忆上下文]
            [CL 注入的关系状态上下文]
            ↓
        LLM 自己融合两层信息，生成回复
```

---

## 七、技术选型

| 决策 | 选择 | 理由 |
|------|------|------|
| 存储 | SQLite 单文件 | 零外部依赖，AstrBot data/ 目录合规 |
| LLM 调用 | `provider.text_chat()` | 后台反思用，不触发钩子，避免递归 |
| 上下文注入 | `extra_user_content_parts` + `TextPart` | 动态内容不进 system_prompt，不影响缓存 |
| 配置 | `_conf_schema.json` (object + items) | AstrBot 原生配置面板 |
| Web 页面 | `pages/debug/index.html` | bridge API，5秒自动刷新 |
| 事件钩子 | `on_private_message` + `on_llm_request` + `after_message_sent` | 最小必要集 |

---

## 八、未来方向

- Phase 2：记忆原子化（从 LM 读取记忆，在 CL 层面做关系链接）
- Phase 2：多用户支持（每个用户独立状态，支持家庭/伴侣场景）
- Phase 2：主动问候（基于状态预测，在合适时机主动发起对话）
- Phase 3：人格演化（在 LLM 深度反思中加入 persona 候选生成，但需人工审核后才应用）
