import json
import os

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from proxy.logger import LOG_FILE

router = APIRouter()


@router.get("/dashboard/metrics")
async def dashboard_metrics():
    from proxy.cache import cache_stats
    from proxy.spend import get_spend_summary
    from proxy.loadbalancer import get_lb_stats

    entries = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    total = len(entries)
    errors = sum(1 for e in entries if e.get("status_code", 0) >= 400)
    latencies = [e["latency_ms"] for e in entries if "latency_ms" in e]
    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0

    by_backend = {}
    for e in entries:
        b = e.get("backend", "unknown")
        if b not in by_backend:
            by_backend[b] = {"count": 0, "total_latency": 0}
        by_backend[b]["count"] += 1
        by_backend[b]["total_latency"] += e.get("latency_ms", 0)

    requests_by_backend = {k: v["count"] for k, v in by_backend.items()}
    latency_by_backend = {
        k: round(v["total_latency"] / v["count"], 2) if v["count"] > 0 else 0
        for k, v in by_backend.items()
    }

    cache = cache_stats()
    spend_data = get_spend_summary()

    return {
        "request_count": total,
        "avg_latency_ms": avg_latency,
        "error_rate": round(errors / total, 4) if total > 0 else 0,
        "cache": cache,
        "spend": spend_data,
        "requests_by_backend": requests_by_backend,
        "latency_by_backend": latency_by_backend,
        "lb_stats": get_lb_stats(),
    }


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OpenClaw LLM Proxy — Dashboard</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0f1117; color: #e1e4e8; padding: 24px; }
h1 { font-size: 24px; margin-bottom: 4px; }
.subtitle { color: #8b949e; font-size: 13px; margin-bottom: 24px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }
.card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 20px; }
.card .label { font-size: 12px; color: #8b949e; text-transform: uppercase; letter-spacing: 1px; }
.card .value { font-size: 32px; font-weight: 700; margin-top: 4px; color: #fff; }
.card .unit { font-size: 14px; color: #8b949e; font-weight: 400; }
.section { margin-bottom: 24px; }
.section h2 { font-size: 16px; margin-bottom: 12px; color: #c9d1d9; }
.bar-row { display: flex; align-items: center; margin-bottom: 8px; }
.bar-label { width: 120px; font-size: 13px; color: #8b949e; flex-shrink: 0; }
.bar-track { flex: 1; height: 24px; background: #21262d; border-radius: 4px; overflow: hidden; margin: 0 12px; }
.bar-fill { height: 100%; border-radius: 4px; transition: width .5s ease; }
.bar-value { width: 80px; font-size: 13px; color: #c9d1d9; text-align: right; flex-shrink: 0; }
.color-green { background: #3fb950; }
.color-blue { background: #58a6ff; }
.color-orange { background: #f0883e; }
.color-red { background: #f85149; }
.color-purple { background: #bc8cff; }
.color-teal { background: #39d2c0; }
.updated { font-size: 11px; color: #484f58; text-align: right; }
</style>
</head>
<body>
<h1>OpenClaw LLM Proxy</h1>
<p class="subtitle">Live dashboard — auto-refreshes every 10s</p>

<div class="grid">
  <div class="card"><div class="label">Total Requests</div><div class="value" id="req-count">—</div></div>
  <div class="card"><div class="label">Avg Latency</div><div class="value" id="avg-latency">—<span class="unit"> ms</span></div></div>
  <div class="card"><div class="label">Error Rate</div><div class="value" id="error-rate">—<span class="unit"> %</span></div></div>
  <div class="card"><div class="label">Cache Hit Rate</div><div class="value" id="cache-rate">—<span class="unit"> %</span></div></div>
  <div class="card"><div class="label">Cache Size</div><div class="value" id="cache-size">—</div></div>
  <div class="card"><div class="label">Total Spend</div><div class="value" id="total-spend">$<span id="spend-val">—</span></div></div>
</div>

<div class="section">
  <h2>Requests by Backend</h2>
  <div id="req-bars"></div>
</div>

<div class="section">
  <h2>Avg Latency by Backend</h2>
  <div id="lat-bars"></div>
</div>

<div class="section">
  <h2>Spend by Backend</h2>
  <div id="spend-bars"></div>
</div>

<p class="updated" id="updated"></p>

<script>
const COLORS = ['color-green','color-blue','color-orange','color-red','color-purple','color-teal'];
let colorMap = {};
let ci = 0;
function getColor(name) {
  if (!colorMap[name]) colorMap[name] = COLORS[ci++ % COLORS.length];
  return colorMap[name];
}

function renderBars(containerId, data, unit) {
  const el = document.getElementById(containerId);
  const max = Math.max(...Object.values(data), 1);
  el.innerHTML = Object.entries(data).map(([k, v]) =>
    `<div class="bar-row">
      <div class="bar-label">${k}</div>
      <div class="bar-track"><div class="bar-fill ${getColor(k)}" style="width:${(v/max*100).toFixed(1)}%"></div></div>
      <div class="bar-value">${typeof v==='number'? (v<1? v.toFixed(4): v.toFixed(2)): v}${unit||''}</div>
    </div>`
  ).join('');
}

async function refresh() {
  try {
    const r = await fetch('/dashboard/metrics');
    const d = await r.json();
    document.getElementById('req-count').textContent = d.request_count.toLocaleString();
    document.getElementById('avg-latency').innerHTML = d.avg_latency_ms.toFixed(1) + '<span class="unit"> ms</span>';
    document.getElementById('error-rate').innerHTML = (d.error_rate * 100).toFixed(1) + '<span class="unit"> %</span>';
    document.getElementById('cache-rate').innerHTML = ((d.cache?.hit_rate||0) * 100).toFixed(1) + '<span class="unit"> %</span>';
    document.getElementById('cache-size').textContent = d.cache?.size || 0;
    document.getElementById('spend-val').textContent = (d.spend?.total_usd || 0).toFixed(4);
    renderBars('req-bars', d.requests_by_backend || {}, '');
    renderBars('lat-bars', d.latency_by_backend || {}, ' ms');
    renderBars('spend-bars', d.spend?.by_backend || {}, '');
    document.getElementById('updated').textContent = 'Last updated: ' + new Date().toLocaleTimeString();
  } catch(e) {
    document.getElementById('updated').textContent = 'Error: ' + e.message;
  }
}
refresh();
setInterval(refresh, 10000);
</script>
</body>
</html>
"""
