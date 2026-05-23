"""Message conversion helpers shared by custom pydantic-ai model transports."""

from pydantic_ai.messages import ModelMessage, ModelRequest, SystemPromptPart, UserPromptPart


def flatten_messages(messages: list[ModelMessage]) -> tuple[str, str]:
    """Collapse pydantic-ai messages into system and user prompt strings."""
    system_chunks: list[str] = []
    user_chunks: list[str] = []
    for msg in messages:
        if not isinstance(msg, ModelRequest):
            continue
        if msg.instructions:
            system_chunks.append(msg.instructions)
        for part in msg.parts:
            if isinstance(part, SystemPromptPart):
                system_chunks.append(part.content)
            elif isinstance(part, UserPromptPart) and isinstance(part.content, str):
                user_chunks.append(part.content)
    return '\n\n'.join(system_chunks), '\n\n'.join(user_chunks)
