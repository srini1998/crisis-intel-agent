"""A small LLM serving engine: paged KV-cache, continuous batching, schema-constrained decoding.

Built so the crisis agent can run against a server whose scheduling, memory and decoding are
visible and testable, rather than a black box. See docs/engine.md.
"""
