# LLM serving engine (`crisis/engine`)

A small inference server written from scratch in PyTorch, built to serve the agent's report
writer. It implements the scheduling and memory ideas used by production servers (vLLM, TGI) at a
size that fits on a CPU, and it speaks the Ollama and OpenAI chat APIs, so the existing agent runs
against it with no code changes: set `OLLAMA_URL` and go.

```
HTTP (FastAPI)                         engine thread
/api/chat (Ollama)       ─┐    submit   ┌──────────────────────────────────────────────┐
/v1/chat/completions      ├──────────►  │ scheduler (every iteration)                  │
  (OpenAI, SSE streaming) │             │  running rows first, 1 token each            │
/metrics (Prometheus)     │             │  then admit waiting prompts as chunks        │
/health, /v1/models      ─┘             │  under a token budget; preempt newest on OOM │
        ▲   tokens via call_soon_threadsafe   ▼                                      │
        └─────────────────────────────  decode batch + prefill batch → paged KV pool │
                                        │  sample under JSON-schema mask, jump-forward │
                                        └──────────────────────────────────────────────┘
```

## What is in it

| Part | File | Idea |
|---|---|---|
| Paged KV cache | `model.py` | One block pool for all requests; each sequence has a block table. Attention writes K/V into its blocks and gathers its context through the table, so memory is allocated 16 tokens at a time instead of reserved for the maximum length. |
| Continuous batching | `engine.py` | Scheduling happens every forward pass: finished requests leave and waiting ones join mid-flight, instead of waiting for the whole batch. |
| Chunked prefill | `engine.py` | Long prompts are split under a per-step token budget so a 2,000-token prompt does not stall everyone else's decoding. Decode rows and prefill chunks run as two dense batches so short rows are not padded to the chunk length. |
| Preemption | `engine.py` | When blocks run out, the newest request is evicted and later recomputed; outputs are unchanged (tested). |
| Constrained decoding | `constrain.py` | A JSON schema compiles into a byte-level automaton that masks the logits, so output always parses and has the schema's keys, enums and array bounds. Single forced bytes (keys, punctuation) skip sampling ("jump-forward"). Near the end of `max_tokens` the mask keeps only closing moves, so a long request still returns valid JSON. |
| Sampling | `engine.py` | Greedy, temperature, top-p, per-request seeds. |
| API | `server.py` | Ollama `/api/chat` (stream and non-stream, `format`, `options`), OpenAI `/v1/chat/completions` (`response_format` `json_schema` / `json_object`, SSE), Prometheus `/metrics` (TTFT and end-to-end histograms, KV blocks, queue depth, preemptions). A failing step fails its requests with HTTP 500 and the server keeps running. |

## The model

Model weights could not be downloaded in the environment this was built in (Hugging Face and the
Ollama registry are blocked there), so `train.py` trains a 3.7M-parameter byte-level GPT on CPU in
about 10 minutes. It learns to imitate the deterministic baseline report from the exact prompt
`report.llm_report` sends. 152 incidents train it, 37 are held out by content hash, and the
checkpoint with the best held-out loss is kept. It is a test fixture for the serving stack, not a
useful report writer; the numbers below say so.

## Results (CPU, 4 threads, snapshot 2026-10-18T0217Z)

**The agent, unchanged, on 37 held-out incidents** (`crisis-engine eval`, `docs/results/engine_eval.json`)

| | Schema-valid JSON | Reports passing the verifier |
|---|---|---|
| Same prompts, no constraint | 2.7% | n/a |
| With schema-constrained decoding | **100%** | 0% |
| Deterministic baseline (reference) | 100% | 100% |

Constrained decoding is what makes a weak model's output usable by the pipeline at all. The
verifier then rejects every one of its reports (only 15.6% of its facts are grounded and none of
its reports pass every check), which is the system doing its job: nothing ungrounded reaches the
dashboard as verified. A quarter of all output bytes were forced by the schema and skipped
sampling.

**Static vs continuous batching** (`crisis-engine bench`, `docs/results/engine_bench.json`): 64
real report prompts per run, Poisson arrivals, output lengths 40 to 400 tokens, same model and work.

| Arrival rate | Scheduler | Time to first token p50 / p95 | End-to-end p50 / p95 | Output tokens/s |
|---|---|---|---|---|
| 2 req/s | static | 0.082 / 0.841 s | 0.34 / 1.35 s | 188 |
| 2 req/s | continuous | 0.049 / 0.102 s | 0.30 / 0.74 s | 189 |
| 4 req/s | static | 0.283 / 0.839 s | 0.57 / 1.42 s | 363 |
| 4 req/s | continuous | 0.049 / 0.141 s | 0.37 / 1.10 s | 369 |
| 8 req/s | static | 1.938 / 3.292 s | 2.72 / 4.07 s | 545 |
| 8 req/s | continuous | **0.113 / 0.761 s** | **1.42 / 3.53 s** | **612** |

At 8 req/s, continuous batching cuts median time to first token 17x and raises throughput 12%.
At low load both keep up, so throughput matches and only latency differs.

## Correctness tests (`tests/test_engine.py`)

- Paged attention over scattered blocks equals dense attention.
- Engine greedy output equals full recompute in continuous mode, static mode, and with a pool so
  small that preemption happens.
- 800 random walks through the schema automaton always parse, keep schema key order and fit the
  token budget.
- Same seed gives the same sample; the API answers in both Ollama and OpenAI shapes, streams, and
  rejects empty requests.

## Run it

```bash
uv sync && uv pip install torch --index-url https://download.pytorch.org/whl/cpu   # or: uv sync --extra engine
uv run crisis-engine train                       # ~10 min on 4 CPU threads → models/crisis-tiny.pt
uv run crisis-engine serve --port 11435          # Ollama + OpenAI compatible
OLLAMA_URL=http://127.0.0.1:11435 uv run crisis cycle --replay snapshots/2026-10-18T0217Z
uv run crisis-engine eval                        # held-out scores through the agent's own client
uv run crisis-engine bench --rates 2,4,8         # static vs continuous
uv run pytest -q tests/test_engine.py
```

## Limits

CPU only; no CUDA kernels, quantization, tensor parallelism, prefix caching or speculative decoding.
The tokenizer is bytes, so the engine cannot load a Hugging Face checkpoint as it stands. Strings
under constraint are printable ASCII without escapes. Benchmarks are one machine, one run per
setting. `/api/embed` is not served; run the agent with `use_embeddings=False` (BM25 only).
