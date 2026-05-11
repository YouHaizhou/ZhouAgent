# /tools 完整方案文档

## 一、文档目标

本文是 `zhou` 当前 `/tools` 模块的完整版说明，重点回答以下问题：

1. `/tools` 模块怎么用；
2. `tools.toml` 配置文件怎么设置；
3. 第三方 tool 应该下载到哪里、如何安装；
4. 当前代码里一条完整的工具调用时序链路是什么；
5. 使用时有哪些必要限制、注意事项与排错方法。

本文面向两类读者：

- **使用者**：想知道如何在项目里启用 tool；
- **维护者**：想知道当前实现边界、运行方式和时序链路。

---

## 二、当前 /tools 模块已经完成什么

当前版本的 `/tools` 已具备以下能力：

1. **支持 `MCP` 工具源接入**；
2. **支持 `stdio` 方式启动 MCP server**；
3. **支持工具发现（discovery）**；
4. **支持将工具描述传给模型**；
5. **支持接住模型的 tool call 并真实执行**；
6. **支持把 tool result 回传模型，再获得最终回答**；
7. **支持 `/tools` 独立界面查看当前工具分组和状态**；
8. **支持用户级 `tools.toml` 优先于项目级配置**；
9. **支持用户级配置里通过 `${project_dir}` 自动引用当前项目目录**。

一句话概括：

> 当前 `/tools` 已经不是“把工具名字写进 prompt 里”，而是“让模型真的具备工具执行能力”。

---

## 三、/tools 模块怎么用

## 3.1 启动 `zhou`

在任意项目目录中启动：

```powershell
zhou
```

启动后，`zhou` 会在当前工作目录基础上准备会话环境，并在进入对话前刷新工具注册表。

---

## 3.2 查看工具状态

输入：

```text
/tools
```

当前 `/tools` 已经做成类似 `/skills` 的独立界面，特点如下：

- 进入后使用独立 screen buffer 显示；
- 按 `Esc` 返回对话界面；
- 按 `Enter` 也可以返回；
- 当前界面只展示两类工具分组：
  - `file`
  - `git`

界面重点展示：

- 当前实际生效的 `tools.toml` 路径；
- 已启用 source 数量；
- ready / failed 数量；
- 已发现工具总数；
- 每个工具分组的状态与工具数。

---

## 3.3 在普通对话中让模型使用工具

你不需要手动输入具体工具名。

只要直接给出任务，例如：

```text
在当前项目下新建一个 test.md
```

或者：

```text
请读取当前目录下的 README.md，然后总结里面的安装步骤
```

如果当前可用工具足够，模型会自动：

1. 看到本轮可用 `tools` 描述；
2. 决定是否发起 tool call；
3. 调用 `filesystem.*` 或 `git.*` 工具；
4. 得到结果后继续推理；
5. 返回最终自然语言答案。

---

## 3.4 当前推荐的使用方式

### 文件相关任务

适合直接让模型执行，例如：

- 新建文件；
- 读取文件；
- 编辑文件；
- 列出目录；
- 搜索文件；
- 获取文件信息。

这些通常走：

- `filesystem.read_text_file`
- `filesystem.write_file`
- `filesystem.edit_file`
- `filesystem.list_directory`
- `filesystem.search_files`

### Git 相关任务

适合让模型执行，例如：

- 查看仓库状态；
- 查看日志；
- 查看 diff；
- 切换分支；
- add / commit / stash 等。

这些通常走：

- `git.git_status`
- `git.git_log`
- `git.git_diff`
- `git.git_branch`
- `git.git_add`
- `git.git_commit`

注意：`git` 工具要求目标目录本身是 git 仓库，否则只能 ready，不能正确执行仓库级操作。

---

## 四、配置文件优先级与加载规则

当前 `tools.toml` 有两级：

1. **用户级配置**
2. **项目级配置**

优先级如下：

```text
用户级 tools.toml > 项目级 tools.toml
```

也就是说，当前实现会优先读取：

```text
C:\Users\34306\.zhou\tools.toml
```

如果用户级配置不存在，再回退到当前项目目录下：

```text
<当前工作目录>\.zhou\tools.toml
```

### 当前实现意义

这样设计后：

- 你可以在用户目录维护一份全局可复用工具配置；
- 所有项目默认都能复用这套工具接入；
- 如果以后需要，也可以通过删除或移走用户级配置，让项目级配置重新生效。

---

## 五、tools.toml 怎么设置

## 5.1 当前支持的配置形态

当前只支持：

- `[[sources]]`
- `type = "mcp"`
- `transport = "stdio"`

也就是说，当前所有第三方工具都必须以 MCP server 的形式接入，并通过 stdio 子进程通信。

---

## 5.2 当前推荐的完整配置示例

当前用户目录下的推荐配置如下：

```toml
[[sources]]
id = "filesystem"
type = "mcp"
enabled = true
transport = "stdio"
command = "node"
args = [
  "C:/Users/34306/.zhou/mcp/filesystem/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js",
  "${project_dir}"
]

[[sources]]
id = "git"
type = "mcp"
enabled = true
transport = "stdio"
command = "node"
args = [
  "C:/Users/34306/.zhou/mcp/git/node_modules/@cyanheads/git-mcp-server/dist/index.js"
]
cwd = "${project_dir}"

[sources.env]
MCP_TRANSPORT_TYPE = "stdio"
```

---

## 5.3 字段说明

### `id`

工具源的唯一标识，例如：

- `filesystem`
- `git`

后续 discovered tool 会组合成：

- `filesystem.read_text_file`
- `git.git_status`

---

### `type`

当前固定为：

```toml
type = "mcp"
```

表示该工具源是一个 MCP server。

---

### `enabled`

是否启用该 source：

```toml
enabled = true
```

如果设为 `false`，该 source 会被识别，但不会参与 discovery 和调用。

---

### `transport`

当前固定为：

```toml
transport = "stdio"
```

表示通过子进程标准输入输出与 MCP server 通信。

---

### `command`

启动命令，例如：

```toml
command = "node"
```

表示使用 Node.js 启动该 server。

---

### `args`

传给启动命令的参数，例如：

```toml
args = [
  "C:/Users/34306/.zhou/mcp/filesystem/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js",
  "${project_dir}"
]
```

含义：

- 第一个参数是 server 入口脚本；
- 第二个参数是 server 允许访问的目录。

---

### `cwd`

可选，表示 MCP server 启动时的工作目录。

例如 git server：

```toml
cwd = "${project_dir}"
```

表示在当前项目目录下启动。

---

### `[sources.env]`

可选，表示需要传给该 source 的环境变量。

例如：

```toml
[sources.env]
MCP_TRANSPORT_TYPE = "stdio"
```

这个字段对某些 MCP server 很关键。比如当前使用的 git MCP server 就要求显式指定 transport。

---

## 5.4 `${project_dir}` 变量说明

为了让**用户级配置**可以在多个项目中复用，当前实现支持以下变量：

- `${project_dir}`
- `$PROJECT_DIR`
- `{project_dir}`

运行时会自动替换为：

- 当前启动 `zhou` 时的工作目录

例如你在：

```text
G:\work\projects\ZhouAgent\test
```

目录里启动 `zhou`，则：

```toml
cwd = "${project_dir}"
```

会在运行时被展开为：

```text
G:\work\projects\ZhouAgent\test
```

这使得用户级 `tools.toml` 不必写死某个项目路径。

---

## 六、第三方 tool 怎么下载，下载到哪里

## 6.1 当前设计原则

当前 `/tools` 模块已经完成“接入与调用”，但**没有做自动下载命令**。

也就是说：

- `zhou` 负责读取配置、发现工具、执行工具；
- 第三方 MCP server 的下载安装，当前需要手动完成。

这是有意为之。

因为第一版最重要的是跑通：

```text
配置 -> discovery -> tool call -> result 回注 -> 最终回答
```

而不是先做一整套工具市场、安装器和版本管理系统。

---

## 6.2 当前推荐的下载位置

当前建议把第三方 MCP server 统一安装到用户目录：

```text
C:\Users\34306\.zhou\mcp\
```

例如：

```text
C:\Users\34306\.zhou\mcp\filesystem
C:\Users\34306\.zhou\mcp\git
```

这样做的好处：

1. 工具与具体项目解耦；
2. 多个项目可共用一套已安装 MCP server；
3. 便于统一升级与维护；
4. 与用户级 `tools.toml` 的全局配置逻辑一致。

---

## 6.3 当前已经验证可用的工具

### filesystem

推荐安装到：

```text
C:\Users\34306\.zhou\mcp\filesystem
```

安装命令示例：

```powershell
npm install --prefix "C:\Users\34306\.zhou\mcp\filesystem" @modelcontextprotocol/server-filesystem
```

入口脚本通常为：

```text
C:/Users/34306/.zhou/mcp/filesystem/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js
```

---

### git

推荐安装到：

```text
C:\Users\34306\.zhou\mcp\git
```

安装命令示例：

```powershell
npm install --prefix "C:\Users\34306\.zhou\mcp\git" @cyanheads/git-mcp-server
```

入口脚本通常为：

```text
C:/Users/34306/.zhou/mcp/git/node_modules/@cyanheads/git-mcp-server/dist/index.js
```

注意：这个 git MCP server 运行时需要：

```text
MCP_TRANSPORT_TYPE=stdio
```

因此必须在 `tools.toml` 的 `[sources.env]` 中配置。

---

## 6.4 后续是否会支持自动下载

有可能，但当前版本不做。

后续如果扩展，可以考虑：

- `/tools install <name>`
- 统一安装清单；
- 版本管理；
- 缓存目录；
- 下载源配置。

但那是**安装/分发层**，不影响当前 `/tools` 作为运行时工具协议层已经成立。

---

## 七、当前 /tools 模块的完整工作链路

这一部分是当前实现最核心的内容。

工具真正成立，不是因为它被列在 `/tools` 页面上，而是因为下面这条链路已经闭环：

```text
用户输入
-> 程序发现当前可用工具
-> 程序把工具描述传给模型
-> 模型决定发起 tool call
-> 程序执行真实 MCP 工具
-> 程序把结果回传模型
-> 模型生成最终答案
```

---

## 八、完整时序链图

## 8.1 高层时序图

```text
User
  -> zhou.main.run()
  -> refresh_tools(session)
  -> tools.discover_tool_registry(cwd)
  -> discover_tools_config_path(cwd)
  -> 读取用户级或项目级 tools.toml
  -> resolve_source_templates(..., cwd)
  -> inspect_and_discover_source(...)
  -> discover_tools_via_stdio(...)
  -> request_mcp(initialize)
  -> request_mcp(tools/list)
  -> parse_tools_list(...)
  -> build_openai_tools(session)
  -> llm.chat_with_tools(...)
  -> llm._chat_once_with_messages(...)
  -> Model returns tool_calls
  -> build_tool_executor()._execute(...)
  -> tools.call_tool(...)
  -> start_stdio_process(...)
  -> initialize_mcp_session(...)
  -> request_mcp(initialize)
  -> request_mcp(tools/call)
  -> stringify_tool_result(...)
  -> llm.chat_with_tools() append tool result
  -> llm._chat_once_with_messages(...)
  -> Model returns final answer
  -> main.run() print(response)
```

---

## 8.2 按模块拆分的真实时序

### 阶段 A：用户发起请求

用户输入自然语言任务，例如：

```text
在当前项目下新建一个 test.md
```

进入：

- `src/zhou/main.py` 的 `run()`

`run()` 会先判断这是不是命令：

- `/exit`
- `/skills`
- `/tools`

如果不是命令，就进入正常对话链路。

---

### 阶段 B：刷新工具注册表

在正常对话链路里，先执行：

- `refresh_tools(session)`

对应：

- `src/zhou/main.py`
- `src/zhou/tools.py::discover_tool_registry()`

这一步会：

1. 先找用户级 `C:\Users\34306\.zhou\tools.toml`；
2. 如果不存在，再找当前项目下 `.zhou/tools.toml`；
3. 解析 `[[sources]]`；
4. 把 `${project_dir}` 替换成当前项目目录；
5. 逐个 source 做 discovery。

---

### 阶段 C：工具发现（discovery）

每个 source 会走：

- `inspect_and_discover_source()`
- `discover_tools_via_stdio()`

以 MCP stdio source 为例：

1. 启动 MCP server 子进程；
2. 发送 `initialize`；
3. 发送 `notifications/initialized`；
4. 请求 `tools/list`；
5. 解析返回的工具清单；
6. 转成内部 `ToolDescriptor` 列表。

如果某个 source 失败：

- 不会阻塞其他 source；
- 不会直接让 CLI 崩掉；
- 会在状态里标记为 `failed`。

---

### 阶段 D：把工具描述传给模型

工具发现完成后，`main.py` 会执行：

- `build_openai_tools(session)`
- `tool_to_openai_function(tool)`

这一步的作用是：

- 把内部 `ToolDescriptor` 转成模型 API 认识的 `tools` 数组。

当前实现还做了一层**安全 tool name 映射**，因为部分模型接口不允许 `function.name` 带 `.`。

例如内部名称：

```text
filesystem.read_text_file
```

传给模型时会变成类似：

```text
filesystem__read_text_file
```

等模型真的发起 tool call 后，再映射回内部真实名字执行。

---

### 阶段 E：模型决定是否调用工具

进入：

- `src/zhou/llm.py::chat_with_tools()`

这一轮请求会把：

- `system prompt`
- `user message`
- `tools`

一起发给模型。

模型有两种可能：

#### 情况 1：不需要工具

如果模型直接返回普通文本，没有 `tool_calls`，那就直接结束这一轮。

#### 情况 2：需要工具

如果模型返回 `tool_calls`，就进入执行阶段。

---

### 阶段 F：真实执行工具

一旦模型返回 `tool_calls`，执行器会走：

- `build_tool_executor()`
- `_execute()`
- `tools.call_tool()`

`tools.call_tool()` 的具体流程是：

1. 根据 tool name 找到内部 `ToolDescriptor`；
2. 找到其所属 `ToolSourceConfig`；
3. 把模型给的 arguments JSON 解析成对象；
4. 再启动一次对应 MCP server 子进程；
5. 先 `initialize`；
6. 再发 `tools/call`；
7. 拿到结果；
8. 用 `stringify_tool_result()` 收敛成文本。

这一步已经是“真实工具调用”，不是 prompt 模拟。

---

### 阶段 G：把工具结果回传模型

工具执行完之后，`llm.chat_with_tools()` 会把两类消息补回上下文：

1. assistant 的 tool call message；
2. tool 的执行结果 message。

然后再次请求模型。

这里还有一个重要兼容点：

- 对于 thinking mode，必须把 `reasoning_content` 原样带回；
- 当前实现已经处理了这个问题，避免第二轮请求报 400。

---

### 阶段 H：模型返回最终答案

第二轮或后续轮次如果模型不再返回 `tool_calls`，就说明它已经基于工具结果完成推理。

最后：

- `main.run()` 负责把最终回答打印到终端。

至此，一次完整的工具时序闭环结束。

---

## 九、用户级配置与项目级配置的推荐实践

## 9.1 推荐做法

推荐把**通用工具安装在用户目录**，并把默认工具源写到：

```text
C:\Users\34306\.zhou\tools.toml
```

这样好处最大。

---

## 9.2 什么适合放用户级

适合全局复用的工具，例如：

- `filesystem`
- `git`
- 通用浏览器工具
- 通用搜索工具

这些工具本质上不依赖某个特定项目，只依赖“当前项目目录”作为运行上下文。

---

## 9.3 什么适合放项目级

如果以后某些项目要使用特殊工具，例如：

- 某个项目专属本地服务；
- 某个项目专属数据库调试器；
- 某个项目专属脚本型 MCP server；

那更适合单独放在项目级 `.zhou/tools.toml` 里。

但在当前优先级规则下，只有**用户级配置不存在**时，项目级配置才会生效。

如果后续要同时合并两级配置，那是下一阶段设计，不属于当前版本。

---

## 十、当前版本的必要限制

当前版本已经可用，但还存在明确边界。

## 10.1 当前只支持 MCP

当前不支持：

- 自定义原生 tool DSL；
- 内建本地工具注册系统；
- 远程 market / registry。

---

## 10.2 当前只支持 stdio transport

当前所有 source 都要求：

```toml
transport = "stdio"
```

还不支持：

- SSE
- WebSocket
- HTTP stream

---

## 10.3 当前未做自动下载

当前你需要手动安装第三方 MCP server。

`zhou` 负责的是：

- 发现
- 调用
- 协议通信
- 回注结果

不是：

- 自动下载
- 自动升级
- 自动卸载

---

## 10.4 git 工具要求当前目录是仓库

即使 `git` source 本身 ready，如果当前项目目录不是 git 仓库，也不能正常执行仓库级操作。

例如：

- `git status`
- `git log`
- `git diff`

这些都要求目标目录本身包含 `.git`。

---

## 十一、为什么要区分 configured / ready / discovered

这是 `/tools` 里最重要的状态边界。

### configured

表示配置文件里声明了 source。

### ready

表示 source 成功启动并完成基础握手。

### discovered

表示成功拿到了这个 source 暴露出来的工具列表。

因此：

- `configured` 不等于可调用；
- `ready` 不等于真正有工具；
- `discovered` 才表示模型本轮确实可能调用这些工具。

这也是为什么 `/tools` 界面要展示状态，而不是只罗列工具名。

---

## 十二、常见排错方式

## 12.1 `/tools` 打开后没有工具

先检查：

1. `tools.toml` 是否存在；
2. 当前实际生效的是用户级还是项目级配置；
3. `command` 路径是否正确；
4. 对应的 npm 包是否真的装到了指定目录；
5. `node` 是否在 PATH 中可用。

---

## 12.2 模型报 `function.name` 非法

这是因为某些模型接口要求：

```text
[a-zA-Z0-9_-]+
```

不允许工具名带 `.`。

当前实现已经在 `main.py` 中做了安全映射。

如果后续再次出现，优先检查：

- 是否运行的是最新安装版本；
- `python -m pip install -U -e .` 是否重新执行过。

---

## 12.3 模型报 `reasoning_content` 必须回传

这是 thinking mode 的多轮请求兼容问题。

当前实现已经在 `llm.py` 中处理：

- assistant 的 `reasoning_content`
- assistant 的 `reasoning`

都会在工具回合中原样带回。

如果再次出现该报错，说明当前运行的不是最新代码版本。

---

## 12.4 git source ready 但 git tool 调用失败

常见原因：

1. 当前目录不是 git 仓库；
2. 没有先设置 working dir；
3. `cwd = "${project_dir}"` 未生效；
4. MCP server 所需环境变量未设置。

---

## 12.5 更新代码后功能没生效

如果你是通过安装后的 `zhou` 命令运行，改完代码后需要重新安装：

```powershell
cd /d G:\work\projects\ZhouAgent
python -m pip install -U -e .
```

这是最常见的原因之一。

---

## 十三、推荐的初始化与更新命令

## 13.1 重新安装当前项目

```powershell
cd /d G:\work\projects\ZhouAgent
python -m pip install -U -e .
```

---

## 13.2 安装 filesystem MCP server

```powershell
npm install --prefix "C:\Users\34306\.zhou\mcp\filesystem" @modelcontextprotocol/server-filesystem
```

---

## 13.3 安装 git MCP server

```powershell
npm install --prefix "C:\Users\34306\.zhou\mcp\git" @cyanheads/git-mcp-server
```

---

## 13.4 启动后验证

```text
/tools
```

检查：

- 当前 `Config` 是否指向用户级 `tools.toml`；
- `file` / `git` 是否都显示为 `ready`；
- 工具总数是否正常。

---

## 十四、后续可扩展方向

虽然当前 `/tools` 已经完成主链路，但后续还可以扩展：

1. 用户级与项目级配置合并，而不是二选一；
2. `/tools detail` 或二级界面，查看每组工具详情；
3. `/tools install` 自动安装 MCP server；
4. 内建下载清单和版本管理；
5. 支持更多 transport；
6. 引入权限边界与更细的策略配置；
7. 支持更多全局变量，而不只是 `${project_dir}`。

但这些都建立在当前这条主链路已经跑通的基础上。

---

## 十五、总结

当前 `/tools` 模块已经完成的，不只是一个命令或一个展示界面，而是一条完整闭环：

```text
配置文件
-> 发现工具源
-> 获取工具描述
-> 传给模型
-> 模型发起 tool call
-> 程序真实执行
-> 回传结果
-> 模型生成最终答案
```

你可以把它理解为：

- `/skills` 负责“模型怎么工作”；
- `/tools` 负责“模型能做什么操作”。

当前版本最重要的价值有三点：

1. **tools 已真实接入运行时，不再是 prompt 模拟**；
2. **用户级配置已成立，可在多项目中复用**；
3. **filesystem + git 两类核心工具已形成最小可用闭环**。

一句话总结：

> `/tools` 的意义，不是让用户看到工具清单，而是让模型真正具备稳定、可追踪、可配置的外部操作能力。
