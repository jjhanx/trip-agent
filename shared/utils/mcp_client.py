"""MCP client wrapper for agents to call MCP server tools."""

from typing import Any

import httpx


class MCPClient:
    """HTTP-based MCP client for calling MCP server tools (Streamable HTTP transport)."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke an MCP tool and return the result.

        Uses MCP tools/call JSON-RPC over HTTP.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # MCP Streamable HTTP: POST to /mcp or similar with tools/call
            url = f"{self.base_url}/mcp" if "/mcp" not in self.base_url else self.base_url
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"MCP tool error: {data['error']}")
            result = data.get("result", {})
            if "content" in result and result["content"]:
                # MCP returns content as list of parts
                first = result["content"][0]
                if isinstance(first, dict) and "text" in first:
                    return {"text": first["text"]}
            return result
