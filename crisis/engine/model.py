"""Decoder-only transformer whose attention reads and writes a paged KV-cache.

One forward pass serves a ragged batch: some rows are prompt chunks (prefill), others are single
decode tokens. Each row has a start position and a block table; new keys and values are written
into the shared block pool, then every query attends over its sequence's cached keys.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F

from .tokenizer import VOCAB_SIZE


@dataclass
class Config:
    vocab_size: int = VOCAB_SIZE
    n_layer: int = 4
    n_head: int = 4
    d_model: int = 256
    max_seq: int = 2048
    dropout: float = 0.0

    @property
    def head_dim(self) -> int:
        return self.d_model // self.n_head


class KVPool:
    """Fixed pool of KV blocks shared by all sequences: [layer, k|v, block*block_size, head, head_dim]."""

    def __init__(self, cfg: Config, num_blocks: int, block_size: int, dtype=torch.float32):
        self.num_blocks, self.block_size = num_blocks, block_size
        self.data = torch.zeros(cfg.n_layer, 2, num_blocks * block_size, cfg.n_head, cfg.head_dim, dtype=dtype)

    def bytes(self) -> int:
        return self.data.numel() * self.data.element_size()


@dataclass
class Batch:
    """A ragged batch. Row i holds `lengths[i]` new tokens starting at position `starts[i]`."""
    tokens: torch.Tensor        # [B, Tq] padded
    starts: torch.Tensor        # [B]
    lengths: torch.Tensor       # [B]
    block_tables: torch.Tensor  # [B, max_blocks] padded with 0


class Attention(nn.Module):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.qkv = nn.Linear(cfg.d_model, 3 * cfg.d_model)
        self.proj = nn.Linear(cfg.d_model, cfg.d_model)

    def forward(self, x, layer: int, pool: KVPool | None, batch: Batch | None):
        B, T, _ = x.shape
        H, D = self.cfg.n_head, self.cfg.head_dim
        q, k, v = self.qkv(x).view(B, T, 3, H, D).unbind(2)
        if pool is None:  # reference path: plain causal attention over the whole sequence
            y = F.scaled_dot_product_attention(q.transpose(1, 2), k.transpose(1, 2), v.transpose(1, 2), is_causal=True)
            return self.proj(y.transpose(1, 2).reshape(B, T, -1))

        bs = pool.block_size
        pos = batch.starts[:, None] + torch.arange(T)[None, :]                     # [B, T]
        valid = torch.arange(T)[None, :] < batch.lengths[:, None]                   # [B, T]
        # write new keys/values into their slots
        slot = batch.block_tables.gather(1, (pos // bs).clamp(max=batch.block_tables.shape[1] - 1)) * bs + pos % bs
        flat_slot = slot[valid]
        pool.data[layer, 0].index_copy_(0, flat_slot, k[valid])
        pool.data[layer, 1].index_copy_(0, flat_slot, v[valid])
        # gather each row's whole context from its blocks
        ctx = int((batch.starts + batch.lengths).max())
        nblk = math.ceil(ctx / bs)
        idx = (batch.block_tables[:, :nblk, None] * bs + torch.arange(bs)[None, None, :]).reshape(B, -1)[:, :ctx]
        K = pool.data[layer, 0][idx]                                                # [B, ctx, H, D]
        V = pool.data[layer, 1][idx]
        kpos = torch.arange(ctx)[None, None, :]                                     # [1, 1, ctx]
        mask = kpos <= pos[:, :, None]                                              # causal + own length
        y = F.scaled_dot_product_attention(q.transpose(1, 2), K.transpose(1, 2), V.transpose(1, 2),
                                           attn_mask=mask[:, None, :, :])
        return self.proj(y.transpose(1, 2).reshape(B, T, -1))


class Block(nn.Module):
    def __init__(self, cfg: Config):
        super().__init__()
        self.ln1, self.ln2 = nn.LayerNorm(cfg.d_model), nn.LayerNorm(cfg.d_model)
        self.attn = Attention(cfg)
        self.mlp = nn.Sequential(nn.Linear(cfg.d_model, 4 * cfg.d_model), nn.GELU(), nn.Linear(4 * cfg.d_model, cfg.d_model))

    def forward(self, x, layer, pool, batch):
        x = x + self.attn(self.ln1(x), layer, pool, batch)
        return x + self.mlp(self.ln2(x))


class GPT(nn.Module):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.tok = nn.Embedding(cfg.vocab_size, cfg.d_model)
        self.pos = nn.Embedding(cfg.max_seq, cfg.d_model)
        self.blocks = nn.ModuleList(Block(cfg) for _ in range(cfg.n_layer))
        self.ln = nn.LayerNorm(cfg.d_model)
        self.head = nn.Linear(cfg.d_model, cfg.vocab_size, bias=False)
        self.head.weight = self.tok.weight
        for name, w in self.named_parameters():
            if w.dim() >= 2:
                nn.init.normal_(w, std=0.02 / (2 * cfg.n_layer) ** 0.5 if name.endswith(("proj.weight", "mlp.2.weight")) else 0.02)

    def forward(self, tokens: torch.Tensor, pool: KVPool | None = None, batch: Batch | None = None):
        T = tokens.shape[1]
        if batch is None:
            pos = torch.arange(T)[None, :]
        else:
            pos = (batch.starts[:, None] + torch.arange(T)[None, :]).clamp(max=self.cfg.max_seq - 1)
        x = self.tok(tokens) + self.pos(pos)
        for i, blk in enumerate(self.blocks):
            x = blk(x, i, pool, batch)
        return self.head(self.ln(x))

    def n_params(self) -> int:
        return sum(p.numel() for p in self.parameters()) - self.tok.weight.numel()

    def save(self, path) -> None:
        torch.save({"config": asdict(self.cfg), "state": self.state_dict()}, path)

    @classmethod
    def load(cls, path) -> "GPT":
        ck = torch.load(path, map_location="cpu", weights_only=True)
        m = cls(Config(**ck["config"]))
        m.load_state_dict(ck["state"])
        return m.eval()
