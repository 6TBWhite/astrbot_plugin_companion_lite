# CompanionLite

私人陪伴场景关系感知插件。跟踪亲近度、边界压力、能量等关系状态，提供每日情感弧线与连续性注入，并适配 LivingMemory 协同。

> **执行基准**：`docs/execution-plan-slim.md`
> 
> 阶段 2/2.5 已冻结（减法完成，不再新增状态字段、周期字段、事件类型、注入模板）。
> 阶段 3（每日弧线与连续性）已实现，阶段 4 待验证，阶段 5 无限期搁置。

## 核心定位

- **LivingMemory**：管“发生了什么”（事实记忆的捕获、摘要、检索、注入）
- **CompanionLite**：管“我们之间的关系”（熟悉度、亲近度、边界压力、能量、风格偏好）
- **DailyArc**：管“昨天以什么状态结束，今天该怎么接”——这是唯一不能被记忆数据库和 LLM 自身替代的层

```
LivingMemory:   "用户上周三提到喜欢猫，对 Rust 感兴趣"
CompanionLite:  "我和这个用户比较熟了，他今天状态一般，回复短一点比较好"
DailyArc:       "昨天对话以疲惫收尾，今天轻一点接，不要急着推新话题"
```

## 功能

- **关系状态跟踪**：熟悉度（只读底色）、亲近度、边界压力、能量
- **规则 + LLM 双轨学习**：即时关键词分类 + 每 12 条 / 30 分钟 LLM 深度反思
- **每日情感弧线（P3）**：反思时由 LLM 提炼当日情绪走势、关系趋势、重要互动与次日相处指导；注入 `<continuity>` 块提供跨日连续性
- **风格画像**：回复长度、语气、主动程度，从对话中自动学习
- **沉默机制**：能量低或边界压力高时，注入 `<silence_intent>` 让 LLM 自然简短回复
- **LivingMemory 协同**：只读检测，信任 LM 管理事实记忆，零主动写入
- **调试仪表盘**：WebUI 侧栏实时查看关系状态、弧线预览、消息缓冲、风格画像、系统健康

## 架构

```
CompanionLite 插件
│
├── 消息捕获层 (on_llm_request / on_llm_response)
│   用户消息在注入前捕获，assistant 回复在 LLM 响应后捕获
│   跳过工具调用中间轮与系统命令结果
│
├── 即时事件层 (events.py / state_engine.py)
│   EventEngine.classify()      → 关键词 → 事件类型 + confidence
│   StateEngine.apply_event()   → 即时状态更新 + 习惯化/敏化/限速/门控
│   storage.append_message()    → 消息缓冲
│
├── 深度反思层 (reflection.py)
│   近期消息缓冲 → LLM 反思
│   返回：状态数值矫正、风格更新、周期策略、每日弧线(arc_mood/arc_trend/
│         arc_highlights/tomorrow_guidance)
│
├── 每日弧线层 (arc.py)
│   ArcEngine.update_from_reflection()  → 写入 daily_arc 表
│   ArcEngine.build_continuity_text()   → 生成 <continuity> 注入块
│   48h 过期 / cooldown 过滤 / guidance 消毒
│
├── 沉默机制层 (silence.py)
│   energy < 25                    → 低能量沉默
│   boundary_pressure >= max(75, boundary_threshold+15) → 强边界沉默
│
├── 上下文注入层 (context_builder.py / main.py)
│   <companion_context>
│     <cycle_state>          → 周期策略 / 规则指导
│     <relationship_state>   → 关系自然语言描述
│     <continuity>           → 昨日走势 + guidance（P3）
│     <style_preference>     → 回复风格偏好
│   </companion_context>
│
├── 命令层
│   /cp_status, /cp_profile, /cp_reset, /cp_silent
│   /bond, /unbond
│
├── Debug WebUI (pages/debug/index.html)
│   侧栏六面板：状态总览 / 连续性(弧线) / 指导与注入 / 风格画像 / 消息缓冲 / 系统信息
│   支持深/浅色切换（SVG 图标）
│
└── LivingMemory 感知层 (livingmemory_integration.py)
    只读检测，每次 /health 实时检查
```

## 安装

1. 将插件目录放入 AstrBot 的 `data/plugins/` 目录
2. 在 WebUI 插件管理中启用 CompanionLite
3. 重启 AstrBot

## 配置

插件配置面板位于 WebUI → 插件管理 → CompanionLite。

### 基础设置

| 配置项          | 默认值  | 说明                      |
| ------------ | ---- | ----------------------- |
| 启用消息捕获       | true | 捕获私聊消息用于关系状态学习          |
| 启用 LLM 上下文注入 | true | 在 LLM 请求前注入关系状态上下文      |
| 启用沉默机制       | true | bot 在状态不佳时可以选择简短回复或保持沉默 |
| 启用深度反思       | true | 每 N 条消息触发 LLM 辅助深度关系分析  |
| 主用户 ID 列表    | 空    | 逗号分隔的用户 ID              |
| 日志级别         | info | 预留配置项                   |
| 最短学习消息长度     | 2    | 低于此长度的消息不参与学习           |
| 最长学习消息长度     | 500  | 高于此长度的消息不参与学习           |
| 最大缓冲消息数      | 120  | 消息缓冲上限                  |
| 近期速率窗口(秒)    | 60   | 用于活跃聊天检测                |

### 深度反思设置

| 配置项          | 默认值 | 说明                    |
| ------------ | --- | --------------------- |
| 反思触发消息间隔     | 12  | 每收到多少条消息触发一次 LLM 深度反思 |
| 反思触发时间间隔(分钟) | 30  | 距离上次反思至少间隔多少分钟才再次触发   |

### 连续性设置（P3）

| 配置项     | 默认值  | 说明                              |
| ------- | ---- | ------------------------------- |
| 启用连续性注入 | true | 在 LLM 上下文中注入跨日弧线信息，可关闭用作 A/B 验证 |
| 连续性回顾天数 | 3    | 查看最近多少天的弧线用于趋势计算（范围 1-7）        |

### 沉默机制设置

| 配置项    | 默认值 | 说明                     |
| ------ | --- | ---------------------- |
| 能量沉默阈值 | 25  | 能量低于此值时进入低能量沉默模式       |
| 边界沉默阈值 | 60  | 边界压力高于此值 + 额外增量触发强边界沉默 |

### LivingMemory 协同

| 配置项                | 默认值          | 说明                             |
| ------------------ | ------------ | ------------------------------ |
| 委托记忆给 LivingMemory | true         | 检测到 LivingMemory 活跃时，信任其管理长期记忆 |
| LivingMemory 插件名称  | LivingMemory | 用于检测 LivingMemory 插件实例的名称      |

### LLM 设置

| 配置项             | 默认值 | 说明                         |
| --------------- | --- | -------------------------- |
| 深度反思 LLM 提供商 ID | 空   | 留空则使用默认 LLM 提供商            |
| 最大注入上下文字符数      | 900 | 注入 LLM 的关系状态上下文最大长度（含连续性块） |

## 命令

| 命令            | 权限  | 功能                   |
| ------------- | --- | -------------------- |
| `/cp_status`  | 管理员 | 查看关系状态摘要             |
| `/cp_profile` | 管理员 | 查看完整关系画像（含风格偏好）      |
| `/cp_reset`   | 管理员 | 重置当前用户的关系状态与消息缓冲     |
| `/cp_silent`  | 管理员 | 手动进入低能量模式（energy=15） |
| `/bond`       | 主用户 | 手动建立亲密关系档（仅供调试验证）    |
| `/unbond`     | 主用户 | 解除手动亲密关系，回到自然积累档     |

`/cp_status` / `/cp_profile` / `/cp_reset` / `/cp_silent` 需要管理员权限。
`/bond` / `/unbond` 仅对 `main_user_ids` 中已配置的主用户生效，用户许可仍由配置控制。

## 调试仪表盘

重载插件后，在 WebUI 进入 `astrbot_plugin_companion_lite/page/debug` 页面。

### 面板分区

| 面板      | 内容                                                                                                  |
| ------- | --------------------------------------------------------------------------------------------------- |
| 状态总览    | 活跃三维（closeness / boundary_pressure / energy）+ familiarity 底色 + 观测量（safety / mood）+ 周期态势 + 最近事件与门控原因 |
| 连续性（弧线） | 注入预览 + 开关状态 + 今日弧线 + 近 7 天弧线卡片 + 刷新/重置按钮                                                            |
| 指导与注入   | 最后注入给 LLM 的完整上下文文本                                                                                  |
| 风格画像    | 偏好长度 / 语气 / 主动程度                                                                                    |
| 消息缓冲    | 最近 20 条用户消息 + 清空 / 手动触发反思                                                                           |
| 系统信息    | LM 状态 / 配置开关 / 缓冲数 / 后台任务 / 反思任务                                                                    |

### 侧栏徽章

- **普通策略**（绿灯）/ **收敛策略**（红灯）
- **LivingMemory 运行中** / **LivingMemory 未运行**
- 今日弧线日期（有 arc 数据时显示日期）

## 关系状态说明

### 活跃决策维度（P2/P2.5 冻结后）

| 维度                | 范围       | 角色                    |
| ----------------- | -------- | --------------------- |
| closeness         | -50..100 | 亲近度，参与门控、边界姿态、周期权重    |
| boundary_pressure | 0..100   | 边界压力，参与门控、边界姿态、衰减速率分档 |
| energy            | 10..90   | 能量，参与沉默决策、学习速率        |

### 只读底色

| 维度          | 范围     | 角色                |
| ----------- | ------ | ----------------- |
| familiarity | 0..100 | 熟悉度，参与过早亲密门控，不再调参 |

### 观测量（不参与姿态/边界决策）

| 维度     | 范围     | 角色            |
| ------ | ------ | ------------- |
| safety | 0..100 | 安全感，仅展示与被事件更新 |
| mood   | -      | 心情，仅展示与被事件更新  |

### 边界姿态

| 姿态   | 条件                                         |
| ---- | ------------------------------------------ |
| 放松亲近 | closeness >= 45 且 boundary_pressure < 10   |
| 正常   | 默认                                         |
| 谨慎   | boundary_pressure >= 22                    |
| 防御   | boundary_pressure >= 40 或 closeness < 0    |
| 强边界  | boundary_pressure >= 65 或 closeness <= -35 |

### 核心事件类型

| 用户消息特征         | 事件类型               | 状态变化（大致方向）            |
| -------------- | ------------------ | --------------------- |
| 谢谢你 / 帮大忙了     | gratitude          | closeness+2, energy+1 |
| 别烦我 / 走开       | boundary_push      | boundary_pressure+8   |
| 喜欢你 / 想你了（方向性） | affection          | closeness+5           |
| 无聊 / 没意思       | boredom            | energy-3              |
| 短一点 / 别太长      | style_length_short | preferred_length→简短   |
| 展开讲讲 / 详细说说    | style_length_long  | preferred_length→详细   |
| 温柔点 / 哄哄我      | style_tone_soft    | preferred_tone→温柔     |
| 打直球 / 说重点      | style_tone_direct  | preferred_tone→直球     |
| 不想聊            | rest_request       | bp+2, 能量恢复, 少追问       |

> 词表经过了 57 项文本层回归，防止"我喜欢吃火锅"被误判为 affection、"滚动条"被误判为越界。

## 注入到 LLM 的上下文示例

```xml
<companion_context>
<priority>优先级：周期策略 > 总体回复基调 > 连续性背景 > 表达偏好</priority>
<cycle_state>[LLM 周期策略或规则指导]</cycle_state>
<relationship_state>
关系：熟人；有些亲近感，几乎没有边界压力。
状态：心情平静，精力正常，相处姿态放松。
</relationship_state>
<continuity>
昨天对话以轻松闲聊为主，整体氛围良好。
今天建议：可以延续自然的闲聊节奏，注意对方是否有新话题。
</continuity>
<style_preference>
表达偏好：回复长度偏中等，语气偏自然，主动程度为正常接话。
</style_preference>
被问感受时用自然日常语言表达，不复述数值和术语。
</companion_context>
```

沉默模式下会追加：

```xml
<silence_intent>
你现在精力不足。平静克制地简短回应，不冷嘲、不赌气、不解释话少，不主动开启新话题。
</silence_intent>
```

## 与 LivingMemory 的关系

- **平行层**：LM 管事实记忆，CL 管关系感知，互不写入对方数据
- **只读检测**：每次健康检查实时调用 `livingmemory.detect()`，不缓存结果
- **零主动写入**：CL 不调用 `memory_engine.add_memory()`，不干扰 LM 的生命周期
- **LLM 注入互补**：LM 先注入记忆，CL 后注入关系状态，LLM 同时看到两层
- **消息捕获链路对齐**：用户消息从 `on_llm_request` 捕获，assistant 回复从 `on_llm_response` 捕获——与 LivingMemory 一致的链路，系统命令不会进入双方缓冲

## 数据存储

- SQLite 单文件，位于 `data/plugin_data/astrbot_plugin_companion_lite/companion_lite.db`
- 4 张表：`companion_state`（关系状态）、`style_profile`（风格画像）、`message_buffer`（消息缓冲）、`daily_arc`（每日情感弧线）
- 插件更新 / 重装不会丢失数据

## 文件结构

```
astrbot_plugin_companion_lite/
├── __init__.py                  # 插件元信息
├── main.py                      # 插件入口、接线、命令、Web API
├── config.py                    # 配置定义与反序列化
├── state.py                     # CompanionState / StyleProfile 数据结构
├── state_engine.py              # 事件应用、姿态判定、时间衰减
├── events.py                    # 关键词分类引擎（EventEngine）
├── context_builder.py           # LLM 上下文注入文本构建
├── silence.py                   # 沉默机制判定与文案
├── reflection.py                # LLM 深度反思 prompt 与解析
├── arc.py                       # 每日情感弧线与连续性引擎（P3）
├── storage.py                   # SQLite 存储层
├── binding.py                   # 主用户绑定管理
├── livingmemory_integration.py  # LivingMemory 只读检测
├── _conf_schema.json            # 配置面板 schema
├── pages/
│   └── debug/
│       └── index.html           # Debug WebUI 侧栏面板
└── docs/
    ├── execution-plan-slim.md   # 当前执行基准（P2/P2.5 冻结 + P3 瘦身）
    ├── changelog.md             # 变更日志
    ├── design.md                # 设计文档
    └── oldplan/                 # 原 phase 1-5 全量计划（参考存档）
```

## 技术栈

- Python 3.9+
- 零外部依赖
- 使用 AstrBot 框架自带能力（Star、filter、provider、web API）

## License

MIT
