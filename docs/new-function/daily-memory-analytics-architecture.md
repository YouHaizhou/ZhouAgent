# Daily Memory Analytics 架构方案

> 本文只讨论 `daily-memory analytics` 分析层的架构设计。  
> 不讨论 `daily-memory` 原始存储本身的实现，不讨论 `memory` / `daily-memory` 的落盘位置设计，因为这些已经确定。

---

# 1. 目标与边界

## 1.1 目标

`daily-memory analytics` 的目标不是替代现有 memory 系统，而是在既有原始对话沉淀之上，构建一层更高粒度的“日级分析资产”。

它要解决的问题是：

1. 把某一天的对话内容整理成结构化回顾。
2. 从日级对话中抽取稳定主题、知识点和工作内容摘要。
3. 为后续周级画像、知识图谱和长期用户建模提供稳定输入。
4. 在不污染主对话链路的前提下，把“长期可读的信息资产”从原始对话中提炼出来。

---

## 1.2 非目标

本文明确不做以下事情：

1. 不设计 `daily-memory` 原始数据如何存储。
2. 不设计 `memory` / `daily-memory` 的目录布局和路径派生规则。
3. 不把 analytics 直接并入现有 memory 向量检索主链路。
4. 不讨论实时分析、实时推送、移动端通知、云同步。
5. 不做多人协作画像。
6. 不做 AI 教练式主动干预。
7. 不做人格判断。

---

## 1.3 第一版用户假设

第一版默认单用户。

这是一个重要前提，因为当前会话、归档与对话沉淀虽然有 `session_id`，但没有完整的多人隔离建模语义。`daily-memory analytics` 第一版因此采用：

- 单用户
- 单本地工作区上下文
- 多 session 汇总到同一用户视角

后续若支持多用户，需要补：

- `user_id`
- 用户级 analytics 分桶
- 用户隔离的 profile / graph

但这些不属于当前阶段。

---

# 2. 与现有系统的关系

## 2.1 与 memory 的关系：互补，不替代

现有 memory 更偏：

- 检索型
- 碎片型
- 供主对话引用
- 以 turn 或 memory record 为粒度

`daily-memory analytics` 更偏：

- 回顾型
- 总览型
- 面向人读和后续批处理
- 以“天”为粒度

因此两者关系是：

## memory = 事实碎片层  
## analytics = 日级结构化理解层

两者会有信息重叠，但职责不同：

- memory 用于“找过去提过什么”
- analytics 用于“看这一天整体发生了什么”

---

## 2.2 与主对话 Agent 的关系

主对话 Agent 负责：

- 回答当前问题
- 使用必要工具
- 生成当前轮有效结果

`daily-memory analytics` 不应参与主对话实时决策。

它的职责是：

- 在主对话之后异步或惰性结算
- 基于已有数据做结构化分析
- 为将来的回顾 / 周级画像 / 图谱构建提供输入

也就是说：

## 主对话模型解决当前问题  
## analytics 模块处理“这一天到底发生了什么”

---

## 2.3 与 memory model 的关系

当前项目里已经存在独立的后台 `memory model`，其作用是：

- 对单轮 turn 做 enrichment
- 生成 `reasoning_summary`
- 生成 `tags`
- 生成 `memory_candidates`
- 决策 session/folder 级 memory 的 insert / update / skip

这说明：

## 项目里已经存在“专门控制记忆提取与写入”的独立提示词和独立模型职责

因此 `daily-memory analytics` 不应再复用主 `Agent.md` 来承担这些职责，而应采用：

- 主对话提示词：只面向当前任务处理
- memory model 提示词：只面向 turn 级记忆提取与决策
- analytics 提示词：只面向日级结构化分析

三者职责应明确分离。

---

# 3. 分层架构

建议把 analytics 视为一个独立分析层，而不是 memory 子模块。

## 3.1 三层模型

### A. 原始层
来源于现有系统，analytics 只消费，不负责定义。

包括：

- session turns
- global archive
- turn 级 reasoning summary
- tool calls
- tags
- memory candidates

### B. 结构化分析层
由 analytics 生成，是本文重点。

包括：

- daily summary
- daily observation
- daily topic extraction
- daily artifact summary

### C. 推断聚合层
由结构化分析层继续聚合得到。

包括：

- weekly profile
- topic graph
- long-term growth timeline

---

## 3.2 依赖方向

依赖必须单向：

```text
raw sources -> daily analytics -> weekly/profile/graph
```

更具体地说：

- 推断聚合层只依赖结构化分析层
- 不直接回头读取原始 turns 作为主输入

这样做的好处是：

1. 避免耦合失控
2. 限制 token 成本
3. 让 schema 演进更可控
4. 让 weekly/profile/graph 不依赖原始对话全文

---

# 4. 分析对象定义

## 4.1 分析单元

第一版的基本分析单元是：

## 一个自然日内、同一用户视角下的全部有效对话活动

它可能来自：

- 多个 session
- 同一项目下多次启动
- 同一天内多轮任务切换

analytics 不关心这些轮次属于哪个 REPL 生命周期，而只关心它们在同一天里形成了什么“日级整体”。

---

## 4.2 输入最小集合

daily analytics 第一版不要求读取所有原始细节，只要求拿到足够支撑日总结的信息。

推荐最小输入字段：

- 日期
- session_id
- user 文本
- assistant 文本
- reasoning_summary
- tool_calls
- tags
- memory_candidates
- cwd / project_name

如果后续发现质量不足，再考虑补充：

- tool result 摘要
- 文件修改摘要
- 错误信息摘要

第一版不要直接依赖完整 tool output 原文。

---

# 5. 日级产物设计

第一版建议生成两类核心产物：

1. `daily_summary`
2. `daily_observation`

先不把图谱作为日级必备产物，而是把图谱节点提取视为可选派生产物。

---

## 5.1 Daily Summary

`daily_summary` 回答的是：

- 今天主要聊了什么
- 做了什么
- 推进了什么
- 涉及了哪些知识点
- 用户今天关注点是什么

建议 schema：

```json
{
  "schema_version": 1,
  "date": "2026-05-05",
  "session_ids": ["..."],
  "turn_count": 18,
  "topics": [
    "Qdrant Docker 服务端模式",
    "tool loop 成本控制",
    "skills 选择交互问题"
  ],
  "knowledge_points": [
    "Qdrant",
    "Docker Desktop",
    "Tool Calling",
    "TUI 交互"
  ],
  "work_summary": [
    "调整 Qdrant Docker 启动链路",
    "重构工具循环限制策略",
    "分析 /skills 选择行为"
  ],
  "artifacts": [
    "src/zhou/main.py",
    "src/zhou/llm.py",
    "src/zhou/tui.py"
  ],
  "user_focus": [
    "本地 agent 运行稳定性",
    "长期记忆产品方向",
    "降 token 成本"
  ],
  "open_questions": [
    "daily analytics 如何与 memory 分层",
    "知识图谱的真正用途是什么"
  ],
  "confidence": 0.82
}
```

---

## 5.2 topics 与 knowledge_points 的区分

这是一个必须显式定义的边界。

### topics
表示“今天实际讨论/处理的主题”，偏任务叙事。

例如：

- `Qdrant Docker 服务端模式`
- `tool loop 成本控制`
- `skills 交互行为分析`

### knowledge_points
表示从 topics 中抽取出来的更稳定的知识标签，偏概念。

例如：

- `Qdrant`
- `Docker Desktop`
- `Tool Calling`
- `Prompt Cost Control`

区别可以概括为：

## topics = 今天做了什么  
## knowledge_points = 今天触达了哪些知识概念

如果实践中发现模型区分不稳定，Phase 2 可以考虑把两者合并，但第一版先保留。

---

## 5.3 Daily Observation

`daily_observation` 不是人格评价，而是：

## 基于证据的当日工作/学习行为观察

它回答的是：

- 今天用户表现出哪些具体工作模式
- 今天有哪些明显的阻塞模式
- 有哪些可执行建议

建议 schema：

```json
{
  "schema_version": 1,
  "date": "2026-05-05",
  "observed_strengths": [
    {
      "observation": "能持续沿着异常链路追到具体实现位置",
      "evidence_turn_ids": ["t12", "t14"],
      "excerpt": "先定位主链路，再针对关键模块做修复",
      "confidence": 0.73
    }
  ],
  "observed_blockers": [
    {
      "observation": "在实现与抽象之间来回切换，导致局部修补较多",
      "evidence_turn_ids": ["t7", "t10"],
      "excerpt": "先改运行问题，再回头整理架构",
      "confidence": 0.67
    }
  ],
  "actionable_suggestions": [
    "复杂改动前先固定边界和验收标准",
    "需要跨模块改动时先画调用链或时序图"
  ]
}
```

---

## 5.4 observation 的约束原则

为了避免“正确的废话”，必须约束：

1. 每条 observation 都要带证据
2. 没证据的观察不输出
3. 可以输出空 observation
4. 不允许人格判断
5. 不允许泛化到“你这个人怎么样”

允许的表达：

- 今天在某问题上反复切换验证路径
- 今天多次回到同一模块修补实现
- 今天更偏向先落地再抽象

不允许的表达：

- 用户是一个急躁的人
- 用户性格偏保守
- 用户缺乏系统思维

也就是说：

## 观察对象必须是“对话中体现出的具体行为”，不是“对人的本质判断”

---

# 6. schema version 与兼容策略

所有 analytics 文档都建议带：

- `schema_version`

策略如下：

1. 第一版 schema 尽量只加字段，不改语义
2. 若 schema 有兼容性破坏，再提升版本号
3. 旧数据允许继续存在
4. 如果用户显式要求重建，可用新版本重新生成

第一版不做自动迁移系统。

因为 analytics 本质上是可再生数据，不需要像核心业务数据库那样做重迁移。

---

# 7. 结算策略

## 7.1 采用惰性结算

第一版推荐惰性结算，而不是实时分析。

触发时机：

- 启动时
- 或显式命令触发时

逻辑：

1. 检查哪些日期还没有 analytics 结果
2. 检查哪些日期被标记为 dirty
3. 对这些日期做补算

这样可以避免：

- 每轮 turn 后都发起分析 LLM 调用
- 主对话链路阻塞
- 高频、低收益的重复总结

---

## 7.2 结算状态模型

为防止崩溃中断和重复结算，建议状态使用三态：

- `pending`
- `settling`
- `settled`

可选第四态：

- `failed`

状态流转：

```text
pending -> settling -> settled
pending -> settling -> failed
failed -> pending   (手动重试或下次允许重试)
```

若程序在 `settling` 阶段崩溃，则下次启动将其视为需重算。

---

## 7.3 dirty 标记

建议单独维护 analytics 状态文件，例如：

```json
{
  "dirty_dates": ["2026-05-05"],
  "days": {
    "2026-05-05": {
      "status": "pending",
      "updated_at": "..."
    }
  }
}
```

turn 写入完成后，不立即做重型分析，只做：

- 把当日标记为 dirty
- 状态置为 `pending`

这样即使程序崩溃，dirty 信息也能保留。

---

## 7.4 单次补算上限

建议第一版单次启动最多同步补算 7 天。

原因：

1. 防止长时间阻塞启动
2. 防止第一次恢复时调用量过大
3. 与一周级画像窗口天然兼容

超过 7 天的历史数据：

- 暂不自动全部处理
- 后续可由后台线程或显式命令补算

第一版先不做复杂后台队列系统，但保留扩展点。

---

# 8. 成本控制设计

因为 analytics 本身会新增模型调用，成本必须被显式控制。

## 8.1 不用原始全文做日总结主输入

第一版不建议把当日所有原始 turns 全文直接喂给模型。

更合理的输入是压缩后的结构：

- user 摘要
- assistant 摘要
- reasoning_summary
- tags
- memory_candidates
- tool_calls

这样可以把 daily analytics 的 prompt 体积控制在可接受范围。

---

## 8.2 Phase 1 的最小调用策略

第一版建议每日最多 2 次分析调用：

1. `daily_summary`
2. `daily_observation`

如果想进一步降本，也可以合并成 1 次调用，让模型同时输出两块结构化 JSON。

但合并调用的风险是：

- prompt 更复杂
- 输出 schema 更大
- 某一部分失败时影响整次结果

因此第一版更推荐：

## 先拆成 2 个独立产物，逻辑更稳定

---

## 8.3 confidence 的来源

第一版可以接受 LLM 自评 confidence，但必须把它视为：

## 仅供参考的弱信号

不要把 confidence 当作严格统计量。

后续若要增强可信度，可以加入规则修正，例如：

- 跨 turn 证据数量
- 跨 session 重复出现次数
- 跨天持续性

第一版先不做复杂算法。

---

# 9. 周级画像与图谱的输入关系

## 9.1 weekly_profile 只依赖 daily analytics

weekly_profile 不应直接回读原始 turns。

它只依赖：

- `daily_summary`
- `daily_observation`

在聚合前先做预处理：

- topic 频次统计
- observation 去重
- user_focus 聚类
- artifact 高频统计

之后再交给模型做语义归纳。

这样可以避免周总结再次读取大量原始对话。

---

## 9.2 topic graph 也只依赖 daily analytics

图谱构建第一版不依赖原始 turns，而只依赖 daily 层的 topics / knowledge_points。

这样可以把图谱逻辑做成近似纯算法处理：

- 节点统计
- 共现边建立
- 频次和近因权重计算

不强依赖 LLM。

---

# 10. 图谱第一版策略

## 10.1 第一版只做弱图谱

建议图谱节点只包含：

- `topic`
- `knowledge_point`
- `artifact`

边只包含：

- `co_occurs_with`
- `touches_artifact`
- `repeated_on`

第一版不做：

- `depends_on`
- `is_a`
- `causes`
- 其他强语义边

因为这些边需要更多推理，稳定性差、成本高。

---

## 10.2 节点 importance 先用规则算法

第一版不建议让模型为每个节点单独打分。

推荐手写公式，例如：

```text
importance = 0.4 * frequency
           + 0.3 * recency
           + 0.2 * cross_day_persistence
           + 0.1 * core_topic_bonus
```

其中：

- `frequency`：出现频次归一化
- `recency`：最近一次出现距离当前多近
- `cross_day_persistence`：跨天持续出现情况
- `core_topic_bonus`：是否被 daily_summary 主主题明确命中

这样成本最低、可解释性也更强。

---

# 11. 用户感知与交互

如果 analytics 永远只在后台，用户会感知不到其价值。

第一版建议最低限度提供两个入口：

## 11.1 启动时轻提示

例如：

- 已结算昨日分析
- 昨日主要主题：A / B / C

只做一行摘要，不自动展开长文。

## 11.2 显式命令入口

建议后续提供：

- `/analytics`
- `/analytics day 2026-05-05`
- `/analytics week`

第一版如果还不想做命令，也至少要让产物路径可预期、可查看。

---

# 12. 隐私与脱敏边界

第一版可以接受“本地文件由用户自己负责”的前提，但仍建议在 analytics prompt 中加一条约束：

- 不要复制完整密钥、token、密码
- 不要原样保留明显敏感值
- 需要提及时用“某 API key / 某本地路径配置”这种抽象表述

也就是说：

## 第一版不做复杂脱敏系统，但应避免把敏感原文直接复制进 summary

---

# 13. 模块划分建议

为了避免和现有 memory 主链路耦合，建议新增独立模块。

## 13.1 `analytics_store.py`
职责：

- analytics 目录读写
- state 文件维护
- day status 维护
- schema_version 读写

## 13.2 `daily_digest.py`
职责：

- 聚合同一天输入数据
- 生成 `daily_summary`
- 生成 `daily_observation`

## 13.3 `profile_builder.py`
职责：

- 读取多个日级产物
- 生成周级画像
- 更新 latest profile

## 13.4 `topic_graph.py`
职责：

- 根据 daily topics / knowledge points 构建图谱节点与边
- 计算 frequency / recency / importance

## 13.5 `analytics_scheduler.py`
职责：

- 启动时检查 dirty / pending / failed
- 安排补算
- 管理单次补算上限

---

## 13.6 依赖方向

建议依赖图如下：

```text
analytics_store.py   <- 纯存储层

daily_digest.py      <- analytics_store + llm/client + raw data readers
profile_builder.py   <- analytics_store + llm/client
topic_graph.py       <- analytics_store
analytics_scheduler.py <- analytics_store + daily_digest + profile_builder + topic_graph
main.py              <- analytics_scheduler
```

禁止：

- `profile_builder` 反向依赖 `daily_digest`
- `topic_graph` 反向依赖主对话链路
- analytics 直接侵入 `memory.py` 核心读写路径

---

# 14. Phase 划分与验收

## Phase 1：Daily Analytics 最小闭环

目标：

- 可以对某一天的数据生成 `daily_summary`
- 可以生成 `daily_observation`
- 可以在启动时惰性补算缺失日期

验收标准：

### 功能验收

1. 7 天内缺失日期可成功补算
2. 补算失败不会破坏状态
3. dirty / pending / settling / settled 状态可恢复

### 质量验收

人工抽查 3 天结果：

- 70% 的 topics 能准确概括当天主要内容
- observation 不出现明显人格判断
- work_summary 对人类可读且有回顾价值

### 性能验收

- 单日补算时间可接受
- 不阻塞主交互过久

---

## Phase 2：Weekly Profile

目标：

- 从 daily analytics 聚合出一周级稳定观察
- 输出用户成长趋势与高频主题

前提：

- daily_summary 质量足够稳定
- daily_observation 不充满模板化废话

---

## Phase 3：Topic Graph

目标：

- 基于 daily analytics 构建可用的轻量图谱
- 提供主题共现、高频主题、跨天持续主题能力

前提：

- topics / knowledge_points 粒度已相对稳定

---

## Phase 4：回灌主对话

目标：

- 只在必要场景下，把 analytics 结果回灌给主对话 Agent

最小回灌单元建议优先级：

1. 最近日总结摘要
2. 高频主题
3. 最新周画像
4. 图谱局部上下文

不要一开始就大规模注入所有 analytics 数据。

---

# 15. 当前最值得先明确的工程决策

在开始编码前，建议先固定以下决策：

1. `daily_summary` 与 `daily_observation` 的 schema
2. `schema_version` 机制
3. 状态文件 schema（dirty/pending/settling/settled/failed）
4. 单次补算上限
5. 输入最小集合
6. topics 与 knowledge_points 的区分规则
7. observation 的 prompt 约束边界
8. 启动期同步补算与异步补算边界

这些决策一旦明确，Phase 1 才容易稳定落地。

---

# 16. 结论

`daily-memory analytics` 的本质，不是再造一个新的 memory 系统，而是在既有对话沉淀之上，补一层“日级结构化理解”。

它的价值在于：

- 把碎片对话转成可回顾资产
- 为 weekly profile 提供稳定基础
- 为 topic graph 提供低成本输入
- 未来为主对话回灌提供更高层次的用户背景

最重要的架构原则有三条：

1. **与 memory 主链路解耦**：analytics 是消费者，不是 memory 子系统。  
2. **只做日级结构化理解，不碰原始存储实现**：存储位置和 raw 体系已定，不重复设计。  
3. **先做最小闭环，再做画像和图谱**：先把每天的分析产物做稳定，再谈更重的长期能力。

这才是当前阶段最稳、最可落地的方向。
