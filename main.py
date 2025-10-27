"""Thin wrapper module for backwards-compatible CLI execution."""

from __future__ import annotations

from amul_stock_watcher.cli import main

__all__ = ["main"]

if __name__ == "__main__":
    main()
