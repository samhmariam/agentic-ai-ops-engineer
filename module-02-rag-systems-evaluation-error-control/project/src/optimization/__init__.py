"""Streaming + latency-optimisation primitives — RAG Latency Optimization module.

The streaming HTTP router (``src.optimization.routes.router``) is
deliberately NOT re-exported here. Eagerly importing it at package
load time creates a circular import when a script-context invocation
(e.g. INSTRUCTIONS.md §11's ``compare_ttft`` example) triggers the
package's ``__init__`` before FastAPI's app factory has finished
importing it via ``src.gateway.app``. The router's only consumer is
``src.gateway.app``, which imports it via the direct path
``from src.optimization.routes import router`` — no re-export needed.
"""

from src.optimization.streaming import (
    compare_ttft,
    measure_ttft_blocking,
    measure_ttft_streaming,
    stream_completion,
)

__all__ = [
    "stream_completion",
    "measure_ttft_blocking",
    "measure_ttft_streaming",
    "compare_ttft",
]
