# Agent 回归测试 Runner 设计

## 1. 文档目标

本文承接：

- `测试开发增强方案.md`
- `Agent结构化回归测试设计（目录结构与Case格式）.md`

本文件只聚焦一个核心问题：

> 如果当前阶段要做“单轮真实链路 + 结构化断言”的回归测试，那么 runner 应该怎么设计。

本文不展开具体代码实现细节，而是定义：

- runner 的职责边界
- 输入输出
- 执行主流程
- 断言执行顺序
- 证据采集模型
- 失败分类模型
- 报告结构

---

## 2. Runner 的定位

Runner 不是普通的 pytest 包装器，也不是单纯的脚本批跑器。

它在这个项目里的定位更接近：

> Agent 真实执行链路的结构化验证调度器

它要解决的是：

1. 读取 case
2. 准备独立测试环境
3. 驱动一次真实 Agent 执行
4. 收集 tool / memory / answer / turn 等执行证据
5. 基于结构化断言得出 pass / fail
6. 输出 trace、artifact 和报告

---

## 3. Runner 设计原则

## 3.1 真实执行优先

当前阶段明确不采用 mock，所以 runner 设计必须围绕“真实链路执行”展开。

这意味着：

- 主模型真实请求
- tool 真实发现与真实调用
- memory 真实检索与真实写入
- session / turn 真实落盘

Runner 不负责伪造执行结果，只负责：

- 调度执行
- 采集证据
- 做结构化判定

---

## 3.2 断言与执行分离

Runner 不应把断言逻辑散落在执行逻辑里。

建议拆为两层：

- 执行层：负责跑 case、采集结果
- 断言层：负责基于结果判定是否通过

这样后续才能更容易扩展：

- 新断言类型
- 新报告形式
- 新失败分类规则

---

## 3.3 证据先行

因为是真实链路测试，所以失败归因会比 mock 测试更复杂。

因此 runner 的核心能力不只是“判断失败”，更是：

> 失败时必须留下足够证据，便于快速分析。

所以每次执行都应优先沉淀：

- 输入
- tool calls
- tool results 摘要
- memory 检索摘要
- memory 写入摘要
- 最终回答摘录
- turn 落盘信息
- 执行耗时
- 错误信息

---

## 3.4 单轮闭环优先

当前阶段只做单轮输入，所以 runner 应明确围绕：

- 一次输入
- 一次 Agent 执行
- 一次结构化判定

先把这一层做扎实，再考虑多轮调度。

---

## 4. Runner 的职责边界

## 4.1 Runner 负责

- 读取一个或一组 case
- 校验 case 格式
- 为每个 case 准备独立执行上下文
- 调用 Agent 主执行入口
- 收集结构化证据
- 执行断言
- 写 trace / artifact / report
- 汇总测试结果

## 4.2 Runner 不负责

- 修改 Agent 主业务逻辑
- 改写模型输出
- mock 工具或 memory
- 处理多轮 replay
- 做 benchmark 长期统计

---

## 5. Runner 的输入

Runner 的输入建议分为三层。

## 5.1 Case 输入

来自 `test/agent_cases/**/*.json`：

- name
- category
- description
- input
- environment
- assertions
- analysis

这是最主要的业务输入。

---

## 5.2 Runner 配置输入

用于控制本次批跑行为。

建议包括：

- `case_glob`
- `category_filter`
- `fail_fast`
- `max_cases`
- `output_dir`
- `trace_enabled`
- `artifact_enabled`
- `report_format`

例如：

```json
{
  "case_glob": "test/agent_cases/**/*.json",
  "category_filter": ["tools", "memory"],
  "fail_fast": false,
  "max_cases": 20,
  "trace_enabled": true,
  "artifact_enabled": true,
  "report_format": ["json", "markdown"]
}
```

---

## 5.3 环境输入

来自当前项目运行环境：

- cwd
- `.zhou` 配置
- tools 配置
- skills 配置
- model API 配置
- memory 配置

Runner 不单独定义这些，而是消费项目现有运行环境。

---

## 6. Runner 的输出

Runner 的输出建议分为四层。

## 6.1 控制台输出

面向快速查看：

- 当前 running case
- pass / fail
- failure_type
- 简短原因

例如：

```text
[PASS] read_agent_file_should_call_read_tool
[FAIL] plain_question_should_not_call_tool  failure_type=tool_mismatch
```

---

## 6.2 Trace 输出

写入 `test/traces/`，面向结构化分析。

每个 case 一份 trace，建议命名：

```text
test/traces/{timestamp}_{case_name}.json
```

---

## 6.3 Artifact 输出

写入 `test/artifacts/`，面向调试取证。

例如：

- final_answer.txt
- tool_calls.json
- turn_record.json
- memory_summary.json

---

## 6.4 汇总 Report 输出

写入 `test/reports/`，面向批跑结果查看。

建议同时支持：

- JSON 汇总
- Markdown 汇总

---

## 7. Runner 执行主流程

当前阶段推荐 runner 主流程如下：

```text
加载 runner 配置
→ 扫描 case 文件
→ 逐个读取并校验 case
→ 为 case 准备独立执行环境
→ 调用 Agent 单轮执行入口
→ 收集执行证据
→ 执行 flow/tools/memory/answer 断言
→ 生成 case result
→ 写 trace / artifact
→ 汇总为报告
```

---

## 8. Case 生命周期设计

每个 case 从进入 runner 到结束，建议经历 8 个阶段。

## 8.1 `loaded`

case 已从文件系统读取。

## 8.2 `validated`

case 格式校验通过。

## 8.3 `prepared`

执行环境准备完成，包括：

- 独立 session
- 路径校验
- 输出目录准备

## 8.4 `running`

开始真实执行 Agent 单轮流程。

## 8.5 `collected`

执行结束，证据已收集完成。

## 8.6 `asserted`

结构化断言已执行完成。

## 8.7 `persisted`

trace / artifact 已写盘。

## 8.8 `finished`

case 最终状态完成，可进入汇总报告。

---

## 9. Runner 与 Agent 主链路的连接方式

当前阶段最关键的问题之一是：

> runner 应该如何驱动一次真实执行。

建议原则是：

## 9.1 不要走交互式 REPL

runner 不应该通过模拟终端输入去测 `run()`。

原因：

- 交互逻辑噪声太大
- TUI 干扰测试稳定性
- 很难精准收集结构化证据

## 9.2 应直接调用“单轮主编排入口”

也就是尽量对接：

- `_bootstrap()` 负责准备资源
- `_handle_turn()` 负责单轮执行

如果后续需要，可考虑从 `main.py` 中再抽一个更纯净的 runner-friendly 入口，例如：

- `execute_single_turn_for_test(...)`

但当前设计层面，runner 应围绕“单轮主编排入口”构建。

---

## 10. 证据采集模型

当前阶段建议把证据分为 6 类。

## 10.1 基础信息证据

- case_name
- category
- started_at
- ended_at
- duration_ms
- session_id
- cwd

## 10.2 flow 证据

- 是否抛异常
- 是否得到最终回答
- 是否生成 turn
- 是否成功落盘

## 10.3 tool 证据

- 实际调用的工具列表
- 每个工具的参数摘要
- 工具调用顺序
- 工具结果摘要
- 工具异常信息

## 10.4 memory 证据

- 是否触发 search
- search 命中的 scope 摘要
- memory context 是否构造
- 是否触发写入
- 写入的 scope/class 摘要

## 10.5 answer 证据

- 最终回答全文
- 最终回答摘录
- 长度
- reasoning_summary

## 10.6 persistence 证据

- turn path
- meta path
- archive 是否写入
- turn_id / timestamp

---

## 11. 结构化断言执行顺序

建议断言顺序固定，便于报告稳定。

## 11.1 第一层：flow 断言

先判断主流程是否成立：

- 是否执行成功
- 是否有最终回答
- 是否 turn 落盘

如果这一层失败，通常可以直接判定：

- `flow_break`
- `runtime_error`

并且后续断言可以转为“尽力执行”。

---

## 11.2 第二层：tool 断言

在 flow 基本成立后，再判断：

- `must_call`
- `must_not_call`
- `argument_contains`
- 调用顺序

这一层失败，归为：

- `tool_mismatch`

---

## 11.3 第三层：memory 断言

再判断：

- 是否发生检索
- 是否发生写入
- scope/class 是否符合预期

这一层失败，归为：

- `memory_mismatch`

---

## 11.4 第四层：answer 断言

最后判断：

- 包含关键词
- 不包含错误关键词
- 最小长度

这一层失败，归为：

- `answer_mismatch`

---

## 12. 为什么断言顺序要这样排

原因是：

### 12.1 flow 是前提条件

主流程没走通时，tool / memory / answer 的判断价值会显著下降。

### 12.2 tool 与 memory 是行为证据

它们比最终 answer 更接近“系统行为本身”，更适合优先判定。

### 12.3 answer 最容易受模型表述波动影响

所以放在最后，避免它掩盖更本质的执行行为问题。

---

## 13. 失败分类模型

建议当前阶段先固定 5 类失败。

## 13.1 `flow_break`

主流程未正常完成，例如：

- 无 final answer
- turn 未落盘
- 主执行链路中断

## 13.2 `runtime_error`

执行过程中抛出异常，例如：

- API 请求失败
- tool 调用异常
- 文件读写异常

## 13.3 `tool_mismatch`

工具调用行为与预期不一致，例如：

- 该调用没调用
- 不该调用却调用了
- 参数缺少关键字段

## 13.4 `memory_mismatch`

记忆行为与预期不一致，例如：

- 预期 search 未发生
- 预期 write 未发生
- scope/class 不符合预期

## 13.5 `answer_mismatch`

最终回答与结构化断言不一致，例如：

- 缺失关键词
- 出现禁用关键词
- 长度不足

---

## 14. Case Result 结构建议

建议每个 case 最终统一输出如下结果结构：

```json
{
  "case_name": "read_agent_file_should_call_read_tool",
  "category": "tools",
  "status": "failed",
  "failure_type": "tool_mismatch",
  "duration_ms": 4123,
  "session_id": "...",
  "assertions": {
    "flow": "passed",
    "tools": "failed",
    "memory": "passed",
    "answer": "passed"
  },
  "evidence": {
    "tool_calls": [
      {
        "name": "filesystem.list_dir",
        "arguments_excerpt": "{\"path\":\".\"}"
      }
    ],
    "memory_scopes_hit": ["session"],
    "memory_write_scopes": ["session"],
    "answer_excerpt": "..."
  },
  "error": null
}
```

---

## 15. Trace 文件结构建议

trace 比 case result 更完整。

建议字段：

```json
{
  "trace_id": "uuid",
  "case_name": "...",
  "started_at": "...",
  "ended_at": "...",
  "duration_ms": 1234,
  "input": "...",
  "environment": {
    "cwd": "...",
    "session_mode": "isolated",
    "memory_mode": "real"
  },
  "execution": {
    "tool_calls": [...],
    "memory_search": {...},
    "memory_write": {...},
    "answer": {...},
    "turn_persist": {...}
  },
  "assertions": {
    "flow": {...},
    "tools": {...},
    "memory": {...},
    "answer": {...}
  },
  "result": {
    "status": "passed",
    "failure_type": null
  }
}
```

---

## 16. Artifact 文件建议

为了避免 trace 文件过度膨胀，建议原始内容单独放 artifact。

例如一个 case 对应目录：

```text
test/artifacts/{case_name}/
├── final_answer.txt
├── tool_calls.json
├── tool_results.json
├── memory_summary.json
└── turn_record.json
```

这样做的好处是：

- trace 适合程序分析
- artifact 适合人工排查

---

## 17. 汇总报告结构建议

汇总报告建议至少输出：

### 顶层摘要
- 总 case 数
- pass 数
- fail 数
- 总耗时

### 分类摘要
- flow_break 数量
- runtime_error 数量
- tool_mismatch 数量
- memory_mismatch 数量
- answer_mismatch 数量

### 单 case 明细
- case_name
- category
- status
- failure_type
- duration_ms

---

## 18. Runner 的扩展口预留

虽然当前阶段不做 replay 和多轮，但 runner 设计里建议预留扩展口。

## 18.1 多轮扩展口

当前 `input` 是字符串，未来可扩展为：

- `turns[]`

Runner 层面则从“单轮 execute”扩展为“按 turn 顺序 execute”。

## 18.2 replay 扩展口

当前 trace / artifact 已经是 replay 的基础数据源。

未来若要增加 replay，可直接在 runner 上加：

- success case 池
- replay 次数
- 多次通过率统计

## 18.3 mock 扩展口

虽然当前明确不做 mock，但执行层与断言层分离后，未来如果要引入 mock，不需要重写整套报告体系。

---

## 19. 当前阶段建议的实现顺序

### Step 1
先做 case loader：

- 扫描 JSON case
- 校验字段合法性

### Step 2
做单 case 执行器：

- 准备独立 session
- 调用单轮主入口
- 收集执行证据

### Step 3
做断言器：

- flow 断言
- tools 断言
- memory 断言
- answer 断言

### Step 4
做 trace / artifact writer

### Step 5
做汇总报告 writer

---

## 20. 结论

当前阶段最合理的 runner 设计，应围绕如下闭环展开：

> 读取 case → 真实执行 → 收集证据 → 结构化断言 → 失败分类 → 结果落盘

这套设计的重点不在于“把回答字符串比对正确”，而在于：

- 验证 Agent 主流程是否成立
- 验证 tool / memory / answer 关键行为是否符合预期
- 失败时是否能留下足够证据支持分析

这正是当前 ZhouAgent 做测试开发特色增强时，最值得优先实现的一层能力。
