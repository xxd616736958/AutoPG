# AutoPG 最优架构设计

> 基于 LangChain 1.3 + LangGraph 1.2 生态的最佳实践。
> 原则：充分利用官方组件，自定义只在必要时介入。

---

## 一、项目结构

```
autopg/
├── graph.py                          # ← langgraph serve 唯一入口
│   └── compiled_graph                # 模块级导出：SqliteSaver + 完整编排图
│
├── agents/                           # Agent 定义（每个 = create_agent 调用）
│   ├── __init__.py
│   ├── main.py                       # 主对话 agent
│   ├── explore.py                    # 只读搜索 agent
│   ├── plan.py                       # 架构设计 agent
│   ├── general.py                    # 通用编码 agent
│   └── db_admin.py                   # 数据库管家 agent（示例扩展）
│
├── middleware/                        # 中间件（继承官方 AgentMiddleware）
│   ├── __init__.py
│   ├── collapse.py                   # ContextCollapseMiddleware
│   ├── compact.py                    # AutoCompactMiddleware
│   ├── permissions.py                # PermissionCheckMiddleware
│   ├── tool_budget.py               # ToolResultBudgetMiddleware
│   ├── file_cache.py                # FileCacheMiddleware
│   ├── session.py                   # SessionPersistenceMiddleware
│   └── tracking.py                  # TokenTrackingMiddleware
│
├── context.py                         # AgentContext dataclass + Runtime 绑定
│
├── tools/                             # 工具（不变）
│   └── ...
│
├── query_engine.py                    # 薄层：图 + 会话 + 中断 + provider
│
├── cli/                               # 终端（不变）
│   ├── repl.py
│   ├── commands.py
│   └── session_picker.py
│
├── context/                           # 数据层（不变）
│   ├── collapse.py                   # CollapseManager
│   ├── compact.py                    # CompactManager
│   ├── memory.py                     # MemoryManager
│   └── __init__.py
│
└── utils/                             # 基础设施（不变）
    ├── session.py
    ├── file_cache.py
    ├── config.py
    └── permissions.py
```

---

## 二、核心设计：编排层 + 执行层

```
┌─────────────────────────────────────────────────────────────┐
│  graph.py (raw StateGraph — 编排层)                        │
│                                                             │
│  ┌──────────┐   ┌───────────┐   ┌───────────┐             │
│  │  router  │──→│  main     │──→│  merge    │──→ ...      │
│  │  (手写)  │   │  (create  │   │  (手写)   │             │
│  │          │   │  _agent)  │   │           │             │
│  └──────────┘   └───────────┘   └───────────┘             │
│       │                                                │
│       ├──→ explore (create_agent) ──→ merge            │
│       ├──→ plan    (create_agent) ──→ merge            │
│       └──→ general (create_agent) ──→ merge            │
│                                                             │
│  compiled_graph = orchestrator.compile(                    │
│      checkpointer=SqliteSaver.from_conn_string(            │
│          "~/.autopg/checkpoints.db"                     │
│      )                                                     │
│  )                                                         │
└─────────────────────────────────────────────────────────────┘
```

- **编排层** (raw StateGraph)：路由、合并、条件分支。自定义逻辑。
- **执行层** (create_agent)：每个 agent 的标准 ReAct 循环。官方生成。
- **中间件** (AgentMiddleware)：横切关注点。每个 agent 独立配置。

---

## 三、AgentContext

```python
# context.py
from dataclasses import dataclass, field
from typing import Optional, Callable, Any

@dataclass
class AgentContext:
    """Runtime.context 的类型定义。LangGraph 自动注入 Runtime(context=this)。"""
    session_id: str
    cwd: str = ""
    provider: str = "deepseek"
    model: str = "deepseek-v4-flash"
    permission_mode: str = "default"
    auto_save: bool = True
    is_non_interactive: bool = False

    # 数据层依赖（中间件通过 context 获取）
    collapse_manager: Optional[Any] = None
    compact_manager: Optional[Any] = None
    file_cache: Optional[Any] = None
    total_usage: dict = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})

    # 回调（中间件通过 context 调用）
    on_stream_token: Optional[Callable[[str], None]] = None
    on_tool_start: Optional[Callable[[str, str], None]] = None
    on_tool_end: Optional[Callable[[str, str], None]] = None
    on_permission_check: Optional[Callable[[str, bool, str], bool]] = None

    # 基础设施
    result_temp_dir: str = ""
    child_engines: list = field(default_factory=list)
```

使用方式：

```python
# 中间件中
class SessionPersistenceMiddleware(AgentMiddleware):
    async def aafter_agent(self, state, runtime):
        ctx = runtime.context          # 类型安全：AgentContext
        save_session(ctx.session_id, state["messages"], metadata={
            "model": ctx.model, "cwd": ctx.cwd,
        })
        return None

# 图节点中
async def call_model(state, config, *, context: AgentContext):
    if context.on_stream_token:
        context.on_stream_token(token)
    ...
```

---

## 四、Agent 定义

```python
# agents/explore.py
from langchain.agents import create_agent
from ..middleware import FileCacheMiddleware, ToolResultBudgetMiddleware
from ..tools import read, glob, grep, web_search, web_fetch

def build_explore_agent() -> 'CompiledStateGraph':
    """只读搜索 agent。"""
    return create_agent(
        model="deepseek-v4-flash",
        tools=[read, glob, grep, web_search, web_fetch],
        middleware=[
            FileCacheMiddleware(),
            ToolResultBudgetMiddleware(max_result_chars=50_000),
        ],
        system_prompt=(
            "You are a read-only search agent. "
            "You CANNOT write, edit, or execute code. "
            "Find information and report it back concisely. "
            "Be thorough — search multiple locations and patterns."
        ),
        context_schema=AgentContext,
        name="explore",
    )


# agents/plan.py
from langchain.agents import create_agent
from ..middleware import ContextCollapseMiddleware

def build_plan_agent() -> 'CompiledStateGraph':
    """架构设计 agent。"""
    return create_agent(
        model="deepseek-v4-pro",
        tools=[read, glob, grep],
        middleware=[ContextCollapseMiddleware()],
        system_prompt=(
            "You are a software architect. Design implementation plans. "
            "Do NOT write code. Output structured plans."
        ),
        context_schema=AgentContext,
        name="plan",
    )


# agents/main.py
from langchain.agents import create_agent
from ..middleware import (
    ContextCollapseMiddleware, AutoCompactMiddleware,
    PermissionCheckMiddleware, FileCacheMiddleware,
    ToolResultBudgetMiddleware, SessionPersistenceMiddleware,
    TokenTrackingMiddleware,
)
from ..tools import all_tools

def build_main_agent() -> 'CompiledStateGraph':
    """主对话 agent — 完整的工具集和中间件栈。"""
    return create_agent(
        model="deepseek-v4-flash",
        tools=all_tools,
        middleware=[
            ContextCollapseMiddleware(),
            AutoCompactMiddleware(),
            PermissionCheckMiddleware(),
            FileCacheMiddleware(),
            ToolResultBudgetMiddleware(),
            TokenTrackingMiddleware(),
            SessionPersistenceMiddleware(),
        ],
        system_prompt=dynamic_system_prompt(),  # 从 system_prompt.py 构建
        context_schema=AgentContext,
        checkpointer=None,  # 由编排层统一管理
        name="main",
    )
```

---

## 五、编排器

```python
# graph.py — 模块级导出，langgraph serve 入口

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from typing import TypedDict, Annotated, Literal
from langgraph.graph.message import add_messages

from .agents.main import build_main_agent
from .agents.explore import build_explore_agent
from .agents.plan import build_plan_agent
from .agents.general import build_general_agent
from .context import AgentContext


class OrchestratorState(TypedDict):
    messages: Annotated[list, add_messages]
    active_agent: str                     # "main" | "explore" | "plan" | "general"
    agent_results: dict                   # agent_name → result summary
    turn_count: int
    system_prompt: str


def _build_orchestrator() -> StateGraph:
    """编排层 — raw StateGraph，自定义路由逻辑。"""
    workflow = StateGraph(OrchestratorState, context_schema=AgentContext)

    # 注册子图（每个 = create_agent 生成的 CompiledStateGraph）
    workflow.add_node("main", build_main_agent())
    workflow.add_node("explore", build_explore_agent())
    workflow.add_node("plan", build_plan_agent())
    workflow.add_node("general", build_general_agent())

    # 自定义节点（编排逻辑 — 需要手写）
    workflow.add_node("router", _route_to_agent)
    workflow.add_node("merge_results", _merge_agent_results)

    # 入口：router 决定调用哪个 agent
    workflow.set_entry_point("router")

    # router → 目标 agent
    workflow.add_conditional_edges("router", _pick_agent, {
        "main": "main",
        "explore": "explore",
        "plan": "plan",
        "general": "general",
    })

    # 所有 agent 执行完 → merge → 可能再 route 或 end
    workflow.add_edge("main", "merge_results")
    workflow.add_edge("explore", "merge_results")
    workflow.add_edge("plan", "merge_results")
    workflow.add_edge("general", "merge_results")

    workflow.add_conditional_edges("merge_results", _should_continue, {
        "route": "router",
        "end": END,
    })

    return workflow


async def _route_to_agent(state: OrchestratorState, config, *, context: AgentContext):
    """分析用户意图，决定用哪个 agent。纯编排逻辑。"""
    # 默认 main agent 处理
    return {"active_agent": "main"}


def _pick_agent(state: OrchestratorState) -> Literal["main", "explore", "plan", "general"]:
    return state["active_agent"]


async def _merge_agent_results(state: OrchestratorState, config, *, context: AgentContext):
    """合并 agent 输出到主对话。纯编排逻辑。"""
    return {"turn_count": state.get("turn_count", 0) + 1}


def _should_continue(state: OrchestratorState) -> Literal["route", "end"]:
    if state.get("turn_count", 0) > 50:
        return "end"
    return "end"  # 默认一轮结束


# ── 模块级导出 ──
import os
db_path = os.path.join(os.path.expanduser("~/.autopg"), "checkpoints.db")
os.makedirs(os.path.dirname(db_path), exist_ok=True)

compiled_graph = _build_orchestrator().compile(
    checkpointer=SqliteSaver.from_conn_string(db_path),
)
```

---

## 六、中间件系统

```python
# middleware/collapse.py
from langchain.agents.middleware.types import AgentMiddleware
from ..context import AgentContext

class ContextCollapseMiddleware(AgentMiddleware):
    """继承官方 AgentMiddleware。"""

    async def abefore_model(self, state, runtime) -> dict | None:
        ctx: AgentContext = runtime.context
        collapse_mgr = ctx.collapse_manager
        if not collapse_mgr or len(state["messages"]) <= 20:
            return None

        result = await collapse_mgr.apply_collapses_if_needed(
            state["messages"], state.get("turn_count", 0)
        )
        if result.get("changed"):
            return {"messages": result["messages"]}
        return None
```

**每个中间件继承官方 `AgentMiddleware`，接收官方的 `Runtime`，从 `runtime.context` 获取类型安全的 `AgentContext`。**

和当前中间件实现的区别只有一处：`runtime` 是 `Runtime[AgentContext]` 而不是 `dict`。其他逻辑完全不变。

---

## 七、QueryEngine

```python
# query_engine.py
class QueryEngine:
    """薄层 — 绑定 compiled_graph + 会话管理 + provider 选择。"""

    def __init__(self, ...):
        self._stack = MiddlewareStack([...])  # 如需要额外非图中间件
        ...

    async def submit_message(self, prompt):
        """运行 compiled_graph，消费 astream_events 产出自定义事件。"""
        state = build_initial_state(prompt)
        context = AgentContext(
            session_id=self._session_id,
            collapse_manager=self._collapse,
            compact_manager=self._compact,
            on_stream_token=self.on_stream_token,
            on_tool_start=self.on_tool_start,
            ...
        )
        config = {"configurable": {"thread_id": self._session_id}}

        async for event in compiled_graph.astream_events(
            state, config, context=context, version="v2"
        ):
            kind = event["event"]
            if kind == "on_chat_model_stream":
                yield {"type": "token", "content": event["data"]["chunk"].content}
            elif kind == "on_tool_start":
                yield {"type": "tool_start", ...}
            elif kind == "on_tool_end":
                yield {"type": "tool_end", ...}

        # 结果直接从 graph state 获取（不需要 after_agent 中间件）
        final_state = compiled_graph.get_state(config)
        ...
```

**`submit_message` 不再是中间件编排器。** 中间件已经在图内部——`create_agent` 把它编织进了 agent 节点。`submit_message` 只做三件事：构建 state + context、运行图、把 `astream_events` 转成 CLI 需要的自定义事件。

---

## 八、架构对比：当前 vs 最优

| 维度 | 当前架构 | 最优架构 |
|------|---------|---------|
| 图定义 | QueryEngine 内部动态编译 | `graph.py` 模块级导出 |
| 中间件执行 | 图外 `astream_events` 驱动 | 图内编译时编织（`create_agent`） |
| Runtime | 手写 dict | `AgentContext` dataclass + `Runtime` |
| Checkpoint | `MemorySaver` | `SqliteSaver` 持久化 |
| Agent 创建 | 每个子智能体 new QueryEngine | `create_agent` 生成子图 |
| 部署 | 无 | `langgraph serve` 一键部署 |
| LangSmith | 不支持 | 自动追踪 |
| 中间件基类 | 自建 `AgentMiddleware` | 继承官方 `AgentMiddleware` |
| 多 Agent | `_child_engines` 手动管理 | 子图 + `Send` + `Command.goto` |

---

## 九、子智能体执行

```python
# agents/explore.py 已经是一个完整的 CompiledStateGraph
# 编排器中用原生子图路由：

# Option A: 直接子图调用
workflow.add_node("explore", build_explore_agent())

# Option B: 动态并行（多个 explore agent 同时跑）
from langgraph.types import Send

def _fanout_explore(state):
    tasks = state.get("pending_tasks", [])
    return [Send("explore", {"messages": [HumanMessage(content=t)]}) for t in tasks]

workflow.add_conditional_edges("router", _fanout_explore, ["explore"])
```

不再需要 `_child_engines` 列表和手动中断传播。LangGraph 的 `Send` 和 `Command.goto` 原生处理。

---

## 十、deploy

```bash
# 开发
python -m autopg.main

# 部署为 HTTP API
langgraph serve graph.py

# 自动生成以下端点：
# POST /runs              — invoke/stream
# GET  /runs/{id}         — status
# GET  /threads/{id}/state — checkpoint
# POST /assistants         — 创建
```

前端直接调 HTTP API。

---

## 十一、关键设计决策

1. **编排层用 raw StateGraph，执行层用 create_agent。** 编排需要自定义路由，执行是标准 ReAct。两者不冲突。

2. **中间件继承官方 AgentMiddleware。** 自己的基类删掉。中间件类本身不动——只改继承和 `runtime.context` 访问方式。

3. **AgentContext 不替代 Runtime。** `Runtime` 是容器，`AgentContext` 是内容。两者都用。

4. **SqliteSaver 和 JSONL 共存。** SqliteSaver 做图状态持久化，JSONL 做会话 transcript。不互相替代。

5. **`submit_message` 不再是中间件编排器。** 中间件已经在图内部。它只做事件转换。

6. **每个 agent 有独立的工具集、模型、中间件栈。** 和 AutoPG 的 AgentDefinition 完全对应。
