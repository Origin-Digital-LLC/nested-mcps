import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import FastAPI, Request
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool
from openai import AsyncAzureOpenAI

sys.path.insert(0, str(Path(__file__).parent.parent))
from mcp1_vectorstore.settings import settings

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

mcp_app = Server("mcp1-vectorstore")
sse_transport = SseServerTransport("/messages/")

# Populated at startup
_doc_matrix: np.ndarray | None = None
_client: AsyncAzureOpenAI | None = None


async def embed(texts: list[str]) -> np.ndarray:
    response = await _client.embeddings.create(
        input=texts,
        model=settings.azure_embedding_deployment,
    )
    vectors = [item.embedding for item in response.data]
    return np.array(vectors, dtype=np.float32)


@mcp_app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search",
            description="Semantic search over Acme Robotics documents.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return",
                        "default": 3,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="list_documents",
            description="Return all Acme Robotics documents with their IDs.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@mcp_app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "list_documents":
        results = [
            {"doc_id": i, "content": doc} for i, doc in enumerate(DOCUMENTS)
        ]
        return [TextContent(type="text", text=json.dumps(results))]

    if name == "search":
        query = arguments["query"]
        top_k = int(arguments.get("top_k", 3))

        query_vec = (await embed([query]))[0]
        norms = np.linalg.norm(_doc_matrix, axis=1)
        scores = np.dot(_doc_matrix, query_vec) / (
            norms * np.linalg.norm(query_vec) + 1e-10
        )
        top_indices = np.argsort(scores)[::-1][:top_k]
        results = [
            {
                "doc_id": int(idx),
                "content": DOCUMENTS[idx],
                "score": float(scores[idx]),
            }
            for idx in top_indices
        ]
        return [TextContent(type="text", text=json.dumps(results))]

    raise ValueError(f"Unknown tool: {name}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _doc_matrix, _client
    _client = AsyncAzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )
    _doc_matrix = await embed(DOCUMENTS)
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/sse")
async def handle_sse(request: Request):
    async with sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp_app.run(
            streams[0], streams[1], mcp_app.create_initialization_options()
        )


async def _messages_app(scope, receive, send):
    await sse_transport.handle_post_message(scope, receive, send)


app.mount("/messages", _messages_app)
