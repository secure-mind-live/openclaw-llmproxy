# OpenClaw LLM Proxy — Complete Architecture

## The 6 Containers

```
┌────────────┬────────────────────────────────────────────────────┐
│ Container  │ Role                                               │
├────────────┼────────────────────────────────────────────────────┤
│ proxy      │ FastAPI proxy — routes, translates, caches, scans  │
│ ollama     │ Local LLM inference (llama3.2:1b, etc.)            │
│ redis      │ Shared cache + atomic rate limiting across workers │
│ postgres   │ Persistent logs, spend tracking, audit trail       │
│ kafka      │ Async non-blocking log writes (500K+ req/s)        │
│ monitor    │ Health checks every 60s, alerts on failure         │
└────────────┴────────────────────────────────────────────────────┘
```

## Full Request Lifecycle

Every single step a request goes through, from client to backend and back:

```
 CLIENT (OpenClaw / curl / Web App)
   │
   │  POST /v1/chat/completions
   │  {"model": "llama3.2:1b", "messages": [...]}
   │  Authorization: Bearer <proxy-key>
   │
   ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 1. NGINX / K8S INGRESS                                   │
 │    - TLS termination (HTTPS → HTTP)                      │
 │    - proxy_buffering off (for SSE streaming)             │
 │    - client_max_body_size 10m                            │
 └──────────────────────┬───────────────────────────────────┘
                        ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 2. SIZE LIMIT MIDDLEWARE                                  │
 │    proxy/sizelimit.py                                    │
 │    - Check Content-Length header                          │
 │    - If >10MB → 413 Request Entity Too Large             │
 └──────────────────────┬───────────────────────────────────┘
                        ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 3. AUTH MIDDLEWARE                                        │
 │    proxy/auth.py                                         │
 │    - Check Authorization: Bearer <token>                 │
 │    - If missing/wrong → 401 Unauthorized                 │
 │    - /health, /dashboard exempt                          │
 └──────────────────────┬───────────────────────────────────┘
                        ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 4. RATE LIMIT MIDDLEWARE                          REDIS  │
 │    proxy/ratelimit.py                              ◄──►  │
 │    - Sliding window per-IP (ZADD + ZCARD)                │
 │    - Atomic across all workers/pods via Redis            │
 │    - If >60 RPM → 429 Too Many Requests                 │
 └──────────────────────┬───────────────────────────────────┘
                        ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 5. SECURITY SCANNER                                       │
 │    proxy/security.py (AgnosticSecurity)                   │
 │                                                           │
 │    Inbound scan:                                          │
 │    - PII detection (SSN, email, credit card, etc.)        │
 │    - Prompt injection detection (pattern matching)        │
 │                                                           │
 │    Enforcement (SECURITY_PII_MODE / INJECTION_MODE):      │
 │    - "block" → 403 Forbidden + alert webhook              │
 │    - "redact" → replace PII with [REDACTED], continue     │
 │    - "log" → detect and log, but don't block              │
 │                                                           │
 │    Webhook: fires to SECURITY_WEBHOOK_URL on detection    │
 └──────────────────────┬───────────────────────────────────┘
                        ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 6. CACHE CHECK                                    REDIS  │
 │    proxy/cache.py                                  ◄──►  │
 │    - Key: SHA256(model + messages)                       │
 │    - Skip if stream=true or temperature>0                │
 │    - HIT → return cached response immediately (0ms)      │
 │    - MISS → continue to backend                          │
 └──────────────────────┬───────────────────────────────────┘
                   MISS ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 7. BUDGET CHECK                                          │
 │    proxy/spend.py                                        │
 │    - Read monthly_budget_usd from backends.json          │
 │    - If monthly spend >= budget → 402 Payment Required   │
 └──────────────────────┬───────────────────────────────────┘
                        ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 8. KEY INJECTION                                          │
 │    proxy/keymanager.py                                   │
 │    - Read api_key from backends.json for this backend    │
 │    - Replace Authorization header with backend's key     │
 │    - Client only needs proxy key, not provider keys      │
 └──────────────────────┬───────────────────────────────────┘
                        ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 9. ROUTER + LOAD BALANCER                                │
 │    proxy/router.py + proxy/loadbalancer.py               │
 │    - Match model prefix: gpt-* → OpenAI, claude-* → etc │
 │    - If multiple "urls" → round_robin / random /         │
 │      least_latency selection                             │
 └──────────────────────┬───────────────────────────────────┘
                        ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 10. API TRANSLATION                                       │
 │     proxy/translators/                                    │
 │     - OpenAI format in → native format out                │
 │     - anthropic.py: path→/v1/messages, system msg,        │
 │       x-api-key header, content blocks                    │
 │     - gemini.py: path→/v1/models/{m}:generateContent,    │
 │       contents/parts format, generationConfig              │
 │     - Passthrough for OpenAI/Ollama/vLLM (no change)     │
 └──────────────────────┬───────────────────────────────────┘
                        ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 11. HTTP REQUEST + RETRY                                  │
 │     proxy/retry.py                                       │
 │     - httpx AsyncClient (100 connections, 20 keepalive)  │
 │     - Retry on 429/503 with exponential backoff          │
 │     - Per-backend timeout_s from backends.json           │
 │     - Max 3 retries before giving up                     │
 └──────────────────────┬───────────────────────────────────┘
                        │
           ┌────────────┴────────────────────────┐
           │            BACKENDS                  │
           │                                      │
           │  ┌────────┐ ┌──────────┐ ┌────────┐ │
           │  │ OpenAI │ │Anthropic │ │ Google │ │
           │  │ gpt-*  │ │claude-*  │ │gemini-*│ │
           │  └────────┘ └──────────┘ └────────┘ │
           │  ┌────────┐ ┌──────────┐ ┌────────┐ │
           │  │ Ollama │ │  vLLM    │ │OpenClaw│ │
           │  │default │ │ vllm/*   │ │  GW    │ │
           │  └────────┘ └──────────┘ └────────┘ │
           └────────────┬────────────────────────┘
                        │
                        │ ← If 5xx/timeout/connect error
                        │   AND fallback chain configured
                        │   → try next backend in chain
                        │   (NOT on 429 — that's rate limit)
                        ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 12. RESPONSE TRANSLATION                                  │
 │     - Anthropic content blocks → OpenAI choices format    │
 │     - Gemini candidates/parts → OpenAI choices format     │
 │     - Token count normalization                           │
 │     - Streaming: SSE chunk-by-chunk translation           │
 └──────────────────────┬───────────────────────────────────┘
                        ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 13. OUTBOUND SECURITY SCAN                                │
 │     - Scan LLM response for PII leakage                  │
 │     - If redact mode: scrub PII from response before      │
 │       returning to client                                 │
 └──────────────────────┬───────────────────────────────────┘
                        ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 14. SPEND TRACKING                              POSTGRES │
 │     proxy/spend.py                                ◄──►   │
 │     - cost = (prompt_tokens/1K * price) +                │
 │              (completion_tokens/1K * price)               │
 │     - Persist to PostgreSQL spend table                   │
 │     - Track by backend, model, day, month                │
 └──────────────────────┬───────────────────────────────────┘
                        ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 15. CACHE STORE                                   REDIS  │
 │     - If cacheable (temp=0, non-streaming, 200)    ◄──►  │
 │     - Store response with TTL in Redis                   │
 │     - Next identical request → instant cache hit         │
 └──────────────────────┬───────────────────────────────────┘
                        ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 16. LOG                                     KAFKA→PG     │
 │     proxy/logger.py                                      │
 │     Priority: Kafka (async) → PG (sync) → JSONL          │
 │                                                           │
 │     Fields: timestamp, method, path, backend, model,      │
 │     status_code, latency_ms, prompt_tokens,               │
 │     completion_tokens, inbound_scan, outbound_scan,       │
 │     cache_hit, cost_usd                                   │
 └──────────────────────┬───────────────────────────────────┘
                        ▼
              Response returned to client
```

## Background Services

```
 ┌──────────────────────────────────────────────────────────┐
 │ ALWAYS RUNNING:                                           │
 │                                                           │
 │  Monitor (scripts/monitor.py) — every 60s:                │
 │    - Health check      - Auth enforcement                 │
 │    - Dashboard up      - Chat completion works            │
 │                                                           │
 │  Kafka consumer (your SIEM/ELK) — reads from topic:       │
 │    llmproxy.requests → Elasticsearch / Splunk / etc.      │
 │                                                           │
 │  GitHub Actions CI — every push:                           │
 │    97 unit tests → Docker build → smoke tests → monitor   │
 └──────────────────────────────────────────────────────────┘
```

## API Endpoints

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` | No | Backend reachability + configured routes |
| `GET /dashboard` | No | Live HTML dashboard with charts |
| `GET /dashboard/metrics` | No | JSON metrics for dashboard polling |
| `GET /logs` | Yes | Query log entries (filters: backend, model, since, limit) |
| `GET /spend` | Yes | Cost breakdown by backend, model, daily |
| `ANY /{path}` | Yes | Catch-all proxy to LLM backends |

## Data Flow by Storage Backend

```
                Write Path                    Read Path
                ─────────                     ────────
Logs:     Kafka (async, batched)         PG Read Replica (indexed)
             ↓ (consumer)                     ↑
          PostgreSQL Primary              Dashboard / /logs API
             ↓ (fallback)
          JSONL file

Cache:    Redis SET (with TTL)           Redis GET
             ↓ (fallback)                     ↑
          In-memory OrderedDict          Same process

Rate      Redis ZADD (sorted set)        Redis ZCARD
Limit:       ↓ (fallback)                     ↑
          In-memory dict                 Same process

Spend:    PostgreSQL INSERT              PostgreSQL SUM/GROUP BY
             ↓ (fallback)                     ↑
          spend.jsonl                    /spend API
```

## Infrastructure Tiers

```
┌─────────────────────────────────────────────────────────────┐
│ Dev (zero config)          ~200 req/s                       │
│   uvicorn + in-memory state + JSONL logs                    │
├─────────────────────────────────────────────────────────────┤
│ Production                 ~5K-15K req/s                    │
│   + Redis (shared cache + rate limiting)                    │
│   + PostgreSQL (persistent logs + spend)                    │
├─────────────────────────────────────────────────────────────┤
│ High Scale                 ~50K-100K req/s                  │
│   + K8s HPA (2→10 pods)                                    │
│   + Multiple uvicorn workers                                │
├─────────────────────────────────────────────────────────────┤
│ Extreme Scale              ~500K-1M+ req/s                  │
│   + Kafka (async non-blocking log writes)                   │
│   + Redis Cluster (sharded cache/rate limiting)             │
│   + PG Read Replicas (dashboard queries off primary)        │
└─────────────────────────────────────────────────────────────┘
```

## Files and Responsibilities

| File | Role |
|---|---|
| `proxy/main.py` | FastAPI app, middleware registration, proxy handler with fallback loop, streaming/buffered split |
| `proxy/router.py` | Loads backends.json, prefix-matches model → backend, integrates load balancer |
| `proxy/loadbalancer.py` | Round-robin, random, least-latency URL selection across multiple backend URLs |
| `proxy/fallback.py` | Resolves fallback chain, decides if failure is eligible for fallback |
| `proxy/cache.py` | MemoryCache or RedisCache (auto-selects), LRU with TTL |
| `proxy/spend.py` | Cost calculation, budget enforcement, PostgreSQL or JSONL persistence |
| `proxy/retry.py` | Exponential backoff on 429/503, per-backend timeouts |
| `proxy/auth.py` | Bearer token middleware, exempt paths |
| `proxy/ratelimit.py` | MemoryRateLimiter or RedisRateLimiter (sorted sets), per-IP sliding window |
| `proxy/sizelimit.py` | Request body size limit middleware |
| `proxy/security.py` | PII detection, injection scanning, block/redact/log modes |
| `proxy/alerts.py` | Webhook alerts for security events |
| `proxy/keymanager.py` | Per-backend API key injection from backends.json |
| `proxy/translators/` | API format translation (OpenAI ↔ Anthropic, OpenAI ↔ Gemini) |
| `proxy/logger.py` | Kafka → PostgreSQL → JSONL log writer, PG read replica queries |
| `proxy/dashboard.py` | GET /logs, GET /spend endpoints |
| `proxy/web_dashboard.py` | GET /dashboard HTML page, GET /dashboard/metrics JSON |
| `proxy/config.py` | All environment variable defaults |
| `scripts/smoke_test.sh` | Post-deploy verification (9 checks) |
| `scripts/monitor.py` | Continuous background health monitor |
