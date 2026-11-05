import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE), str(HERE.parents[1])]  # golden/clinic (app) + repo root (core)
