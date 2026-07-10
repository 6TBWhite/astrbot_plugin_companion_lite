# AstrBot_Plugin CompanionLite

[![AstrBot](https://img.shields.io/badge/AstrBot-Plugin-blue)](https://github.com/Soulter/AstrBot)
[![Python](https://img.shields.io/badge/Python-3.9+-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

私人陪伴场景关系感知插件。让 bot 记住你们之间的关系状态——有多熟、有多亲近、边界在哪、现在累不累——并在每条回复中自然体现。

## 核心定位

```
LivingMemory:   "用户上周三提到喜欢猫，对 Rust 感兴趣"
CompanionLite:  "我和这个用户比较熟了，他今天状态一般，回复短一点比较好"
DailyArc:       "昨天对话以疲惫收尾，今天轻一点接，不要急着推新话题"
```

- **关系状态跟踪**：熟悉度、亲近度、边界压力、能量，四个维度独立演化
- **bot 有累的权利**：精力非线性四段模型——精神好时话多但消耗快，累了话少想休息
- **规则 + LLM 双轨学习**：即时关键词分类 + 每 12 条 / 30 分钟 LLM 深度反思
- **每日情感弧线**：反思时由 LLM 提炼当日情绪走势与次日相处指导，跨天注入连续性
- **风格画像**：回复长度、语气、主动程度，从对话中自动学习
- **沉默机制**：能量低或边界压力高时，注入沉默指令让 LLM 自然简短回复
- **LivingMemory 协同**：只读检测，信任 LM 管理事实记忆，零主动写入
- **调试仪表盘**：WebUI 侧栏实时查看关系状态、弧线预览、消息缓冲、风格画像

## 安装

### 1. 获取插件

如果插件已发布到 AstrBot 插件市场，您可以直接从市场安装。

如果从仓库获取，请打开插件 GitHub 仓库页面，点击绿色的 `Code` 按钮，选择 `Download ZIP` 下载源代码压缩包。下载完成后，在 AstrBot 管理面板中前往「插件」→「安装插件」→「从文件安装」，选择该 `.zip` 文件上传即可。

### 2. 依赖项

本插件零外部依赖，仅使用 AstrBot 框架自带能力。

### 3. 配置文件

插件根目录包含以下配置文件，无需手动创建：

| 文件 | 说明 |
|------|------|
| `_conf_schema.json` | 插件配置定义，用于 WebUI 配置面板 |
| `metadata.yaml` | 插件元数据（名称、作者、版本等） |

### 4. 重载/重启 AstrBot

安装或更新插件后，在 AstrBot WebUI 中找到本插件并点击"重载插件"，或直接重启 AstrBot 服务，即可使更改生效。

插件初始化时会自动创建 SQLite 数据库和必要的数据表。

## 配置

所有配置项均可在 WebUI 插件面板中修改。

### 基础设置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enable_message_capture` | bool | `true` | 捕获私聊消息用于关系状态学习 |
| `enable_llm_hook` | bool | `true` | 在 LLM 请求前注入关系状态上下文 |
| `enable_silence` | bool | `true` | bot 在状态不佳时简短回复或保持沉默 |
| `enable_deep_reflection` | bool | `true` | 每 N 条消息触发 LLM 深度关系分析 |
| `main_user_ids` | string | `""` | 逗号分隔的用户 ID。留空时插件不学习、不注入 |
| `min_message_length` | int | `2` | 低于此长度的消息不参与学习 |
| `max_message_length` | int | `500` | 高于此长度的消息不参与学习 |
| `max_buffer_messages` | int | `120` | 每用户最多保留多少条待反思消息 |
| `recent_rate_window_seconds` | int | `60` | 活跃聊天检测的时间窗口 |
| `bond_familiarity_floor` | float | `55.0` | /bond 时熟悉度起步线 |
| `bond_closeness_floor` | float | `50.0` | /bond 时亲近度起步线 |
| `bond_boundary_ceiling` | float | `15.0` | /bond 时边界压力上限 |

### 深度反思设置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `reflection_message_interval` | int | `12` | 每收到多少条消息触发一次 LLM 深度反思 |
| `reflection_time_interval_minutes` | int | `30` | 距离上次反思至少间隔多少分钟才再次触发 |

### 每日弧线与连续性

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enable_continuity_injection` | bool | `true` | 把昨天的弧线与相处建议注入到今天（也是 A/B 验证开关） |
| `continuity_lookback_days` | int | `3` | 生成连续性提示时回看最近几天的弧线趋势（1-7） |
| `enable_arc_finalization` | bool | `true` | 跨天首次反思时把昨天累积的建议压缩成正式明日指导 |
| `arc_midday_compress_threshold` | int | `4` | 一天内累积到几条建议就先做一次中间压缩（0=禁用） |
| `arc_max_segments` | int | `5` | 每天最多保留几条建议片段 |

### 沉默机制设置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `silence_energy_threshold` | int | `25` | 能量低于此值时进入低能量沉默模式 |
| `silence_boundary_threshold` | int | `60` | 边界压力高于此值时进入防御沉默模式 |

### LivingMemory 协同

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `delegate_memory_to_livingmemory` | bool | `true` | 检测到 LM 活跃时信任其管理长期记忆 |
| `livingmemory_plugin_name` | string | `LivingMemory` | 用于检测 LivingMemory 插件实例的名称 |

### LLM 设置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `reflection_provider_id` | string | `""` | 深度反思使用的 LLM 提供商 ID，留空用默认 |
| `max_context_chars` | int | `900` | 注入 LLM 的关系状态上下文最大长度 |

## 使用方式

### 日常使用

配置好 `main_user_ids` 后，插件自动工作：

1. **捕获**：你发给 bot 的每条私聊消息被捕获并分类（感谢/越界/亲密/无聊/休息等）
2. **即时更新**：每条消息即时更新关系状态（亲近度涨了、边界压力升了、精力掉了）
3. **深度反思**：每 12 条消息或 30 分钟，LLM 回顾整段对话，矫正数值、更新风格、生成周期策略
4. **注入**：每条回复前，关系状态以自然语言注入 LLM 上下文，bot "知道"现在该怎么回

### 用户命令

| 命令 | 权限 | 功能 |
|------|------|------|
| `/cp_status` | 管理员 | 查看关系状态摘要 |
| `/cp_profile` | 管理员 | 查看完整关系画像（含风格偏好） |
| `/cp_reset` | 管理员 | 重置当前用户的关系状态与消息缓冲 |
| `/cp_silent` | 管理员 | 手动进入低能量模式（energy=15） |
| `/bond` | 主用户 | 手动建立亲密关系档（调试验证用） |
| `/unbond` | 主用户 | 解除手动亲密关系，回到自然积累档 |

## 关系状态说明

### 四个核心维度

| 维度 | 范围 | 角色 |
|------|------|------|
| **能量 energy** | 10-90 | 互动余裕。聊天消耗、休息恢复，非线性四段演化 |
| **亲近度 closeness** | -50~100 | 亲近感。负值表示疏离/排斥，参与姿态判定 |
| **边界压力 boundary_pressure** | 0-100 | 短期压力。越界升高、修复降低，高压时 bot 收敛 |
| **熟悉度 familiarity** | 0-100 | 认知底色。只升不降的长期积累，决定关系标签 |

### 精力非线性模型

bot 的精力不是线性恢复的——精神好时活跃消耗大，累了恢复极慢：

| 区间 | 自然演化 | 事件消耗 | 事件回血 | 微消耗 |
|------|---------|---------|---------|--------|
| ≥69 很有精神 | -3/h 下滑 | ×2.0 | ×0.0 归零 | 正常扣 |
| 56-68 状态不错 | +2/h 朝70 | ×1.0 | ×0.3 | 正常扣 |
| 43-55 普通 | +1.5/h 朝55 | ×0.6 | ×0.8 | 正常扣 |
| 31-42 微疲 | +1.5/h 朝55 | ×0.6 | ×0.8 | 正常扣 |
| ≤30 累了 | +0.5/h 朝30 | ×0.3 | ×1.0 全额 | 豁免 |

密集聊天时每条额外扣 `uniform(0.30, 0.60)`，活跃期间暂停自然回血（15 分钟没人继续缠着才恢复）。实测 24 轮 40 分钟从 70 降到 ~59。

### 边界姿态

| 姿态 | 触发条件 |
|------|---------|
| 放松亲近 | closeness ≥ 45 且 bp < 10 |
| 正常 | 默认 |
| 谨慎 | bp ≥ 22 |
| 防御 | bp ≥ 40 或 closeness < 0 |
| 强边界 | bp ≥ 65 或 closeness ≤ -35 |

### 核心事件类型

| 用户消息特征 | 事件类型 | 状态变化（大致方向） |
|------------|---------|-------------------|
| 谢谢你 / 帮大忙了 | gratitude | closeness+, energy+ |
| 别烦我 / 走开 | boundary_push | boundary_pressure+8 |
| 喜欢你 / 想你了（方向性） | affection | closeness+（低熟悉度时反向） |
| 无聊 / 没意思 | boredom | energy-3 |
| 不想聊 | rest_request | energy 恢复, 少追问 |

> 词表经过 57 项文本层回归，防止"我喜欢吃火锅"被误判为 affection。

## 注入到 LLM 的上下文示例

用 `---` 分隔块，只报非默认维度，默认偏好不注入：

```
<companion_context>
优先级：周期策略 > 回复基调 > 连续性 > 表达偏好。不要复述这些内容。
---
关系：认识。Para状态：平静，能量稳定，状态不错。回复基调：稳定自然。
---
周期(warm)：保持自然接话，语气可以略微柔和，注意对方如果提到累就少追问。
---
连续性：上次相处整体轻松愉快。今天建议：延续自然闲聊节奏。近几天持续稳定。
</companion_context>
```

沉默模式下追加纯指令行：

```
疲惫低落：1-2句温柔简短回应，可收束对话，不展开新话题。
```

## 调试仪表盘

重载插件后，在 WebUI 进入 `astrbot_plugin_companion_lite/page/debug` 页面。

| 面板 | 内容 |
|------|------|
| 状态总览 | 四个核心维度 + 观测量 + 周期态势 + 最近事件 |
| 连续性（弧线） | 注入预览 + 今日弧线 + 近 7 天弧线卡片 |
| 指导与注入 | 最后注入给 LLM 的完整上下文文本 |
| 风格画像 | 偏好长度 / 语气 / 主动程度 |
| 消息缓冲 | 最近 20 条用户消息 + 手动触发反思 |
| 系统信息 | LM 状态 / 配置开关 / 后台任务 |

## 与 LivingMemory 的关系

- **平行层**：LM 管事实记忆，CL 管关系感知，互不写入对方数据
- **只读检测**：每次健康检查实时调用 `livingmemory.detect()`，不缓存结果
- **零主动写入**：CL 不调用 `memory_engine.add_memory()`，不干扰 LM 的生命周期
- **LLM 注入互补**：LM 先注入记忆，CL 后注入关系状态，LLM 同时看到两层

## 数据存储

- SQLite 单文件，位于 `data/plugin_data/astrbot_plugin_companion_lite/companion_lite.db`
- 4 张表：`companion_state`、`style_profile`、`message_buffer`、`daily_arc`
- 插件更新 / 重装不会丢失数据

## 注意事项

- 需要在配置中设置 `main_user_ids` 才会开始学习和注入，留空时插件静默不工作
- 深度反思会额外消耗 LLM 调用（每 12 条消息或 30 分钟一次）
- 精力模型有随机性（高频微消耗 `uniform(0.30, 0.60)`），同一场景下数值可能略有差异
- `/bond` 是调试验证用途，正常使用不需要手动执行——关系状态会随对话自然演化

## 文件结构

```
astrbot_plugin_companion_lite/
├── main.py                      # 插件入口、命令、Web API
├── config.py                    # 配置定义
├── state.py                     # 关系状态数据结构
├── state_engine.py              # 事件应用、姿态判定、能量模型
├── events.py                    # 关键词分类引擎
├── context_builder.py           # LLM 上下文注入构建
├── silence.py                   # 沉默机制
├── reflection.py                # LLM 深度反思
├── arc.py                       # 每日情感弧线引擎
├── storage.py                   # SQLite 存储层
├── binding.py                   # 主用户绑定
├── livingmemory_integration.py  # LivingMemory 只读检测
├── _conf_schema.json            # 配置面板 schema
├── pages/debug/index.html       # Debug WebUI
└── docs/                        # 设计文档与数学建模
```

## 技术栈

- Python 3.9+
- 零外部依赖
- 使用 AstrBot 框架自带能力（Star、filter、provider、web API）

## License

MIT
