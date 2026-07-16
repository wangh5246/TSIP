#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

test_files=()
while IFS= read -r test_file; do
  test_files+=("$test_file")
done < <(find tests -maxdepth 1 -type f -name 'test_*.py' | sort)

python -m pytest -q "${test_files[@]}"
