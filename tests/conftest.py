"""Pytest conftest — sets up test mode before any imports."""

import os
import sys

os.environ["RASPIMIDIHUB_TEST_MODE"] = "1"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "plugins"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
