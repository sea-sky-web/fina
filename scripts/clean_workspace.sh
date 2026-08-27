#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

find . \
  -path './backend/.venv' -prune -o \
  -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.ruff_cache' \) \
  -exec rm -rf {} +

find . \
  -path './backend/.venv' -prune -o \
  -type f -name '*.pyc' \
  -delete
