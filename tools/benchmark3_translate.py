"""benchmark3: time the Chinese -> English translation path via OpenAI.

Runs _translate_to_english() on representative CJK queries and reports
per-call latency (cold + warm/cache) plus total wall time.
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "orchestrator"))

# Load .env
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

from agent_dispatcher import _translate_to_english, _translate_cache  # noqa: E402

QUERIES = [
    "修复登录页面的样式问题",
    "优化数据库查询性能",
    "添加用户头像上传功能",
    "调试 WebSocket 连接断开的 bug",
    "重构消息分发模块",
]

print(f"OPENAI_API_KEY set: {bool(os.getenv('OPENAI_API_KEY'))}")
print(f"SUMMARY_MODEL: {os.getenv('SUMMARY_MODEL', 'gpt-4o-mini')}")
print(f"queries: {len(QUERIES)}\n")

# Cold pass
_translate_cache.clear()
cold = []
t0 = time.perf_counter()
for q in QUERIES:
    s = time.perf_counter()
    out = _translate_to_english(q)
    dt = time.perf_counter() - s
    cold.append(dt)
    print(f"[cold {dt*1000:7.1f}ms] {q!r} -> {out!r}")
total_cold = time.perf_counter() - t0

# Warm pass (cache hits)
warm = []
t0 = time.perf_counter()
for q in QUERIES:
    s = time.perf_counter()
    _translate_to_english(q)
    warm.append(time.perf_counter() - s)
total_warm = time.perf_counter() - t0

def stats(xs):
    xs = sorted(xs)
    n = len(xs)
    return {
        "min": xs[0] * 1000,
        "p50": xs[n // 2] * 1000,
        "max": xs[-1] * 1000,
        "avg": sum(xs) / n * 1000,
    }

print(f"\ncold total: {total_cold*1000:.1f}ms  per-call: {stats(cold)}")
print(f"warm total: {total_warm*1000:.3f}ms  per-call: {stats(warm)}")
