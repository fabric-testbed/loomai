"""Only genuine 'this model cannot take tools' errors may disable tool calling."""
import pytest

from app.routes.ai_chat import _error_says_tools_unsupported


@pytest.mark.parametrize("text", [
    "This model does not support function calling",
    "tools is not supported with this model",
    "Unsupported parameter: 'tools' is not supported with this model.",
    "Invalid parameter: tool_choice",
    "function calling is not available for this model",
    '"auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser',
    "unknown parameter: tools",
])
def test_unsupported_phrases_disable_tools(text):
    assert _error_says_tools_unsupported(text)


@pytest.mark.parametrize("text", [
    # OpenAI-style sequencing error after a bad trim: fix the conversation, not the model.
    "Invalid parameter: messages with role 'tool' must be a response to a preceeding message with 'tool_calls'.",
    "tool message must follow a tool_calls message",
    "No tool call found for tool_call_id call_123",
    # Unrelated errors that merely contain the word.
    "rate limit exceeded while executing tool",
    "context length exceeded: 9000 tokens of tools + messages",
    "",
])
def test_other_errors_do_not_disable_tools(text):
    assert not _error_says_tools_unsupported(text)
