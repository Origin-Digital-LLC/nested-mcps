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
MCP 2: Orchestrator        ← FastAPI/uvicorn, runs on the server
     │  HTTP/SSE (:8001)
     ▼
MCP 1: Vector Store        ← FastAPI/uvicorn, internal only
```

**MCP 1 (`mcp1_vectorstore`)** is a low-level in-memory vector store. On startup it embeds 10 Acme Robotics documents via Azure OpenAI, then serves semantic search using numpy cosine similarity. It runs as a standalone HTTP service and is never exposed to Claude Desktop directly.

**MCP 2 (`mcp2_orchestrator`)** runs an agentic reasoning loop using GPT-4.1 via Azure AI Foundry. It exposes a single `ask` tool via HTTP/SSE, decomposes questions into tasks, retrieves against MCP 1 over HTTP, and synthesizes a final answer. Independent tasks are dispatched in parallel via `asyncio.gather`.

**The proxy** (`extension/server/proxy.py`) is a thin stdio↔HTTP bridge. Claude Desktop spawns it locally; it connects to MCP 2 over the network. This is the only piece that runs on client machines.

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
extension/
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

In two separate terminals:

```bash
make run-mcp1   # vector store on http://0.0.0.0:8001
make run-mcp2   # orchestrator on http://0.0.0.0:8002
```

## Connecting Claude Desktop (local dev)

Run `make claude-config` to print the config block, then paste it into `%APPDATA%\Claude\claude_desktop_config.json` and restart Claude Desktop.

This spawns `proxy.py` via WSL, which connects to MCP 2 over HTTP. Both servers must be running first.

## Enterprise Deployment (claude.ai)

For enterprise claude.ai, no proxy or client-side installation is needed:

1. Deploy MCP 2 on an internal server with a publicly reachable HTTPS URL
2. An org admin adds the URL once: **claude.ai → Settings → Connectors → Add custom connector**
3. Users click to enable it — no URL entry, no configuration

MCP 1 stays internal; only MCP 2 needs to be reachable from Anthropic's servers.

## Distributing via Claude Desktop Extension (.mcpb)

Any Claude Desktop user — not just local dev — needs the proxy to connect to an internal server, since Claude Desktop only speaks stdio. The `.mcpb` packages the proxy and all Python dependencies into a one-click install.

```bash
make pack   # produces acme-orchestrator-proxy.mcpb
```

Before packing, update `MCP2_URL` in `extension/manifest.json` to point at your internal server (e.g. `http://mcp.acme-internal.com:8002`). Distribute the `.mcpb` to users — they double-click it in Windows Explorer and Claude Desktop installs it automatically.

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