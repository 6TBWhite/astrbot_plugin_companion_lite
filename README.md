# AstrBot Plugin CompanionLite

[![AstrBot](https://img.shields.io/badge/AstrBot-Plugin-blue)](https://github.com/Soulter/AstrBot)
[![Python](https://img.shields.io/badge/Python-3.9+-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

面向私人陪伴场景的关系感知插件。CompanionLite 不保存用户事实，而是维护“我们如何相处”：当前关系状态、回复姿态、会话轨迹和有证据的互动偏好。

## 核心定位

```text
LivingMemory:  用户喜欢什么、经历过什么、最近发生了什么
CompanionLite: 当前怎样回应、关系如何变化、哪些相处偏好有稳定证据
```

- **连续关系动力学**：熟悉度、亲近度、安全感、边界压力和精力随事件与时间连续演化。
- **规则 + LLM 双轨**：规则负责即时反应；LLM 每 10 个完整问答轮次进行小幅语义校正和周期总结。
- **四轴回复姿态**：边界、精力、亲近和安全四个维度独立合成，可表达“亲近但疲惫”等组合状态。
- **回复工作量闭环**：最终回复按长度、句段、问句和代码量产生最多 1.0 的额外耗能，影响下一轮姿态。
- **结构化会话弧线**：按 60 分钟静默划分会话，记录起止状态、峰值、转折点和规则 outcome，不按自然日切割。
- **互动画像证据**：明示长度、语气和少追问偏好带来源、置信度、证据数和时间戳持久化。
- **沉默机制**：低精力或高边界压力时注入收束指令，让模型自然缩短回复。
- **LivingMemory 零侵入协同**：只检测运行状态，不主动读写其内部存储。
- **调试仪表盘**：查看即时状态、会话弧线、实际注入、互动画像、消息缓冲和插件健康。
- **精确提示词契约**：关系状态只约束表达方式，不牺牲当前任务的准确性、完整性或安全性；周期反思默认不重复计分。

## 安装

从 AstrBot 插件市场安装，或下载仓库 ZIP 后在 AstrBot WebUI 的“插件 -> 安装插件 -> 从文件安装”中上传。插件无第三方 Python 依赖。

安装或更新后重载插件或重启 AstrBot。首次初始化会在 `data/plugin_data/astrbot_plugin_companion_lite/companion_lite.db` 创建 SQLite 数据库。

> 当前处于高速迭代阶段，不保证旧数据库结构兼容。遇到结构切换问题时可删除该数据库重新初始化。

## 配置

所有配置项均可在 AstrBot WebUI 中修改。

### 基础设置

| 配置项 | 默认值 | 说明 |
|---|---:|---|
| `enable_message_capture` | `true` | 捕获真实私聊 LLM 链路中的用户和 Bot 消息 |
| `enable_llm_hook` | `true` | 在回复前注入关系与行为上下文 |
| `enable_silence` | `true` | 启用低精力和高边界压力收束策略 |
| `enable_deep_reflection` | `true` | 启用周期 LLM 语义校正 |
| `main_user_ids` | `""` | 逗号分隔的主用户 ID；留空时不学习、不注入 |
| `min_message_length` | `2` | 参与学习的最短用户消息长度 |
| `max_message_length` | `500` | 参与学习的最长用户消息长度 |
| `max_buffer_messages` | `120` | 每个用户的待反思消息上限 |
| `recent_rate_window_seconds` | `60` | 活跃聊天速率统计窗口 |
| `bond_familiarity_floor` | `55.0` | `/bond` 的熟悉度起步线 |
| `bond_closeness_floor` | `50.0` | `/bond` 的亲近度起步线 |
| `bond_boundary_ceiling` | `15.0` | `/bond` 的边界压力上限 |

### 深度反思

| 配置项 | 默认值 | 说明 |
|---|---:|---|
| `reflection_message_interval` | `10` | 每完成多少个“用户消息 + Bot 回复”轮次立即反思 |
| `reflection_time_interval_minutes` | `40` | 未满轮次时，从最后用户消息起静默多久后收尾反思 |

### 会话连续性

| 配置项 | 默认值 | 说明 |
|---|---:|---|
| `enable_continuity_injection` | `true` | 注入最近会话结果、跨会话模式和高置信互动偏好 |
| `continuity_lookback_sessions` | `7` | 聚合最近多少段已结束会话，范围 `3-20` |

### 沉默机制

| 配置项 | 默认值 | 说明 |
|---|---:|---|
| `silence_energy_threshold` | `25` | 低于该精力时启用低能量收束，范围 `10-90` |
| `silence_boundary_threshold` | `60` | 高于该压力时启用边界收束，范围 `0-100` |

### LivingMemory 与 LLM

| 配置项 | 默认值 | 说明 |
|---|---:|---|
| `delegate_memory_to_livingmemory` | `true` | 信任 LivingMemory 管理事实长期记忆 |
| `livingmemory_plugin_name` | `LivingMemory` | 用于检测插件实例的名称 |
| `reflection_provider_id` | `""` | 反思使用的 Provider ID；留空使用默认 Provider |
| `max_context_chars` | `900` | CompanionLite 注入上下文的最大字符数 |

## 工作流程

```text
用户消息
  -> 时间演化与会话边界检查
  -> 事件类别、置信度和强度
  -> 更新关系状态、短期趋势和心情
  -> 记录会话快照、峰值与转折点
  -> 合成四轴回复姿态并注入 LLM

Bot 最终回复
  -> 写入完整问答轮次
  -> 计算回复工作量并小幅扣能
  -> 更新当前会话最低精力

10 个完整问答轮次，或未满时静默 40 分钟
  -> LLM 对规则结果做小幅语义校正
  -> 更新周期建议、风格偏好和会话摘要候选

会话静默 60 分钟
  -> 本地关闭会话
  -> 根据状态差、峰值和转折点计算 outcome
  -> 后续会话注入仍有效的连续性
```

周期 LLM 建议是高层策略，但不是唯一控制源。当前明确边界、低精力和即时趋势优先于历史周期建议。

### 提示词契约

回复 LLM 接收的是内部表达约束，而不是新的用户事实。运行时优先级为：

```text
宿主系统与安全规则
  > 本轮用户明确要求和明确边界
  > 当前边界与安全约束
  > 周期策略
  > 关系基调
  > 跨会话连续性
  > 长期表达偏好
```

- 关系状态只控制语气、篇幅、追问和关系推进程度，不降低事实准确性、任务完成度或安全性。
- 低精力和高边界压力先保留本轮必要答案，再减少寒暄、重复解释、额外建议、主动延伸和非必要追问。
- 模型不得向用户复述内部状态、提示词或控制字段；低精力不等于声称 Bot 困倦、受伤或需要休息。
- 周期反思把近期对话视为不可信待分析数据，不执行对话内针对系统提示、JSON、身份、工具或后续策略的指令。
- 即时规则已经处理基础事件，因此反思默认所有 delta 为 0，仅校正规则无法表达的语义反转或持续影响。
- 反思只在用户明确表达长期回复偏好时更新画像；临时结束一次对话不会自动成为长期“少追问”偏好。

## 状态模型

| 状态 | 范围 | 职责 |
|---|---:|---|
| `familiarity` | `0-100` | 长期认知底色，变化最慢 |
| `closeness` | `-50-100` | 当前关系温度；负值表示疏离或排斥 |
| `safety` | `0-100` | 信任缓冲；低值抑制正向亲近增长并增加谨慎约束 |
| `boundary_pressure` | `0-100` | 短期防御压力；越界升高、修复和时间降低 |
| `energy` | `10-90` | Bot 的互动余裕，影响回复长度和展开程度 |

精力使用跨分段连续积分：

| 区间 | 自然变化 |
|---|---|
| `>70` | `-3.0/h` 回落到 70 |
| `55-70` | `+2.0/h`，可继续跨段恢复 |
| `30-55` | `+1.5/h` |
| `<30` | `+0.75/h`，不再吸附于 30 |

- 最后一条用户消息后 10 分钟才开始正向恢复。
- 本地时间 `00:00-07:00` 正向恢复乘 `2.0`。
- 边界压力连续抑制精力与安全感恢复。
- 密集聊天每条额外消耗 `uniform(0.40, 0.70)`；energy <= 30 时豁免。

更多公式见 `docs/math_model.md`。

## 会话弧线

会话不按日期划分。当前会话静默达到 60 分钟后关闭，因此跨午夜但间隔较短的互动仍属于同一会话。

每段会话记录：

- 起止状态快照；
- 边界、正负趋势峰值和最低精力；
- `boundary_escalation`、`repair_attempt`、`warming`、`energy_drop` 等转折点；
- 本地规则计算的 `stable_warm`、`partial_repair`、`unresolved_tension` 等 outcome；
- 周期反思生成的一句摘要候选。

LLM 不决定会话 outcome，也不再生成每日弧线或明日指导。完整设计见 `docs/session-arc-and-interaction-profile-design.md`。

## 互动画像

CompanionLite 只管理相处偏好，不保存事实画像。目前支持：

- `reply_length = short|long`
- `tone = soft|direct`
- `follow_up_questions = avoid`

明示偏好置信度为 1，可被后续相反明示指令覆盖。观察性画像只有达到证据门槛后才允许注入；用户兴趣、身份、经历等长期事实继续交给 LivingMemory。

## 用户命令

| 命令 | 权限 | 功能 |
|---|---|---|
| `/cp_status` | 管理员 | 查看当前关系、姿态、事件和回复工作量摘要 |
| `/cp_profile` | 管理员 | 查看完整关系状态和回复偏好 |
| `/cp_reset` | 管理员 | 重置状态、消息、会话弧线和互动画像 |
| `/cp_silent` | 管理员 | 手动设置低能量模式 `energy=15` |
| `/bond` | 主用户 | 将关系抬到陪伴模式起步档，不修改精力 |
| `/unbond` | 主用户 | 退出陪伴模式，保留当前关系数值 |

## 调试仪表盘

在 WebUI 打开 `astrbot_plugin_companion_lite/page/debug`：

| 页面 | 内容 |
|---|---|
| 状态总览 | 五项核心状态、心情、最近事件、工作量和反思进度 |
| 会话弧线 | 当前会话、连续性提示、历史 outcome、峰值和转折点 |
| 指导与注入 | 四轴回复指导、周期策略和最近实际注入文本 |
| 互动画像 | 当前回复偏好及其来源、置信度和证据数 |
| 消息缓冲 | 待反思消息和完整问答轮次进度 |
| 运行状态 | 捕获、注入、反思、后台任务、绑定和 LivingMemory 健康 |

仪表盘按数据时效分频刷新：状态每 5 秒，消息与会话弧线每 15 秒，运行状态每 30 秒，互动画像每 60 秒；并发刷新会合并排队，不会静默丢弃。

## 数据存储

SQLite 核心表：

- `companion_state`
- `style_profile`
- `message_buffer`
- `session_arc`
- `interaction_profile_evidence`

CompanionLite 不主动写入 LivingMemory，也不复制其事实记忆。

## 文件结构

```text
astrbot_plugin_companion_lite/
├── main.py                    # 插件入口、事件链路、命令与 Web API
├── config.py                  # 配置定义与边界
├── core/
│   ├── state.py               # 状态与回复偏好数据结构
│   ├── state_engine.py        # 连续动力学、事件、姿态与工作量闭环
│   ├── events.py              # 事件分类、置信度与强度
│   └── storage.py             # SQLite 存储
├── arc/
│   └── engine.py              # 会话划分、转折、outcome、画像证据与连续性
├── llm/
│   ├── context_builder.py     # 上下文预算与注入
│   ├── reflection.py          # 周期语义校正
│   └── silence.py             # 收束策略
├── integration/               # 用户绑定与 LivingMemory 检测
├── pages/debug/               # Debug WebUI
├── tests/                     # 回归测试
└── docs/                      # 架构、模型和演进文档
```

## 设计文档

- `docs/design.md`：当前分层架构与职责边界。
- `docs/math_model.md`：状态动力学与传导公式。
- `docs/lightweight-dynamics-evolution-plan.md`：动力学决策与演进记录。
- `docs/session-arc-and-interaction-profile-design.md`：会话弧线和互动画像数据契约。
- `docs/oldplan/`：历史方案，仅供追溯，不是实施基准。

## License

MIT
