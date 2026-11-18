"""HTTP front end for the engine: Ollama-compatible and OpenAI-compatible chat, plus metrics.

`/api/chat` speaks the subset of Ollama's API the crisis agent uses (messages, `format` as a JSON
schema or "json", `options.temperature/top_p/seed/num_predict`, `stream`), so the agent runs
unchanged with `OLLAMA_URL` pointed here. `/v1/chat/completions` speaks the OpenAI shape, with
`response_format` of type `json_schema` or `json_object`, and server-sent events when streaming.

The engine runs its scheduling loop in one background thread. Request handlers only enqueue a
sequence and wait on an asyncio queue that the engine thread feeds with `call_soon_threadsafe`.
"""

from __future__ import annotations

import asyncio
import codecs
import json
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse

from .engine import Engine, SamplingParams, Sequence
from .tokenizer import chat_prompt, encode

_DONE = object()


def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


class Histogram:
    def __init__(self, buckets):
        self.buckets, self.counts, self.total, self.n = list(buckets), [0] * len(buckets), 0.0, 0

    def observe(self, v: float) -> None:
        self.n, self.total = self.n + 1, self.total + v
        for i, b in enumerate(self.buckets):
            if v <= b:
                self.counts[i] += 1

    def lines(self, name: str) -> list[str]:
        out = [f"# TYPE {name} histogram"]
        out += [f'{name}_bucket{{le="{b}"}} {c}' for b, c in zip(self.buckets, self.counts)]
        out += [f'{name}_bucket{{le="+Inf"}} {self.n}', f"{name}_sum {self.total:.6f}", f"{name}_count {self.n}"]
        return out


class Server:
    def __init__(self, engine: Engine, model_name: str):
        self.engine, self.model_name = engine, model_name
        self.ttft = Histogram([0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30])
        self.e2e = Histogram([0.1, 0.5, 1, 2, 5, 10, 30, 60, 120])
        self.requests = {"ok": 0, "error": 0}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self.engine.loop_forever, args=(self._stop,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def generate(self, messages: list[dict], params: SamplingParams) -> asyncio.Queue:
        """Enqueue one request; the returned queue yields text pieces, then the finished Sequence."""
        loop, q = asyncio.get_running_loop(), asyncio.Queue()
        dec = codecs.getincrementaldecoder("utf-8")(errors="replace")

        def on_token(tok: int) -> None:
            piece = dec.decode(bytes([tok]))
            if piece:
                loop.call_soon_threadsafe(q.put_nowait, piece)

        def on_finish(seq: Sequence) -> None:
            tail = dec.decode(b"", final=True)
            if tail:
                loop.call_soon_threadsafe(q.put_nowait, tail)
            if seq.first_token_at:
                self.ttft.observe(seq.first_token_at - seq.arrival)
            self.e2e.observe(seq.finished_at - seq.arrival)
            self.requests["error" if seq.finish_reason == "error" else "ok"] += 1
            loop.call_soon_threadsafe(q.put_nowait, seq)

        if not messages:
            raise HTTPException(400, "messages must not be empty")
        try:
            self.engine.submit(encode(chat_prompt(messages)), params, on_token, on_finish)
        except ValueError as exc:
            self.requests["error"] += 1
            raise HTTPException(400, str(exc)) from exc
        return q

    def metrics(self) -> str:
        e, s = self.engine, self.engine.stats
        lines = [
            "# TYPE engine_requests_total counter",
            *(f'engine_requests_total{{status="{k}"}} {v}' for k, v in self.requests.items()),
            "# TYPE engine_running gauge", f"engine_running {len(e.running)}",
            "# TYPE engine_waiting gauge", f"engine_waiting {len(e.waiting)}",
            "# TYPE engine_kv_blocks_used gauge", f"engine_kv_blocks_used {e.blocks.used}",
            "# TYPE engine_kv_blocks_total gauge", f"engine_kv_blocks_total {e.blocks.total}",
            "# TYPE engine_steps_total counter", f"engine_steps_total {s.steps}",
            "# TYPE engine_prefill_tokens_total counter", f"engine_prefill_tokens_total {s.prefill_tokens}",
            "# TYPE engine_decode_tokens_total counter", f"engine_decode_tokens_total {s.decode_tokens}",
            "# TYPE engine_forced_tokens_total counter", f"engine_forced_tokens_total {s.forced_tokens}",
            "# TYPE engine_preemptions_total counter", f"engine_preemptions_total {s.preemptions}",
        ]
        return "\n".join(lines + self.ttft.lines("engine_ttft_seconds") + self.e2e.lines("engine_e2e_seconds")) + "\n"


def _ollama_params(body: dict) -> SamplingParams:
    o, fmt = body.get("options") or {}, body.get("format")
    return SamplingParams(max_tokens=int(o.get("num_predict", 256)), temperature=float(o.get("temperature", 0.8)),
                          top_p=float(o.get("top_p", 1.0)), seed=o.get("seed"),
                          schema=fmt if isinstance(fmt, dict) else None, json_mode=fmt == "json")


def _openai_params(body: dict) -> SamplingParams:
    rf = body.get("response_format") or {}
    schema = (rf.get("json_schema") or {}).get("schema") if rf.get("type") == "json_schema" else None
    return SamplingParams(max_tokens=int(body.get("max_tokens") or body.get("max_completion_tokens") or 256),
                          temperature=float(body.get("temperature", 1.0)), top_p=float(body.get("top_p", 1.0)),
                          seed=body.get("seed"), schema=schema, json_mode=rf.get("type") == "json_object")


def _usage(seq: Sequence) -> dict:
    return {"prompt_tokens": len(seq.prompt), "completion_tokens": len(seq.out),
            "total_tokens": len(seq.prompt) + len(seq.out)}


def create_app(engine: Engine, model_name: str = "crisis-tiny") -> FastAPI:
    srv = Server(engine, model_name)

    @asynccontextmanager
    async def lifespan(_app):
        srv.start()
        yield
        srv.stop()

    app = FastAPI(title="crisis engine", lifespan=lifespan)
    app.state.server = srv

    @app.get("/health")
    def health():
        return {"status": "ok", "model": model_name, "running": len(engine.running), "waiting": len(engine.waiting)}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics():
        return srv.metrics()

    @app.get("/v1/models")
    def models():
        return {"object": "list", "data": [{"id": model_name, "object": "model", "owned_by": "local"}]}

    @app.get("/api/tags")
    def tags():
        return {"models": [{"name": model_name, "model": model_name}]}

    @app.post("/api/chat")
    async def ollama_chat(req: Request):
        body = await req.json()
        q = srv.generate(body.get("messages") or [], _ollama_params(body))
        name = body.get("model", model_name)

        def final(seq: Sequence, content: str) -> dict:
            return {"model": name, "created_at": _iso(time.time()), "message": {"role": "assistant", "content": content},
                    "done": True, "done_reason": seq.finish_reason, "prompt_eval_count": len(seq.prompt),
                    "eval_count": len(seq.out), "total_duration": int((seq.finished_at - seq.arrival) * 1e9)}

        if body.get("stream", True):
            async def ndjson():
                while True:
                    item = await q.get()
                    if isinstance(item, Sequence):
                        yield json.dumps(final(item, "")) + "\n"
                        return
                    yield json.dumps({"model": name, "created_at": _iso(time.time()),
                                      "message": {"role": "assistant", "content": item}, "done": False}) + "\n"
            return StreamingResponse(ndjson(), media_type="application/x-ndjson")
        parts = []
        while not isinstance(item := await q.get(), Sequence):
            parts.append(item)
        if item.finish_reason == "error":
            raise HTTPException(500, "generation failed")
        return final(item, "".join(parts))

    @app.post("/v1/chat/completions")
    async def openai_chat(req: Request):
        body = await req.json()
        q = srv.generate(body.get("messages") or [], _openai_params(body))
        rid, created, name = f"chatcmpl-{uuid.uuid4().hex[:24]}", int(time.time()), body.get("model", model_name)

        if body.get("stream"):
            async def sse():
                def chunk(delta, finish=None):
                    return "data: " + json.dumps({"id": rid, "object": "chat.completion.chunk", "created": created,
                                                  "model": name, "choices": [{"index": 0, "delta": delta,
                                                                              "finish_reason": finish}]}) + "\n\n"
                yield chunk({"role": "assistant"})
                while not isinstance(item := await q.get(), Sequence):
                    yield chunk({"content": item})
                yield chunk({}, item.finish_reason)
                yield "data: [DONE]\n\n"
            return StreamingResponse(sse(), media_type="text/event-stream")
        parts = []
        while not isinstance(item := await q.get(), Sequence):
            parts.append(item)
        if item.finish_reason == "error":
            raise HTTPException(500, "generation failed")
        return {"id": rid, "object": "chat.completion", "created": created, "model": name,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "".join(parts)},
                             "finish_reason": item.finish_reason}], "usage": _usage(item)}

    return app


def main(argv=None) -> None:
    import argparse

    import uvicorn

    from .model import GPT, Config

    p = argparse.ArgumentParser(description="Serve a model with continuous batching")
    p.add_argument("--model", default="models/crisis-tiny.pt", help="checkpoint path, or 'random' for an untrained model")
    p.add_argument("--name", default="crisis-tiny")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=11435)
    p.add_argument("--num-blocks", type=int, default=1024)
    p.add_argument("--block-size", type=int, default=16)
    p.add_argument("--max-batch-tokens", type=int, default=1024)
    p.add_argument("--max-seqs", type=int, default=32)
    p.add_argument("--mode", choices=["continuous", "static"], default="continuous")
    a = p.parse_args(argv)
    model = GPT(Config()) if a.model == "random" else GPT.load(a.model)
    model.eval()
    eng = Engine(model, a.num_blocks, a.block_size, a.max_batch_tokens, a.max_seqs, a.mode)
    uvicorn.run(create_app(eng, a.name), host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
