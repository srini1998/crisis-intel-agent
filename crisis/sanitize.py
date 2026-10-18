"""Quarantine instruction-like text in feed strings before they reach the model.

This is a heuristic first layer, not a guarantee: a paraphrased instruction can slip past
these patterns. The structural verifier (alert level from structured fields only, numbers
must be cited) is the layer that does not depend on recognizing the attack.
"""

from __future__ import annotations

import copy
import re

from .sources import Doc

PATTERNS = [
    r"\b(ignore|disregard|forget|override)\b[^.]{0,40}\b(previous|prior|above|all|earlier|system)\b[^.]{0,40}\b(instructions?|prompts?|rules?|messages?)\b",
    r"\b(system|developer|admin(istrator)?)\s+(notice|message|prompt|instruction|override)\b",
    r"\b(to|for|attention)\s+(the\s+)?(ai|assistant|model|llm|chatbot)\b",
    r"\byou\s+(must|should|are\s+required\s+to|will)\s+(now\s+)?(report|state|say|write|include|output|respond)\b",
    r"\binclude\s+the\s+word\b",
    r"\bnew\s+instructions?\b",
]
_RE = re.compile("|".join(f"(?:{p})" for p in PATTERNS), re.IGNORECASE)
_SENTENCE = re.compile(r"[^.!?\n]*[.!?\n]?")
MARK = "[removed: instruction-like text]"


def quarantine_text(text: str) -> tuple[str, list[str]]:
    """Drop whole sentences that contain an instruction-like pattern. Returns (clean, removed)."""
    removed, kept = [], []
    for sentence in _SENTENCE.findall(text):
        if sentence and _RE.search(sentence):
            removed.append(sentence.strip())
            kept.append(f" {MARK} ")
        else:
            kept.append(sentence)
    return "".join(kept).strip(), removed


def sanitize(docs: list[Doc]) -> tuple[list[Doc], list[dict]]:
    out, events = [], []
    for d in docs:
        c = copy.deepcopy(d)
        for field in ("title", "text"):
            clean, removed = quarantine_text(getattr(c, field))
            if removed:
                setattr(c, field, clean)
                events.append({"doc": d.key, "field": field, "removed": removed})
        out.append(c)
    return out, events
