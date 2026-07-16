#!/usr/bin/env python3
"""Stable executable wrapper for the WayBill formal CLI."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from script.waybill_formal_cli import main  # noqa: E402
from waybill_formal.core import FormalError  # noqa: E402


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FormalError as exc:
        print(f"formal gate failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
