# session_flow 测试的真实调用链与 fake 替换点

## 一、先给一句话结论

`tests/integration/test_session_flow.py` 不是在“测 fake 逻辑”，而是在：

- 用 fake 依赖驱动真实的 `src` 主流程代码
- 重点验证 session 状态流、多轮历史管理、异步回写一致性

它属于：

## 代码级 mock/stub 集成测试

不是纯单元测试，也不是全真端到端测试。

---

## 二、这组测试到底有没有调用 `src` 里的代码

### 有，而且调用的是主流程核心代码

测试入口直接引入：

- `zhou.main._handle_turn`
- `zhou.session.SessionState`
- `zhou.session.load_turn_records`

也就是说，测试在真实执行：

1. 单轮主流程编排
2. 消息构造
3. turn 持久化
4. turn 替换
5. reload 后再读取历史
6. 异步 callback 接线

### 这组测试真实会经过的代码链路

#### 主流程入口
- `src/zhou/main.py::_handle_turn`

#### session 相关
- `src/zhou/session.py::SessionState.build_turn_messages`
- `src/zhou/session.py::SessionState.append_turn`
- `src/zhou/session.py::SessionState.replace_turn`
- `src/zhou/session.py::SessionState.from_storage`
- `src/zhou/session.py::load_turn_records`

#### memory / async 回写相关
- `src/zhou/memory/manager.py::apply_enriched_result`

所以这组测试测的并不是“假流程”，而是：

## 真的业务状态流，只是把外部依赖替换掉了

---

## 三、哪些部分是真实执行的

### 1. `_handle_turn` 主流程
真实执行：
- memory search 调用入口
- memory context 注入
- system prompt 构造
- tool 列表构造
- turn_messages 拼装
- 流事件消费
- answer 收集
- `build_turn_record`
- `session.append_turn`
- `archive_writer.append_turn`
- `worker.submit(...)`
- `callback=lambda enriched: apply_enriched_result(...)`

### 2. `SessionState` 的状态管理
真实执行：
- `message_history` 更新
- `turns.jsonl` 写入
- `replace_turn` 后重载 `message_history`
- 重新从磁盘 `from_storage(...)` 加载

### 3. enriched turn 的回写逻辑
真实执行：
- `apply_enriched_result(...)`
- `replace_turn(...)`
- 后续轮次再读取到新版本历史

---

## 四、哪些部分是 fake / stub / mock

### 1. `FakeLlmClient`
作用：
- 不调用真实模型
- 返回预设流事件
- 记录传入的 `messages`

它既是：
- stub：提供预设事件流
- mock：记录调用参数供断言

### 2. `FakeMemoryManager`
作用：
- 不连接真实 mem0 / qdrant
- 返回预设 memory search 结果
- 记录 search / write / versioned_write 行为

它主要承担：
- stub：返回预设检索结果
- fake：用内存记录写入行为

### 3. `FakeArchiveWriter`
作用：
- 不做真实全局归档
- 只记录是否被调用、参数是什么

### 4. `FakeWorker` / `TurnMutatingWorker`
作用：
- 不起真实异步模型调用
- 控制 callback 是否立即触发
- 模拟 enriched turn 回写

### 5. `refresh_tools` patch
在测试中通过 patch：
- 把 `zhou.main.refresh_tools` 替换成 no-op

作用：
- 不触发真实 MCP tool discovery
- 避免本地 `.zhou/logs/mcp-server.log` 句柄占用
- 保证 session 状态测试稳定

---

## 五、为什么要这样分

因为这组测试的目标不是：

- 测真实模型是否回答正确
- 测真实工具发现是否成功
- 测真实 mem0 / qdrant 是否连通

而是：

## 测状态流编排是否正确

具体就是：
- 同 session 是否继承历史
- 新 session 是否隔离旧历史
- enriched turn 是否会影响后续轮次读取结果

所以这里最合理的测试策略就是：

### 该保真的保真
- 主流程
- session 状态
- 持久化
- reload
- callback 接线

### 该替换的替换
- LLM
- memory 基础设施
- archive 外部写入
- 真实工具发现
- 真实异步 worker

---

## 六、这组测试的 3 个核心风险点

### 1. 同 session 历史继承失效
测试名：
- `test_same_session_should_carry_previous_history_into_next_turn`

本质风险：
- 多轮对话断上下文
- 第二轮没有正确带入上一轮历史

### 2. 跨 session 历史污染
测试名：
- `test_new_session_should_not_leak_old_history`

本质风险：
- 新 session 错读旧 session history
- 用户串话
- 会话隔离失效

### 3. enriched turn 一致性失效
测试名：
- `test_enriched_turn_should_replace_persisted_record_and_be_visible_after_reload`

本质风险：
- 异步回写成功了，但后续轮次还在读旧 turn
- 状态更新与后续读取不一致

---

## 七、这组测试不覆盖什么

这点也必须明确。

它不覆盖：
- 真实 MCP tool discovery
- 真实 mem0 / qdrant
- 真实模型输出质量
- 真实网络错误与超时
- 真实并发和进程级资源问题

这些内容如果要验证，需要放到：
- 真实依赖集成测试
- 更重的端到端测试

---

## 八、应该怎么理解这组测试的价值

最准确的理解方式是：

## 它是“用 fake 依赖驱动真实状态流”的集成测试

所以它的价值在于：
- 快
- 稳
- 可复现
- 可进 CI
- 能发现多轮状态管理问题

而不是去替代所有真实测试。

---

## 九、面试里怎么讲最合适

可以这样描述：

> 这组测试不是简单地 mock 掉所有逻辑，而是保留了 Agent 单轮主流程、session 状态持久化和异步回写后的 reload 逻辑，只把模型、记忆基础设施、归档和真实工具发现替换成 fake/stub。这样我测到的是多轮状态流的真实业务行为，同时保证了本地和 CI 的稳定性。
