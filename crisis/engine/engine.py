"""Scheduler, KV block manager and sampling.

Each `step()` builds one ragged batch under a token budget:

* running sequences contribute their pending tokens (usually one decode token; several when
  constrained decoding jump-forwards over forced bytes);
* waiting sequences are admitted in arrival order while the budget and free KV blocks allow,
  with long prompts split into chunks (chunked prefill);
* if a running sequence needs a block and none is free, the newest running sequence is preempted:
  its blocks are freed and it is recomputed later from its prompt plus what it already generated.

`mode="static"` turns off admission while a batch is running, which is the classic static
batching baseline the benchmark compares against.
"""

from __future__ import annotations

import itertools
import logging
import math
import threading
import time
from collections import deque
from dataclasses import replace, dataclass, field
from typing import Callable

import torch

from .constrain import Constraint
from .model import GPT, Batch, KVPool
from .tokenizer import BOS, EOS

log = logging.getLogger(__name__)


@dataclass
class SamplingParams:
    max_tokens: int = 256
    temperature: float = 0.0
    top_p: float = 1.0
    seed: int | None = None
    schema: dict | None = None     # JSON schema for constrained decoding
    json_mode: bool = False        # any JSON value, no schema
    ignore_eos: bool = False       # generate exactly max_tokens (benchmarks)


@dataclass
class Sequence:
    id: int
    prompt: list[int]
    params: SamplingParams
    on_token: Callable[[int], None] | None = None
    on_finish: Callable[["Sequence"], None] | None = None
    out: list[int] = field(default_factory=list)
    num_computed: int = 0
    blocks: list[int] = field(default_factory=list)
    forced: int = 0
    preemptions: int = 0
    finish_reason: str | None = None
    error: str | None = None
    arrival: float = field(default_factory=time.perf_counter)
    first_token_at: float | None = None
    finished_at: float | None = None
    constraint: Constraint | None = None
    generator: torch.Generator | None = None

    @property
    def tokens(self) -> list[int]:
        return self.prompt + self.out

    @property
    def pending(self) -> int:
        return len(self.tokens) - self.num_computed


class BlockManager:
    def __init__(self, num_blocks: int, block_size: int):
        self.block_size = block_size
        self.free = deque(range(1, num_blocks))   # block 0 is the padding block, never handed out
        self.total = num_blocks - 1

    def needed(self, seq: Sequence, upto: int) -> int:
        return max(0, math.ceil(upto / self.block_size) - len(seq.blocks))

    def allocate(self, seq: Sequence, upto: int) -> bool:
        n = self.needed(seq, upto)
        if n > len(self.free):
            return False
        seq.blocks.extend(self.free.popleft() for _ in range(n))
        return True

    def release(self, seq: Sequence) -> None:
        self.free.extend(seq.blocks)
        seq.blocks = []

    @property
    def used(self) -> int:
        return self.total - len(self.free)


@dataclass
class Stats:
    steps: int = 0
    prefill_tokens: int = 0
    decode_tokens: int = 0
    forced_tokens: int = 0
    preemptions: int = 0
    finished: int = 0
    batch_rows: int = 0
    step_seconds: float = 0.0


class Engine:
    def __init__(self, model: GPT, num_blocks: int = 512, block_size: int = 16, max_batch_tokens: int = 512,
                 max_seqs: int = 32, mode: str = "continuous"):
        assert mode in ("continuous", "static")
        self.model, self.mode = model.eval(), mode
        self.pool = KVPool(model.cfg, num_blocks, block_size)
        self.blocks = BlockManager(num_blocks, block_size)
        self.max_batch_tokens, self.max_seqs = max_batch_tokens, max_seqs
        self.waiting: deque[Sequence] = deque()
        self.running: list[Sequence] = []
        self.stats = Stats()
        self._ids = itertools.count()
        self._lock = threading.Lock()
        self._wake = threading.Event()

    # ---- submission -------------------------------------------------------------------------
    def submit(self, prompt: list[int], params: SamplingParams, on_token=None, on_finish=None) -> Sequence:
        # Context is fixed, so the full prompt wins over a generous max_tokens: shrink the generation
        # budget first, and only cut the prompt (keeping BOS and the newest context) as a last resort.
        constraint = Constraint(params.schema) if params.schema is not None or params.json_mode else None
        floor = 64 if constraint is None else max(64, constraint.reserve + 1)  # room to close the JSON
        limit, min_gen = self.model.cfg.max_seq - 1, min(params.max_tokens, floor)
        if min_gen < 1:
            raise ValueError("max_tokens must be at least 1")
        if len(prompt) + min_gen > limit:
            keep = limit - min_gen
            prompt = prompt[:1] + prompt[-(keep - 1):]
        if len(prompt) + params.max_tokens > limit:
            params = replace(params, max_tokens=limit - len(prompt))
        seq = Sequence(next(self._ids), prompt, params, on_token, on_finish)
        seq.constraint = constraint
        if params.seed is not None:
            seq.generator = torch.Generator().manual_seed(params.seed)
        with self._lock:
            self.waiting.append(seq)
        self._wake.set()
        return seq

    def has_work(self) -> bool:
        return bool(self.waiting or self.running)

    # ---- scheduling -------------------------------------------------------------------------
    def _preempt_newest(self, keep: Sequence) -> bool:
        victims = [s for s in self.running if s is not keep]
        if not victims:
            return False
        v = max(victims, key=lambda s: s.arrival)
        self.running.remove(v)
        self.blocks.release(v)
        v.num_computed = 0
        v.preemptions += 1
        self.stats.preemptions += 1
        self.waiting.appendleft(v)
        return True

    def _schedule(self) -> list[tuple[Sequence, int]]:
        rows: list[tuple[Sequence, int]] = []
        budget = self.max_batch_tokens
        for seq in list(self.running):
            if seq not in self.running:
                continue  # preempted earlier in this loop
            n = min(seq.pending, budget)
            if n <= 0:
                continue
            while not self.blocks.allocate(seq, seq.num_computed + n):
                if not self._preempt_newest(seq):
                    raise RuntimeError("KV pool too small for a single sequence")
            rows.append((seq, n))
            budget -= n
        rows = [(s, n) for s, n in rows if s in self.running]
        static = self.mode == "static"
        admit = not static or not self.running
        if static and admit:
            budget = 1 << 30  # a static batch prefills every admitted prompt in full, like a naive server
        with self._lock:
            while admit and self.waiting and budget > 0 and len(self.running) < self.max_seqs:
                seq = self.waiting[0]
                n = min(seq.pending, budget)
                if not self.blocks.allocate(seq, seq.num_computed + n):
                    break
                self.waiting.popleft()
                self.running.append(seq)
                rows.append((seq, n))
                budget -= n
        return rows

    # ---- one iteration ----------------------------------------------------------------------
    def _forward(self, rows: list[tuple[Sequence, int]]) -> torch.Tensor:
        T = max(n for _, n in rows)
        nblk = max(len(s.blocks) for s, _ in rows)
        toks = torch.zeros(len(rows), T, dtype=torch.long)
        tables = torch.zeros(len(rows), nblk, dtype=torch.long)
        for i, (s, n) in enumerate(rows):
            toks[i, :n] = torch.tensor(s.tokens[s.num_computed:s.num_computed + n])
            tables[i, :len(s.blocks)] = torch.tensor(s.blocks)
        starts = torch.tensor([s.num_computed for s, _ in rows])
        lengths = torch.tensor([n for _, n in rows])
        return self.model(toks, self.pool, Batch(toks, starts, lengths, tables))

    @torch.no_grad()
    def step(self) -> int:
        rows = self._schedule()
        if not rows:
            return 0
        t0 = time.perf_counter()
        # Decode rows (one token each) and prefill chunks run as two dense batches, so a long
        # prefill chunk never pads every decode row out to its length.
        groups = [g for g in ([r for r in rows if r[1] == 1], [r for r in rows if r[1] > 1]) if g]
        self.stats.steps += 1
        self.stats.batch_rows += len(rows)
        for group in groups:
            logits = self._forward(group)
            for i, (s, n) in enumerate(group):
                was_prefill = s.num_computed < len(s.prompt)
                s.num_computed += n
                if was_prefill:
                    self.stats.prefill_tokens += n
                if s.pending == 0:  # caught up: sample the next token
                    self._emit(s, self._sample(s, logits[i, n - 1]))
        self.stats.step_seconds += time.perf_counter() - t0
        return len(rows)

    def _sample(self, s: Sequence, logits: torch.Tensor) -> int:
        if s.constraint is not None:
            mask = torch.full_like(logits, float("-inf"))
            mask[list(s.constraint.allowed(s.params.max_tokens - len(s.out)))] = 0
            logits = logits + mask
        else:
            logits = logits.clone()
            logits[BOS] = float("-inf")  # BOS only ever starts a prompt
            if s.params.ignore_eos:
                logits[EOS] = float("-inf")
        p = s.params
        if p.temperature <= 0:
            return int(logits.argmax())
        probs = torch.softmax(logits / p.temperature, -1)
        if p.top_p < 1.0:
            sp, si = probs.sort(descending=True)
            keep = sp.cumsum(0) - sp < p.top_p
            probs = torch.zeros_like(probs).scatter(0, si[keep], sp[keep])
        return int(torch.multinomial(probs, 1, generator=s.generator))

    def _emit(self, s: Sequence, tok: int) -> None:
        while True:
            if s.first_token_at is None:
                s.first_token_at = time.perf_counter()
            if tok == EOS:
                return self._finish(s, "stop")
            if s.constraint is not None:
                s.constraint.advance(tok)
            s.out.append(tok)
            self.stats.decode_tokens += 1
            if s.on_token:
                s.on_token(tok)
            if len(s.out) >= s.params.max_tokens or len(s.tokens) >= self.model.cfg.max_seq:
                return self._finish(s, "length")
            # jump-forward: a single allowed byte needs no forward pass to choose
            if s.constraint is not None and len(allowed := s.constraint.allowed(s.params.max_tokens - len(s.out))) == 1:
                tok = next(iter(allowed))
                if tok != EOS:
                    s.forced += 1
                    self.stats.forced_tokens += 1
                continue
            return

    def _finish(self, s: Sequence, reason: str) -> None:
        s.finish_reason, s.finished_at = reason, time.perf_counter()
        if s in self.running:
            self.running.remove(s)
        self.blocks.release(s)
        self.stats.finished += 1
        if s.on_finish:
            s.on_finish(s)

    # ---- drivers ----------------------------------------------------------------------------
    def run_until_done(self) -> None:
        while self.has_work():
            self.step()

    def loop_forever(self, stop: threading.Event) -> None:
        """Serve until `stop` is set. A failing step fails the batch's requests, not the server."""
        while not stop.is_set():
            if not self.has_work():
                self._wake.wait(0.05)
                self._wake.clear()
                continue
            try:
                self.step()
            except Exception as exc:  # noqa: BLE001 - keep serving other requests
                log.exception("engine step failed; failing %d running sequences", len(self.running))
                for s in list(self.running):
                    s.error = repr(exc)
                    self._finish(s, "error")
