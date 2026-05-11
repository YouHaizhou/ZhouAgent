# Memory 方案文档

## 一、文档目标

本文档用于收敛 `ZhouAgent` 记忆系统的**第一阶段落地范围**，并给出与当前代码结构匹配的**接口设计草案**。

前提约束：

- 记忆底层默认基于 `mem0`；
- 第一阶段目标不是一次性做完整分层记忆平台；
- 第一阶段优先解决“可接入、可分层、可检索、可渐进演进”；
- 暂不深入到具体数据库部署命令、完整元数据治理、评价算法细节。

这份文档的定位不是纯理念草稿，而是：

```text
面向 ZhouAgent 当前代码结构的第一阶段实施方案
+ Memory 模块接口设计草案
```

---

## 二、当前判断

基于现有需求与 `MEM0_LOCAL_DEPLOYMENT_PLAN_CN.md`，可以先明确几个判断。

### 1. `mem0` 是底层能力，不是完整记忆系统

在 `ZhouAgent` 中，`mem0` 更适合承担：

- 记忆写入；
- 语义检索；
- 底层存储抽象；
- 基础 CRUD 能力。

但它不应直接承担：

- global / folder / session 的完整路由；
- session working memory 的全部运行时状态管理；
- 评价生成逻辑；
- promotion 策略；
- Agent 侧的记忆拼装策略。

所以最终结构应理解为：

```text
ZhouAgent Runtime
  -> Memory Manager / Router
  -> mem0
  -> Vector Store
```

其中真正需要由当前项目自己掌控的，是 `Memory Manager / Router` 这一层。

---

### 2. 第一阶段不应该一次性把所有记忆层全做完

虽然目标上有：

- global memory
- folder memory
- session memory
- user evaluation
- working memory
- promotion

但第一阶段不建议全部同时落地。

否则会很快从“给 agent 加记忆”演变成“同时开发一套复杂记忆平台”。

因此第一阶段应该优先实现：

- scope 分层；
- 基础写入；
- 基础检索；
- 与当前对话主循环的接入。

---

### 3. 当前最需要的是“接口稳定”，不是“功能最全”

当前 `ZhouAgent` 的主体架构还在持续演进：

- `main.py` 负责会话编排；
- `session.py` 负责会话状态；
- `llm.py` 负责 turn loop 与事件流；
- `tui.py` 负责输出。

因此，记忆系统的第一阶段重点应是：

```text
先把 Memory 的调用位置、分层边界、接口抽象定下来
```

这样后续即便调整 `mem0` 配置、向量库或策略，也不会冲击主流程。

---

## 三、第一阶段范围

## 3.1 第一阶段目标

第一阶段只做以下事情：

### A. 建立三层 scope 的逻辑模型

至少在接口和 metadata 语义上支持：

- `global`
- `folder`
- `session`

### B. 跑通最小写入闭环

第一阶段优先支持写入以下三类记忆：

1. `session short-term memory`
2. `folder long-term memory`
3. `global knowledge`

### C. 跑通最小检索闭环

第一阶段优先支持：

- 搜 session 记忆
- 搜 folder 记忆
- 搜 global 记忆
- 聚合多层检索结果

### D. 与当前 agent turn 流程接通

记忆系统要至少能插入两类位置：

1. **请求前检索**
   - 根据当前 `user_input` 和 `cwd` 检索记忆
   - 返回可注入模型上下文的内容

2. **请求后写入**
   - 根据本轮用户输入和最终回答写入记忆
   - 暂时优先写 session short-term

### E. 当前代码实现对应的基础时序

下面时序图对应当前 `ZhouAgent` 已落地的 session 级记忆闭环。

```text
User
  -> main.run()
  -> SessionState.load_latest_or_new(cwd)
  -> refresh_skills(session)
  -> refresh_tools(session)
  -> 输入 user_input
  -> memory.search_all_scopes(user_input, cwd, session_id)
  -> build_system_prompt(session)
  -> build_openai_tools(session)
  -> LlmClient.respond_turn(system_prompt, turn_messages, tools, tool_executor)
  -> 模型流式返回 reasoning / tool_calls / answer
  -> session.append_turn(user_input, answer_text)
  -> memory.write_session_short_term(cwd, session_id, user_input, answer_text)
  -> SessionState.save()
```

这个时序里，记忆系统当前实际参与了两个关键节点：

- **请求前检索**：`memory.search_all_scopes(...)`
- **请求后写入**：`memory.write_session_short_term(...)`

但第一阶段代码里，检索结果目前主要完成了“链路打通”和“能力接入”，还没有进一步拼装进独立 memory prompt，因此当前重点是：

- 检索入口已经接到主循环；
- 写入入口已经接到最终回答之后；
- session 级记忆已经能落到 mem0 / Qdrant；
- 后续可以继续增强“记忆结果如何注入模型上下文”。

### F. 按模块触发的时序拆解

#### 1. `main.py`：主调度入口

```text
run()
  -> ensure_project_layout(cwd)
  -> ensure_user_config_file()
  -> AppConfig.load()
  -> build_memory_manager(config)
  -> SessionState.load_latest_or_new(cwd)
  -> refresh_skills(session)
  -> refresh_tools(session)
  -> 接收用户输入
```

职责：

- 初始化当前项目运行环境；
- 恢复上一次 session；
- 创建 memory manager；
- 在每一轮 turn 前后调度 memory、tools、skills 与 llm。

#### 2. `session.py`：会话恢复与会话级持久化

```text
SessionState.load_latest_or_new(cwd)
  -> load_latest(cwd)
  -> from_storage(cwd, session_id)
  -> load_message_history(turns.jsonl)

本轮完成后
  -> append_turn(user_input, answer_text)
  -> append_turn_to_storage(...)
  -> save()
```

职责：

- 默认恢复当前目录最近一次活跃 session；
- 从 `turns.jsonl` 重建消息历史；
- 持久化 `active_skill_names`、`last_active_at` 等 session 元信息；
- 作为 memory scope 中 `session_id` 的来源。

#### 3. `skills.py`：skills 发现与恢复

```text
refresh_skills(session)
  -> discover_skills(cwd/.zhou/skills)
  -> session.set_available_skills(skills)
  -> 根据 session.meta 中 active_skill_names 恢复启用状态
```

职责：

- 扫描项目本地可用 skills；
- 在 session 恢复后，把历史启用的 skills 映射回当前 skill 对象；
- 供 `build_system_prompt(session)` 组装进 system prompt。

#### 4. `tools.py`：工具注册与调用链路

```text
refresh_tools(session)
  -> discover_tool_registry(cwd)
  -> discover_tools_config_path(cwd)
  -> 读取 tools.toml
  -> 构造 ToolRegistry

build_openai_tools(session)
  -> tool_to_openai_function(tool)
  -> 生成 OpenAI tools 数组

模型返回 tool_call 后
  -> build_tool_executor(session)
  -> call_tool(...)
  -> tools/call
  -> tool_result 回注模型
```

职责：

- 发现当前项目或全局 tools 配置；
- 把内部 `ToolDescriptor` 转成模型 API 的 `tools` 参数；
- 在模型发起 tool call 后执行本地 MCP 工具；
- 把工具结果回注到对话轮次中。

#### 5. `llm.py`：模型交互与 tool round-trip

```text
respond_turn(system_prompt, messages, tools, tool_executor)
  -> tools 非空时进入 chat_with_tools(...)
  -> _stream_round(messages, tools, stream_answer_immediately=False)
  -> payload 中直接携带 tools
  -> SSE 解析 reasoning/content/tool_calls
  -> 如有 tool_calls，执行 tool_executor
  -> 追加 role=tool 消息
  -> 再发下一轮模型请求
  -> 直到返回最终 answer
```

职责：

- 构造真正发给模型的请求 payload；
- 直接通过 HTTP `payload["tools"] = tools` 把工具列表传给模型；
- 解析 streaming 中的 `tool_calls`；
- 驱动 tool call -> tool result -> 下一轮模型请求 的闭环。

#### 6. `memory.py`：记忆写入、检索与 scope 路由

```text
请求前
  -> memory.search_all_scopes(query, cwd, session_id)
    -> search_session_memory(...)
    -> search_folder_memory(...)
    -> search_global_memory(...)

请求后
  -> memory.write_session_short_term(cwd, session_id, user_input, assistant_text)
    -> write_memory(MemoryRecord(...))
    -> mem0 client.add(...)
```

职责：

- 对外暴露统一 memory manager 接口；
- 按 `global / folder / session` 组织检索；
- 按 `user_id / agent_id / cwd / session_id` 过滤与写入；
- 把 Agent 对话记录落入 mem0 / Qdrant。

---

## 3.2 第一阶段暂不做

第一阶段先不完整实现以下内容：

1. 自动生成 `folder user evaluation`
2. 自动生成 `global user evaluation`
3. 自动 `promotion_session_to_folder`
4. 自动 `promotion_folder_to_global`
5. 复杂记忆衰减与清理策略
6. 图记忆 / graph memory
7. UI 管理界面
8. 多端同步
9. working memory 全量接入 `mem0`

这些内容可以在基础闭环跑通后逐步补上。

---

## 四、第一阶段建议落地的记忆层

为了避免实现过重，第一阶段应先只落地以下内容。

## 4.1 Session Short-Term Memory

这一层用于保存：

- 当前 session 内临时但有上下文价值的信息；
- 当前对话中形成的近期约束；
- 当前问题域下短期有效的事实。

这一层适合率先接入 `mem0`，因为它已经具备：

- 可被语义检索；
- 可在下一轮或后续轮中复用；
- 不要求强结构化运行时读写。

---

## 4.2 Folder Long-Term Memory

这一层是整个系统里最重要的一层。

它承载：

- 某个 `cwd` 下长期有效的项目记忆；
- 某个目录逐步形成的垂直领域认知；
- 用户在这个目录下长期稳定的任务模式和约束。

这一层直接决定：

> 这个文件夹下的 agent 是否会逐渐演化成真正有领域倾向的垂直 agent。

所以第一阶段即便做得保守，也应该尽早预留这层能力。

---

## 4.3 Global Knowledge

这一层用于承载：

- 跨项目可复用知识；
- 用户主动投喂的资料；
- 全局适用的知识库内容。

这部分和 session / folder 的自动对话记忆不同，它更像：

- 全局 RAG 资料层；
- 用户自己的长期知识底座。

第一阶段即便先只做接口和写入入口，也值得先预留。

---

## 五、第一阶段暂缓的内容

## 5.1 User Evaluation

`folder user evaluation` 和 `global user evaluation` 虽然很重要，但第一阶段建议只预留：

- 类型定义；
- metadata 约束；
- 接口位置。

暂时不急着做自动生成。

原因：

- 评价比事实更不稳定；
- 很容易受少量对话误导；
- 需要更新、覆盖、修正策略；
- 第一阶段更应先保证记忆基础链路正确。

---

## 5.2 Session Working Memory

Working Memory 很重要，但不建议第一阶段完整交给 `mem0`。

它更像运行时状态容器，通常包含：

- Task Plan
- 当前状态
- Intermediate Results

这类数据的特点是：

- 高频读写；
- 生命周期短；
- 结构化程度高；
- 更像运行时状态而不是长期语义资产。

因此当前建议是：

```text
第一阶段先把 Working Memory 作为独立接口预留
但不强制全部落到 mem0
```

也就是说，第一阶段可以：

- 先定义 `WorkingMemoryStore` 或类似接口；
- 先用本地内存 / 本地结构化存储承接；
- 后续再决定是否统一纳入 mem0。

---

## 六、与当前代码的接入位置

结合当前代码结构，记忆系统最合理的接入点不在 `llm.py`，而在 `main.py` 的会话编排层。

当前主链路大致是：

```text
用户输入
-> build_system_prompt(session)
-> build_turn_messages(user_input)
-> client.respond_turn(...)
-> append_assistant_turn(...)
```

第一阶段记忆应插入两个位置。

## 6.1 请求前检索

在调用模型之前：

```text
user_input
-> memory.search(...)
-> build memory context
-> 注入 prompt / messages
-> respond_turn(...)
```

这一阶段目标是：

- 基于 `user_input` 和 `cwd` 检索相关记忆；
- 把相关记忆整理成紧凑上下文；
- 喂给当前模型调用。

---

## 6.2 请求后写入

在最终 answer 产出后：

```text
assistant_text
-> session.append_assistant_turn(...)
-> memory.write_session_memory(...)
```

第一阶段建议先写：

- 当前用户输入；
- 当前最终回答；
- 必要的 scope / cwd / session_id 元数据。

至于 tool result、reasoning、评价提炼，后续再加。

---

## 七、接口设计原则

第一阶段的 Memory 模块应遵循以下原则。

### 1. 上层不直接依赖 mem0 SDK 细节

`main.py` 不应直接调用 `mem0.Memory()`。

应由 `memory.py` 或 `memory_manager.py` 提供统一接口。

### 2. Scope 与 Kind 显式化

不要把：

- scope
- kind
- memory_class
- cwd
- session_id

隐含在字符串命名里。

应在接口和元数据中明确出现。

### 3. Working Memory 与 Long-Term Memory 分开抽象

即便后续它们都可能最终接入 `mem0`，第一阶段也不应先混在一个接口里。

### 4. 先保证可替换性

未来可能替换：

- `mem0` 配置
- 向量库
- 检索策略
- promotion 策略

所以当前接口应优先稳定，不要让外部库形态直接污染主业务调用。

---

## 八、第一阶段接口设计草案

以下不是最终定稿，而是当前最适合 `ZhouAgent` 的接口方向。

## 8.1 基础枚举 / 类型

建议先定义三组概念。

### `MemoryScope`

```python
from enum import Enum

class MemoryScope(str, Enum):
    GLOBAL = "global"
    FOLDER = "folder"
    SESSION = "session"
```

### `MemoryKind`

```python
class MemoryKind(str, Enum):
    KNOWLEDGE = "knowledge"
    USER_EVALUATION = "user_evaluation"
    LONG_TERM = "long_term"
    SHORT_TERM = "short_term"
    WORKING = "working"
```

### `MemoryClass`

```python
class MemoryClass(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
```

---

## 8.2 统一记忆对象

第一阶段可以先定义一个较轻量的统一对象：

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass(slots=True)
class MemoryRecord:
    content: str
    scope: MemoryScope
    kind: MemoryKind
    memory_class: MemoryClass
    cwd: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    importance: float = 0.0
    source: str = "conversation"
    metadata: dict[str, Any] = field(default_factory=dict)
```

这个对象的作用是：

- 成为项目内部统一的 memory 表达；
- 不让上层直接感知 mem0 原始入参结构；
- 后续便于加字段和做适配。

---

## 8.3 检索结果对象

建议单独定义：

```python
@dataclass(slots=True)
class MemorySearchHit:
    record: MemoryRecord
    score: float
```

以及聚合结果：

```python
@dataclass(slots=True)
class MemorySearchResult:
    hits: list[MemorySearchHit]
```

这样后续就可以：

- 分层排序；
- 合并不同 scope 结果；
- 做去重；
- 做 context 压缩。

---

## 8.4 Memory Manager 主接口

建议第一阶段先定义一个核心管理器，例如：

```python
class MemoryManager:
    def write_memory(self, record: MemoryRecord) -> None:
        ...

    def search_memory(
        self,
        query: str,
        *,
        scope: MemoryScope | None = None,
        cwd: str | None = None,
        session_id: str | None = None,
        kind: MemoryKind | None = None,
        limit: int = 8,
    ) -> MemorySearchResult:
        ...

    def search_all_scopes(
        self,
        query: str,
        *,
        cwd: str,
        session_id: str,
        limit_per_scope: int = 4,
    ) -> dict[str, MemorySearchResult]:
        ...
```

这是第一阶段最核心的两类能力：

- 写入
- 检索

---

## 8.5 面向业务语义的便捷接口

在主接口之上，再补一层更贴近 agent 的方法。

### 写 Session Short-Term

```python
def write_session_short_term(
    self,
    *,
    cwd: str,
    session_id: str,
    user_input: str,
    assistant_text: str,
) -> None:
    ...
```

### 写 Folder Long-Term

```python
def write_folder_long_term(
    self,
    *,
    cwd: str,
    content: str,
    memory_class: MemoryClass = MemoryClass.SEMANTIC,
) -> None:
    ...
```

### 写 Global Knowledge

```python
def write_global_knowledge(
    self,
    *,
    content: str,
    source: str = "knowledge_base",
) -> None:
    ...
```

### 搜 Session

```python
def search_session_memory(
    self,
    query: str,
    *,
    cwd: str,
    session_id: str,
    limit: int = 5,
) -> MemorySearchResult:
    ...
```

### 搜 Folder

```python
def search_folder_memory(
    self,
    query: str,
    *,
    cwd: str,
    limit: int = 5,
) -> MemorySearchResult:
    ...
```

### 搜 Global

```python
def search_global_memory(
    self,
    query: str,
    *,
    limit: int = 5,
) -> MemorySearchResult:
    ...
```

这些接口的好处是：

- 上层 `main.py` 不需要手工拼 scope / kind；
- 接口名就表达了业务语义；
- 后续底层实现变动时，主流程改动更小。

---

## 8.6 Working Memory 接口草案

第一阶段先独立抽象，不强制绑定 `mem0`：

```python
class WorkingMemoryStore:
    def read_task_plan(self, session_id: str) -> str | None:
        ...

    def write_task_plan(self, session_id: str, content: str) -> None:
        ...

    def read_state(self, session_id: str) -> dict[str, object] | None:
        ...

    def write_state(self, session_id: str, state: dict[str, object]) -> None:
        ...

    def append_intermediate_result(self, session_id: str, content: str) -> None:
        ...
```

后续如果决定统一进 mem0，再做适配层即可。

---

## 九、与当前 SessionState 的关系

当前 `SessionState` 已经有：

- `cwd`
- `message_history`

第一阶段建议：

### 1. 不替换 `message_history`

当前 `message_history` 继续负责：

- 当前 session 内直接传给模型的短期对话上下文。

也就是说：

```text
message_history = 当前会话上下文
memory system = 可沉淀、可检索、可跨轮复用的记忆层
```

两者不是一回事。

### 2. 为 SessionState 增加 session_id

第一阶段建议尽快补一个稳定的 `session_id`。

因为如果没有 `session_id`：

- session scope 无法真正隔离；
- short-term memory 只能退化成“当前进程共享”；
- working memory 更无从谈起。

所以后续最小改动之一应是：

```python
session_id: str
```

并在启动会话时初始化。

---

## 十、第一阶段建议实施顺序

结合当前项目状态，建议按下面顺序推进。

## 阶段 1：定义内部抽象

先做：

- `MemoryScope`
- `MemoryKind`
- `MemoryClass`
- `MemoryRecord`
- `MemorySearchHit`
- `MemorySearchResult`
- `MemoryManager` 接口
- `WorkingMemoryStore` 接口

这一阶段先不追求跑通 mem0，只先把项目内部边界定稳。

---

## 阶段 2：接最小 mem0 后端

实现一个 mem0-backed 的 memory store，先支持：

- `write_memory()`
- `search_memory()`
- metadata 过滤

这一阶段优先打通：

- session short-term
- folder long-term
- global knowledge

---

## 阶段 3：接入 main.py 主流程

接入两个位置：

### 请求前

- `search_all_scopes()`
- 组装 memory context
- 注入 system prompt 或 messages

### 请求后

- `write_session_short_term()`
- 可选：在非常明确的条件下写 folder long-term

这一阶段跑通后，agent 就开始拥有最基础的分层记忆能力。

---

## 阶段 4：再补评价与提升机制

等基础闭环稳定后，再考虑：

- folder user evaluation
- global user evaluation
- promotion 策略
- pruning 策略
- working memory 是否统一纳入 mem0

---

## 十一、当前文档结论

对 `ZhouAgent` 来说，第一阶段最合理的做法不是一次性实现完整记忆平台，而是：

```text
先建立稳定的 Memory 抽象层
-> 先打通 global / folder / session 的最小闭环
-> 先接入主会话流程
-> 再逐步补评价、提升、working memory
```

一句话总结：

> 第一阶段的重点不是“把所有记忆都做完”，而是先把 `mem0` 放到正确的位置上：作为长期记忆底层能力，被 `Memory Manager` 管理，并与 ZhouAgent 当前会话编排层稳定对接。
