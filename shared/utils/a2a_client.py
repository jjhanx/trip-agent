"""A2A client for agent-to-agent communication."""

import json
import uuid
from typing import Any

import httpx


class A2AClient:
    """Simple HTTP client to call other A2A agents."""

    def __init__(self, base_url: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def send_message(self, text: str) -> str:
        """Send a text message and get the agent's text response.

        Uses message/send JSON-RPC format.
        """
        url = self.base_url
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": text}],
                    "messageId": uuid.uuid4().hex,
                }
            },
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"A2A error: {data['error']}")
            result = data.get("result", {})
            # result.message.parts (중첩) 또는 result.parts (result가 메시지 자체인 경우)
            parts = None
            if "message" in result and "parts" in result["message"]:
                parts = result["message"]["parts"]
            elif "parts" in result:
                parts = result["parts"]
            if parts:
                for part in parts:
                    if "text" in part:
                        return part["text"]
            return json.dumps(result)
