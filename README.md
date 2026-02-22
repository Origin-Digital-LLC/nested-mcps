# acme-mcp

A two-layer nested MCP (Model Context Protocol) system demonstrating MCP composition over HTTP/SSE — a server that is simultaneously a client to another MCP server.

## Architecture

```
Claude Desktop
     │  stdio
     ▼
[stdio proxy]              ← spawned by Claude Desktop, bridges stdio ↔ HTTP
     │  HTTP/SSE (:8002)
     ▼
MCP 2: Orchestrator        ← FastAPI/uvicorn, exposed on internal network
     │  HTTP/SSE (:8001)
     ▼
MCP 1: Vector Store        ← FastAPI/uvicorn, internal only
```

**MCP 1 (`mcp1_vectorstore`)** is a low-level in-memory vector store. On startup it embeds 10 Acme Robotics documents via Azure OpenAI, then serves semantic search using numpy cosine similarity. It runs as a standalone HTTP service and is never exposed to Claude Desktop directly.

**MCP 2 (`mcp2_orchestrator`)** runs an agentic reasoning loop using GPT-4.1 via Azure AI Foundry. It exposes a single `ask` tool via HTTP/SSE, decomposes questions into tasks, retrieves against MCP 1 over HTTP, and synthesizes a final answer. Independent tasks are dispatched in parallel via `asyncio.gather`.

**The proxy** (`dxt/server/proxy.py`) is a thin stdio↔HTTP bridge packaged as a Claude Desktop Extension (`.dxt`). Claude Desktop spawns it locally; it connects to MCP 2 over the network. This is the only piece that runs on client machines.

## Project Structure

```
src/
├── mcp1_vectorstore/
│   ├── settings.py       # endpoint, api_key, embedding deployment, port
│   └── server.py         # FastAPI/SSE: search + list_documents tools
└── mcp2_orchestrator/
    ├── settings.py       # endpoint, api_key, chat deployment, mcp1_url
    ├── mcp1_client.py    # HTTP/SSE client wrapping MCP 1
    ├── agent.py          # Agentic loop: scratchpad, task planning, parallel search
    └── server.py         # FastAPI/SSE: exposes the ask tool
dxt/
├── manifest.json         # Claude Desktop Extension manifest
└── server/
    └── proxy.py          # stdio ↔ HTTP/SSE bridge (runs on client machines)
```

## Server Setup

### 1. Install dependencies

```bash
uv sync
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in Azure credentials
```

### 3. Start the servers

In two separate terminals (or `make -j2 run-mcp1 run-mcp2`):

```bash
make run-mcp1   # vector store on http://0.0.0.0:8001
make run-mcp2   # orchestrator on http://0.0.0.0:8002
```

## Claude Desktop Installation (via .dxt)

The `.dxt` file packages the proxy and all Python dependencies into a single installable extension. Build it once; distribute the file.

### Prerequisites (build machine only)

```bash
npm install -g @anthropic-ai/dxt
```

### Build the extension

```bash
make pack-dxt
```

This runs `uv pip install --target dxt/lib mcp httpx anyio` to bundle Python deps, then `dxt pack dxt/` to produce `acme-orchestrator-proxy.dxt`.

### Install on each client machine

1. Copy `acme-orchestrator-proxy.dxt` to the client (email, internal portal, etc.)
2. Double-click it in Windows Explorer — Claude Desktop installs it automatically
3. Restart Claude Desktop

The extension connects to `http://127.0.0.1:8002` by default. To point at an internal server instead, update `MCP2_URL` in `dxt/manifest.json` before running `make pack-dxt`.

## Tools

### MCP 1 tools (internal, HTTP only)

| Tool             | Input                          | Output                       |
| ---------------- | ------------------------------ | ---------------------------- |
| `search`         | `query: str`, `top_k: int = 3` | `[{doc_id, content, score}]` |
| `list_documents` | —                              | `[{doc_id, content}]`        |

### MCP 2 tool (exposed via HTTP/SSE)

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