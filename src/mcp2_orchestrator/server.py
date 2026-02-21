import asyncio
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

sys.path.insert(0, str(Path(__file__).parent.parent))
from mcp2_orchestrator.agent import Agent
from mcp2_orchestrator.mcp1_client import Mcp1Client

app = Server("mcp2-orchestrator")


@app.list_tools()
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


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "ask":
        raise ValueError(f"Unknown tool: {name}")

    question = arguments["question"]
    mcp1 = Mcp1Client()
    agent = Agent(mcp1)
    answer = await agent.run(question)
    return [TextContent(type="text", text=answer)]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
