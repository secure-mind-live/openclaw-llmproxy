"""OpenClaw LLM Proxy Python SDK.

Usage:
    from sdk import OpenClawClient

    client = OpenClawClient(
        base_url="https://llmproxy.company.com",
        api_key="team-alpha-key-xxx",
    )

    # Chat completion (routed by proxy based on model name)
    response = client.chat("gpt-4", "What is 2+2?")
    print(response.content)

    # Streaming
    for chunk in client.stream("llama3.2:1b", "Count to 5"):
        print(chunk, end="", flush=True)

    # Works with OpenAI SDK too:
    from openai import OpenAI
    openai_client = client.as_openai()
    resp = openai_client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": "Hello"}],
    )
"""

from sdk.client import OpenClawClient

__all__ = ["OpenClawClient"]
