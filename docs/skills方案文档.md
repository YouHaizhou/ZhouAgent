# /skills 方案文档

## 一、文档目标

本文档用于定义 `zhou` 的 `/skills` 系统第一版方案，综合前两轮分析，明确以下内容：

- `/skills` 的目标和定位
- skill 的目录扫描规则
- skill 规范设计
- 多 skill 的会话模型
- TUI 交互方式
- skill 如何持续作用于当前会话
- 后续实现时的边界与注意事项

这份方案文档默认采用以下原则：

- 支持多 skill；
- skill 为项目级能力，而不是全局能力；
- skill 的激活范围是“当前 `zhou` 会话”；
- skill 当前本质上是对 system prompt 的持续增强；
- 第一版先解决“发现、选择、激活、持续生效”，不引入复杂编排。

---

## 二、/skills 的目标定位

`/skills` 不是一个简单的“读取本地文件”功能，而是 `zhou` 进入本地可扩展 agent 形态的第一步。

它的核心目标是：

> 为当前项目提供一套本地 skill 系统，让用户在终端中交互式选择一个或多个 skill，并在当前会话内持续启用这些 skill，从而改变模型后续的工作方式、输出风格和任务处理模式。

从系统角色看：

- MCP 解决的是“工具如何接入”；
- skill 解决的是“模型如何工作”；
- `/skills` 解决的是“用户如何在当前项目中启用这些工作方式”。

因此，skill 更接近：

- 本地行为模式；
- 项目级提示增强；
- 会话级工作方法集。

---

## 三、/skills 的用户体验目标

在用户视角下，`/skills` 的体验应该是：

1. 用户在 `zhou` 会话中输入 `/skills`；
2. 程序进入一个轻量 TUI 界面；
3. TUI 中列出当前项目可用的所有 skill；
4. 用户通过方向键移动、空格勾选、回车确认；
5. 被选中的 skill 在当前会话中持续生效；
6. 用户后续正常对话时，不需要重复指定这些 skill；
7. 用户可以再次进入 `/skills` 修改当前启用状态。

这个体验的重点是：

- 交互轻量；
- 作用域清晰；
- 状态持续；
- 不打断正常对话。

---

## 四、skill 的作用域设计

### 1. 项目级作用域

skill 只属于当前打开目录对应的项目，不是用户全局 skill。

这意味着：

- 不同项目可以有不同 skill；
- skill 与项目上下文天然绑定；
- skill 可随项目一起管理；
- 项目切换后 skill 集合随之变化。

这是一个非常重要的约束，因为它保证了：

- skill 来源明确；
- skill 不会跨项目污染；
- 用户能清楚知道当前 skill 集从哪里来。

### 2. 会话级激活范围

用户在 `/skills` 中启用 skill 后，该 skill 只在：

- 当前 `zhou` 进程；
- 当前会话生命周期；
- 当前项目上下文

内持续生效。

不会自动持久化到下次启动，除非未来明确增加会话恢复机制。

也就是说，第一版默认：

- 会话开始时，active skills 为空；
- 用户手动选择后，在本会话持续有效；
- 退出 `zhou` 后失效。

---

## 五、skill 的目录发现规则

这是第一版中必须严格固定的部分。

### 1. 目录根位置

只扫描当前工作目录下：

```text
.zhou/skills/
```

### 2. 有效 skill 的结构

每个一级子目录视为一个 skill 候选项，只有当该目录下存在 `skill.md` 时，才视为有效 skill。

有效结构示例：

```text
project/
└─ .zhou/
   └─ skills/
      ├─ code-review/
      │  └─ skill.md
      ├─ docs/
      │  └─ skill.md
      └─ teaching/
         └─ skill.md
```

### 3. 无效情况

以下情况都不视为有效 skill：

- `.zhou/skills/` 下的一级目录没有 `skill.md`
- 更深层嵌套位置存在 `skill.md`，但不在一级子目录直接下方
- 不是目录，只是普通文件

例如：

```text
project/
└─ .zhou/
   └─ skills/
      ├─ empty-folder/
      ├─ nested/
      │  └─ other/
      │     └─ skill.md
      └─ note.txt
```

这里都不应被识别为有效 skill。

### 4. 第一版扫描规则总结

第一版扫描规则可以严格表述为：

1. 查找当前工作目录下 `.zhou/skills/`
2. 遍历其一级子目录
3. 若子目录内存在 `skill.md`，则记录为 skill
4. skill 名默认取子目录名
5. 不进行递归扫描

这个规则应当固定，避免边界模糊。

---

## 六、skill 规范设计

## 1. 为什么必须有规范

虽然第一版也可以直接把 `skill.md` 当普通文本读入，但一旦引入：

- TUI 列表展示
- 多 skill 同时启用
- 当前激活状态展示
- 后续筛选和管理

skill 就必须有结构化描述。

否则会出现：

- 列表里不知道显示什么名字；
- 不知道如何展示简介；
- 不知道 skill 之间怎么区分；
- skill 内容只能靠人工猜。

因此，`zhou` 需要自己的项目内 skill 规范。

### 2. 是否存在行业统一标准

当前没有一个像 MCP 那样被广泛统一采纳的“skill 标准协议”。

因此，`zhou` 不需要刻意模仿 MCP 的协议形式，而应该设计一个：

- 面向 prompt / 行为增强的本地规范；
- 足够简单；
- 足够可扩展。

### 3. 推荐规范形式

第一版推荐使用：

> `Markdown + Frontmatter`

也就是：

- 文件前部使用结构化元信息；
- 文件正文作为 skill 的指令内容；
- 整体仍然保留 Markdown 的可读性。

### 4. 推荐 skill.md 结构

建议每个 `skill.md` 采用如下结构：

```md
---
name: code-review
title: 代码审查
description: 用于对当前项目代码做结构、可维护性和风险审查
tags:
  - code
  - review
---

你当前处于“代码审查”模式。

请优先关注：
1. 可读性
2. 边界处理
3. 异常路径
4. 命名一致性
5. 是否有过度复杂逻辑

输出要求：
- 先给结论
- 再列风险点
- 最后给修改建议
```

### 5. 第一版元信息字段

第一版建议字段只保留：

- `name`：skill 的机器名，唯一标识
- `title`：展示名称
- `description`：技能简介
- `tags`：标签列表

你要求规范设计里不需要：

- `version`
- `language`
- `author`

因此本方案明确不纳入这些字段。

### 6. 字段含义说明

#### `name`

- 用于唯一标识 skill；
- 应尽量与目录名一致；
- 建议使用小写短横线风格，例如 `code-review`。

#### `title`

- 用于 TUI 中展示；
- 面向用户，可用中文；
- 应尽量简短清晰。

#### `description`

- 用于 TUI 中显示简介；
- 用一句话说明 skill 的用途；
- 面向用户而非模型。

#### `tags`

- 用于后续筛选、分类或状态展示；
- 第一版可先只解析，不强依赖。

### 7. 正文内容的定位

Frontmatter 后面的正文内容，视为：

- 当前 skill 的核心行为说明；
- 持续注入模型的提示增强内容；
- skill 被激活后真正起作用的部分。

可以理解为：

> 元信息解决“怎么管理”，正文解决“怎么生效”。

---

## 七、多 skill 设计

## 1. 为什么要支持多 skill

支持多 skill 以后，用户可以在一个会话中同时启用多个工作方式，例如：

- 代码审查
- 中文教学
- 输出尽量结构化

这会比单 skill 更灵活，也更贴近真实使用需求。

### 2. 当前会话状态模型

由于支持多 skill，会话状态不再是单值，而是一个集合。

可抽象为：

- `active_skills = []`
- 每个元素包含：
  - name
  - title
  - description
  - tags
  - body
  - path

第一版推荐把 active skills 保存在内存中，不做本地持久化。

### 3. 第一版的组合策略

多 skill 的真正难点在于组合冲突，但第一版不处理复杂冲突管理。

第一版默认策略是：

> 多个 skill 按固定顺序拼接注入 prompt，不做显式优先级系统。

顺序可以采用：

- TUI 中用户最终选中的顺序；
- 或按目录名排序；
- 或按扫描顺序。

建议第一版使用：

> 按 TUI 中当前选中结果的显示顺序拼接。

### 4. 为什么第一版不做冲突系统

因为第一版最重要的是先解决：

- 发现 skill
- 选择 skill
- 激活 skill
- 持续生效

如果一开始就引入：

- 优先级
- 冲突检测
- 兼容约束
- 自动覆盖策略

会显著增加复杂度。

因此第一版只采用最简单策略：

- 多 skill 可以共存；
- 最终统一拼接；
- 由模型在整体指令中吸收。

---

## 八、/skills 的 TUI 交互方案

## 1. 交互目标

`/skills` 的 TUI 不是完整终端应用，只是一个轻量选择器。

它的目标是：

- 清晰展示可用 skill；
- 支持多选；
- 支持方向键操作；
- 支持当前激活状态可视化；
- 不打断主会话节奏。
- 展示当前已激活skill
## 2. 建议交互方式

第一版推荐如下按键行为：

- `↑ / ↓`：上下移动当前高亮项
- `→ / ←`：选中 / 取消选中当前 skill
- `Enter`：确认当前选择并返回主会话
- `Esc`：取消本次修改并退出

### 3. 列表展示建议

建议 TUI 至少显示：

- 当前 skill 是否已选中
- `title`
- `description`

例如逻辑上可以表现为：

```text
[✓] 代码审查       用于对当前项目代码做结构与风险审查
[ ] 中文教学       用于以教学解释方式输出内容
[✓] 文档整理       用于将分析结果组织成结构化文档
```

### 4. 当前状态提示

由于支持多 skill，必须提供当前状态可见性。

第一版建议至少做到：

- 在 `/skills` TUI 中显示哪些项当前已勾选；
- 返回主界面后，active skills 存于会话状态中；

---

## 九、skill 如何在当前会话中持续生效

这是 skill 系统的核心。

### 1. 基本原则

用户启用 skill 后，skill 不应只影响一次对话，而应：

- 在当前 `zhou` 会话内持续存在；
- 每轮模型调用都被带上；
- 直到用户重新进入 `/skills` 修改，或退出会话。

### 2. 当前实现建议

第一版推荐将 skill 作为 system prompt 的附加层注入。

即每次发起模型请求时，最终 system prompt 由三层组成：

1. 基础系统提示
2. 当前已激活 skill 的集合说明
3. 各 skill 的正文内容

### 3. 推荐拼接方式

逻辑上可组织为：

```text
[基础系统提示]
你是 zhou，一个简洁、友好、可靠的中文 AI 助手。

[当前会话已启用 skills]
以下 skills 在本次会话中持续启用，请始终遵循。

Skill: 代码审查
...skill body...

Skill: 中文教学
...skill body...
```

### 4. 这样做的好处

- 与当前项目结构兼容；
- 不需要重写模型调用协议；
- 可以自然支持多 skill；
- 后续可逐步升级为更复杂的 prompt 组装层。

### 5. 第一版暂不做的内容

第一版不做：

- skill 条件触发
- skill 自动切换
- skill 作用域细分
- skill 之间的复杂依赖管理

---

## 十、命令系统建议

随着 `/skills` 出现，输入内容将分为：

- 普通自然语言对话
- 本地控制命令

因此建议把命令系统显式化。

### 1. 第一版建议命令

- `/skills`：打开 skill 选择器
- `/exit`：退出会话
- `/quit`：退出会话

---

## 十一、启动界面优化方向

结合前两轮分析，启动界面也应与 `/skills` 一起同步升级。

### 1. 总体原则

启动界面应当：

- 极简；
- 有品牌感；
- 中文；
- 信息少而明确；
- 与后续 `/skills` 命令保持统一。

### 2. 信息边界

启动界面建议只包括：

- 图形化的 `zhou` 标识；
- 一行简短中文提示；
- 一行当前支持命令提示。

### 3. 命令提示建议

由于 `/skills` 将成为重要入口，欢迎界面建议至少提示：

- 输入内容开始对话
- 输入 `/skills` 管理技能
- 输入 `/exit` 退出

### 4. 风格原则

启动界面不建议再使用方框，建议采用：

- 图形化 `zhou`
- 轻量颜文字或字形
- 克制的终端配色
- dim 辅助说明

也就是说：

> 启动界面应是品牌入口，而不是帮助面板。

---

## 十二、第一版实现边界

为了保证 `/skills` 第一版可落地，建议严格限制范围。

### 第一版要实现

1. `/skills` 命令入口
2. 扫描当前项目 `.zhou/skills/*/skill.md`
3. 解析 frontmatter + markdown 正文
4. 方向键 + 空格 + 回车 的多选 TUI
5. 当前会话 active skills 内存状态
6. 多 skill 持续注入 system prompt
7. 启动界面中加入 `/skills` 提示

### 第一版先不实现

1. 多 skill 冲突检测
2. skill 优先级系统
3. skill 依赖关系
4. skill 参数化
5. skill 自动启用规则
6. skill 远程同步
7. skill 市场
8. skill 跨项目共享

---

## 十三、推荐的后续模块拆分

随着 `/skills` 系统落地，项目结构建议演进为：

```text
src/zhou/
├─ main.py
├─ config.py
├─ llm.py
├─ errors.py
├─ commands.py
├─ session.py
├─ skills.py
└─ tui.py
```

### 各模块职责建议

- `main.py`：主循环与入口
- `commands.py`：命令解析
- `session.py`：会话状态，尤其是 active skills
- `skills.py`：skill 扫描、解析、加载
- `tui.py`：多选交互界面
- `llm.py`：最终 prompt 组装与模型调用

---

## 十四、最终结论

综合两轮分析，`/skills` 的第一版可以定义为：

> 为 `zhou` 增加一个项目级本地多 skill 系统：通过 `/skills` 打开 TUI 多选界面，从当前工作目录的 `.zhou/skills/*/skill.md` 中发现 skill，解析统一的 markdown + frontmatter 规范，并将所选 skills 作为当前会话的持续性 system prompt 增强层。

这是一个合理、清晰、可渐进扩展的第一版方案。

它的价值在于：

- 把 skill 限定在项目上下文中；
- 把 skill 从随意文本推进到结构化规范；
- 把会话从“纯聊天”推进到“有状态的 agent runtime”；
- 为后续的工具、记忆、命令系统打下基础。


---

## 十五、/skills 完整时序图

下面这部分用于说明当前代码里一条完整的 `/skills` 链路，从用户输入命令、进入选择界面、更新会话状态，到后续普通对话中 skill 持续注入 system prompt 的全过程。

### 1. 高层时序图

```text
User
  -> main.run()
  -> commands.parse_command("/skills")
  -> main.open_skills_picker(session)
  -> main.refresh_skills(session)
  -> skills.discover_skills(cwd)
  -> skills.load_skill(skill.md)
  -> skills.parse_skill_document(content)
  -> session.set_available_skills(...)
  -> tui.pick_skills(...)
  -> tui.render_skill_picker(...)
  -> User 方向键/回车/Esc
  -> main.open_skills_picker(session)
  -> session.set_active_skills_by_names(...)
  -> main.render_skills_summary(...)
  -> 返回主对话界面
  -> User 输入普通问题
  -> main.build_system_prompt(session)
  -> skills.build_skill_system_prompt(active_skills)
  -> llm.stream_chat(...) 或 llm.chat_with_tools(...)
  -> 模型基于 skills 增强后的 system prompt 生成回答
```

### 2. 命令触发阶段

用户在终端输入：

```text
/skills
```

进入：

- `src/zhou/main.py::run()`
- `src/zhou/commands.py::parse_command()`

这一阶段只负责判断：

- 当前输入是不是命令；
- 如果是 `/skills`，则不进入普通聊天，而是切到 skill 选择流程。

### 3. skill 发现阶段

进入：

- `src/zhou/main.py::open_skills_picker()`
- `src/zhou/main.py::refresh_skills()`
- `src/zhou/skills.py::discover_skills()`

这一步会：

1. 扫描当前工作目录下 `.zhou/skills/`；
2. 遍历每个子目录；
3. 查找其中的 `skill.md`；
4. 对每个 `skill.md` 执行解析。

如果某个目录不满足结构要求，例如：

- 不是目录；
- 没有 `skill.md`；
- 正文为空；

则不会被加入最终可选 skill 列表。

### 4. skill 解析阶段

每个候选 skill 会进入：

- `skills.load_skill()`
- `skills.parse_skill_document()`
- `skills.parse_frontmatter_lines()`

在这一阶段，程序会从 `skill.md` 中提取：

- `name`
- `title`
- `description`
- `tags`
- `body`
- `path`

然后组装成 `session.Skill` 对象。

这一步完成后，`discover_skills()` 返回的是一组结构化 `Skill`，而不是原始 markdown 文本。

### 5. 会话状态更新阶段

当 skills 被发现后，会进入：

- `src/zhou/session.py::SessionState.set_available_skills()`

这一阶段会更新当前会话里的：

- `available_skills`

并且做一件重要的事：

- 如果某些之前激活的 skill 已经不在当前项目里了，会自动从 `active_skills` 中移除。

也就是说，`SessionState` 在这里承担的是：

> skill 可用集合与激活集合的统一状态入口。

### 6. TUI 交互阶段

发现完成后，进入：

- `src/zhou/tui.py::pick_skills()`

在 Windows 下，会进一步进入：

- `alternate_screen()`
- `render_skill_picker()`

界面层会：

1. 进入独立 screen buffer；
2. 渲染 Skills / Actions / Status 三块；
3. 接收方向键、左右键、回车、Esc；
4. 根据按键更新当前焦点与选中状态。

按键语义：

- `↑ / ↓`：移动焦点
- `→`：选中当前 skill
- `←`：取消当前 skill
- `Enter`：确认当前选择
- `Esc`：取消修改并返回

如果不是 Windows，则走 fallback 交互逻辑。

### 7. 选择结果落盘到会话阶段

当用户按下 `Enter` 确认后，会回到：

- `src/zhou/main.py::open_skills_picker()`

然后执行：

- `SessionState.set_active_skills_by_names(...)`

这一步会根据用户选中的 skill 名称，更新：

- `session.active_skills`

如果用户按的是 `Esc`，则：

- 本次修改不生效；
- `active_skills` 保持原样。

### 8. 命令结束后的摘要输出阶段

选择器退出后，程序进入：

- `main.render_skills_summary(session, result)`

这一步会向主对话输出流打印：

- `applied` 或 `cancelled`
- 当前会话中 active skill 数量
- 当前激活 skill 列表
- 每个 skill 对应的 path

这部分的作用不是继续交互，而是：

> 给用户一个稳定、可回看、可确认的会话状态摘要。

### 9. skills 持续生效阶段

当用户退出 `/skills` 后，再输入普通问题时，会进入：

- `main.build_system_prompt(session)`
- `skills.build_skill_system_prompt(session.active_skills)`

这一阶段会把：

1. 基础系统提示；
2. 当前 active skills 的描述；
3. 每个 skill 的正文内容；

拼成最终 system prompt。

也就是说，skills 的真正作用不是停留在 `/skills` 页面本身，而是在：

- 后续每轮模型调用
- 普通流式聊天
- 或带 tools 的多轮调用

中持续生效。

### 10. 与普通对话链路的衔接

后续普通用户输入会进入两种路径之一：

#### 路径 A：没有 tools

```text
User 普通输入
-> main.build_system_prompt(session)
-> skills.build_skill_system_prompt(active_skills)
-> llm.stream_chat(...)
-> 模型返回文本
```

#### 路径 B：有 tools

```text
User 普通输入
-> main.build_system_prompt(session)
-> skills.build_skill_system_prompt(active_skills)
-> main.build_openai_tools(session)
-> llm.chat_with_tools(...)
-> 模型在 skills + tools 双重条件下工作
```

这说明当前 agent 的运行语义是：

- `skills` 提供行为模式；
- `tools` 提供可执行能力；
- 两者会在 `main.py` 汇合，再共同影响模型。

### 11. 为什么这条时序是 /skills 的核心链路

因为 `/skills` 真正成立，不是因为它能打开一个 TUI，而是因为它完成了下面这条闭环：

```text
项目目录发现 skills
-> 解析 skill.md
-> 用户在终端中选择
-> 结果进入 SessionState
-> 后续每轮模型请求都持续带上这些 skill
```

这条闭环一旦成立，`/skills` 就不再是一次性命令，而是一个真正的：

- 项目级 skill 系统
- 会话级状态系统
- 持续性 prompt 增强层
