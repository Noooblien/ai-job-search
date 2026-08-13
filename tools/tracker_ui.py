#!/usr/bin/env python3
"""Launch the local job tracker UI (127.0.0.1 only).

Usage:
    python3 tools/tracker_ui.py
    python3 tools/tracker_ui.py --port 8765
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from tracker.server import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
