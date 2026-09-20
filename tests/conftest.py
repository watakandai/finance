import sys
from pathlib import Path

# Tests import the package from the repo root without installing it, which is
# the same thing `python -m finance.cli` does.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
