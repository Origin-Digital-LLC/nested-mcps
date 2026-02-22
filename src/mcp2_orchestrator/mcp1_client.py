import json
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.types import TextContent

sys.path.insert(0, str(Path(__file__).parent.parent))
from mcp2_orchestrator.settings import settings


class Mcp1Client:
    """Thin async wrapper around the MCP 1 HTTP/SSE server."""

    def __init__(self):
        self._mcp1_url = settings.mcp1_url

    async def search(self, query: str, top_k: int = 3) -> list[dict]:
        async with sse_client(f"{self._mcp1_url}/sse") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "search", {"query": query, "top_k": top_k}
                )
                content = result.content[0]
                if not isinstance(content, TextContent):
                    raise RuntimeError(
                        f"Expected TextContent from search, got {type(content)}"
                    )
                return json.loads(content.text)

    async def list_documents(self) -> list[dict]:
        async with sse_client(f"{self._mcp1_url}/sse") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("list_documents", {})
                content = result.content[0]
                if not isinstance(content, TextContent):
                    raise RuntimeError(
                        f"Expected TextContent from list_documents, got {type(content)}"
                    )
                return json.loads(content.text)
