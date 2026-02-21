import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

sys.path.insert(0, str(Path(__file__).parent.parent))
from mcp2_orchestrator.settings import settings


class Mcp1Client:
    """Thin async wrapper around the MCP 1 subprocess."""

    def __init__(self):
        self._server_params = StdioServerParameters(
            command="python",
            args=[settings.mcp1_server_path],
        )

    async def search(self, query: str, top_k: int = 3) -> list[dict]:
        async with stdio_client(self._server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "search", {"query": query, "top_k": top_k}
                )
                return json.loads(result.content[0].text)

    async def list_documents(self) -> list[dict]:
        async with stdio_client(self._server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("list_documents", {})
                return json.loads(result.content[0].text)
