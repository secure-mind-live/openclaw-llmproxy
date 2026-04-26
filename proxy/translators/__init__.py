"""API format translation layer.

Translates between OpenAI chat completion format (the proxy's lingua franca)
and native formats for Anthropic, Google Gemini, etc.

Backends that are already OpenAI-compatible (openai, ollama, vllm, openclaw)
pass through unchanged.
"""

from proxy.translators.anthropic import (
    translate_request as _anthropic_request,
    translate_response as _anthropic_response,
    translate_stream_chunk as _anthropic_stream_chunk,
)
from proxy.translators.gemini import (
    translate_request as _gemini_request,
    translate_response as _gemini_response,
    translate_stream_chunk as _gemini_stream_chunk,
)

TRANSLATABLE_BACKENDS = {"anthropic", "google"}


def needs_translation(backend_name: str) -> bool:
    return backend_name in TRANSLATABLE_BACKENDS


def translate_request(body: dict | None, headers: dict, path: str,
                      backend_name: str, is_streaming: bool = False) -> tuple[dict | None, dict, str]:
    """Translate OpenAI-format request to target backend format.

    Returns (translated_body, translated_headers, translated_path).
    """
    if not body or backend_name not in TRANSLATABLE_BACKENDS:
        return body, headers, path

    if backend_name == "anthropic":
        return _anthropic_request(body, headers, path)
    if backend_name == "google":
        return _gemini_request(body, headers, path, is_streaming)

    return body, headers, path


def translate_response(response_body: dict | None, backend_name: str) -> dict | None:
    """Translate backend response back to OpenAI format."""
    if not response_body or backend_name not in TRANSLATABLE_BACKENDS:
        return response_body

    if backend_name == "anthropic":
        return _anthropic_response(response_body)
    if backend_name == "google":
        return _gemini_response(response_body)

    return response_body


def translate_stream_chunk(chunk_bytes: bytes, backend_name: str) -> bytes:
    """Translate a streaming chunk to OpenAI SSE format."""
    if backend_name not in TRANSLATABLE_BACKENDS:
        return chunk_bytes

    if backend_name == "anthropic":
        return _anthropic_stream_chunk(chunk_bytes)
    if backend_name == "google":
        return _gemini_stream_chunk(chunk_bytes)

    return chunk_bytes
