# 每日记忆 / 用户成长画像 / 知识图谱 — 拷问文档

> 本文对 `daily-memory-analytics-architecture.md` 进行逐决策分支的追问审查。
> 每个区块包含：追问 → 设计方案的回答 → 推荐答案（若无明确回答）。

---

## 1. 目标的清晰性

### Q1：这个能力的「用户」是谁？
文档说"让 agent 对提问者形成持续认知"，但"提问者"是单人还是多人？如果 ZhouAgent 被团队共用，每日总结是对整个团队的认知还是对个人的？方案中 session / turn 的设计是否区分多用户？

**推荐答案**：第一版默认单用户。如果未来支持多用户，需要 session 级标注 user_id。当前 turns.jsonl 和 global archive 都没有 user_id 字段，这是一个隐式假设。

### Q2：差异化价值的具体度量是什么？
文档说"差异化能力不是堆普通 agent 功能"，但"差异化"的具体度量是什么？怎么判断这个能力"做成了"？靠用户主观感受还是靠某个可量化指标（比如 daily summary 被回顾的次数、用户画像被后续 prompt 引用的次数）？

**推荐答案**：先定主观标准——用户能否在启动时看到有信息增量的昨日总结。能，就算 Phase 1 成功。

### Q3：这个能力与现有 memory 体系是"互补"还是"替代"？
文档说"保持现有 memory 主链路不变"，但 daily summary / observation 产出的信息，与 session/global memory 里的 memory_candidates 有大量重叠。两者同时存在会不会让用户困惑——同一件事既在 memory 里又在 daily summary 里？

**推荐答案**：定位为不同粒度。memory 是"具体事实片段"供检索，daily summary 是"日级结构化总览"供回顾。不替代，互补。

---

## 2. 产品定位的拷问

### Q4：这个能力面向的是"回顾过去"还是"提升未来"？
文档说"对未来问答有帮助的长期背景"，但 Phase 4 才回灌到 prompt。Phase 1-3 期间，daily summary 的用途纯粹是给用户回顾的吗？用户需要主动翻看，还是 agent 主动在适当时机提醒？

**推荐答案**：Phase 1-3 是"供用户回顾"为主，agent 不主动提醒。Phase 4 才考虑 agent 自动引用。

### Q5：「本地长期陪伴型 Agent」的定位，是否假设用户每天都用？
如果用户一周只用一次，惰性结算会一次补算 7 天的数据。这里有两个问题：(a) 补算质量——没有当日上下文，只靠 turns.jsonl 回溯，总结质量会下降多少？(b) 用户体验——一次生成 7 天的总结，用户看了会有"堆量感"吗？

**推荐答案**：(a) 接受质量下降，因为 turns.jsonl 里已有 reasoning_summary 和 tags，足够做日总结；(b) 在启动时不展示全部历史总结，只提示"已补算 N 天"，让用户主动查看。

---

## 3. 三层存储模型的拷问

### Q6：「原始层 / 结构化层 / 推理层」的依赖方向是什么？
文档说三层分层存储，但没有明确：推理层是否只依赖结构化层？还是可以直接读原始层？如果推理层绕过结构化层直接读原始层，分层就形同虚设。如果强制走结构化层，结构化层的更新就必须在推理层之前完成。

**推荐答案**：推理层只依赖结构化层。这样结构化层的 schema 变更可控，推理层逻辑更干净。

### Q7：结构化层的 schema 演进的兼容策略是什么？
daily_summary.json 的 schema 一旦定义，后续修改字段会面临历史数据迁移问题。方案没有提到 schema versioning 策略。是每次改 schema 都重新生成所有历史 daily summary，还是做向后兼容？

**推荐答案**：给 daily_summary.json 加 `schema_version` 字段。改 schema 时尽量做向后兼容（只加字段不改字段），需要重新生成的情况通过惰性补算自然覆盖（下次启动补算缺失日期时用新 schema 重新生成）。

### Q8：「confidence」字段的算法是什么？
daily_summary 的 confidence: 0.82、daily_observation 的 confidence: 0.68——这些数字从哪来？是 LLM 自己给的，还是后计算法？如果是 LLM 给的，跨模型的 confidence 是否可比？如果是算法算的，算法逻辑是什么？

**推荐答案**：Phase 1 使用 LLM 自评 confidence，在 prompt 中要求给出 0-1 的数值并附带理由。Phase 2+ 可对连续多天的同一类观察做 cross-day consistency 计算，作为额外的置信度修正。

---

## 4. 惰性结算的拷问

### Q9：惰性结算的「幂等」怎么保证？
文档说"保证幂等和可重复生成"，但 LLM 生成的内容天然不幂等——同一天的数据跑两次可能产出不同的 daily_summary。方案打算怎么处理：覆盖旧结果？生成新版本做 diff？还是保留多版本？

**推荐答案**：覆盖旧结果（始终只有一份最新 daily_summary）。幂等性通过结算状态标记来保证——已结算日期不再重新结算，除非用户显式请求。

### Q10：跨会话日期怎么判断？
用户可能在同一天启动多次 zhou，每次启动都触发惰性结算检查。如果第一次启动已经结算了"昨天"，第二次启动时"昨天"的状态标记还是"已结算"，不会再跑。但如果第一次启动时正在结算中（LLM 调用中）就崩溃了，会不会留下"已结算"标记但没有实际数据？

**推荐答案**：使用三态标记：`pending` → `settling` → `settled`。结算开始时写 `settling`，完成后写 `settled`。启动时识别 `settling` 状态视为需要重新结算。

### Q11：补算的最大天数限制是多少？为什么是这个数？
文档提到"限制单次最大补算天数"但没给数字。如果用户一个月没用 zhou，启动时补算 30 天，可能耗时很长。要不要考虑异步后台补算？

**推荐答案**：单次启动最多补算 7 天。超过 7 天的历史日期放入队列，后续在 REPL 空闲时异步补算（Phase 2 做）。

---

## 5. 数据模型的拷问

### Q12：daily_summary 的 topics 和 knowledge_points 有什么区别？
`topics` 是 ["Qdrant Docker server mode", "tool-calling loop design"]——看起来很具体、近乎 task 描述。`knowledge_points` 是 ["Qdrant", "Docker Desktop", "tool loop"]——是更抽象的知识点标签。这两者的生成逻辑和粒度区分标准是什么？LLM 能稳定区分吗？

**推荐答案**：`topics` = 今天实际讨论/工作的主题（偏叙事），`knowledge_points` = 从主题中抽取的结构化知识点（偏标签）。在 prompt 中给出两者的示例对比，让 LLM 学会区分。如果实践中区分度差，Phase 2 可合并。

### Q13：daily_observation 的「observed_blockers」和 actionable_suggestions 会不会变成"正确的废话"？
比如 "有时先局部修补，再回头统一抽象"——这个观察如果没有足够证据支撑，读起来就像 LLM 在套模板。怎么防止每天的 observation 变成千篇一律的列表？

**推荐答案**：(a) 强制每一条 observation 带 evidence_turn_ids，没有明确证据就不输出；(b) 在 prompt 中要求 observation 要具体到"今天的具体什么行为体现了这个模式"；(c) 如果当天没有足够证据支撑任何 observation，允许 daily_observation 为空或只有 1-2 条。

### Q14：weekly_profile 的聚合逻辑是什么？
文档说"聚合多个 daily summary"，但聚合是简单的拼接 + LLM 总结？还是有去重/聚类/频次统计？如果是 LLM 做，要不要把所有 daily summary 一次性塞入 prompt？如果一个人用了 7 天，每天 3 个 topics，累积 21 个 topics 加 7 个 observation——prompt 会很长。

**推荐答案**：先做统计预处理（topic 频次排序、observation 去重），再喂给 LLM 做语义聚合。不要直接把 7 天 raw data 全塞。

### Q15：knowledge_points 的命名规范是什么？
knowledge_points 里的 "Qdrant" 和 "Docker Desktop" 和 "tool loop" 命名粒度不一致——"Qdrant" 是产品名，"Docker Desktop" 是更具体的产品，"tool loop" 是抽象概念。如果不统一命名规范，topic_graph 的节点会混乱。

**推荐答案**：定义 knowledge_point 命名规则：优先使用技术社区通用名称，避免自造缩写。对同义不同名的情况（如 "Qdrant" / "qdrant" / "vector store"），在 node 的 aliases 字段中建立映射。Phase 1 不强制完全一致，Phase 3 建图时做别名合并。

---

## 6. 存储结构的拷问

### Q16：analytics 目录为什么平铺在 .zhou 下？
文档建议 `.zhou/analytics/`。但 `.zhou/` 下目前已有 `memory/`、`archive/`、`sessions/`。analytics 和 memory 是什么关系？如果 analytics 产出是 memory 的上层抽象，目录结构是否该体现这个层级关系（比如 `.zhou/memory/analytics/`）？

**推荐答案**：保持 `.zhou/analytics/` 独立。它在职责上是 memory / archive 的消费者而非子集。如果放在 `.zhou/memory/` 下，会暗示 analytics 受 memory 管理，这不对。

### Q17：daily 目录按日期平铺，会不会文件太多？
一年 365 天 = 365 个目录 = 每个目录 ~5 个 JSON 文件 = 1825 个文件/年。对文件系统和目录列表有没有影响？

**推荐答案**：第一年没问题。未来可考虑按月归档（`daily/2026-05/`），但 Phase 1 不需要。

### Q18：turns.index.json 的内容和用途是什么？
文档提到了这个文件但没有定义 schema。它和 session 目录下的 turns.jsonl 是什么关系？是 turns.jsonl 的索引（加速检索）还是 turns.jsonl 的日级切片副本？

**推荐答案**：`turns.index.json` 是日级索引，记录该日期涉及哪些 session 的哪些 turn range，以及关键摘要。用于加速"按日期聚合 turns"而不需要扫描所有 session 的 turns.jsonl。Schema：
```json
{
  "date": "2026-05-05",
  "sessions": [
    {
      "session_id": "xxx",
      "turn_range": [1, 18],
      "turn_ids": ["..."]
    }
  ]
}
```

---

## 7. 数据来源的拷问

### Q19：数据来源里「tags」「memory_candidates」是否已足够覆盖 daily summary 需求？
文档说"优先使用系统已有数据"，但已有 tags 是 turn 级的、由当前 memory model（LLM）生成的。如果 memory model 的 enrichment 质量不高，daily summary 会不会是垃圾进垃圾出？

**推荐答案**：daily summary 的输入还包括 turns.jsonl 的完整对话内容和 reasoning_summary，不只是 tags。即使 tags 质量一般，对话内容本身足够支撑日总结。

### Q20：为什么没有考虑从 tool_calls 的返回值中抽取信息？
daily summary 的 artifacts 列表列出了当天涉及的文件，但 tool_calls 的返回结果（比如读取的文件内容 diff）可能包含更多结构化信息。方案只用了 tool_calls 的"调用记录"，没有用到"调用结果"。

**推荐答案**：Phase 1 只用 tool_calls 的元信息（调用了什么、参数是什么）。Phase 2 考虑从 tool_calls 返回结果中抽取"修改了哪些文件""解决了哪些错误"作为 work_summary 的补充。

---

## 8. 图谱策略的拷问

### Q21：node 的 importance 怎么计算？
`importance: 0.77`——是 LLM 主观给的还是算法计算的？如果是 LLM 给的，7 天 30 个 topic 节点，每个节点都调一次 LLM 评 importance 成本太高。如果是算法——公式是什么？

**推荐答案**：`importance = f(frequency, recency, cross_day_persistence, parent_topic_weight)`。frequency 加权 0.4，recency 加权 0.3，跨天持续性加权 0.2，是否核心主题加权 0.1。Phase 1 先用手写公式，Phase 2 可引入 LLM 复核。

### Q22：edge 的 `type` 枚举是否够用？
五种边类型：`co_occurs_with`、`used_in`、`touches_artifact`、`supports_capability`、`repeated_on`。这五种是否能覆盖所有实际出现的知识关系？比如 "Qdrant depends on Docker"——这是 `depends_on` 还是 `co_occurs_with`？如果不做 `depends_on`，图谱会漏掉重要的因果/依赖关系。

**推荐答案**：Phase 3 先只用 `co_occurs_with`（最稳，不需要 LLM 深度推理关系类型）。`depends_on`、`is_a` 等语义边放到 Phase 4+。

### Q23：图谱的"真的有用"标准怎么验证？
文档说"图谱不应该只是展示"，但所有四个用途（主题聚类、prompt 背景、知识轨迹展示、高频未掌握主题发现）都依赖于 LLM 在后续任务中使用图谱的能力。怎么判断图谱真的提升了后续任务的质量，而不是又一个"形式感强实际没用"的产物？

**推荐答案**：A/B 测试：给 LLM 同样的任务，一组提供图谱上下文，一组不提供，比较输出质量（由用户打分或 LLM-as-judge 评估）。Phase 1-3 不做，Phase 4 需要设计评估框架。

---

## 9. 用户画像边界的拷问

### Q24：「基于对话证据」的「证据」粒度是什么？
文档说每条观察带 evidence。但 evidence 是 turn_id 列表还是具体的对话引用？如果只有 turn_id 列表，用户去翻原始对话的成本很高。如果带具体引用，会不会导致 observation JSON 膨胀？

**推荐答案**：evidence 层用 `turn_ids` + `excerpt`（不超过 50 字的原文摘要）。既有可追溯性又不会过分膨胀。

### Q25：如果用户明确表示不想被"画像"，怎么处理？
有些用户可能对"agent 在分析我"感到不适。方案是否应该提供 opt-out 机制？opt-out 后是停止生成所有 observation 还是只停止 profile 聚合？

**推荐答案**：在配置中加 `analytics.user_observation_enabled: true/false`。关闭后：(a) 不生成 daily_observation.json；(b) 不生成 weekly_profile.json；(c) daily_summary.json 继续生成（不含用户观察内容）。

### Q26：「不做人格判断」这条线怎么在 prompt 层面执行？
"不做人格判断"是人的原则，但 LLM 不一定理解什么是"人格判断"什么不是。方案没有给出 prompt 层面的执行策略。怎么确保 LLM 不会输出"用户是一个急躁的人"？

**推荐答案**：在 daily_observation prompt 中加正面示例和负面示例（few-shot）。正面："今天用户在 debug Docker 问题时反复尝试了 4 种方法才找到根因，体现了排查问题的韧性"。负面（禁止）："用户是一个很有耐心的人"。Phase 1 通过 prompt engineering 保证，Phase 2 可加输出后校验（检测禁止词汇）。

---

## 10. 架构衔接的拷问

### Q27：「在 turn 写入后做轻量事件记录或 mark dirty」——谁来 mark？怎么 mark？
文档说 turn 写入后只做轻量标记。这个标记存在哪？存在 SessionState 的内存变量里？还是写一个 `.analytics_dirty` 文件？如果 zhou 崩溃重启，这个标记还在吗？

**推荐答案**：在 `.zhou/analytics/.state.json` 中维护一个 `dirty_dates: ["2026-05-05"]` 列表。turn 写入后追加当前日期到 dirty_dates。启动惰性结算时先检查 dirty_dates，再检查缺失日期。崩溃不影响——dirty 信息已持久化。

### Q28：analytics 模块需要自己的 LLM client 吗？
现有的 `llm.py` 提供的 `chat()` / `stream()` 接口是否够用？daily summary 生成需要一个长上下文 prompt（聚合全天所有 turns），可能超出现有接口的 token 限制。

**推荐答案**：复用现有 `llm.py` 的 client。如果单次 prompt 包含一天所有 turns 会超 token 限制，先做摘要压缩——用 reasoning_summary + tags + tool_calls 做输入，不传完整对话。

### Q29：如果 daily summary 生成失败（LLM 调用报错），结算状态怎么处理？
是跳过该日期，还是重试？如果跳过，该日期永远不会有 daily summary 了吗？下次启动会再试吗？

**推荐答案**：失败时状态保持 `pending`（从 `settling` 回退到 `pending`）。下次启动时自动重试。连续失败 3 次后标记为 `failed`，不再自动重试，用户可手动触发重新结算。

---

## 11. 模块划分的拷问

### Q30：五个新模块的导入依赖方向是什么？
方案列出 5 个新模块但没有画依赖图。`daily_digest.py` 需要读 turns、调 LLM、写 analytics 存储——它会依赖 `analytics_store.py`、`llm.py`、`session.py`。`profile_builder.py` 依赖 `analytics_store.py` 和 `daily_digest.py` 吗？还是只读存储文件？依赖方向不清晰，容易引入循环依赖。

**推荐答案**：
```
analytics_store.py       ← 无项目内部依赖（纯文件读写）
daily_digest.py          ← analytics_store + llm + session（读 turns）
profile_builder.py       ← analytics_store + llm（只读 analytics 存储，不调 daily_digest）
topic_graph.py           ← analytics_store
analytics_scheduler.py   ← analytics_store + daily_digest + profile_builder + topic_graph
main.py                  ← analytics_scheduler
```
没有循环依赖。

### Q31：`analytics_scheduler.py` 和 `main.py` 的启动耦合程度？
文档说在 main.py 启动期加入 `settle_pending_daily_analytics(config, session)` 一个调用。但如果补算涉及多次 LLM 调用，这个函数会阻塞启动直到所有补算完成。用户可能等不及。

**推荐答案**：启动时只做 `settle_pending` 的同步检查 + 同步生成最近 1 天的 summary（快速）。其余补算用 `threading.Thread` 后台异步执行。main.py 的调用签名不变，内部调度逻辑在 `analytics_scheduler` 中处理。

---

## 12. 分阶段路线的拷问

### Q32：Phase 1 的「稳定」怎么定义？
"把当天聊了什么这件事做稳定"——这里的"稳定"指什么？连续 7 天产出质量一致？补算逻辑跑通？还是用户在回顾 daily summary 时认可信息价值？没有验收标准，Phase 1 就是一个无底洞。

**推荐答案**：
- 功能验收：惰性补算在 7 天内数据上跑通，不报错、不丢数据
- 质量验收：用户选 3 天的 daily summary 做人工评估，70% 的 topics 被认为"准确概括了当天内容"
- 性能验收：补算 1 天的耗时不超过 30 秒

### Q33：Phase 2 → Phase 4 之间的耦合依赖是什么？
如果 Phase 2 的 weekly_profile 质量不好，Phase 3 的 topic_graph 还能做吗？如果 topic_graph 不做，Phase 4 的回灌用什么做背景？各阶段之间的耦合依赖没有明确。

**推荐答案**：
- Phase 2 依赖 Phase 1（需要 daily_summary 和 daily_observation）
- Phase 3 依赖 Phase 1（需要 daily topics），不硬依赖 Phase 2（weekly_profile 对图谱不是必需输入）
- Phase 4 依赖 Phase 1+2+3 中至少完成 Phase 1（daily summary 是最小回灌单元）

### Q34：每个 Phase 的 LLM 调用量预估？
Phase 1 每天至少 2 次 LLM 调用（daily_summary + daily_observation）。如果用户用了 7 天，惰性结算一次会触发 14 次 LLM 调用。成本和延迟是否可接受？

**推荐答案**：Phase 1 每次调用 token 量预估：daily_summary prompt ~2000 tokens + 输出 ~500 tokens；daily_observation prompt ~1500 tokens + 输出 ~400 tokens。总计每天 ~4400 tokens。7 天 = ~30K tokens。使用本地模型（Ollama）成本为零但延迟取决于硬件；使用 API（如 Claude）约 $0.03-0.10（取决于模型）。可接受。

---

## 13. 风险规避的拷问

### Q35：「总结主观」的风险规避只靠 evidence + confidence 够吗？
evidence 和 confidence 是技术手段，但主观性的根源在 prompt。如果 prompt 引导 LLM 做"观察用户模式"，LLM 天然倾向于编造模式。confidence 数字也可能被 LLM 随意给出。有没有更根本的规避方式？

**推荐答案**：Phase 1 的 daily_observation prompt 使用"约束式提问"而非"开放式提问"。不写"请观察用户今天的工作模式"，而是写"请列出今天用户在对话中反复使用的具体行为（如：多次修改同一个函数、反复切换话题方向等），每条行为附带对应的 turn_id"。这样约束 LLM 产出更贴近事实。

### Q36：「低价值 topics 做降权」——低价值怎么定义？
文档说对低价值 topics 做降权，但没定义低价值标准。如果标准是"只出现一次"，那用户第一次提到的新主题就被标记为低价值——这可能不对，因为新主题往往是未来重点。

**推荐答案**：低价值 = 出现在少于 2 个 turn 中 AND 不是用户显式提问的主题 AND 与当前项目无关的零散话题。新主题（首次出现但用户深入探讨）不降权，通过 turn_count 和对话深度判断。

### Q37：有没有考虑过「不做什么」的明确清单？
方案在 10 节说了"不建议做"，在 Phase 1 说了"先不做"。但只有这些够吗？比如：不做实时分析、不做每日推送通知、不做社交分享、不做云端同步、不做多人协作——这些是否也应该明确排除？

**推荐答案**：建议在文档中增加一个独立的"明确排除"章节，列出：
- 不做实时分析（所有结算为惰性/批量）
- 不做移动端推送
- 不做云端存储
- 不做多人用户画像
- 不做 AI 教练式主动干预

---

## 14. 未被讨论的议题

### Q38：daily summary 的隐私边界？
turns.jsonl 包含完整对话，daily_summary.json 包含结构化摘要。如果用户用 zhou 处理敏感内容（密钥、个人信息），这些信息在 daily_summary 中是否被保留？是否需要设计脱敏策略？

**推荐答案**：Phase 1 不做脱敏（因为数据在本地，用户自己负责）。Phase 2 考虑在 daily_summary prompt 中加入"不要复制具体的密钥、密码、token 等内容"的约束。

### Q39：如何让用户"感知"到这个能力的存在？
如果 analytics 全在后台默默运行，用户可能完全不知道有 daily summary 存在。方案没有考虑用户交互设计——用户怎么查看 daily summary？在 TUI 里新增一个命令？还是启动时自动展示昨天的总结？

**推荐答案**：启动时在欢迎信息中加一行"昨日回顾：讨论了 X、Y、Z，解决了 A、B"（约 80 字）。用户输入 `/analytics` 查看完整 daily summary。输入 `/analytics week` 查看周画像（Phase 2 后）。

### Q40：这个能力对现有 memory 检索的影响？
如果 daily summary 和 topic graph 独立于现有 memory_store（Qdrant）之外，那当 agent 需要检索"用户过去讨论过 Qdrant 什么"时，是查 Qdrant 的 memory 还是查 analytics 的 topic_graph？两个信息源可能不一致——memory 里有碎片化的事实，analytics 里有结构化的总结。

**推荐答案**：短期（Phase 1-3）两者独立，agent 只查 memory_store。Phase 4 设计统一检索层，agent 一个接口同时获得碎片化事实（memory）和结构化上下文（analytics）。避免用户或 agent 在两个信息源之间困惑。

---

## 拷问总结

| 维度 | 已覆盖 | 关键缺口 |
|------|--------|----------|
| 目标与定位 | Q1-Q5 | 多用户假设未澄清、成功度量未定义 |
| 存储模型 | Q6-Q8, Q16-Q18 | schema 演进的兼容策略、turns.index.json 未定义 |
| 惰性结算 | Q9-Q11 | 结算状态的原子性、异步补算策略 |
| 数据模型 | Q12-Q15, Q29-Q30 | topics vs knowledge_points 区分标准、naming convention |
| 图谱 | Q21-Q23 | importance 公式、边的语义粒度、效果验证框架 |
| 画像边界 | Q24-Q26, Q35-Q36 | prompt 层面的执行保障、opt-out 机制 |
| 架构衔接 | Q27-Q31 | dirty 标记的持久化、依赖方向、启动阻塞处理 |
| 分阶段路线 | Q32-Q34 | Phase 验收标准、token 成本预估 |
| 未讨论议题 | Q38-Q40 | 隐私脱敏、用户交互设计、与 memory 检索的统一 |

**结论**：方案在"做什么"层面已经相当清晰，但在"怎么做"的工程细节和边界条件上存在 40 个需要明确的决策点。建议在进入 Phase 1 编码前，先对 Q6-Q11、Q27-Q31、Q32-Q34 这三组与实现直接相关的议题给出明确答案。
