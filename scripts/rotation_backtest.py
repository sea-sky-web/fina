"""向后兼容入口：python scripts/rotation_backtest.py [--multi|--validate]

回测引擎已迁移到 backend/app/rotation_engine，本脚本只负责转发。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.rotation_engine.__main__ import cli  # noqa: E402

if __name__ == "__main__":
    cli()
