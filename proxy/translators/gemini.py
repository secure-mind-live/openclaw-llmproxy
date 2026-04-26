"""Translate between OpenAI chat completion format and Google Gemini API."""

import json
import time


def translate_request(body: dict, headers: dict, path: str,
                      is_streaming: bool = False) -> tuple[dict, dict, str]:
    """Convert OpenAI request → Gemini generateContent request."""
    messages = body.get("messages", [])
    model = body.get("model", "gemini-pro")

    # Build contents array
    contents = []
    system_text = ""

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "system":
            system_text += content + "\n"
            continue

        gemini_role = "model" if role == "assistant" else "user"
        contents.append({
            "role": gemini_role,
            "parts": [{"text": content}],
        })

    # Prepend system message to first user message
    if system_text and contents:
        for c in contents:
            if c["role"] == "user":
                c["parts"][0]["text"] = system_text.strip() + "\n\n" + c["parts"][0]["text"]
                break

    translated = {"contents": contents}

    # Generation config
    gen_config = {}
    if "temperature" in body:
        gen_config["temperature"] = body["temperature"]
    if "top_p" in body:
        gen_config["topP"] = body["top_p"]
    if "max_tokens" in body:
        gen_config["maxOutputTokens"] = body["max_tokens"]
    if "stop" in body:
        stops = body["stop"] if isinstance(body["stop"], list) else [body["stop"]]
        gen_config["stopSequences"] = stops
    if gen_config:
        translated["generationConfig"] = gen_config

    # Tool translation
    if "tools" in body:
        func_declarations = []
        for tool in body["tools"]:
            if tool.get("type") == "function":
                func = tool["function"]
                func_declarations.append({
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {}),
                })
        if func_declarations:
            translated["tools"] = [{"functionDeclarations": func_declarations}]

    # Header translation — extract API key for query param
    new_headers = dict(headers)
    auth = new_headers.pop("authorization", "")
    api_key = auth.replace("Bearer ", "") if auth.startswith("Bearer ") else auth
    new_headers["content-type"] = "application/json"
    # Remove auth header — key goes in URL
    new_headers.pop("x-api-key", None)

    # Path translation
    action = "streamGenerateContent" if is_streaming else "generateContent"
    translated_path = f"v1/models/{model}:{action}"
    if api_key:
        translated_path += f"?key={api_key}"

    return translated, new_headers, translated_path


def translate_response(body: dict) -> dict:
    """Convert Gemini generateContent response → OpenAI format."""
    candidates = body.get("candidates", [])
    content = ""
    finish_reason = "stop"

    if candidates:
        candidate = candidates[0]
        parts = candidate.get("content", {}).get("parts", [])
        for part in parts:
            if "text" in part:
                content += part["text"]

        reason_map = {
            "STOP": "stop",
            "MAX_TOKENS": "length",
            "SAFETY": "content_filter",
            "RECITATION": "content_filter",
        }
        finish_reason = reason_map.get(candidate.get("finishReason", "STOP"), "stop")

    # Token usage
    usage_meta = body.get("usageMetadata", {})
    prompt_tokens = usage_meta.get("promptTokenCount", 0)
    completion_tokens = usage_meta.get("candidatesTokenCount", 0)
    total_tokens = usage_meta.get("totalTokenCount", prompt_tokens + completion_tokens)

    return {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("modelVersion", "gemini-pro"),
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
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
    }


def translate_stream_chunk(chunk_bytes: bytes) -> bytes:
    """Convert Gemini streaming chunk → OpenAI SSE chunk.

    Gemini returns newline-delimited JSON or JSON array chunks.
    """
    text = chunk_bytes.decode("utf-8", errors="replace").strip()
    if not text:
        return b""

    # Gemini may wrap in array brackets
    text = text.lstrip("[,").rstrip("],")
    if not text.strip():
        return b""

    output_lines = []
    for segment in text.split("\n"):
        segment = segment.strip().rstrip(",")
        if not segment:
            continue
        try:
            data = json.loads(segment)
        except json.JSONDecodeError:
            continue

        candidates = data.get("candidates", [])
        if not candidates:
            continue

        parts = candidates[0].get("content", {}).get("parts", [])
        for part in parts:
            part_text = part.get("text", "")
            if part_text:
                chunk = {
                    "id": f"chatcmpl-{int(time.time())}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": data.get("modelVersion", "gemini-pro"),
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": part_text},
                            "finish_reason": None,
                        }
                    ],
                }
                output_lines.append(f"data: {json.dumps(chunk)}\n\n")

        finish_reason = candidates[0].get("finishReason")
        if finish_reason == "STOP":
            chunk = {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": data.get("modelVersion", "gemini-pro"),
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }
                ],
            }
            output_lines.append(f"data: {json.dumps(chunk)}\n\n")
            output_lines.append("data: [DONE]\n\n")

    return "".join(output_lines).encode("utf-8") if output_lines else b""
