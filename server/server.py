"""
LLM proxy server for HotkeyExplain.
Listens on :8000, routes /v1/chat/completions to the appropriate mlx backend.

Model routing:
  - Qwen3.6-35B-A3B-*  → mlx-vlm (port 8001) — multimodal, handles text + vision
  - Qwen3.6-27B-*      → mlx-lm  (port 8002) — dense text model

Any model not explicitly mapped falls through to the vlm backend (port 8001).
The proxy is transparent: it streams SSE verbatim from the backend.
"""

import asyncio
import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
import json

app = FastAPI()

VLM_BACKEND = os.getenv("VLM_BACKEND", "http://127.0.0.1:8001")
LM_BACKEND  = os.getenv("LM_BACKEND",  "http://127.0.0.1:8002")

DENSE_MODELS = {"Qwen3.6-27B", "qwen3.6-27b"}


def _normalize_sse_line(line: bytes) -> bytes:
    """Normalize an mlx-vlm SSE `data:` chunk to a clean standard OpenAI chunk.

    mlx-vlm emits non-standard / always-present-even-when-null fields
    (top-level `"timings":null`, `"usage":null`; per-choice `"logprobs":null`;
    per-delta `"reasoning":null,"tool_calls":null,...`). Open WebUI's stream
    parser silently drops the whole message when these are present, rendering an
    empty bubble. Stripping them makes mlx-vlm chunks byte-structurally identical
    to the mlx-lm (27B) chunks that already render fine.
    Non-data lines and `[DONE]` pass through unchanged."""
    s = line.strip()
    if not s.startswith(b"data:"):
        return line
    data = s[5:].strip()
    if data == b"[DONE]" or not data:
        return line
    try:
        obj = json.loads(data)
        # Drop non-standard / null top-level fields (mlx-vlm emits
        # "timings":null,"usage":null which some clients choke on).
        obj.pop("timings", None)
        if obj.get("usage") is None:
            obj.pop("usage", None)
        for ch in obj.get("choices", []):
            if ch.get("logprobs") is None:
                ch.pop("logprobs", None)
            delta = ch.get("delta")
            if isinstance(delta, dict):
                ch["delta"] = {k: v for k, v in delta.items() if v is not None}
        return b"data: " + json.dumps(obj, ensure_ascii=False).encode("utf-8")
    except Exception:
        return line  # leave anything unexpected untouched


def _pick_backend(model_id: str) -> str:
    for name in DENSE_MODELS:
        if name.lower() in model_id.lower():
            return LM_BACKEND
    return VLM_BACKEND


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/models")
async def models():
    return {
        "object": "list",
        "data": [
            {"id": "mlx-community/Qwen3.6-35B-A3B-4bit", "object": "model"},
            {"id": "mlx-community/Qwen3.6-27B-4bit",     "object": "model"},
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.body()
    try:
        payload = json.loads(body)
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid JSON"})

    model_id = payload.get("model", "")
    backend  = _pick_backend(model_id)
    stream   = payload.get("stream", False)

    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in ("host", "content-length")}

    async def generate():
        # The mlx-vlm backend emits deltas with every OpenAI field present even
        # when null ("reasoning":null,"tool_calls":null,...). Some SSE clients
        # (e.g. Open WebUI) fail to render `content` when these null fields are
        # present. Normalize each chunk to a clean minimal delta. We buffer by
        # line so a chunk split mid-event is handled correctly.
        buf = b""
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream("POST", f"{backend}/v1/chat/completions",
                                     content=body, headers=headers) as resp:
                async for chunk in resp.aiter_bytes():
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        yield _normalize_sse_line(line) + b"\n"
        if buf:
            yield _normalize_sse_line(buf)

    if stream:
        return StreamingResponse(generate(), media_type="text/event-stream")

    # Non-streaming: collect full response
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(f"{backend}/v1/chat/completions",
                                 content=body, headers=headers)
    return JSONResponse(status_code=resp.status_code, content=resp.json())
