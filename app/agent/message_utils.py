"""Small message helpers used by the platform-neutral conversation runner."""

from __future__ import annotations

from app.platforms.types import Conversation, MessageSender


def last_non_system(conversation: Conversation):
    """Return the latest non-system message with visible text."""

    for message in reversed(conversation.messages):
        if message.sender != MessageSender.SYSTEM and message.text.strip():
            return message
    return None


def candidate_messages_since_last_reply(conversation: Conversation):
    """Return the current consecutive candidate turn after the latest recruiter reply."""

    pending = []
    for message in reversed(conversation.messages):
        if message.sender == MessageSender.ME:
            break
        if message.sender == MessageSender.CANDIDATE and message.text.strip():
            pending.append(message)
    return list(reversed(pending))


def message_sent(conversation: Conversation, text: str) -> bool:
    """Return whether a normalized outgoing message already appears in history."""

    needle = "".join(text.split())
    return any(
        message.sender == MessageSender.ME and needle and needle in "".join(message.text.split())
        for message in conversation.messages
    )


def append_sent(state: dict[str, object], message: str) -> None:
    """Append a just-sent message to the runner state."""

    sent = state.get("sent_messages")
    if not isinstance(sent, list):
        sent = []
    sent.append(message)
    state["sent_messages"] = sent
