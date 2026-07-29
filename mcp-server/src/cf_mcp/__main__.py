"""Entry point: ``python -m cf_mcp`` or the ``cf-mcp`` script."""

from __future__ import annotations

from .server import run


def main() -> None:
    run()


if __name__ == "__main__":
    main()
