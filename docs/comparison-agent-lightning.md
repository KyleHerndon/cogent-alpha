# Coglet vs. Microsoft Agent Lightning — Architectural Comparison

## Executive Summary

Coglet and Agent Lightning solve fundamentally different problems in the AI agent space:

- **Coglet** is a **runtime framework for hierarchical agent orchestration** — it defines how agents are structured, supervised, and communicate at runtime.
- **Agent Lightning** is an **optimization/training framework for existing agents** — it wraps around any agent system to apply reinforcement learning, prompt optimization, and fine-tuning.

They are complementary, not competing. Coglet defines what agents *are* and how they *run*; Agent Lightning defines how agents *improve* over time.

---

## 1. Core Abstractions

### Coglet

Two primitives forming a recursive hierarchy:

| Primitive | Role | Interface |
|-----------|------|-----------|
| **COG** (Create, Observe, Guide) | Slow, reflective supervisor | `create()`, `observe()`, `guide()` |
| **LET** (Listen, Enact, Transmit) | Fast, reactive executor | `@listen`, `@enact`, `transmit()` |

Every Coglet is both a COG (supervising children) and a LET (supervised by a parent). This creates a fractal tree where layers differ in cadence and scope, not in interface.

### Agent Lightning

Three components in a decoupled pipeline:

| Component | Role | Communication |
|-----------|------|---------------|
| **Runner** | Executes agent tasks, emits spans | Polls LightningStore for rollouts |
| **LightningStore** | Central hub: tasks, traces, resources | Database + message queue |
| **Algorithm** | Reads spans, produces improved resources | Posts updated weights/prompts to store |

The Runner wraps existing agents (from any framework). The Algorithm applies RL/optimization. The Store decouples them.

---

## 2. Design Philosophy

| Dimension | Coglet | Agent Lightning |
|-----------|--------|-----------------|
| **Primary concern** | Agent structure and supervision | Agent optimization and training |
| **Metaphor** | Erlang/OTP supervision tree | RL training loop |
| **Agent definition** | Defined by the framework (Coglet subclass) | Wraps agents from any framework |
| **Communication** | Async channels (`@listen`, `transmit`) | Structured spans via tracers |
| **Hierarchy** | First-class recursive COG/LET tree | Flat: Runner executes, Algorithm learns |
| **State management** | Mixins (GitLet, CodeLet, Memory protocol) | LightningStore (resources, rollouts) |
| **Failure handling** | Supervision tree with restart policies | Rollout status machine (succeeded/failed/cancelled) |

---

## 3. Communication Models

### Coglet: Channel-Based Async Messaging

```
Data plane:    @listen("channel") → handler
Control plane: @enact("command")  → handler
Output:        transmit("channel", data)
Supervision:   observe(child, "channel"), guide(child, command)
```

- Fire-and-forget, location-agnostic
- Backpressure-tolerant pub/sub via ChannelBus
- COG observes LET only through the channel protocol — no direct introspection

### Agent Lightning: Span-Based Tracing

```
Execution:  Runner polls Store for Rollouts → executes agent → emits Spans
Learning:   Algorithm reads Spans from Store → produces updated Resources
Delivery:   Trainer streams Resources back to inference engine
```

- Spans indexed by (rollout_id, attempt_id, sequence_id)
- Tracers: AgentOps (OpenTelemetry-based), Weave, or LLMProxy for remote agents
- Store is the single synchronization point

### Key Difference

Coglet channels carry **live operational data** between agents at runtime. Agent Lightning spans carry **training telemetry** collected passively for offline optimization.

---

## 4. Hierarchy and Supervision

### Coglet

- Recursive supervision tree: every COG manages LETs, every COG is itself a LET
- `CogBase(restart="on_error", max_restarts=3, backoff_s=1.0)` — declarative restart policy
- `on_child_error()` — parent decides restart/stop/escalate
- `CogletRuntime.tree()` — ASCII visualization of live hierarchy
- MulLet — fan-out N identical children with map/reduce

### Agent Lightning

- Flat two-tier: Algorithm (one) → Runners (many)
- No hierarchical supervision; Runners are independent workers
- Rollout lifecycle: queuing → preparing → running → succeeded/failed/cancelled
- Scaling is horizontal: add more Runners, they all poll the same Store

### Key Difference

Coglet's hierarchy is **structural** — it defines how agents relate, supervise, and recover from failures at every level. Agent Lightning's architecture is **flat** — it has a single coordinator (Algorithm) and parallel workers (Runners), focused on throughput of training rollouts rather than operational fault tolerance.

---

## 5. Extensibility Model

### Coglet: Mixins

Behavior is composed via mixins applied at the class level:

| Mixin | Capability |
|-------|-----------|
| **LifeLet** | `on_start()` / `on_stop()` lifecycle hooks |
| **TickLet** | `@every(interval, unit)` periodic execution |
| **GitLet** | Repo-as-policy: behavior versioned as git commits |
| **CodeLet** | In-memory function table, hot-swappable |
| **LogLet** | Separate log stream from transmit stream |
| **MulLet** | Fan-out N children with map/reduce |
| **ProgLet** | Unified program table with pluggable executors |
| **SuppressLet** | Output gating |
| **WebLet** | CogWeb UI registration |

### Agent Lightning: Pluggable Components

Each architectural layer is swappable:

| Extension Point | Options |
|----------------|---------|
| **Store backend** | InMemoryLightningStore, SqliteLightningStore, MongoDB |
| **Tracer** | AgentOps (OpenTelemetry), Weave, LLMProxy |
| **Algorithm** | LightningRL (GRPO/PPO), Prompt Optimization, SFT, custom |
| **Execution strategy** | SharedMemory (single-process), Client-Server (distributed) |
| **Agent wrapper** | LitAgent subclass or agl.emit_xxx() helpers |

### Key Difference

Coglet mixins extend **what an agent can do** (version code, schedule tasks, manage fleets). Agent Lightning plugins extend **how training works** (different stores, tracers, RL algorithms).

---

## 6. Tracing and Observability

### Coglet: CogletTrace

- Lightweight jsonl recorder wrapping `transmit()` and `_dispatch_enact()`
- Records: timestamp, coglet type, operation, target channel, data
- Post-mortem replay via `CogletTrace.load()`
- Primarily a debugging tool, not a training pipeline

### Agent Lightning: Full Tracing Pipeline

- Structured spans (borrowing OpenTelemetry semantics)
- Span types: LLM calls, tool invocations, graph edges, reward emissions, code blocks
- Monotonic sequence IDs for ordering in distributed settings
- Traces are the primary input to the optimization algorithm
- Credit assignment module decomposes task-level rewards to per-step rewards

### Key Difference

Coglet tracing is for **debugging** — understanding what happened. Agent Lightning tracing is for **training** — feeding data into RL algorithms.

---

## 7. Where They Could Complement Each Other

Agent Lightning is explicitly designed to wrap any agent framework. A natural integration would be:

1. **Coglet defines the agent hierarchy** — COG/LET tree with supervision, channels, mixins
2. **Agent Lightning wraps Coglet agents for optimization** — tracers capture LLM calls within Coglets, the Algorithm optimizes prompts or fine-tunes models used by PolicyCoglets

Specific integration points:

| Coglet Component | Agent Lightning Role |
|-----------------|---------------------|
| PolicyCoglet (ProgLet + LLM) | Wrap with LitAgent or agl.emit_xxx() to capture LLM spans |
| `transmit()` / `@listen()` | Could emit spans for reward signals |
| GitLet (repo-as-policy) | Updated prompts/weights from Algorithm committed as git patches |
| CogletTrace (jsonl) | Could feed into LightningStore as spans |
| COG `observe()` | Natural point for reward computation |

---

## 8. Summary Table

| Aspect | Coglet | Agent Lightning |
|--------|--------|-----------------|
| **Purpose** | Agent runtime & orchestration | Agent optimization & training |
| **Architecture** | Recursive supervision tree | Flat runner-store-algorithm pipeline |
| **Agent model** | Define agents as Coglet subclasses | Wrap agents from any framework |
| **Communication** | Async channels (data + control planes) | Structured spans via tracers |
| **Hierarchy** | Deep: COG/LET recursion | Shallow: Algorithm → Runners |
| **Fault tolerance** | Restart policies, on_child_error | Rollout retry/cancellation |
| **Extensibility** | Class mixins (GitLet, TickLet, etc.) | Pluggable stores, tracers, algorithms |
| **Tracing** | Debug-oriented jsonl recorder | Training-oriented span pipeline |
| **Optimization** | Manual (COG adjusts LET via guide) | Automated (RL, prompt opt, SFT) |
| **Deployment** | Location-agnostic channels | SharedMemory or Client-Server |
| **Language** | Python | Python 81.8%, TypeScript 15.6% |
| **License** | — | MIT |
| **Maturity** | Active development | v0.3.0 (Dec 2025), 16k+ GitHub stars |

---

## 9. Architectural Takeaways for Coglet

Ideas from Agent Lightning that could inform Coglet's evolution:

1. **Structured span format**: Coglet's jsonl trace could adopt a richer span model (with span types, parent-child relationships, and monotonic sequence IDs) to support both debugging and potential optimization pipelines.

2. **Reward-aware tracing**: Adding reward signals to the trace stream would enable automated feedback loops, where a COG could use algorithmic optimization (not just hand-coded logic) to improve its LETs.

3. **Resource versioning in the store**: Agent Lightning's immutable resource snapshots (prompt templates, model weights) with a "latest" pointer is a clean pattern that could complement GitLet's commit-based versioning.

4. **Execution strategies**: Agent Lightning's SharedMemory vs. Client-Server execution modes are a useful pattern for Coglet's location-agnostic channels — making the deployment topology an explicit, configurable strategy.

5. **Credit assignment**: Agent Lightning's hierarchical RL with per-step credit assignment could be valuable for Coglet's COG/LET hierarchy, where a COG needs to determine which LET actions contributed to outcomes.
