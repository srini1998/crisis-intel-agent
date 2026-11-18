"""crisis-engine: train | serve | eval | bench. Each subcommand forwards its own flags (try --help)."""

from __future__ import annotations

import sys


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmds = {"train": "train", "serve": "server", "eval": "evaluate", "bench": "bench"}
    if not argv or argv[0] not in cmds:
        sys.exit(f"usage: crisis-engine {{{','.join(cmds)}}} [options]")
    from importlib import import_module

    import_module(f"crisis.engine.{cmds[argv[0]]}").main(argv[1:])


if __name__ == "__main__":
    main()
