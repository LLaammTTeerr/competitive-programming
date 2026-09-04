"""Entry point: ``python -m polygon_mcp`` or the ``polygon-mcp`` script."""

from __future__ import annotations

from .server import run


def main() -> None:
    run()


if __name__ == "__main__":
    main()
