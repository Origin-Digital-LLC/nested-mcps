# acme-mcp: Nested MCP System — Implementation Plan

## Context & Background

### What We're Building
A two-layer nested MCP (Model Context Protocol) system:

- **MCP 1** (`mcp1_vectorstore`): A low-level MCP server that acts as an in-memory vector store. It embeds documents using an Azure OpenAI embedding model and serves semantic search via numpy cosine similarity.
- **MCP 2** (`mcp2_orchestrator`): A high-level MCP server exposed to Claude Desktop. It runs an agentic loop using GPT-4.1 via Azure AI Foundry. It receives a question, decomposes it into tasks (with parallel/sequential dependencies), executes them using MCP 1 as its retrieval backend, and returns a synthesized final answer.

External systems (e.g., Claude Desktop) connect only to MCP 2. MCP 2 spawns MCP 1 as a subprocess and connects to it as an internal MCP client. MCP 1 is an implementation detail — never exposed directly.

### Why This Architecture
- Decouples retrieval (MCP 1) from orchestration (MCP 2). Swapping the vector store doesn't touch agent logic.
- Demonstrates MCP composition: a server that is simultaneously a client to another MCP server.
- Both servers communicate via **stdio** (JSON-RPC 2.0 over stdin/stdout), which is the standard local MCP transport.

### Protocol Basics
MCP is built on JSON-RPC 2.0. The client/server handshake:
1. Client sends `initialize`
2. Server responds with capabilities (tools, resources, prompts it exposes)
3. Client calls tools via `tools/call`

Tools are defined with a name, description, and JSON Schema for inputs. The LLM uses the schema to know how to invoke them.

### Transport
Both servers use **stdio**. MCP 2 spawns MCP 1 as a subprocess via the MCP Python SDK's subprocess client. Claude Desktop spawns MCP 2 the same way.

---

## Tech Stack

- **Package manager**: `uv`
- **MCP SDK**: `mcp` (official Anthropic Python SDK)
- **Embeddings + Chat**: Azure OpenAI via `openai` SDK (pointed at Azure AI Foundry endpoint)
- **Vector math**: `numpy` (cosine similarity — FAISS is overkill for 10 documents)
- **Config**: `pydantic-settings` reading from `.env`
- **Python**: 3.11+

---

## Project Structure

```
acme-mcp/
├── pyproject.toml
├── .env                          # Real credentials (gitignored)
├── .env.example                  # Placeholder template
├── README.md
└── src/
    ├── mcp1_vectorstore/
    │   ├── __init__.py
    │   └── server.py
    └── mcp2_orchestrator/
        ├── __init__.py
        ├── server.py
        ├── agent.py
        └── mcp1_client.py
```

---

## Environment Variables (`.env`)

Managed via `pydantic-settings`. All Azure resources are assumed to be in the same Azure AI Foundry project.

```env
AZURE_OPENAI_ENDPOINT=https://your-foundry-endpoint.openai.azure.com/
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_API_VERSION=2025-01-01-preview
AZURE_CHAT_DEPLOYMENT=gpt-4.1
AZURE_EMBEDDING_DEPLOYMENT=text-embedding-3-small

# Absolute path to MCP 1 server script (used by MCP 2 to spawn subprocess)
MCP1_SERVER_PATH=/absolute/path/to/src/mcp1_vectorstore/server.py
```

Create a `Settings` class in a shared `config.py` (or inline per server) using `pydantic-settings` `BaseSettings`. It should read from `.env` automatically.

---

## pyproject.toml

Single `uv` project with two entry points:

```toml
[project]
name = "acme-mcp"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "mcp",
    "openai",
    "numpy",
    "pydantic-settings",
]

[project.scripts]
mcp1 = "mcp1_vectorstore.server:main"
mcp2 = "mcp2_orchestrator.server:main"
```

---

## MCP 1: Vector Store Server (`src/mcp1_vectorstore/server.py`)

### Responsibilities
- On startup: embed all 10 Acme Robotics documents using the Azure embedding endpoint. Store as a numpy array (shape: `[10, embedding_dim]`).
- Expose two tools to MCP clients.

### Tools

**`search`**
- Input: `query: str`, `top_k: int` (default 3)
- Behavior: Embed the query via Azure OpenAI, compute cosine similarity against the document matrix, return top-k results.
- Output: List of `{ "content": str, "score": float, "doc_id": int }`

**`list_documents`**
- Input: none
- Behavior: Return all document contents with their IDs.
- Output: List of `{ "doc_id": int, "content": str }`

### Document Data (hardcoded in server.py)

10 documents about a fictional company **Acme Robotics**. This data is entirely fabricated — no LLM has been trained on it, so any correct answers must come from retrieval.

```python
DOCUMENTS = [
    "Acme Robotics was founded in 2019 by CEO Dana Holt, formerly a principal engineer at Boston Dynamics.",
    "The company's flagship product is the AX-7, a warehouse navigation robot that uses lidar and a proprietary pathfinding algorithm called GridMind.",
    "GridMind was developed by Dr. Yusuf Okafor, Acme's Head of AI, who joined from CMU's robotics lab in 2021.",
    "Acme closed a $42M Series B in March 2024 led by Horizon Ventures. The round included participation from Ford's strategic investment arm.",
    "The AX-7 is deployed in 14 fulfillment centers across the Midwest, including three operated by a logistics firm called GreatLakes Distribution.",
    "Acme's main competitor is Fulcrum Robotics, which makes the R-Series robots and has 3x the revenue but older sensor tech.",
    "Dana Holt's long-term vision is to expand into hospital logistics by 2027, targeting medication delivery and sterile supply chain.",
    "Acme employs 87 people as of Q1 2025. Engineering is 60% of headcount. The office is in Ann Arbor, Michigan.",
    "The AX-7 has a list price of $85,000 per unit. GreatLakes Distribution operates 23 units and is Acme's largest single customer.",
    "Acme is in early talks with a European distributor, Munich-based RoboLogistik GmbH, to expand into the EU market in 2026.",
]
```

### Implementation Notes
- Use `AsyncOpenAI` with `azure_endpoint` and `api_key` from settings.
- Embed all documents at startup inside `main()` before starting the server.
- Cosine similarity: `np.dot(query_vec, doc_matrix.T) / (norm(query_vec) * norm(doc_matrix, axis=1))`.
- Use `mcp.server.Server` and `stdio_server` from the MCP SDK (same pattern as standard MCP Python quickstart).

---

## MCP 2: Orchestrator Server (`src/mcp2_orchestrator/`)

### `mcp1_client.py` — MCP 1 Client Wrapper

Wraps the MCP Python SDK's subprocess client. On init, spawns MCP 1 as a subprocess using the path from settings. Exposes two async methods:

- `async search(query: str, top_k: int) -> list[dict]`
- `async list_documents() -> list[dict]`

These are thin wrappers that call the MCP client's `call_tool()` and parse the response. This class is instantiated once and shared across the agent loop.

### `agent.py` — Agentic Loop

This is the core logic. It is **not** an MCP server itself — it's a Python class invoked by the MCP 2 server when the `ask` tool is called.

#### Scratchpad / Task List

Maintain an in-memory dict per run:

```python
scratchpad = {
    "question": str,
    "tasks": [
        {
            "id": int,
            "description": str,
            "status": "pending" | "running" | "complete" | "blocked",
            "depends_on": list[int],   # task IDs this task waits for
            "result": str | None,
        }
    ],
    "final_answer": str | None,
}
```

The LLM sees the current scratchpad state serialized as JSON in the system prompt on every iteration.

#### Tools Available to the Agent (internal, not MCP-exposed)

Define these as OpenAI function-calling tool schemas passed to the chat completion:

- **`search_knowledge`**: `{ query: str, top_k?: int }` — calls MCP 1 via `mcp1_client.search()`
- **`add_task`**: `{ description: str, depends_on: list[int] }` — adds a new task to scratchpad
- **`complete_task`**: `{ task_id: int, result: str }` — marks task done, stores result
- **`finish`**: `{ answer: str }` — stores final answer, terminates loop

#### Loop Logic

```
while iterations < MAX_ITERATIONS:
    1. Find all tasks where status == "pending" and all depends_on are "complete"
    2. If multiple are runnable with no interdependencies → dispatch in parallel via asyncio.gather
    3. Build messages: system prompt (with scratchpad JSON) + conversation history
    4. Call Azure OpenAI chat completion with tool schemas
    5. Process tool calls:
        - search_knowledge → call MCP 1, store result in conversation
        - add_task / complete_task → update scratchpad
        - finish → set final_answer, break loop
    6. If no tool call and no finish → LLM gave a plain response, treat as implicit finish
```

**Parallel dispatch**: When step 1 finds multiple runnable tasks, dispatch `search_knowledge` calls for all of them concurrently using `asyncio.gather`, then feed all results back before the next LLM call.

**System prompt** should instruct the model to:
- Always consult the scratchpad before deciding what to do next
- Break complex questions into tasks before searching
- Use `depends_on` when a search requires the result of a prior search
- Call `finish` only when all tasks needed to answer the question are complete
- Never answer from prior knowledge — always use `search_knowledge`

#### MAX_ITERATIONS
Hard cap at 10 loop iterations. If hit, return whatever partial answer exists with a warning.

### `server.py` — MCP 2 Server

Exposes one tool to Claude Desktop:

**`ask`**
- Input: `question: str`
- Behavior: Instantiates `Mcp1Client`, instantiates `Agent`, calls `agent.run(question)`, returns final answer string.
- Output: The synthesized answer as `TextContent`.

Uses `mcp.server.Server` + `stdio_server`. Settings loaded via `pydantic-settings`.

---

## Claude Desktop Registration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "acme-orchestrator": {
      "command": "uv",
      "args": ["run", "python", "src/mcp2_orchestrator/server.py"],
      "cwd": "/absolute/path/to/acme-mcp"
    }
  }
}
```

MCP 1 is **not** registered here. It is spawned as a subprocess by MCP 2 internally.

---

## Test Questions

Use these to validate the system with Claude Desktop. The LLM cannot know these answers from training data.

### Q1 — Sequential (two-hop)
> "Who developed the navigation algorithm used in Acme's flagship product, and what is their academic background?"

Expected path:
1. Search for flagship product → finds AX-7 and GridMind (docs 1, 2)
2. Search for GridMind developer → finds Dr. Yusuf Okafor, CMU background (doc 3)
Task 2 depends on Task 1.

### Q2 — Parallel + synthesis
> "Compare Acme's market position: how large is their biggest customer relationship, and how do they stack up against their main competitor?"

Expected path:
1. Search largest customer (GreatLakes, 23 units, doc 9) — independent
2. Search competitor (Fulcrum Robotics, doc 6) — independent
Both tasks run in parallel, then synthesized.

### Q3 — Multi-hop stretch
> "What is Acme's growth strategy, and does their current funding support it?"

Expected path:
1. Search growth strategy → hospital logistics + EU expansion (docs 7, 10)
2. Search funding → $42M Series B (doc 4)
Can be parallel or sequential depending on agent decomposition.

---

## Implementation Order for Claude Code

1. `pyproject.toml` + `.env.example` + project scaffold
2. Shared settings (`pydantic-settings` config, importable by both servers)
3. `mcp1_vectorstore/server.py` — document data, embedding on startup, numpy search, two MCP tools
4. `mcp2_orchestrator/mcp1_client.py` — subprocess MCP client wrapping MCP 1
5. `mcp2_orchestrator/agent.py` — scratchpad dataclass, tool schemas, agentic loop with parallel dispatch
6. `mcp2_orchestrator/server.py` — MCP server exposing `ask` tool, wires agent + client together
7. Test MCP 1 in isolation (call `list_documents` and `search` directly)
8. Test MCP 2 via Claude Desktop with the three questions above

---

## Key Constraints for Claude Code

- Use `AsyncOpenAI` with `azure_endpoint`, not the default OpenAI endpoint
- MCP SDK pattern: `Server`, `@app.list_tools()`, `@app.call_tool()`, `stdio_server` — follow the official Python MCP quickstart structure
- All async — both servers and the agent loop use `asyncio`
- Do not use `sentence-transformers` or FAISS — embeddings come from Azure, vector math is numpy only
- `pydantic-settings` `BaseSettings` must be the sole source of configuration — no hardcoded credentials anywhere
- The scratchpad is per-request in-memory state only, not persisted
