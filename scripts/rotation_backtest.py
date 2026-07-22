"""向后兼容入口：python scripts/rotation_backtest.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rotation.__main__ import main

if __name__ == "__main__":
    main()
