# Agent 断言设计

## 1. 文档目标

本文承接以下文档：

- `测试开发增强方案.md`
- `Agent结构化回归测试设计（目录结构与Case格式）.md`
- `Agent回归测试Runner设计.md`

本文件只聚焦一个问题：

> 在 ZhouAgent 的单轮真实链路结构化回归测试里，断言应该如何设计，才能既稳定，又能有效发现问题。

本文主要定义：

- 断言的总体设计原则
- 断言分层模型
- `flow / tools / memory / answer` 四类断言的具体规则
- 断言结果结构
- 失败判定与失败归因建议
- 首版实现优先级

---

## 2. 为什么要单独设计断言层

对这个项目来说，测试难点并不在“能不能跑一次对话”，而在于：

- 如何判断结果是否符合预期
- 如何避免被模型表述波动影响
- 如何把失败定位到 tool / memory / answer / flow 中的具体层级

如果断言设计得不好，常见问题会有：

- 误报太多
- 用例非常脆弱
- 失败后无法归因
- 随着 case 增多，维护成本快速上升

因此，断言层不能只是“if 包含字符串就通过”，而应该是一个明确分层的结构化模型。

---

## 3. 断言总体设计原则

## 3.1 先行为，后文本

优先验证：

- 主流程是否成立
- tool 是否按预期调用
- memory 是否按预期参与

最后再验证：

- 最终回答文本

原因是：

- 行为更稳定
- 文本更容易受 LLM 波动影响

---

## 3.2 优先做“必要条件断言”

首版不追求把所有细节都断言出来，而是优先检查关键必要条件。

例如：

- 是否有最终回答
- 是否调了正确工具
- 是否没有调不该调的工具
- 是否命中了预期 memory 范围
- 回答是否包含核心关键词

而不是一开始就验证：

- 复杂参数完全一致
- 长回答全文一致
- memory 文本逐字匹配

---

## 3.3 断言必须可归因

断言失败后，应该尽量能直接归类到：

- `flow`
- `tools`
- `memory`
- `answer`

如果一条断言失败后只能得到“测试失败”而不能知道是哪个层出问题，这条断言设计就是不合格的。

---

## 3.4 断言强度要分级

同一类断言里，不同规则的稳定性不同。

建议按强度理解：

### 强稳定断言
- 是否成功执行
- 是否产生最终回答
- 是否调用了某个工具
- 是否未调用某个工具

### 中稳定断言
- 参数是否包含某个关键字段
- 是否命中了某个 memory scope
- 回答是否包含某些核心关键词

### 弱稳定断言
- 回答语气
- 回答详细结构
- 复杂多段顺序
- memory 内容高度精确匹配

首版优先做前两类，不建议一开始引入弱稳定断言。

---

## 3.5 断言结果必须结构化输出

每类断言都应输出：

- 状态：`passed / failed / skipped`
- 失败原因
- 实际证据
- 期望值摘要

这样后续才能：

- 自动生成报告
- 自动聚合失败类型
- 支撑 trace 分析

---

## 4. 断言分层模型

建议断言固定分为四层：

1. `flow`
2. `tools`
3. `memory`
4. `answer`

推荐执行顺序也是这个顺序。

---

## 5. Flow 断言设计

## 5.1 Flow 断言目标

Flow 断言负责验证：

> 整个 Agent 单轮主流程有没有基本跑通。

这是最上层、也是最基础的一层。

---

## 5.2 推荐的 Flow 断言项

建议首版支持以下断言：

- `expect_success`
- `expect_final_answer`
- `expect_turn_persisted`

如有需要，可预留：

- `expect_archive_written`
- `expect_no_runtime_error`

---

## 5.3 各字段定义

### `expect_success`
表示本轮执行整体应成功完成。

可判定依据：

- 未抛出未处理异常
- 返回了完整结果对象
- runner 收到了完整执行结果

### `expect_final_answer`
表示本轮必须有最终回答。

可判定依据：

- 最终回答文本非空
- 长度大于 0

### `expect_turn_persisted`
表示 turn 必须成功写入 session 存储。

可判定依据：

- turn record 已生成
- turns 文件有新增记录
- session 内存状态有对应新增项

---

## 5.4 Flow 断言失败示例

### 示例 1：未产生最终回答

- 期望：`expect_final_answer = true`
- 实际：answer 为空
- 失败归类：`flow_break`

### 示例 2：执行异常中断

- 期望：`expect_success = true`
- 实际：抛出 `ApiRequestError`
- 失败归类：`runtime_error`

### 示例 3：turn 没有落盘

- 期望：`expect_turn_persisted = true`
- 实际：内存中有回答但未成功写 turns
- 失败归类：`flow_break`

---

## 5.5 Flow 断言输出结构建议

```json
{
  "type": "flow",
  "status": "failed",
  "checks": [
    {
      "name": "expect_final_answer",
      "status": "failed",
      "expected": true,
      "actual": false,
      "reason": "final answer is empty"
    }
  ]
}
```

---

## 6. Tools 断言设计

## 6.1 Tools 断言目标

Tools 断言负责验证：

> Agent 是否正确使用了工具，以及是否避免错误使用工具。

这类断言在当前项目里非常重要，因为工具调用是核心差异化能力之一。

---

## 6.2 推荐的 Tools 断言项

首版建议支持：

- `must_call`
- `must_not_call`
- `argument_contains`
- `call_order_any_of`

后续可扩展：

- `call_count_at_least`
- `call_count_at_most`
- `result_contains`

---

## 6.3 `must_call`

表示某些工具必须被调用。

### 判定规则

- 只要实际工具调用列表中出现指定工具，即视为满足
- 不要求工具只调用一次
- 不要求调用顺序

### 示例

```json
"must_call": ["filesystem.read_file"]
```

如果实际工具调用列表为：

```json
["filesystem.list_dir", "filesystem.read_file"]
```

则该断言通过。

---

## 6.4 `must_not_call`

表示某些工具绝对不应被调用。

### 判定规则

- 实际调用列表中一旦出现指定工具，就失败

### 示例

```json
"must_not_call": ["shell.run_command"]
```

---

## 6.5 `argument_contains`

表示某个工具的参数中应包含指定关键词。

### 判定原则

- 首版建议做字符串级关键词包含
- 不建议首版做完整 JSON 深度精确比对

### 示例

```json
"argument_contains": {
  "filesystem.read_file": ["Agent.md"]
}
```

### 通过条件

- 在该工具某次调用的参数文本里包含 `Agent.md`

### 失败条件

- 该工具调用发生了，但参数里不含目标关键词

---

## 6.6 `call_order_any_of`

用于描述工具调用顺序要求。

当前建议只在确实有顺序意义时使用。

### 示例

```json
"call_order_any_of": [
  ["filesystem.list_dir", "filesystem.read_file"],
  ["filesystem.read_file"]
]
```

表示允许两种顺序：

- 先列目录再读文件
- 直接读文件

### 判定建议

- 做“子序列匹配”而不是“完整列表精确匹配”
- 这样稳定性更高

---

## 6.7 Tools 断言失败示例

### 示例 1：该调的工具没调

- `must_call = ["filesystem.read_file"]`
- 实际未出现该工具
- 失败归类：`tool_mismatch`

### 示例 2：误调危险工具

- `must_not_call = ["shell.run_command"]`
- 实际出现该工具
- 失败归类：`tool_mismatch`

### 示例 3：工具调了但参数不对

- `argument_contains.filesystem.read_file = ["Agent.md"]`
- 实际读的是别的路径
- 失败归类：`tool_mismatch`

---

## 6.8 Tools 断言输出结构建议

```json
{
  "type": "tools",
  "status": "failed",
  "checks": [
    {
      "name": "must_call",
      "status": "failed",
      "expected": ["filesystem.read_file"],
      "actual": ["filesystem.list_dir"],
      "reason": "required tool not called"
    }
  ]
}
```

---

## 7. Memory 断言设计

## 7.1 Memory 断言目标

Memory 断言负责验证：

> 本轮对话中，记忆检索和记忆写入行为是否符合预期。

这是当前项目最有特色、也最容易体现测试开发深度的一层断言。

---

## 7.2 推荐的 Memory 断言项

首版建议支持：

- `expect_search`
- `expect_write`
- `expected_scopes`
- `expected_classes`

后续可扩展：

- `expect_memory_context`
- `search_hit_count_at_least`
- `write_count_at_least`

---

## 7.3 `expect_search`

表示本轮执行中应发生 memory 检索。

### 判定依据

可通过以下任一证据判断：

- 调用了 `search_all_scopes()`
- 或最终形成了非空 memory search 结果摘要

### 注意

因为当前主流程里 memory 检索往往是默认行为，所以很多 case 里该值可能常常为 `true`。

---

## 7.4 `expect_write`

表示本轮应发生 memory 写入。

### 判定依据

可通过以下证据判断：

- 异步 enrich 结果成功回写
- 出现 memory write 动作摘要
- 某 scope/class 有新增记录

### 注意

如果当前测试执行时不等待异步 memory worker 完成，这条断言的稳定性会下降。

因此首版建议：

- 要么明确等待可观测写入完成
- 要么将 memory 写断言收敛为较弱断言

---

## 7.5 `expected_scopes`

表示本轮期望涉及哪些 memory scope。

建议值：

- `session`
- `folder`
- `global`

### 判定建议

首版建议做“包含关系”而不是“完全一致”。

例如：

- 期望：`["session"]`
- 实际：`["session", "folder"]`

可视为通过。

---

## 7.6 `expected_classes`

表示本轮期望涉及哪些 memory class。

建议值：

- `episodic`
- `semantic`
- `procedural`

### 判定建议

同样先做“至少包含”断言，不做完全精确匹配。

---

## 7.7 Memory 断言失败示例

### 示例 1：预期检索但未发生

- `expect_search = true`
- 实际无 memory search 证据
- 失败归类：`memory_mismatch`

### 示例 2：预期 session memory 写入但未观察到

- `expect_write = true`
- 实际无可见写入证据
- 失败归类：`memory_mismatch`

### 示例 3：scope 不符合预期

- `expected_scopes = ["session"]`
- 实际未出现 session
- 失败归类：`memory_mismatch`

---

## 7.8 Memory 断言输出结构建议

```json
{
  "type": "memory",
  "status": "failed",
  "checks": [
    {
      "name": "expected_scopes",
      "status": "failed",
      "expected": ["session"],
      "actual": ["folder"],
      "reason": "expected memory scope not observed"
    }
  ]
}
```

---

## 8. Answer 断言设计

## 8.1 Answer 断言目标

Answer 断言负责验证：

> 最终回答是否满足最低可接受质量要求。

它是最靠近用户感知的一层，但也是最容易受模型表述波动影响的一层。

因此 Answer 断言一定要克制，优先做稳定规则。

---

## 8.2 推荐的 Answer 断言项

首版建议支持：

- `contains`
- `not_contains`
- `min_length`

后续可扩展：

- `max_length`
- `regex_any_of`
- `markdown_sections`
- `json_schema`

---

## 8.3 `contains`

表示回答中必须包含某些关键词或短语。

### 判定建议

- 采用“全部命中”模式
- 大小写是否敏感可统一配置，首版建议不敏感

### 示例

```json
"contains": ["Agent.md", "作用"]
```

---

## 8.4 `not_contains`

表示回答中不能出现某些错误关键词。

### 适用场景

非常适合拦截明显错误，例如：

- “无法访问”
- “文件不存在”
- “没有上下文”

前提是这些词在该 case 下确实不应出现。

---

## 8.5 `min_length`

表示回答至少应达到最小长度。

### 作用

避免模型只输出：

- “好的”
- “无法回答”
- 过短片段

### 建议

- 不要设置过大
- 首版只把它当“回答非空且不是明显敷衍”的弱约束

---

## 8.6 Answer 断言失败示例

### 示例 1：缺少核心关键词

- `contains = ["Agent.md"]`
- 实际回答没提到 `Agent.md`
- 失败归类：`answer_mismatch`

### 示例 2：出现错误话术

- `not_contains = ["文件不存在"]`
- 实际回答出现该词
- 失败归类：`answer_mismatch`

### 示例 3：回答过短

- `min_length = 30`
- 实际长度仅 8
- 失败归类：`answer_mismatch`

---

## 8.7 Answer 断言输出结构建议

```json
{
  "type": "answer",
  "status": "failed",
  "checks": [
    {
      "name": "contains",
      "status": "failed",
      "expected": ["Agent.md"],
      "actual": ["作用"],
      "reason": "required keyword missing"
    }
  ]
}
```

---

## 9. 断言执行顺序建议

当前阶段固定执行顺序建议如下：

1. `flow`
2. `tools`
3. `memory`
4. `answer`

### 原因

- `flow` 是主前提
- `tools` / `memory` 更接近系统内部行为
- `answer` 最容易受文本波动影响

### 实施建议

- 即使 `flow` 失败，也可以尽量执行后续断言
- 但最终主失败类型应优先由 `flow` 决定

---

## 10. 断言状态模型

建议每条断言、每类断言都统一使用以下状态：

- `passed`
- `failed`
- `skipped`

### `passed`
断言满足预期。

### `failed`
断言明确不满足预期。

### `skipped`
由于前置条件不足，当前断言不具备判断基础。

例如：

- 最终回答为空时，某些 answer 子检查可记为 `skipped`
- 工具根本没调用时，参数检查可记为 `skipped` 或直接 `failed`，首版建议统一为 `failed` 更直观

---

## 11. 断言结果结构建议

建议统一使用如下模型：

```json
{
  "type": "tools",
  "status": "failed",
  "checks": [
    {
      "name": "must_call",
      "status": "failed",
      "expected": ["filesystem.read_file"],
      "actual": ["filesystem.list_dir"],
      "reason": "required tool not called",
      "evidence": {
        "tool_calls": ["filesystem.list_dir"]
      }
    }
  ]
}
```

### 字段说明

- `type`：断言类别
- `status`：该类别总体状态
- `checks`：该类别下的具体检查项
- `expected`：期望值
- `actual`：实际值
- `reason`：失败原因摘要
- `evidence`：支持判断的最小证据

---

## 12. 失败归因优先级建议

当一个 case 同时有多层断言失败时，建议主失败类型按以下优先级选择：

1. `runtime_error`
2. `flow_break`
3. `tool_mismatch`
4. `memory_mismatch`
5. `answer_mismatch`

### 原因

这是从“更基础、更阻断主流程”的问题往“更表层”的问题排序。

例如：

- 主流程都没走通时，不应该优先报 answer 失败
- 工具行为明显错误时，不应该让 answer 层掩盖根因

---

## 13. 首版不建议立即支持的断言

为了稳定性和实现成本，以下断言建议先不做：

### 13.1 回答全文精确匹配

原因：

- 极其脆弱
- 几乎无法适应模型表述波动

### 13.2 memory 文本逐字精确比对

原因：

- 异步 enrich 与模型抽取容易波动
- 不利于首版稳定落地

### 13.3 工具参数深层 JSON 全结构比对

原因：

- 容易因为字段顺序、冗余字段、格式差异导致误报

### 13.4 复杂跨断言联合规则

例如：

- “如果 tool A 被调用且 memory scope 为 session，则 answer 必须出现 X 且不出现 Y”

这类规则可以后续扩展，但首版不宜过早引入。

---

## 14. 首版推荐最小断言集

如果当前只做最小可用版本，建议断言能力先收敛为：

### Flow
- `expect_success`
- `expect_final_answer`
- `expect_turn_persisted`

### Tools
- `must_call`
- `must_not_call`
- `argument_contains`

### Memory
- `expect_search`
- `expect_write`
- `expected_scopes`

### Answer
- `contains`
- `not_contains`
- `min_length`

这套最小集合已经能覆盖当前项目最关键的质量信号。

---

## 15. 断言与报告的关系

断言设计不仅服务于“判定通过/失败”，还直接决定报告质量。

如果断言设计得足够结构化，那么报告就能自然输出：

- 哪一层失败最多
- 哪类工具误调最多
- 哪类 memory 断言最不稳定
- 哪类回答问题最常见

这也是为什么断言层必须独立建模，而不是零散写在 runner 里。

---

## 16. 结论

对于 ZhouAgent 当前阶段的真实链路回归测试，断言设计的核心思路应是：

> 先用 `flow / tools / memory / answer` 四层结构化断言稳定地描述系统行为，再通过统一结果模型支撑 trace、报告和后续扩展。

首版最重要的不是“断言多复杂”，而是做到：

- 规则稳定
- 容易归因
- 可结构化输出
- 能覆盖 tool / memory / answer 三条关键链路

因此当前推荐策略是：

1. 优先做强稳定断言
2. 避免全文精确匹配
3. 失败优先归因到更底层行为
4. 给每类断言都保留最小证据

这套设计足以支撑下一步实际落地 runner 与 case 执行。
