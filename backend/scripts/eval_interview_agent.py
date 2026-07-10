#!/usr/bin/env python3
"""Entry point for the InterviewBoss eval framework.

Delegates to the eval_framework package. Run with:
    RUN_REAL_INTERVIEW_EVAL=1 PYTHONPATH=backend:backend/scripts python3 backend/scripts/eval_interview_agent.py --scenario greeting_role_adherence
"""

import sys
from pathlib import Path

# Add scripts directory to path so eval_framework package can be imported
scripts_dir = str(Path(__file__).resolve().parent)
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

from eval_framework.runner import main

if __name__ == "__main__":
    raise SystemExit(main())
