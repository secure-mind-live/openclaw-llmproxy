"""Translate between OpenAI chat completion format and Anthropic Messages API."""

import json
import time


def translate_request(body: dict, headers: dict, path: str) -> tuple[dict, dict, str]:
    """Convert OpenAI request → Anthropic Messages API request."""
    messages = body.get("messages", [])

    # Extract system messages
    system_parts = []
    non_system_messages = []
    for msg in messages:
        if msg.get("role") == "system":
            system_parts.append(msg.get("content", ""))
        else:
            non_system_messages.append({"role": msg["role"], "content": msg.get("content", "")})

    translated = {
        "model": body.get("model", ""),
        "messages": non_system_messages,
        "max_tokens": body.get("max_tokens", 4096),
    }

    if system_parts:
        translated["system"] = "\n".join(system_parts)

    # Optional fields
    if "temperature" in body:
        translated["temperature"] = body["temperature"]
    if "top_p" in body:
        translated["top_p"] = body["top_p"]
    if "stream" in body:
        translated["stream"] = body["stream"]
    if "stop" in body:
        translated["stop_sequences"] = body["stop"] if isinstance(body["stop"], list) else [body["stop"]]

    # Tool translation
    if "tools" in body:
        translated["tools"] = []
        for tool in body["tools"]:
            if tool.get("type") == "function":
                func = tool["function"]
                translated["tools"].append({
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {}),
                })

    # Header translation
    new_headers = dict(headers)
    auth = new_headers.pop("authorization", "")
    api_key = auth.replace("Bearer ", "") if auth.startswith("Bearer ") else auth
    new_headers["x-api-key"] = api_key
    new_headers["anthropic-version"] = "2023-06-01"
    new_headers["content-type"] = "application/json"

    return translated, new_headers, "v1/messages"


def translate_response(body: dict) -> dict:
    """Convert Anthropic Messages API response → OpenAI format."""
    # Extract text content
    content = ""
    content_blocks = body.get("content", [])
    for block in content_blocks:
        if block.get("type") == "text":
            content += block.get("text", "")

    # Map stop reason
    stop_reason = body.get("stop_reason", "")
    finish_reason_map = {
        "end_turn": "stop",
        "max_tokens": "length",
        "stop_sequence": "stop",
        "tool_use": "tool_calls",
    }
    finish_reason = finish_reason_map.get(stop_reason, "stop")

    # Token usage
    usage = body.get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)

    return {
        "id": body.get("id", f"chatcmpl-{int(time.time())}"),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", ""),
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


def translate_stream_chunk(chunk_bytes: bytes) -> bytes:
    """Convert Anthropic SSE chunk → OpenAI SSE chunk."""
    output_lines = []

    for line in chunk_bytes.decode("utf-8", errors="replace").split("\n"):
        line = line.strip()
        if not line:
            continue

        # Skip event: lines, only process data: lines
        if line.startswith("event:"):
            continue

        if not line.startswith("data:"):
            continue

        data_str = line[len("data:"):].strip()
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        event_type = data.get("type", "")

        if event_type == "content_block_delta":
            delta = data.get("delta", {})
            text = delta.get("text", "")
            if text:
                chunk = {
                    "id": f"chatcmpl-{int(time.time())}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": text},
                            "finish_reason": None,
                        }
                    ],
                }
                output_lines.append(f"data: {json.dumps(chunk)}\n\n")

        elif event_type == "message_start":
            msg = data.get("message", {})
            chunk = {
                "id": msg.get("id", f"chatcmpl-{int(time.time())}"),
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": msg.get("model", ""),
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant"},
                        "finish_reason": None,
                    }
                ],
            }
            output_lines.append(f"data: {json.dumps(chunk)}\n\n")

        elif event_type == "message_stop":
            output_lines.append("data: [DONE]\n\n")

        elif event_type == "message_delta":
            delta = data.get("delta", {})
            stop_reason = delta.get("stop_reason", "")
            if stop_reason:
                finish_reason_map = {"end_turn": "stop", "max_tokens": "length", "stop_sequence": "stop"}
                chunk = {
                    "id": f"chatcmpl-{int(time.time())}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": finish_reason_map.get(stop_reason, "stop"),
                        }
                    ],
                }
                output_lines.append(f"data: {json.dumps(chunk)}\n\n")

    return "".join(output_lines).encode("utf-8") if output_lines else b""
