import json

from proxy.translators import translate_request, translate_response, needs_translation
from proxy.translators.anthropic import (
    translate_request as anthropic_req,
    translate_response as anthropic_resp,
    translate_stream_chunk as anthropic_stream,
)
from proxy.translators.gemini import (
    translate_request as gemini_req,
    translate_response as gemini_resp,
    translate_stream_chunk as gemini_stream,
)


class TestNeedsTranslation:
    def test_anthropic_needs_translation(self):
        assert needs_translation("anthropic")

    def test_google_needs_translation(self):
        assert needs_translation("google")

    def test_openai_no_translation(self):
        assert not needs_translation("openai")

    def test_ollama_no_translation(self):
        assert not needs_translation("ollama")


class TestAnthropicRequest:
    def test_system_message_extracted(self):
        body = {
            "model": "claude-3-opus",
            "messages": [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hi"},
            ],
        }
        result, headers, path = anthropic_req(body, {"authorization": "Bearer sk-test"}, "v1/chat/completions")
        assert result["system"] == "You are helpful"
        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "user"

    def test_path_changed(self):
        body = {"model": "claude-3", "messages": [{"role": "user", "content": "hi"}]}
        _, _, path = anthropic_req(body, {"authorization": "Bearer sk-test"}, "v1/chat/completions")
        assert path == "v1/messages"

    def test_auth_header_translated(self):
        body = {"model": "claude-3", "messages": [{"role": "user", "content": "hi"}]}
        _, headers, _ = anthropic_req(body, {"authorization": "Bearer sk-ant-123"}, "v1/chat/completions")
        assert headers["x-api-key"] == "sk-ant-123"
        assert headers["anthropic-version"] == "2023-06-01"
        assert "authorization" not in headers

    def test_max_tokens_defaulted(self):
        body = {"model": "claude-3", "messages": [{"role": "user", "content": "hi"}]}
        result, _, _ = anthropic_req(body, {}, "")
        assert result["max_tokens"] == 4096

    def test_tools_translated(self):
        body = {
            "model": "claude-3",
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{"type": "function", "function": {"name": "get_weather", "description": "Get weather", "parameters": {"type": "object"}}}],
        }
        result, _, _ = anthropic_req(body, {}, "")
        assert result["tools"][0]["name"] == "get_weather"
        assert "input_schema" in result["tools"][0]


class TestAnthropicResponse:
    def test_basic_response(self):
        body = {
            "id": "msg_123",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello!"}],
            "model": "claude-3-opus",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        result = anthropic_resp(body)
        assert result["choices"][0]["message"]["content"] == "Hello!"
        assert result["choices"][0]["finish_reason"] == "stop"
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 5
        assert result["usage"]["total_tokens"] == 15


class TestAnthropicStreaming:
    def test_content_block_delta(self):
        chunk = b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n'
        result = anthropic_stream(chunk)
        assert b"Hello" in result
        assert b"chat.completion.chunk" in result

    def test_message_stop(self):
        chunk = b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
        result = anthropic_stream(chunk)
        assert b"[DONE]" in result


class TestGeminiRequest:
    def test_messages_to_contents(self):
        body = {
            "model": "gemini-pro",
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
                {"role": "user", "content": "How are you?"},
            ],
        }
        result, _, _ = gemini_req(body, {"authorization": "Bearer key123"}, "v1/chat/completions")
        assert len(result["contents"]) == 3
        assert result["contents"][0]["role"] == "user"
        assert result["contents"][0]["parts"][0]["text"] == "Hi"
        assert result["contents"][1]["role"] == "model"  # assistant → model

    def test_system_prepended_to_first_user(self):
        body = {
            "model": "gemini-pro",
            "messages": [
                {"role": "system", "content": "Be helpful"},
                {"role": "user", "content": "Hi"},
            ],
        }
        result, _, _ = gemini_req(body, {}, "")
        assert len(result["contents"]) == 1  # system not in contents
        assert "Be helpful" in result["contents"][0]["parts"][0]["text"]
        assert "Hi" in result["contents"][0]["parts"][0]["text"]

    def test_path_translated(self):
        body = {"model": "gemini-pro", "messages": [{"role": "user", "content": "hi"}]}
        _, _, path = gemini_req(body, {"authorization": "Bearer key123"}, "v1/chat/completions")
        assert "v1/models/gemini-pro:generateContent" in path
        assert "key=key123" in path

    def test_streaming_path(self):
        body = {"model": "gemini-pro", "messages": [{"role": "user", "content": "hi"}]}
        _, _, path = gemini_req(body, {"authorization": "Bearer key123"}, "", is_streaming=True)
        assert "streamGenerateContent" in path

    def test_generation_config(self):
        body = {
            "model": "gemini-pro",
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.7,
            "top_p": 0.9,
            "max_tokens": 500,
        }
        result, _, _ = gemini_req(body, {}, "")
        assert result["generationConfig"]["temperature"] == 0.7
        assert result["generationConfig"]["topP"] == 0.9
        assert result["generationConfig"]["maxOutputTokens"] == 500


class TestGeminiResponse:
    def test_basic_response(self):
        body = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Hello!"}], "role": "model"},
                    "finishReason": "STOP",
                    "index": 0,
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 5,
                "totalTokenCount": 15,
            },
        }
        result = gemini_resp(body)
        assert result["choices"][0]["message"]["content"] == "Hello!"
        assert result["choices"][0]["finish_reason"] == "stop"
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 5


class TestPassthrough:
    def test_openai_no_translation(self):
        body = {"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]}
        result, headers, path = translate_request(body, {"auth": "x"}, "v1/chat/completions", "openai")
        assert result == body
        assert path == "v1/chat/completions"

    def test_ollama_no_translation(self):
        body = {"model": "llama3", "messages": [{"role": "user", "content": "hi"}]}
        result, _, _ = translate_request(body, {}, "v1/chat/completions", "ollama")
        assert result == body

    def test_response_passthrough(self):
        resp = {"choices": [{"message": {"content": "hi"}}]}
        assert translate_response(resp, "openai") == resp
