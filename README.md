# acme-mcp

A two-layer nested MCP (Model Context Protocol) system demonstrating MCP composition — a server that is simultaneously a client to another MCP server.

## Architecture

```
Claude Desktop
     │  (stdio)
     ▼
MCP 2: Orchestrator        ← exposed externally
     │  spawns subprocess
     │  (stdio)
     ▼
MCP 1: Vector Store        ← internal implementation detail
```

**MCP 1 (`mcp1_vectorstore`)** is a low-level in-memory vector store. On startup it embeds 10 Acme Robotics documents via Azure OpenAI, then serves semantic search using numpy cosine similarity. It is never registered with Claude Desktop directly.

**MCP 2 (`mcp2_orchestrator`)** is what Claude Desktop connects to. It exposes a single `ask` tool. When invoked, it runs an agentic reasoning loop using GPT-4.1 via Azure AI Foundry: it decomposes the question into tasks, executes retrieval against MCP 1, and synthesizes a final answer. Independent tasks are dispatched in parallel via `asyncio.gather`.

## Project Structure

```
src/
├── mcp1_vectorstore/
│   ├── settings.py       # pydantic-settings: endpoint, api_key, embedding deployment
│   └── server.py         # MCP server: search + list_documents tools
└── mcp2_orchestrator/
    ├── settings.py       # pydantic-settings: endpoint, api_key, chat deployment, mcp1 path
    ├── mcp1_client.py    # Subprocess MCP client wrapping MCP 1
    ├── agent.py          # Agentic loop: scratchpad, task planning, parallel search dispatch
    └── server.py         # MCP server: exposes the ask tool to Claude Desktop
```

Each server has its own `settings.py` with only the fields it actually uses — MCP 1 owns the embedding deployment, MCP 2 owns the chat deployment and the path to MCP 1.

## Setup

### 1. Install dependencies

```bash
uv sync
```

### 2. Configure environment

```bash
cp .env.example .env
```

`MCP1_SERVER_PATH` must be an absolute path — MCP 2 uses it to spawn MCP 1 as a subprocess.

### 3. Register with Claude Desktop

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

MCP 1 is **not** registered here — it is spawned internally by MCP 2.

## Tools

### MCP 1 tools (internal)

| Tool             | Input                          | Output                       |
| ---------------- | ------------------------------ | ---------------------------- |
| `search`         | `query: str`, `top_k: int = 3` | `[{doc_id, content, score}]` |
| `list_documents` | —                              | `[{doc_id, content}]`        |

### MCP 2 tool (exposed to Claude Desktop)

| Tool  | Input           | Output                    |
| ----- | --------------- | ------------------------- |
| `ask` | `question: str` | synthesized answer string |

## Agentic Loop

The agent in `agent.py` maintains a per-request scratchpad:

```python
{
  "question": str,
  "tasks": [{"id", "description", "status", "depends_on", "result"}],
  "final_answer": str | None
}
```

The LLM drives the loop using four internal tools: `add_task`, `complete_task`, `search_knowledge`, and `finish`. Tasks with satisfied dependencies are dispatched concurrently. The loop is hard-capped at 10 iterations.

## Test Questions

These questions require multi-hop retrieval over the Acme Robotics knowledge base. The answers are not in any LLM's training data.

**Sequential (two-hop):**

> "Who developed the navigation algorithm used in Acme's flagship product, and what is their academic background?"

**Parallel + synthesis:**

> "Compare Acme's market position: how large is their biggest customer relationship, and how do they stack up against their main competitor?"

**Multi-hop stretch:**

> "What is Acme's growth strategy, and does their current funding support it?"
