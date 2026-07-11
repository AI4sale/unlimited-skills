"""Reserved Stop hook for structured completion receipts.

Unlimited Skills 0.6.7 is retrieval-only.  Raw assistant prose, PR-looking
tokens, URLs, hashes, and test-count strings are not acceptance evidence and
must never trigger durable memory writes.  A later protocol revision will
activate this hook only for a host-supplied, independently verifiable receipt.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    # Consume at most one hook payload so callers can keep the stable hook
    # registration while completion learning remains deliberately disabled.
    try:
        json.load(sys.stdin)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
