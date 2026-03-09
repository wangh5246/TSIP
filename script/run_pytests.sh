#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if ! .venv/bin/python -c "import pytest" >/dev/null 2>&1; then
  echo "pytest is not installed in .venv. Install it first:"
  echo "  .venv/bin/pip install pytest"
  exit 1
fi

.venv/bin/python -m pytest -q tests
