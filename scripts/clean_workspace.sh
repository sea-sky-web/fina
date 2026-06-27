#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

find . \
  -path './backend/.venv' -prune -o \
  -path './frontend/node_modules' -prune -o \
  -path './data/raw' -prune -o \
  -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.ruff_cache' \) \
  -exec rm -rf {} +

find . \
  -path './backend/.venv' -prune -o \
  -path './frontend/node_modules' -prune -o \
  -path './data/raw' -prune -o \
  -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '*.tsbuildinfo' \) \
  -delete

rm -rf frontend/dist frontend/.cache data/clean/_tmp_refresh
rm -f frontend/vite.config.js frontend/vite.config.d.ts
