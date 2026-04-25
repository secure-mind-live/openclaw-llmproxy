# OpenClaw LLM Proxy

A lightweight, configurable reverse proxy for routing LLM API requests to multiple backends — OpenAI, Anthropic, Google, vLLM, Ollama, and OpenClaw — through a single endpoint.

Built for [OpenClaw](https://github.com/ParthaMehtaOrg), the open-source autonomous AI agent. Point OpenClaw at this proxy and get unified access to every LLM backend with auth, rate limiting, PII scanning, and logging — out of the box.

## Features

- **Model-prefix routing** — Requests are routed based on model name prefixes defined in `backends.json`. No code changes needed to add or remove backends.
- **Bearer token authentication** — Protect your proxy with `PROXY_API_KEY`. Disabled when unset (for local dev).
- **SSE streaming** — Full pass-through streaming support for `"stream": true` requests.
- **Rate limiting** — In-memory sliding window rate limiter, per-IP, configurable via `RATE_LIMIT_RPM`.
- **Retry with backoff** — Automatic retry on 429/503 with exponential backoff. Per-backend timeouts configurable in `backends.json`.
- **Request size limits** — Reject oversized payloads with `MAX_REQUEST_SIZE_MB`.
- **PII & injection scanning** — Inbound prompt scanning for PII and injection attacks, outbound response scanning for PII leakage (via [AgnosticSecurity](https://github.com/ParthaMehtaOrg/AgnosticSecurity)).
- **JSONL request logging** — Every request logged with backend, model, latency, token usage, and security scan results.
- **Log viewer API** — `GET /logs` endpoint with filtering by backend, model, date, and limit.
- **Health checks** — `GET /health` shows backend reachability and configured routes.

## Routing

| Model prefix | Backend | URL |
|---|---|---|
| `gpt-*` | OpenAI | `https://api.openai.com` |
| `claude-*` | Anthropic | `https://api.anthropic.com` |
| `gemini-*` | Google | `https://generativelanguage.googleapis.com` |
| `vllm/*` | vLLM | `http://localhost:8080` |
| `openclaw/*` | OpenClaw Gateway | `http://localhost:3000` |
| Everything else | Ollama | `http://localhost:11434` |

Edit `backends.json` to add, remove, or modify backends:

```json
{
  "default": {
    "url": "http://localhost:11434",
    "name": "ollama",
    "timeout_s": 60
  },
  "routes": {
    "gpt-": {
      "url": "https://api.openai.com",
      "name": "openai",
      "timeout_s": 30
    }
  }
}
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run (no auth, local dev)
uvicorn proxy.main:app --host 0.0.0.0 --port 8005

# Run (with auth)
PROXY_API_KEY=your-secret-key uvicorn proxy.main:app --host 0.0.0.0 --port 8005
```

## Usage

**Chat completion (routed to Ollama):**
```bash
curl http://localhost:8005/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-key" \
  -d '{"model": "llama3.2:1b", "messages": [{"role": "user", "content": "Say hello"}]}'
```

**Streaming:**
```bash
curl -N http://localhost:8005/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-key" \
  -d '{"model": "llama3.2:1b", "stream": true, "messages": [{"role": "user", "content": "Say hello"}]}'
```

**Health check (no auth required):**
```bash
curl http://localhost:8005/health
```

**View logs:**
```bash
curl -H "Authorization: Bearer your-secret-key" \
  "http://localhost:8005/logs?backend=ollama&limit=10&since=2026-04-25"
```

## OpenClaw Integration

This proxy is designed to sit between OpenClaw and its LLM providers. Instead of configuring each provider separately in OpenClaw, point it at the proxy and let the router handle the rest.

**1. Start the proxy:**
```bash
PROXY_API_KEY=your-secret-key uvicorn proxy.main:app --host 0.0.0.0 --port 8005
```

**2. Configure OpenClaw to use the proxy as its LLM endpoint:**
```json
{
  "llm": {
    "provider": "openai-compatible",
    "base_url": "http://localhost:8005/v1",
    "api_key": "your-secret-key",
    "model": "gpt-4"
  }
}
```

Change the `model` field to route to any backend:
- `"model": "gpt-4"` — routes to OpenAI
- `"model": "claude-3-opus"` — routes to Anthropic
- `"model": "gemini-pro"` — routes to Google
- `"model": "llama3.2:1b"` — routes to Ollama (local)
- `"model": "openclaw/agent"` — routes to OpenClaw's own gateway

See `openclaw-config.example.json` for a full example with all provider options.

**What OpenClaw gets from the proxy:**
- Single endpoint for all LLM providers (no per-provider config)
- Auth, rate limiting, and size limits protecting your API keys
- PII scanning on prompts and responses
- Full request logging with latency, token usage, and security flags
- Streaming support for real-time agent output

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PROXY_API_KEY` | _(empty, auth disabled)_ | Bearer token for authenticating requests |
| `RATE_LIMIT_RPM` | `60` | Max requests per minute per IP (0 = disabled) |
| `MAX_REQUEST_SIZE_MB` | `10` | Max request body size in MB |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Default Ollama backend URL |
| `PROXY_HOST` | `0.0.0.0` | Proxy listen host |
| `PROXY_PORT` | `8000` | Proxy listen port |
| `LOG_DIR` | `./logs` | Directory for JSONL log files |

## VPS Deployment

Systemd and nginx configs are provided for production deployment:

```bash
# Copy systemd service
sudo cp systemd/openclaw-proxy.service /etc/systemd/system/
sudo systemctl enable --now openclaw-proxy

# Copy nginx config (update server_name and SSL paths)
sudo cp nginx/openclaw-proxy.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/openclaw-proxy.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## Tests

```bash
pip install pytest
python -m pytest tests/test_proxy.py -v
```

## Project Structure

```
├── backends.json              # Backend routing config
├── proxy/
│   ├── main.py                # FastAPI app, proxy handler, streaming
│   ├── auth.py                # Bearer token authentication middleware
│   ├── ratelimit.py           # Sliding window rate limiter middleware
│   ├── sizelimit.py           # Request body size limit middleware
│   ├── retry.py               # Retry logic with exponential backoff
│   ├── router.py              # Model-prefix backend routing
│   ├── dashboard.py           # GET /logs endpoint
│   ├── logger.py              # JSONL request logging
│   ├── security.py            # PII & injection scanning
│   └── config.py              # Environment variable config
├── openclaw-config.example.json # Example OpenClaw config pointing at this proxy
├── tests/
│   └── test_proxy.py          # 33 tests
├── systemd/
│   ├── openclaw-proxy.service # Proxy systemd unit
│   └── ollama.service         # Ollama systemd unit
├── nginx/
│   └── openclaw-proxy.conf    # Nginx TLS reverse proxy config
└── requirements.txt
```
