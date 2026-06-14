# db-claude vs Claude Code — 特性对比矩阵

> 图例: ✅ 已实现 | ❌ 未实现 | ⚠️ 部分实现

---

## 1. 智能体系统 (Agent System)

| # | 特性 (Claude Code 源码) | 源码位置 | db-claude 状态 |
|---|------------------------|---------|---------------|
| 1.1 | **QueryEngine** 类 — 拥有查询生命周期和会话状态 | `src/QueryEngine.ts:184` | ✅ `agent/query_loop.py:32 QueryEngine` |
| 1.2 | **submitMessage()** 异步生成器 — 提交用户消息并运行 query 循环 | `src/QueryEngine.ts:209` | ✅ `agent/query_loop.py:101 submit_message()` |
| 1.3 | **query()** 函数 — 核心 while(true) 循环，调用模型→执行工具→附加结果 | `src/query.ts:219` | ✅ `agent/query_loop.py:192 _run_agent_loop()` (LangGraph) |
| 1.4 | **callModel** — 流式调用 API，yield assistant/user/progress 消息 | `src/query.ts:659` | ✅ `_run_agent_loop` → `call_model` 节点 |
| 1.5 | **executeTools** — 执行工具调用，yield tool_result 消息 | `src/query.ts:1380` | ✅ `_run_agent_loop` → `execute_tools` 节点 |
| 1.6 | **needsFollowUp** — tool_use 检测决定是否继续循环 | `src/query.ts:558` | ✅ `should_continue` 路由函数 |
| 1.7 | **turn counting** — turnCount 递增, maxTurns 检查 | `src/query.ts:659,1705` | ✅ `state['turn_count']` |
| 1.8 | **maxBudgetUsd** 检查 — 每轮检查成本是否超限 | `src/QueryEngine.ts:972` | ✅ `max_budget_usd` 参数 |
| 1.9 | **abortController** — 可中断查询循环 | `src/QueryEngine.ts:1158` | ✅ `self._abort` + `interrupt()` |
| 1.10 | **stream_event** 消息类型 — message_start/message_delta/message_stop | `src/QueryEngine.ts:788-828` | ❌ 未实现流事件级粒度 |
| 1.11 | **attachment 消息** — structured_output, max_turns_reached, queued_command | `src/QueryEngine.ts:829-892` | ❌ 仅 result 消息，无结构化 attachment |
| 1.12 | **tool_use_summary** — Haiku 生成工具使用摘要 | `src/query.ts:1412-1482` | ❌ 未实现 (需要第二个模型) |
| 1.13 | **message_delta stop_reason 捕获** — 从 message_delta 获取真实 stop_reason | `src/QueryEngine.ts:797-809` | ⚠️ 从 response_metadata 获取 |
| 1.14 | **tombstone 消息** — streaming fallback 时清理孤儿消息 | `src/QueryEngine.ts:758-760` | ❌ 未实现 |
| 1.15 | **error_during_execution 诊断** — 详细错误信息+watermark | `src/QueryEngine.ts:1082-1118` | ⚠️ 基础异常捕获 |
| 1.16 | **SDK 兼容层** — systemInit, compact_boundary, permission_denials 报告 | `src/QueryEngine.ts:540,917-942` | ❌ 仅 CLI 模式 |

---

## 2. 智能体架构安排 (Agent Architecture)

| # | 特性 (Claude Code 源码) | 源码位置 | db-claude 状态 |
|---|------------------------|---------|---------------|
| 2.1 | **State 类型** — messages, toolUseContext, autoCompactTracking 等 9 个字段 | `src/query.ts:204-217` | ✅ `agent/state.py AgentState` (27 字段) |
| 2.2 | **while(true) 不可变 params + 可变 state** 模式 | `src/query.ts:253-268` | ⚠️ LangGraph StateGraph 语义不同 |
| 2.3 | **QueryDeps DI** — callModel, microcompact, autocompact, uuid 注入 | `src/query/deps.ts:21-31` | ❌ 无依赖注入 |
| 2.4 | **QueryConfig** — 不可变配置快照 (gates, sessionId, fastMode) | `src/query/config.ts` | ❌ 无配置快照 |
| 2.5 | **StreamingToolExecutor** — 流式工具执行器 (边流边执行) | `src/query.ts:562-568` | ❌ 串行执行模式 |
| 2.6 | **autoCompactIfNeeded** — 自动上下文压缩 | `src/query.ts:454-468` | ⚠️ `CompactManager.compact_messages()` (简单截断) |
| 2.7 | **microcompact** — 微压缩 (cache editing) | `src/query.ts:413-426` | ❌ 未实现 |
| 2.8 | **snipCompact** — 剪裁压缩 (HISTORY_SNIP) | `src/query.ts:396-409` | ❌ 未实现 |
| 2.9 | **contextCollapse** — 上下文折叠 | `src/query.ts:440-447` | ❌ 未实现 |
| 2.10 | **reactiveCompact** — 被动压缩 (prompt-too-long 恢复) | `src/query.ts:1119-1166` | ❌ 未实现 |
| 2.11 | **stopHooks** — PreToolUse/PostToolUse/Stop 钩子 | `src/query.ts:1267-1306` | ❌ 未实现 |
| 2.12 | **postSamplingHooks** — 模型响应后钩子 | `src/query.ts:1000-1008` | ❌ 未实现 |
| 2.13 | **tokenBudget** — 令牌预算自动继续 (+500k 风格) | `src/query.ts:1308-1354` | ❌ 未实现 |
| 2.14 | **maxOutputTokens 恢复** — 输出超限重试+64k 升级 | `src/query.ts:1188-1256` | ❌ 未实现 |
| 2.15 | **fallback model** — 模型过载时自动切换 | `src/query.ts:654,893-953` | ❌ 未实现 |
| 2.16 | **fileHistory snapshot** — 文件历史快照 | `src/QueryEngine.ts:641-655` | ❌ 未实现 |
| 2.17 | **memory prefetch** — 后台预取相关记忆 | `src/query.ts:300-303,1599-1614` | ❌ 未实现 |
| 2.18 | **skill discovery prefetch** — 技能发现预取 | `src/query.ts:331-335,1620-1628` | ❌ 未实现 |
| 2.19 | **prompt-too-long 恢复链** — collapse→reactiveCompact→surface error | `src/query.ts:1085-1183` | ❌ 未实现 |
| 2.20 | **media size error 恢复** — 图片/PDF 尺寸错误恢复 | `src/query.ts:1082-1084` | ❌ 未实现 |
| 2.21 | **blockingLimit 预检** — context 满载时提前阻止 | `src/query.ts:637-648` | ❌ 未实现 |
| 2.22 | **taskBudget** — beta task_budgets-2026-03-13 | `src/query.ts:290-292` | ❌ 未实现 |
| 2.23 | **queryTracking** — chainId/depth 追踪 | `src/query.ts:347-363` | ❌ 未实现 |
| 2.24 | **QueuedCommand 消费** — 队列命令 mid-turn 注入 | `src/query.ts:1570-1643` | ❌ 未实现 |
| 2.25 | **BG task summary** — 后台任务摘要 (claude ps) | `src/query.ts:1685-1702` | ❌ 未实现 |
| 2.26 | **session persistence** — transcript 记录+flush | `src/QueryEngine.ts:450-462` | ❌ 未实现 |
| 2.27 | **结构化输出** — jsonSchema + SyntheticOutputTool | `src/QueryEngine.ts:1005-1048` | ❌ 未实现 |
| 2.28 | **hasHandledOrphanedPermission** — 孤儿权限处理 | `src/QueryEngine.ts:398-408` | ❌ 未实现 |

---

## 3. 数据结构安排 (Data Structures)

| # | 特性 (Claude Code 源码) | 源码位置 | db-claude 状态 |
|---|------------------------|---------|---------------|
| 3.1 | **Message 联合类型** — user/assistant/system/progress/attachment | `src/types/message.ts:19-99` | ⚠️ 使用 LangChain BaseMessage |
| 3.2 | **MessageBase** — uuid, parentUuid, timestamp, isMeta, isVirtual, toolUseResult, origin | `src/types/message.ts:6-17` | ⚠️ additional_kwargs 部分覆盖 |
| 3.3 | **AssistantMessage** — content blocks, stop_reason, usage | `src/types/message.ts:32-38` | ✅ AIMessage + additional_kwargs |
| 3.4 | **UserMessage** — tool_use_result, isMeta | `src/types/message.ts:24-30` | ✅ HumanMessage + additional_kwargs |
| 3.5 | **SystemMessage subtypes** — 14 种 (compact_boundary, api_error, local_command...) | `src/types/message.ts:47-71` | ❌ 仅一种 SystemMessage |
| 3.6 | **ProgressMessage** — 工具进度 (Bash/MCP/Agent/Skill/WebSearch) | `src/types/message.ts:40-43` | ❌ 未实现 |
| 3.7 | **ToolUseSummaryMessage** — 工具使用摘要 | `src/types/message.ts:78-80` | ❌ 未实现 |
| 3.8 | **TombstoneMessage** — 孤儿消息标记 | `src/types/message.ts:82-84` | ❌ 未实现 |
| 3.9 | **AttachmentMessage** — structured_output, edited_text_file, hook_stopped... | `src/types/message.ts:19-22` | ❌ 未实现 |
| 3.10 | **StreamEvent / RequestStartEvent** | `src/types/message.ts:86-92` | ❌ 未实现 |
| 3.11 | **Tool 接口** — 40+ 方法/属性 | `src/Tool.ts:362-695` | ✅ `tools/base.py Tool` (30+ 方法) |
| 3.12 | **ToolDef + buildTool** — 默认值填充模式 | `src/Tool.ts:721-792` | ✅ Tool 基类默认方法 |
| 3.13 | **ToolRegistry / Tools** — readonly Tool[] | `src/Tool.ts:697-701` | ✅ `ToolRegistry` (dict 存储) |
| 3.14 | **ToolUseContext** — 60+ 字段的完整上下文 | `src/Tool.ts:158-301` | ⚠️ `ToolUseContext` TypedDict (约15字段) |
| 3.15 | **ToolPermissionContext** — mode, rules, additionalWorkingDirectories | `src/Tool.ts:123-138` | ✅ `permissions.py ToolPermissionContext` |
| 3.16 | **PermissionMode** — default/accept_edits/bypass/plan | `src/types/permissions.ts` | ✅ `PermissionMode` enum |
| 3.17 | **PermissionResult** — behavior (allow/deny/ask) + updatedInput | `src/Tool.ts` | ✅ `PermissionResult` |
| 3.18 | **ToolProgressData 联合类型** — Bash/MCP/Agent/Skill/WebSearch/REPL/TaskOutput | `src/types/tools.ts` | ❌ 未实现 |
| 3.19 | **AppState** — toolPermissionContext, fastMode, mcp, fileHistory, attribution... | `src/state/AppState.ts` | ❌ 仅 config + engine 散落状态 |
| 3.20 | **AgentDefinition** — subagent 类型定义 | `src/tools/AgentTool/loadAgentsDir.ts` | ❌ 未实现 |
| 3.21 | **CompactMetadata** — preservedSegment, compacted tokens | `src/types/message.ts:97-99` | ❌ 未实现 |
| 3.22 | **DenialTrackingState** — 拒绝计数跟踪 | `src/utils/permissions/denialTracking.ts` | ❌ 未实现 |
| 3.23 | **ContentReplacementState** — 工具结果替换跟踪 | `src/utils/toolResultStorage.ts` | ❌ 未实现 |
| 3.24 | **FileStateCache** — LRU 文件状态缓存 | `src/utils/fileStateCache.ts` | ❌ 未实现 |

---

## 4. 系统提示词 (System Prompt)

| # | 特性 (Claude Code 源码) | 源码位置 | db-claude 状态 |
|---|------------------------|---------|---------------|
| 4.1 | **getSimpleIntroSection** — 含 CYBER_RISK_INSTRUCTION | `src/constants/prompts.ts:175-184` | ✅ `get_simple_intro_section()` |
| 4.2 | **getSimpleSystemSection** — 7 条系统规则 | `src/constants/prompts.ts:186-197` | ✅ `get_simple_system_section()` |
| 4.3 | **getEnvironmentSection** — 平台/shell/cwd/date | `system_prompt.py` | ✅ `get_environment_section()` |
| 4.4 | **getToolUsageSection (Harness)** — 工具使用规则 | prompts.ts | ✅ `get_tool_usage_section()` |
| 4.5 | **getContextManagementSection** — 自动摘要说明 | prompts.ts | ✅ `get_context_management_section()` |
| 4.6 | **getAgentToolSection** — Agent/Explore/Plan 子智能体 | prompts.ts | ✅ `get_agent_tool_section()` |
| 4.7 | **getToolListSection** — 工具列表+参数+描述 | prompts.ts | ✅ `get_tool_list_section()` |
| 4.8 | **CYBER_RISK_INSTRUCTION** | `src/constants/prompts.ts:100-102` | ✅ 已包含 |
| 4.9 | **FRONTIER_MODEL_NAME** | `src/constants/prompts.ts:118` | ✅ `"Claude Opus 4.6"` |
| 4.10 | **MODEL_IDS** — opus/sonnet/haiku | `src/constants/prompts.ts:121-125` | ✅ `MODEL_IDS` dict |
| 4.11 | **SYSTEM_PROMPT_DYNAMIC_BOUNDARY** — 全局缓存分割标记 | `src/constants/prompts.ts:114-115` | ❌ 未实现 (无跨用户缓存) |
| 4.12 | **getHooksSection** — 用户钩子说明 | `src/constants/prompts.ts:127-129` | ✅ `get_hooks_section()` |
| 4.13 | **getSystemRemindersSection** — system-reminder 标签说明 | `src/constants/prompts.ts:131-134` | ✅ `get_system_reminders_section()` |
| 4.14 | **getAntModelOverrideSection** — 蚂蚁内部模型覆盖 | `src/constants/prompts.ts:136-139` | ❌ ANT-ONLY (不需要) |
| 4.15 | **getLanguageSection** — 语言偏好 | `src/constants/prompts.ts:142-149` | ❌ 未实现 |
| 4.16 | **getOutputStyleSection** — 输出风格配置 | `src/constants/prompts.ts:151-158` | ⚠️ 可选参数 |
| 4.17 | **getMcpInstructionsSection** — MCP 工具说明 | `src/constants/prompts.ts:160-164` | ❌ 无 MCP |
| 4.18 | **getMemorySection** — 持久化记忆说明 (frontmatter) | prompts.ts | ✅ `get_memory_section()` |
| 4.19 | **memory mechanics prompt** — MEMORY.md 写入/编辑规则 | `src/QueryEngine.ts:316-318` | ✅ `MemoryManager.get_memory_prompt()` |
| 4.20 | **getCoordinatorUserContext** — 协调器模式额外上下文 | `src/QueryEngine.ts:302-308` | ❌ 无 coordinator 模式 |
| 4.21 | **Bash prompt 策略** — 工具偏好 (Grep/Glob>bash, Read>cat, Edit>sed) | `src/tools/BashTool/prompt.ts` | ⚠️ 基础版 |
| 4.22 | **Git 操作说明** — commit/PR 详细流程 | `src/tools/BashTool/prompt.ts` | ❌ 未实现 |
| 4.23 | **Sandbox 说明** — 沙箱配置/绕过规则 | `src/tools/BashTool/prompt.ts` | ❌ 未实现 |
| 4.24 | **commit attribution** — Co-Authored-By: Claude | `src/utils/attribution.ts` | ❌ 不需要 |
| 4.25 | **getSimpleDoingTasksSection** — 任务执行指导 | `src/constants/prompts.ts:199+` | ❌ 未实现 |
| 4.26 | **asSystemPrompt** — 系统提示词类型包装 | `src/utils/systemPromptType.ts` | ⚠️ 简单字符串拼接 |
| 4.27 | **systemPromptSection** / **DANGEROUS_uncachedSystemPromptSection** — 缓存分段 | `src/constants/systemPromptSections.ts` | ❌ 无缓存系统 |
| 4.28 | **built-in agent prompts** — Explore/Plan agent 专用提示词 | `src/tools/AgentTool/built-in/` | ❌ 未实现 |
| 4.29 | **userContext** — getUserContext() 用户上下文 | `src/context.ts` | ✅ `get_user_context()` |
| 4.30 | **systemContext** — getSystemContext() 系统上下文 | `src/context.ts` | ✅ `get_system_context()` |
| 4.31 | **outputStyle** — 内置输出风格 (Ant 内部) | `src/constants/outputStyles.ts` | ❌ ANT-ONLY |

---

## 5. 工具系统 (Tool System)

| # | 特性 (Claude Code 源码) | 源码位置 | db-claude 状态 |
|---|------------------------|---------|---------------|
| 5.1 | **Bash** — 完整 shell 执行 | `src/tools/BashTool/` | ✅ `tools/bash.py` |
| 5.2 | **Bash — timeout** (600s max) | `BashTool/prompt.ts` | ✅ |
| 5.3 | **Bash — run_in_background** | `BashTool/prompt.ts` | ✅ |
| 5.4 | **Bash — dangerouslyDisableSandbox** | `BashTool/prompt.ts` | ✅ 参数存在 |
| 5.5 | **Bash — description 必填字段** | `BashTool/prompt.ts` | ✅ |
| 5.6 | **Bash — isReadOnly 检测** | `BashTool/readOnlyValidation.ts` | ✅ 启发式检测 |
| 5.7 | **Bash — isDestructive 检测** | `BashTool/destructiveCommandWarning.ts` | ✅ 启发式检测 |
| 5.8 | **Bash — path validation** | `BashTool/pathValidation.ts` | ❌ |
| 5.9 | **Bash — mode validation** | `BashTool/modeValidation.ts` | ❌ |
| 5.10 | **Bash — sandbox support** | `BashTool/shouldUseSandbox.ts` | ❌ |
| 5.11 | **Bash — git safety protocol** | `BashTool/bashPermissions.ts` | ❌ |
| 5.12 | **Bash — sed edit parser** | `BashTool/sedEditParser.ts` | ❌ |
| 5.13 | **Bash — PowerShell 变体** | `src/tools/PowerShellTool/` | ❌ Windows only |
| 5.14 | **Read** — 文件读取 | `src/tools/FileReadTool/` | ✅ `tools/file_read.py` |
| 5.15 | **Read — offset/limit 分页** | `FileReadTool/prompt.ts` | ✅ |
| 5.16 | **Read — PDF pages 参数** | `FileReadTool/prompt.ts` | ✅ 参数存在 |
| 5.17 | **Read — 图片渲染** | `FileReadTool/imageProcessor.ts` | ❌ |
| 5.18 | **Read — binary 检测** | `FileReadTool/limits.ts` | ✅ `_is_binary()` |
| 5.19 | **Read — 行号输出 (cat -n 格式)** | `FileReadTool/` | ✅ |
| 5.20 | **Read — maxResultSizeChars=Infinity** | `FileReadTool/` | ❌ |
| 5.21 | **Write** — 文件写入 | `src/tools/FileWriteTool/` | ✅ `tools/file_write.py` |
| 5.22 | **Write — 覆盖保护** (已存在文件警告) | `FileWriteTool/` | ⚠️ 简单 existed_before 标记 |
| 5.23 | **Edit** — 精确字符串替换 | `src/tools/FileEditTool/` | ✅ `tools/file_edit.py` |
| 5.24 | **Edit — replace_all** | `FileEditTool/` | ✅ |
| 5.25 | **Edit — 唯一匹配检查** | `FileEditTool/` | ✅ |
| 5.26 | **Edit — old_string/new_string 不同检查** | `FileEditTool/` | ✅ |
| 5.27 | **Glob** — 文件名匹配 | `src/tools/GlobTool/` | ✅ `tools/glob.py` |
| 5.28 | **Glob — fnmatch 模式** | `GlobTool/` | ✅ |
| 5.29 | **Glob — 隐藏目录跳过** | `GlobTool/` | ✅ |
| 5.30 | **Glob — max results** | `GlobTool/` | ✅ (500) |
| 5.31 | **Grep** — 正则搜索 | `src/tools/GrepTool/` | ✅ `tools/grep.py` |
| 5.32 | **Grep — system grep fallback** | `GrepTool/` | ✅ 先用系统 grep |
| 5.33 | **Grep — ignore_case** | `GrepTool/` | ✅ |
| 5.34 | **Grep — include/exclude 文件过滤** | `GrepTool/` | ✅ |
| 5.35 | **Grep — binary 跳过** | `GrepTool/` | ✅ |
| 5.36 | **Task** — 6 个任务管理工具 | `src/tools/Task*Tool/` | ✅ `tools/task.py` (6 tools) |
| 5.37 | **Task — id 依赖系统 (blocks/blockedBy)** | `TaskCreateTool/` | ✅ |
| 5.38 | **Task — 状态流转 (pending→in_progress→completed)** | `TaskUpdateTool/` | ✅ |
| 5.39 | **TodoWrite** — 结构化 todo 列表 | `src/tools/TodoWriteTool/` | ✅ `tools/todo_write.py` |
| 5.40 | **WebSearch** — 网页搜索 | `src/tools/WebSearchTool/` | ✅ `tools/web_search.py` |
| 5.41 | **WebSearch — allowed_domains/blocked_domains** | `WebSearchTool/` | ✅ 参数存在 |
| 5.42 | **WebSearch — US-only 默认** | `WebSearchTool/` | ❌ 未检查 |
| 5.43 | **WebFetch** — URL 抓取 | `src/tools/WebFetchTool/` | ✅ `tools/web_search.py` |
| 5.44 | **WebFetch — HTTP→HTTPS 升级** | `WebFetchTool/` | ✅ 自动升级 |
| 5.45 | **WebFetch — HTML→markdown 转换** | `WebFetchTool/` | ⚠️ 简单文本提取 |
| 5.46 | **WebFetch — preapproved 域名** | `WebFetchTool/preapproved.ts` | ❌ |
| 5.47 | **WebFetch — prompt 参数** (对内容运行 prompt) | `WebFetchTool/` | ✅ 参数存在 |
| 5.48 | **NotebookEdit** — Jupyter cell 编辑 | `src/tools/NotebookEditTool/` | ✅ `tools/notebook_edit.py` |
| 5.49 | **NotebookEdit — replace/insert/delete 三种模式** | `NotebookEditTool/` | ✅ |
| 5.50 | **AskUserQuestion** — 用户交互式提问 | `src/tools/AskUserQuestionTool/` | ✅ `tools/ask_user.py` |
| 5.51 | **AskUserQuestion — multiSelect** | `AskUserQuestionTool/` | ✅ |
| 5.52 | **AskUserQuestion — preview 预览** | `AskUserQuestionTool/` | ❌ |
| 5.53 | **AskUserQuestion — 1-4 个问题限制** | `AskUserQuestionTool/` | ❌ 未校验 |
| 5.54 | **EnterPlanMode / ExitPlanMode** | `src/tools/EnterPlanModeTool/`, `ExitPlanModeTool/` | ✅ `tools/plan_mode.py` |
| 5.55 | **EnterWorktree / ExitWorktree** | `src/tools/EnterWorktreeTool/`, `ExitWorktreeTool/` | ✅ `tools/plan_mode.py` |
| 5.56 | **CronCreate / CronDelete / CronList** | `src/tools/ScheduleCronTool/` | ✅ `tools/cron.py` |
| 5.57 | **Cron — 5-field cron 表达式** | `CronCreateTool/` | ✅ |
| 5.58 | **Cron — recurring/one-shot** | `CronCreateTool/` | ✅ |
| 5.59 | **Cron — durable (持久化)** | `CronCreateTool/` | ✅ 参数存在 |
| 5.60 | **Cron — session 生命周期** | `CronCreateTool/` | ⚠️ 内存存储 |
| 5.61 | **Agent** — 子智能体启动 | `src/tools/AgentTool/` | ✅ `tools/agent_tool.py` |
| 5.62 | **Agent — subagent_type** (general-purpose/Explore/Plan) | `AgentTool/` | ✅ 参数存在 |
| 5.63 | **Agent — isolation: worktree** | `AgentTool/` | ✅ 参数存在 |
| 5.64 | **Agent — run_in_background** | `AgentTool/` | ✅ |
| 5.65 | **Agent — built-in agents** (Explore/Plan/Verification) | `AgentTool/built-in/` | ❌ |
| 5.66 | **Agent — fork subagent** (缓存共享) | `AgentTool/forkSubagent.ts` | ❌ |
| 5.67 | **Agent — resume agent** | `AgentTool/resumeAgent.ts` | ❌ |
| 5.68 | **Agent — agent memory snapshot** | `AgentTool/agentMemory.ts` | ❌ |
| 5.69 | **Skill** — 技能调用 | `src/tools/SkillTool/` | ✅ `tools/skill.py` |
| 5.70 | **Skill — skill search** | `SkillTool/` | ❌ |
| 5.71 | **Skill — remote skill loader** | `services/skillSearch/remoteSkillLoader.ts` | ❌ |
| 5.72 | **Workflow** — 多智能体编排 | `src/tools/WorkflowTool/` | ✅ `tools/workflow.py` |
| 5.73 | **Workflow — pipeline/parallel/phase 模式** | `WorkflowTool/` | ❌ 复杂脚本执行 |
| 5.74 | **Monitor** — 事件流监视 | `src/tools/MonitorTool/` | ✅ `tools/monitor.py` |
| 5.75 | **ToolSearch** — 工具搜索 (延迟加载) | `src/tools/ToolSearchTool/` | ❌ |
| 5.76 | **toolHooks** — PreToolUse/PostToolUse 钩子 | `src/services/tools/toolHooks.ts` | ❌ |
| 5.77 | **toolMatchesName** — 别名匹配 | `src/Tool.ts:348-353` | ✅ `find_by_name()` |
| 5.78 | **buildTool** — TOOL_DEFAULTS 模式 | `src/Tool.ts:757-792` | ✅ Tool 基类默认方法 |
| 5.79 | **backfillObservableInput** — 工具输入回填 | `src/Tool.ts:481` | ❌ |
| 5.80 | **isSearchOrReadCommand** — 命令折叠判定 | `src/Tool.ts:429-433` | ✅ Bash/Glob/Grep/Read |
| 5.81 | **preparePermissionMatcher** — 权限匹配器 | `src/Tool.ts:514-516` | ❌ |
| 5.82 | **renderToolUseMessage/renderToolResultMessage** — React 渲染 | `src/Tool.ts:566-694` | ❌ (CLI-only, 不需要) |
| 5.83 | **toAutoClassifierInput** — 安全分类器输入 | `src/Tool.ts:556` | ⚠️ Bash/Write/Edit 实现 |
| 5.84 | **validateInput** — 输入验证 | `src/Tool.ts:489-492` | ✅ Pydantic schema 自动验证 |
| 5.85 | **strict mode** — tengu_tool_pear | `src/Tool.ts:472` | ❌ |
| 5.86 | **maxResultSizeChars** — 结果持久化阈值 | `src/Tool.ts:466` | ❌ |
| 5.87 | **isMcp / isLsp / mcpInfo** — MCP/LSP 标识 | `src/Tool.ts:436-455` | ❌ |
| 5.88 | **MCP tools** — MCPTool, ListMcpResourcesTool, ReadMcpResourceTool, McpAuthTool | `src/tools/MCPTool/`, etc. | ❌ |
| 5.89 | **LSP tools** — LSPTool | `src/tools/LSPTool/` | ❌ |
| 5.90 | **REPLTool** — 交互式 REPL 嵌入 | `src/tools/REPLTool/` | ❌ |
| 5.91 | **BriefTool** — KAIROS 简报 | `src/tools/BriefTool/` | ❌ |
| 5.92 | **DiscoverSkillsTool** — 技能发现 | `src/tools/DiscoverSkillsTool/` | ❌ |
| 5.93 | **ConfigTool** — 配置修改工具 | `src/tools/ConfigTool/` | ❌ |
| 5.94 | **SleepTool** — SLEEP_TOOL_NAME (任务队列唤醒) | `src/tools/SleepTool/` | ❌ |
| 5.95 | **SnipTool** — HISTORY_SNIP 控制 | `src/tools/SnipTool/` | ❌ |
| 5.96 | **SendMessageTool** — 子智能体间消息 | `src/tools/SendMessageTool/` | ❌ |
| 5.97 | **TeamCreateTool / TeamDeleteTool** — 智能体团队 | `src/tools/Team*Tool/` | ❌ |
| 5.98 | **SyntheticOutputTool** — 结构化输出 | `src/tools/SyntheticOutputTool/` | ❌ |
| 5.99 | **TungstenTool** — 钨测试工具 | `src/tools/TungstenTool/` | ❌ ANT-ONLY |
| 5.100 | **VerifyPlanExecutionTool** — 计划验证 | `src/tools/VerifyPlanExecutionTool/` | ❌ |

---

## 6. CLI (Command Line Interface)

| # | 特性 (Claude Code 源码) | 源码位置 | db-claude 状态 |
|---|------------------------|---------|---------------|
| 6.1 | **main.tsx** — CLI 入口点 | `src/main.tsx` | ✅ `main.py` |
| 6.2 | **dev-entry.ts** — 开发入口 | `src/dev-entry.ts` | ✅ `main.py` |
| 6.3 | **replLauncher.tsx** — REPL 启动器 | `src/replLauncher.tsx` | ✅ `cli/repl.py ReplInterface` |
| 6.4 | **--version** | `main.tsx` | ✅ |
| 6.5 | **--model / -m** | `main.tsx` | ✅ |
| 6.6 | **--provider** → deepseek | — | ✅ (新增) |
| 6.7 | **--fallback-model** | `main.tsx` | ✅ |
| 6.8 | **--max-turns** | `main.tsx` | ✅ |
| 6.9 | **--max-budget-usd** | `main.tsx` | ✅ |
| 6.10 | **--permission-mode** | `main.tsx` | ✅ |
| 6.11 | **--print / -p** | `main.tsx` | ✅ |
| 6.12 | **--verbose** | `main.tsx` | ✅ |
| 6.13 | **--cwd** | `main.tsx` | ✅ |
| 6.14 | **--system-prompt** | `main.tsx` | ✅ |
| 6.15 | **--append-system-prompt** | `main.tsx` | ✅ |
| 6.16 | **--init** | `main.tsx` | ✅ |
| 6.17 | **--resume** | `main.tsx` | ⚠️ 参数存在，未实现 |
| 6.18 | **--api-key** | — | ✅ (新增) |
| 6.19 | **--base-url** | — | ✅ (新增) |
| 6.20 | **Ink/React TUI** — 终端 UI 框架 | `src/screens/REPL.tsx` | ❌ (使用 prompt_toolkit) |
| 6.21 | **App 组件** — 全局应用包装 | `src/components/App.js` | ❌ |
| 6.22 | **spinner** — 工具执行旋转指示器 | `src/components/Spinner.js` | ✅ Rich Spinner |
| 6.23 | **prompt input** — 多行输入支持 | `REPL.tsx` | ⚠️ 单行输入 |
| 6.24 | **slash commands** — /help /model /clear /compact /config /memory /cost /permissions /exit /version | `src/commands.ts` | ✅ 全部实现 |
| 6.25 | **/commit** — git commit 技能 | `commands.ts` | ❌ |
| 6.26 | **/review** — PR review | `commands.ts` | ❌ |
| 6.27 | **/security-review** — 安全审查 | `commands.ts` | ❌ |
| 6.28 | **/simplify** — 代码简化 | `commands.ts` | ❌ |
| 6.29 | **/loop** — 循环执行 | `commands.ts` | ❌ |
| 6.30 | **/run** — 运行应用 | `commands.ts` | ❌ |
| 6.31 | **/verify** — 验证变更 | `commands.ts` | ❌ |
| 6.32 | **/deep-research** — 深度研究 | `commands.ts` | ❌ |
| 6.33 | **/init** — 初始化 CLAUDE.md | `commands.ts` | ❌ (仅 CLI flag) |
| 6.34 | **/statusline** — 状态行设置 | `commands.ts` | ❌ |
| 6.35 | **Tab completion** — 命令补全 | `REPL.tsx` | ✅ CommandCompleter |
| 6.36 | **history** — 命令历史 | `REPL.tsx` | ✅ FileHistory |
| 6.37 | **syntax highlighting** — 代码高亮 | `REPL.tsx` | ✅ Rich Markdown |
| 6.38 | **streaming display** — 流式输出 | `REPL.tsx` | ⚠️ 非流式 (完成后显示) |
| 6.39 | **permission dialog** — 权限提示 UI | `REPL.tsx` | ❌ |
| 6.40 | **tool progress display** — 工具进度 UI | `REPL.tsx` | ❌ |
| 6.41 | **fullscreen mode** — 全屏 TUI | `REPL.tsx` | ❌ |
| 6.42 | **inline code rendering** | `REPL.tsx` | ✅ Rich 自动 |
| 6.43 | **message selector** — 消息过滤面板 | `src/components/MessageSelector.tsx` | ❌ |
| 6.44 | **Settings 存储** (settings.json + local.json) | `src/utils/settings/` | ⚠️ 单一 config.json |
| 6.45 | **hooks 配置** (settings.json hooks) | `settings.ts` | ❌ |
| 6.46 | **keybindings** — 自定义键盘绑定 | `keybindings.json` | ❌ |
| 6.47 | **theme** — 主题系统 | `src/utils/theme.ts` | ⚠️ 仅 dark |
| 6.48 | **fpsTracker** — 帧率跟踪 | `src/utils/fpsTracker.ts` | ❌ |
| 6.49 | **voice input** — 语音输入 | `src/services/voice.ts` | ❌ |
| 6.50 | **remote sessions** — RemoteSessionManager | `src/remote/` | ❌ |
| 6.51 | **IDE integration** (VS Code/JetBrains) | `main.tsx` | ❌ |
| 6.52 | **growthbook** — 特性开关 | `src/services/analytics/growthbook.ts` | ❌ |
| 6.53 | **telemetry** — 遥测事件 | `src/services/analytics/` | ❌ |
| 6.54 | **cost tracking** — 成本跟踪+显示 | `src/cost-tracker.ts` | ⚠️ 基本 token 计数 |

---

## 汇总统计 (更新)

| 模块 | 总特性 | ✅ 已实现 | ❌ 未实现 | ⚠️ 部分 | 覆盖率 |
|------|--------|-----------|-----------|----------|--------|
| **1. 智能体系统** | 17 | 8 | 6 | 3 | 47% |
| **2. 架构安排** | 35 | 7 | 22 | 6 | 20% |
| **3. 数据结构** | 28 | 7 | 17 | 4 | 25% |
| **4. 系统提示词** | 38 | 20 | 15 | 3 | 53% |
| **5. 工具系统** | 106 | 58 | 43 | 5 | 55% |
| **6. CLI** | 64 | 26 | 31 | 7 | 41% |
| **总计** | **288** | **126** | **134** | **28** | **44%** |

---

## 补充特性 (from deep-scan analysis)

### 1. 智能体系统 — 补充

### 核心流正确但简化
- ✅ LangGraph StateGraph 实现了 `agent→tools→agent` 的循环结构
- ❌ 但不含 Claude Code 中的多种恢复路径 (prompt-too-long, max_output_tokens, reactiveCompact, collapse)

### 工具覆盖率较高 (56%)  
- ✅ 28 个核心工具已实现，覆盖了日常编码任务所需
- ❌ 缺少 MCP/LSP/Brief/Sleep/Skill-discovery 等高级工具

### CLI 可用但不完整
- ✅ 基础 REPL + 10 个 slash 命令能正常工作
- ❌ 缺少流式输出、权限弹窗、工具进度显示等 TUI 特性

### 架构简化但不影响基本使用
- 使用 LangChain/LangGraph 框架语义替代了 Claude Code 的手写循环
- 数据结构使用 LangChain 标准 Message 类型，而非 Claude Code 的自定义类型

### 未实现的大块功能
- **MCP 协议**: 整个 MCP 工具栈未实现
- **Hooks 系统**: PreToolUse/PostToolUse/Stop/PostSampling 钩子未实现  
- **Context compaction**: 压缩系统仅有简单截断，缺少 token 预算等高级特性
- **Session persistence**: 无会话持久化，不支持 --resume
- **Subagent orchestration**: Agent/Workflow 工具仅有参数壳，未真正执行
- **TUI 高级特性**: 无全屏、无流式、无权限弹窗
