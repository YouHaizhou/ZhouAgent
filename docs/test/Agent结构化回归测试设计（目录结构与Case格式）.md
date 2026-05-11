# Agent 结构化回归测试设计（目录结构与 Case 格式）

## 1. 文档目标

本文只回答两个问题：

1. 如果当前阶段要做 `真实对话链路 + 结构化断言` 的回归测试，目录结构应该怎么设计
2. case 文件应该长什么样，才能支持后续逐步扩展

本文**暂不展开**以下内容：

- replay 机制
- 多轮连续对话测试
- mock 方案
- benchmark 统计平台

当前阶段只聚焦：

> 单轮真实执行 + tool / memory / answer 的结构化断言

---

## 2. 当前阶段的范围定义

### 2.1 本阶段要解决的问题

针对一次真实用户输入，验证 Agent 的关键行为是否符合预期，包括：

- 是否成功完成整轮执行
- 是否调用了预期 tool
- tool 参数/调用顺序是否基本正确
- 是否命中了预期 memory
- 是否写入了预期 memory
- 最终回答是否满足关键结构化约束

### 2.2 本阶段暂不解决的问题

以下内容先不纳入首版：

- 连续 2~N 轮上下文传递验证
- success case 的 replay 重跑
- mock 主模型 / tool / memory
- 大规模 benchmark 统计
- 用例自动分级调度

这样做的原因很明确：

- 多轮测试会立即引入 session 状态推进问题
- replay 会立即引入 memory 污染和环境重建问题
- mock 会让方案主题从“真实链路测试”变成“依赖隔离测试”

而当前最重要的是先把最小闭环打通。

---

## 3. 当前阶段推荐的测试目标

建议先把“单轮真实执行结构化回归”定义为以下目标：

### 3.1 冒烟级目标

保证一次输入不会在主流程中断：

- 无异常退出
- 有最终回答
- turn 成功落盘
- trace 成功记录

### 3.2 行为级目标

验证关键行为是否成立：

- 是否触发预期 tool
- 是否没有触发不该触发的 tool
- 是否命中预期 memory scope
- 是否写入了预期 memory scope/class
- 最终回答是否包含核心结论

### 3.3 可分析目标

当失败时，能快速定位失败属于哪一类：

- flow break
- tool mismatch
- memory mismatch
- answer mismatch
- runtime error

---

## 4. 推荐目录结构

当前阶段建议只引入一套最小目录，避免一开始铺太大。

```text
project/
├── docs/
│   └── test/
│       ├── 测试开发增强方案.md
│       └── Agent结构化回归测试设计（目录结构与Case格式）.md
├── test/
│   ├── agent_cases/
│   │   ├── smoke/
│   │   ├── tools/
│   │   ├── memory/
│   │   └── answer/
│   ├── traces/
│   ├── artifacts/
│   └── reports/
└── src/
```

---

## 5. 各目录职责说明

## 5.1 `test/agent_cases/`

存放结构化回归 case。

建议按测试意图分子目录：

### `test/agent_cases/smoke/`
用于最基本的主流程冒烟：

- 是否能完成一轮问答
- 是否能返回结果
- 是否能落盘

### `test/agent_cases/tools/`
用于验证工具调用行为：

- 是否调用指定 tool
- 是否避免误调 tool
- 是否带正确参数

### `test/agent_cases/memory/`
用于验证记忆行为：

- 是否命中某个 memory scope
- 是否写入某个 memory scope/class
- 是否生成 memory_candidates

### `test/agent_cases/answer/`
用于验证输出结果：

- 是否包含关键结论
- 是否满足格式要求
- 是否不包含错误关键词

---

## 5.2 `test/traces/`

存放测试运行期间的结构化执行证据。

建议内容包括：

- case 基本信息
- 输入
- tool 调用记录
- memory 检索结果摘要
- memory 写入结果摘要
- final answer 摘要
- 断言结果
- 失败分类

这个目录的目标不是“用户直接看”，而是：

- 支撑失败分析
- 支撑后续 replay / benchmark 扩展

---

## 5.3 `test/artifacts/`

存放测试中间产物，偏原始数据。

建议包括：

- turns 快照
- 原始回答文本
- tool 原始结果
- memory model 结果摘录
- 运行时环境信息

与 `traces/` 的区别：

- `traces/` 偏结构化、偏分析结果
- `artifacts/` 偏原始证据、偏调试材料

---

## 5.4 `test/reports/`

存放测试执行后的摘要报告。

建议输出：

- 本次总 case 数
- pass / fail 数
- 每个 case 的状态
- 失败原因分类
- tool / memory / answer 的失败分布

---

## 6. Case 文件设计原则

当前阶段的 case 设计必须满足四个要求：

### 6.1 可读

一个 case 文件打开后，应能快速看懂：

- 这是测什么的
- 输入是什么
- 预期行为是什么
- 失败时主要看哪里

### 6.2 稳定

不能做过于脆弱的全文匹配，而要偏结构化断言。

### 6.3 可扩展

虽然当前不做 replay 和多轮，但 case 格式要给未来留口子。

### 6.4 可归因

断言失败后，应能明确知道属于：

- tool 问题
- memory 问题
- answer 问题
- 主流程问题

---

## 7. 推荐的 Case 基本结构

建议每个 case 采用 JSON 或 YAML。当前阶段更推荐 JSON，原因是：

- 更容易程序读取
- 结构更稳定
- 后续报告生成更直接

推荐结构如下：

```json
{
  "name": "read_agent_file_should_call_read_tool",
  "category": "tools",
  "description": "验证读取 Agent.md 时是否调用预期工具，并在回答中体现文件内容。",
  "input": "读取 Agent.md 的内容，并总结它的作用",
  "environment": {
    "cwd": "project_root",
    "session_mode": "isolated",
    "memory_mode": "real"
  },
  "assertions": {
    "flow": {
      "expect_success": true,
      "expect_final_answer": true,
      "expect_turn_persisted": true
    },
    "tools": {
      "must_call": ["filesystem.read_file"],
      "must_not_call": [],
      "call_order_any_of": [],
      "argument_contains": {
        "filesystem.read_file": ["Agent.md"]
      }
    },
    "memory": {
      "expect_search": false,
      "expect_write": false,
      "expected_scopes": [],
      "expected_classes": []
    },
    "answer": {
      "contains": ["Agent.md", "作用"],
      "not_contains": ["无法访问", "未知文件"],
      "min_length": 20
    }
  },
  "analysis": {
    "failure_tags": ["tool", "answer"],
    "notes": "如果工具未触发，优先检查 tool registry 和 function call 映射。"
  }
}
```

---

## 8. Case 字段说明

## 8.1 `name`

case 唯一标识，建议：

- 全英文小写
- 用下划线分隔
- 名称体现测试意图

例如：

- `read_agent_file_should_call_read_tool`
- `memory_search_should_enrich_answer`
- `plain_question_should_not_call_tool`

---

## 8.2 `category`

用于归类和筛选。

当前建议值：

- `smoke`
- `tools`
- `memory`
- `answer`

---

## 8.3 `description`

面向人读的说明，尽量一句话说清测试目的。

---

## 8.4 `input`

当前阶段先只支持：

- 单轮用户输入

也就是这里先定义为字符串，不支持 `turns[]`。

原因：

- 当前明确暂不做多轮连续测试
- 避免 session 状态管理过早复杂化

未来如果扩展多轮，再把它升级成：

```json
"turns": [
  {"user": "..."},
  {"user": "..."}
]
```

---

## 8.5 `environment`

用于描述本 case 的执行环境要求。

建议字段：

- `cwd`
  - 当前先支持 `project_root`
- `session_mode`
  - 当前建议默认 `isolated`
- `memory_mode`
  - 当前先固定 `real`

### 为什么先引入 `session_mode`

虽然不做多轮，但即使单轮测试也应该考虑隔离：

- 每个 case 用独立 session
- 防止 case 之间互相污染

这是首版就应该保留的能力。

---

## 8.6 `assertions.flow`

用于验证主链路是否走通。

建议字段：

- `expect_success`
- `expect_final_answer`
- `expect_turn_persisted`

这是最基础的一层断言，相当于 Agent 主流程冒烟测试。

---

## 8.7 `assertions.tools`

用于验证工具行为。

建议字段：

- `must_call`
- `must_not_call`
- `call_order_any_of`
- `argument_contains`

### 说明

#### `must_call`
必须调用的工具列表。

#### `must_not_call`
不应调用的工具列表。

#### `call_order_any_of`
如果调用顺序重要，可以定义多个允许顺序。

#### `argument_contains`
验证某个 tool 的参数文本中是否包含指定关键字。

当前阶段不建议一开始就做太强的参数全文比较，先做关键词级别验证更稳。

---

## 8.8 `assertions.memory`

用于验证记忆行为。

建议字段：

- `expect_search`
- `expect_write`
- `expected_scopes`
- `expected_classes`

### 说明

#### `expect_search`
是否预期本轮发生 memory 检索。

#### `expect_write`
是否预期本轮有 memory 写入动作。

#### `expected_scopes`
例如：

- `session`
- `folder`
- `global`

#### `expected_classes`
例如：

- `episodic`
- `semantic`
- `procedural`

当前阶段建议先做“有/无 + scope/class 粗粒度断言”，不要一开始就比较完整 memory 内容。

---

## 8.9 `assertions.answer`

用于验证最终回答。

建议字段：

- `contains`
- `not_contains`
- `min_length`

### 为什么不用全文匹配

因为 Agent / LLM 输出天然存在表述波动。

所以当前阶段最稳的做法是：

- 核心关键词包含
- 错误关键词排除
- 最小长度约束

后续如果有必要，再扩展结构化 schema 断言。

---

## 8.10 `analysis`

用于给失败分析提供人工提示，不参与主流程执行。

建议字段：

- `failure_tags`
- `notes`

### 作用

当 case 失败时，报告可以更快告诉开发者：

- 这是偏 tool 问题
- 还是偏 memory 问题
- 或者优先检查哪里

---

## 9. Case 示例

## 9.1 示例一：普通问题不应调工具

```json
{
  "name": "plain_question_should_not_call_tool",
  "category": "smoke",
  "description": "普通概念问答不应触发任何工具。",
  "input": "请解释一下 session 在这个项目里的作用",
  "environment": {
    "cwd": "project_root",
    "session_mode": "isolated",
    "memory_mode": "real"
  },
  "assertions": {
    "flow": {
      "expect_success": true,
      "expect_final_answer": true,
      "expect_turn_persisted": true
    },
    "tools": {
      "must_call": [],
      "must_not_call": ["filesystem.read_file", "shell.run_command"],
      "call_order_any_of": [],
      "argument_contains": {}
    },
    "memory": {
      "expect_search": true,
      "expect_write": true,
      "expected_scopes": ["session"],
      "expected_classes": []
    },
    "answer": {
      "contains": ["session", "会话"],
      "not_contains": ["无法回答"],
      "min_length": 30
    }
  },
  "analysis": {
    "failure_tags": ["flow", "tool", "answer"],
    "notes": "如果误调工具，优先检查 prompt 与 tool schema。"
  }
}
```

---

## 9.2 示例二：读取文件应触发工具

```json
{
  "name": "read_agent_file_should_call_read_tool",
  "category": "tools",
  "description": "读取 Agent.md 时应触发读文件工具。",
  "input": "读取 Agent.md 的内容，并概括它的职责",
  "environment": {
    "cwd": "project_root",
    "session_mode": "isolated",
    "memory_mode": "real"
  },
  "assertions": {
    "flow": {
      "expect_success": true,
      "expect_final_answer": true,
      "expect_turn_persisted": true
    },
    "tools": {
      "must_call": ["filesystem.read_file"],
      "must_not_call": [],
      "call_order_any_of": [],
      "argument_contains": {
        "filesystem.read_file": ["Agent.md"]
      }
    },
    "memory": {
      "expect_search": true,
      "expect_write": true,
      "expected_scopes": ["session"],
      "expected_classes": []
    },
    "answer": {
      "contains": ["Agent.md"],
      "not_contains": ["文件不存在", "无法访问"],
      "min_length": 30
    }
  },
  "analysis": {
    "failure_tags": ["tool", "answer"],
    "notes": "如果工具未触发，检查 tool registry 刷新和函数名映射。"
  }
}
```

---

## 9.3 示例三：memory 行为验证

```json
{
  "name": "memory_search_should_participate_in_answer",
  "category": "memory",
  "description": "验证 memory 检索是否参与回答构造。",
  "input": "结合之前的上下文，总结这个项目的会话机制",
  "environment": {
    "cwd": "project_root",
    "session_mode": "isolated",
    "memory_mode": "real"
  },
  "assertions": {
    "flow": {
      "expect_success": true,
      "expect_final_answer": true,
      "expect_turn_persisted": true
    },
    "tools": {
      "must_call": [],
      "must_not_call": [],
      "call_order_any_of": [],
      "argument_contains": {}
    },
    "memory": {
      "expect_search": true,
      "expect_write": true,
      "expected_scopes": ["session"],
      "expected_classes": ["episodic", "semantic"]
    },
    "answer": {
      "contains": ["会话", "session"],
      "not_contains": ["没有上下文"],
      "min_length": 30
    }
  },
  "analysis": {
    "failure_tags": ["memory", "answer"],
    "notes": "如果 memory 断言失败，需检查 search_all_scopes 和异步 enrich 回写链路。"
  }
}
```

---

## 10. 当前阶段的 runner 输出建议

虽然本文不展开 runner 代码设计，但 case 格式已经隐含了 runner 需要输出的最小结果结构。

建议每个 case 执行后输出：

```json
{
  "case_name": "read_agent_file_should_call_read_tool",
  "status": "failed",
  "failure_type": "tool_mismatch",
  "assertions": {
    "flow": "passed",
    "tools": "failed",
    "memory": "passed",
    "answer": "passed"
  },
  "evidence": {
    "tool_calls": ["filesystem.list_dir"],
    "memory_scopes_hit": ["session"],
    "answer_excerpt": "..."
  }
}
```

这样后续可以很自然扩展到：

- 失败报告
- trace 存档
- success case 收集
- replay 候选池

---

## 11. 为什么当前先不做多轮连续测试

这是当前方案里一个重要边界。

原因主要有 4 个：

### 11.1 会立即引入 session 状态推进复杂度

多轮 case 需要考虑：

- 上一轮回答如何进入下一轮上下文
- 中间 turn 如何存储和读取
- 每轮断言放在哪一层

### 11.2 会立即引入 memory 污染问题

多轮对话比单轮更容易把：

- session memory
- folder memory
- async memory write

混在一起，导致 case 难以稳定。

### 11.3 失败归因会变困难

单轮失败相对容易分析；多轮失败可能是第 1 轮埋的偏差在第 3 轮放大。

### 11.4 首版应先打通最小闭环

最小闭环应该是：

- 单轮真实执行
- 结构化断言
- 失败分类
- 证据保存

把这一步做扎实，后续再扩展多轮更稳。

---

## 12. 当前阶段的实施顺序建议

### Step 1
先建目录：

- `test/agent_cases/`
- `test/traces/`
- `test/artifacts/`
- `test/reports/`

### Step 2
先写 5~10 个单轮 case：

- 2 个 smoke
- 3 个 tools
- 2 个 memory
- 2 个 answer

### Step 3
runner 先实现最基本能力：

- 读 case
- 跑真实执行
- 收集 tool / memory / answer 证据
- 给出 pass/fail

### Step 4
再补失败分类和报告输出

---

## 13. 结论

如果当前阶段只做一件事，最合理的就是：

> 先做“单轮真实链路结构化回归测试框架”，把目录结构和 case 格式先定下来。

这套方案的优点是：

- 足够有测试开发特色
- 与当前 Agent 项目高度契合
- 不会过早陷入 replay / 多轮状态污染 / mock 策略等复杂问题
- 后续可以自然扩展到多轮测试和 record/replay

因此，当前推荐优先级为：

1. 定目录结构
2. 定 case 格式
3. 跑单轮真实执行
4. 做结构化断言
5. 保存失败证据
