import sys
from pathlib import Path

# eval/ is a folder of scripts, not a package: make its modules importable in tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
