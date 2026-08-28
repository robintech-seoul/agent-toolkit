"""Shared pytest fixtures and path setup for code-wiki tests."""

from __future__ import annotations

import sys
from pathlib import Path

# Add the plugin's bin/ to sys.path so tests can `import lib.config` etc.
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BIN = PLUGIN_ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))
