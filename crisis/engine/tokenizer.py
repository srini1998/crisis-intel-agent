"""Byte-level tokenizer. Every byte is a token, plus BOS and EOS.

Byte tokens make constrained decoding exact: an allowed set of bytes *is* an allowed set of tokens.
"""

from __future__ import annotations

BOS = 256
EOS = 257
VOCAB_SIZE = 258


def encode(text: str, bos: bool = True) -> list[int]:
    ids = list(text.encode("utf-8"))
    return [BOS, *ids] if bos else ids


def decode(ids: list[int]) -> str:
    return bytes(i for i in ids if i < 256).decode("utf-8", errors="replace")


def chat_prompt(messages: list[dict]) -> str:
    """Flatten chat messages into the one template the model was trained on."""
    parts = [f"<|{m['role']}|>\n{m['content']}\n" for m in messages]
    return "".join(parts) + "<|assistant|>\n"
