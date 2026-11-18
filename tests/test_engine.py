import json
import random

import pytest

torch = pytest.importorskip("torch")

from crisis import report  # noqa: E402
from crisis.engine.constrain import Constraint  # noqa: E402
from crisis.engine.engine import BlockManager, Engine, SamplingParams  # noqa: E402
from crisis.engine.model import GPT, Batch, Config, KVPool  # noqa: E402
from crisis.engine.tokenizer import EOS, chat_prompt, decode, encode  # noqa: E402


@pytest.fixture(scope="module")
def model():
    torch.manual_seed(0)
    return GPT(Config(n_layer=2, n_head=2, d_model=64, max_seq=512)).eval()


def reference_greedy(model, prompt, n):
    ids = list(prompt)
    with torch.no_grad():
        for _ in range(n):
            logits = model(torch.tensor([ids]))[0, -1]
            logits[256] = float("-inf")
            ids.append(int(logits.argmax()))
    return ids[len(prompt):]


def prompts(k, seed=0):
    rng = random.Random(seed)
    return [encode("".join(rng.choice("abcdef ghij\n") for _ in range(rng.randint(5, 120)))) for _ in range(k)]


def test_tokenizer_round_trips_utf8_and_formats_chat():
    assert decode(encode("Ünïcode ✓ text", bos=True)) == "Ünïcode ✓ text"
    assert chat_prompt([{"role": "user", "content": "hi"}]) == "<|user|>\nhi\n<|assistant|>\n"


def test_paged_attention_matches_dense_attention(model):
    ids = encode("the quick brown fox jumps over the lazy dog")
    dense = model(torch.tensor([ids]))
    pool = KVPool(model.cfg, num_blocks=16, block_size=4)
    table = torch.tensor([[9, 3, 14, 1, 6, 11, 2, 5, 15, 7, 4, 12]])  # scattered, non-contiguous blocks
    with torch.no_grad():
        a = model(torch.tensor([ids[:17]]), pool, Batch(torch.tensor([ids[:17]]), torch.tensor([0]), torch.tensor([17]), table))
        b = model(torch.tensor([ids[17:]]), pool, Batch(torch.tensor([ids[17:]]), torch.tensor([17]),
                                                         torch.tensor([len(ids) - 17]), table))
    assert torch.allclose(torch.cat([a, b], 1), dense, atol=1e-5)


@pytest.mark.parametrize("mode,blocks,budget", [("continuous", 256, 64), ("static", 256, 64), ("continuous", 22, 16)])
def test_engine_greedy_output_equals_full_recompute(model, mode, blocks, budget):
    """Chunked prefill, ragged mixed batches and preemption-by-recompute must not change outputs."""
    eng = Engine(model, num_blocks=blocks, block_size=8, max_batch_tokens=budget, max_seqs=6, mode=mode)
    ps = prompts(8)
    seqs = [eng.submit(p, SamplingParams(max_tokens=24, ignore_eos=True)) for p in ps]
    eng.run_until_done()
    for p, s in zip(ps, seqs):
        assert s.out == reference_greedy(model, p, 24)
    if blocks == 22:
        assert eng.stats.preemptions > 0
    assert eng.blocks.used == 0


def test_block_manager_never_hands_out_the_padding_block_and_frees_everything(model):
    bm = BlockManager(10, 4)
    eng = Engine(model, num_blocks=10, block_size=4)
    s = eng.submit(encode("x" * 20), SamplingParams(max_tokens=1))
    assert bm.allocate(s, 21)
    assert 0 not in s.blocks and len(s.blocks) == 6
    bm.release(s)
    assert bm.used == 0


def test_same_seed_same_sample_and_different_seed_differs(model):
    eng = Engine(model)
    p = encode("sample me")
    outs = [eng.submit(p, SamplingParams(max_tokens=30, temperature=1.0, seed=s, ignore_eos=True)) for s in (1, 1, 2)]
    eng.run_until_done()
    assert outs[0].out == outs[1].out != outs[2].out


@pytest.mark.parametrize("schema", [report.SCHEMA, None, {"type": "array", "items": {"type": "integer"}, "maxItems": 4},
                                    {"type": "object", "properties": {"x": {"type": "number"}, "ok": {"type": "boolean"}}}])
def test_constrained_random_walks_always_parse_and_fit_the_budget(schema):
    for trial in range(200):
        rng = random.Random(trial)
        c = Constraint(schema)
        budget, out = rng.randint(c.reserve, c.reserve + 300), []
        while not c.done:
            tok = rng.choice(sorted(c.allowed(budget - len(out))))
            if tok == EOS:
                break
            c.advance(tok)
            out.append(tok)
        assert c.done and len(out) <= budget
        value = json.loads(bytes(out))
        if schema and schema.get("type") == "object":
            assert list(value) == list(schema["properties"])


def test_report_schema_output_from_untrained_model_is_schema_shaped(model):
    eng = Engine(model, num_blocks=128, block_size=16)
    msgs = [{"role": "system", "content": report.SYSTEM}, {"role": "user", "content": "doc"}]
    s = eng.submit(encode(chat_prompt(msgs)), SamplingParams(max_tokens=300, schema=report.SCHEMA))
    eng.run_until_done()
    rep = json.loads(decode(s.out))
    assert list(rep) == list(report.SCHEMA["properties"])
    assert rep["alert_level"] in report.SCHEMA["properties"]["alert_level"]["enum"]
    assert s.forced > 0  # keys and punctuation were jump-forwarded, not sampled


def test_long_prompt_keeps_room_to_close_the_json(model):
    eng = Engine(model, num_blocks=128, block_size=16)
    s = eng.submit(encode("y" * 2000), SamplingParams(max_tokens=700, schema=report.SCHEMA))
    eng.run_until_done()
    assert len(s.prompt) + len(s.out) <= model.cfg.max_seq
    json.loads(decode(s.out))


def test_http_api_is_ollama_and_openai_compatible(model):
    from fastapi.testclient import TestClient

    from crisis.engine.server import create_app

    with TestClient(create_app(Engine(model, num_blocks=256, block_size=16), "tiny")) as c:
        msgs = [{"role": "system", "content": report.SYSTEM}, {"role": "user", "content": "doc"}]
        r = c.post("/api/chat", json={"stream": False, "format": report.SCHEMA, "messages": msgs,
                                      "options": {"temperature": 0, "seed": 7, "num_predict": 300}})
        assert r.status_code == 200 and r.json()["done"]
        assert set(json.loads(r.json()["message"]["content"])) == set(report.SCHEMA["properties"])

        r = c.post("/v1/chat/completions", json={"messages": msgs, "max_tokens": 80,
                                                 "response_format": {"type": "json_object"}})
        json.loads(r.json()["choices"][0]["message"]["content"])
        assert r.json()["usage"]["completion_tokens"] > 0

        with c.stream("POST", "/v1/chat/completions", json={"messages": msgs, "max_tokens": 5, "stream": True}) as s:
            lines = [ln for ln in s.iter_lines() if ln]
        assert lines[-1] == "data: [DONE]"

        with c.stream("POST", "/api/chat", json={"messages": msgs, "options": {"num_predict": 5}}) as s:
            assert json.loads([ln for ln in s.iter_lines() if ln][-1])["done"]

        assert c.post("/api/chat", json={"messages": []}).status_code == 400
        assert 'engine_requests_total{status="ok"} 4' in c.get("/metrics").text
