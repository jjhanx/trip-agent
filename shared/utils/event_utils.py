"""A2A event utilities compatible with a2a-sdk 0.3.x."""

import uuid

from a2a.types import Message, Part, Role, TextPart


def new_agent_text_message(text: str) -> Message:
    """Create an agent text message for event queue."""
    return Message(
        role=Role.agent,
        parts=[Part(root=TextPart(text=text))],
        message_id=str(uuid.uuid4()),
    )
