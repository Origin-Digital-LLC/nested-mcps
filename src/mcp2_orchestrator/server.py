from fastapi import FastAPI, Request
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool

from mcp2_orchestrator.agent import Agent
from mcp2_orchestrator.mcp1_client import Mcp1Client

mcp_app = Server("mcp2-orchestrator")
sse_transport = SseServerTransport("/messages/")


@mcp_app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="ask",
            description=(
                "Ask a question about Acme Robotics. "
                "The agent will decompose the question, retrieve relevant information "
                "from the knowledge base, and synthesize a final answer."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to answer",
                    }
                },
                "required": ["question"],
            },
        )
    ]


@mcp_app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "ask":
        raise ValueError(f"Unknown tool: {name}")

    question = arguments["question"]
    mcp1 = Mcp1Client()
    agent = Agent(mcp1)
    answer = await agent.run(question)
    return [TextContent(type="text", text=answer)]


app = FastAPI()


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
