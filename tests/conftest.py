"""Test setup: point DB + display dir at a temp location before orchestrator
modules import. This must run before any `from display_writer import ...`
or `from database import ...` anywhere in the process.
"""

import os
import sys
import tempfile

# Create a session-lifetime temp dir for DB + display files.
_TMP = tempfile.mkdtemp(prefix="xy-phase1-tests-")
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")
os.environ["DISPLAY_DIR"] = os.path.join(_TMP, "display")
os.environ["LOG_DIR"] = os.path.join(_TMP, "logs")
os.environ["BACKUP_DIR"] = os.path.join(_TMP, "backups")
# Prevent load_dotenv from clobbering — the file may or may not exist.
os.environ["XY_TEST_TMP"] = _TMP

# Make `orchestrator/` importable as top-level package dir (matches run.sh).
_ORCH_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "orchestrator"
)
if _ORCH_DIR not in sys.path:
    sys.path.insert(0, _ORCH_DIR)
