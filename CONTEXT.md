# Zhou 项目领域词汇表

本文档定义 Zhou 项目的核心领域概念，作为架构评审、代码导航和 AI 协作的统一语言基础。

---

## 项目

**Zhou** — 一个运行在终端中的中文 AI CLI Agent，支持技能（Skill）激活、MCP 工具调用和三维度记忆系统。

## 核心领域概念

### Session（会话）
一次 Zhou 启动到退出的完整生命周期。每个 Session 拥有唯一 ID，持久化到 `.zhou/session/<session_id>/` 目录下，包含 `meta.json`（元数据）和 `turns.jsonl`（轮次记录）。

### Turn（轮次）
会话中的一轮用户-助手交互，包含：
- 用户输入（`user_input`）
- 助手回复（`assistant_text`）
- 推理摘要（`reasoning_summary`）
- 工具调用记录（`tool_calls`）
- 标签（`tags`）
- 记忆候选（`memory_candidates`）

轮次以 JSONL 格式持久化，对应数据类 `TurnRecord`。

### Skill（技能）
可激活的提示词增强模块。每个 Skill 是一个 Markdown 文件，包含名称、描述、标签和技能正文。Skill 存放在 `.zhou/skills/` 目录下，运行时可通过 `/skills` 命令交互式管理。对应数据类 `Skill`。

### Tool（工具）
通过 MCP（Model Context Protocol）暴露的外部能力，如文件系统操作、Git 操作等。工具源配置在 `.zhou/tools.toml` 中定义，运行时通过 `stdio` 传输层与 MCP 服务器进程通信。对应数据类 `ToolDescriptor`、`ToolRegistry`、`ToolSourceConfig`。

### Memory（记忆系统）
三维度九分类的记忆体系：

- **Scope（维度）**：`Global`（全局）、`Folder`（项目级）、`Session`（会话级）
- **Kind（类型）**：`Knowledge`（知识）、`LongTerm`（长期）、`ShortTerm`（短期）
- **Class（分类）**：`Episodic`（情节）、`Semantic`（语义）、`Procedural`（程序性）

记忆通过 Mem0 库持久化到 Qdrant 向量数据库，支持语义检索。对应枚举 `MemoryScope`、`MemoryKind`、`MemoryClass`，数据类 `MemoryRecord`。

### Memory Model（记忆模型）
LLM 驱动的记忆富化流程。每轮对话结束后，MemoryModelWorker 异步提交 MemoryModelJob，由 LLM 分析当前轮次内容，决定对 Session/Project 记忆的 insert/update/ignore 操作。对应 `EnrichedTurnResult`、`MemoryModelWorker`、`MemoryModelJob`。

### Global Archive（全局归档）
跨会话的长期记忆归档。每轮对话结束时自动追加到全局归档文件，用于跨项目的知识积累。对应 `GlobalArchiveWriter`。

### Turn Enrichment（轮次富化）
基于启发式规则（正则匹配）的轮次标签推导和记忆候选提取。在 `build_turn_record` 时自动执行（`auto_enrich=True`），生成 `tags` 和 `memory_candidates`。对应模块 `turn_enrichment.py`。

### Config（配置）
应用配置体系，包含 LLM 连接参数、记忆系统设置（Qdrant 地址/端口/容器名）、全局归档路径等。支持用户级和项目级配置。对应 `AppConfig`、`MemorySettings`。

---

## 模块关系

```
main.py          — 启动编排（bootstrap + REPL 循环）
session.py       — 会话状态与轮次持久化
turn_enrichment.py — 轮次的启发式富化（标签、记忆候选）
memory.py        — 记忆管理（Mem0 接入、检索、写入、富化结果应用）
memory_model.py  — LLM 驱动的记忆富化（异步 worker）
memory_commands.py — /memory 命令处理
tools.py         — MCP 工具发现与调用
tui.py           — 终端 UI 渲染（TUI）
skills.py        — Skill 发现与系统提示构建
llm.py           — LLM 客户端（API 调用/流式响应）
config.py        — 配置加载
commands.py      — 斜杠命令解析
global_archive.py — 全局归档写入
errors.py        — 错误类型定义
```

## 关键设计决策

- MCP 工具通信统一使用 `stdio` 传输层，每次调用启动独立进程
- 记忆系统依赖第三方 Mem0 库 + Qdrant 向量数据库
- 记忆模型采用异步 worker 模式，不阻塞主对话循环
- Skill 系统提示以"以下 skills 在本次会话中持续启用"的形式注入
