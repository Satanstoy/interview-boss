"""Fail the AC-013 run if application/provider logs disclose fixture secrets."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: assert_ac013_log_redaction.py COMPOSE_LOG")
    contents = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    checks = {
        "provider_key": "real-stack-e2e-provider-key" in contents,
        "authorization_header": re.search(r"(?i)authorization\s*:", contents) is not None,
        "raw_input": "AC013_PRIVATE_RAW_SENTINEL" in contents,
        "private_question": "AC013_PRIVATE_QUESTION_SENTINEL" in contents,
        "sensitive_response": "AC013_PRIVATE_RESPONSE_SENTINEL" in contents,
    }
    leaked = [name for name, found in checks.items() if found]
    result = {
        "status": "failed" if leaked else "passed",
        "scanned_bytes": len(contents.encode("utf-8")),
        "forbidden_classes_found": leaked,
    }
    print(json.dumps(result, sort_keys=True))
    if leaked:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
