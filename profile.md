ZhouAgent 终端智能体开发

项目简介： 从 0 到 1 实现终端 AI Agent，支持在任意目录通过 `zhou` 命令启动，围绕技能编排、工具调用、思考过程显示化与记忆机制完成核心链路设计与功能落地。

设计项目级 `.zhou` 目录体系与配置发现机制，支持`config.toml` 与 `tools.toml` 自动补齐，以及 `skills`、`session` 目录自动创建，形成项目内自配置、自落盘、自隔离的运行模式。

实现 `/skills` 模块，打通本地 skill 发现、激活状态管理、session 持久化与 system prompt 组装链路，支持在会话中动态切换行为约束、任务模式与编码规范。

实现 `/tools` 模块，完成工具注册表发现、函数描述构造、工具调用执行与结果回传链路，形成从模型决策到本地工具执行的闭环。

实现思考过程显示化，基于 reasoning delta、tool call、tool result 与 answer stream 构建事件流渲染机制，在终端分阶段展示推理摘要、工具调用过程与最终回答。

基于 mem0 + Qdrant + HuggingFace Embedding 实现 Agent 记忆机制，按 `global / folder / session` 作用域及 `user_id / agent_id / cwd / session_id` 维度组织记忆写入与检索，验证短期会话记忆、项目级长期记忆与全局知识沉淀能力。