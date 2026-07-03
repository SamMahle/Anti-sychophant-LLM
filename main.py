"""Entry point: python main.py [chat|ask|outcome|pending|corpus|heartbeat]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from interfaces.cli import main

if __name__ == "__main__":
    sys.exit(main())
