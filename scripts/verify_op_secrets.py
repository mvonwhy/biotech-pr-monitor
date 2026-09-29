#!/usr/bin/env python3
"""Verify 1Password secret injection without printing secret values."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.secrets import OnePasswordError, inject_op_secrets, is_op_reference, op_cli_available  # noqa: E402
import os
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def main() -> int:
    print("op CLI on PATH:", op_cli_available())
    if not op_cli_available():
        print("Install: https://developer.1password.com/docs/cli/get-started/")
        return 1
    refs = {k: os.getenv(k) for k in ("X_API_KEY", "X_API_SECRET", "X_BEARER_TOKEN")}
    for k, v in refs.items():
        kind = "op://" if is_op_reference(v) else ("set" if v else "missing")
        print(f"  {k}: config={kind}")
    try:
        resolved = inject_op_secrets()
        print("Resolved from 1Password:", ", ".join(resolved) or "(none — already plaintext or unset)")
        for k in ("X_API_KEY", "X_API_SECRET", "X_BEARER_TOKEN"):
            val = os.getenv(k) or ""
            ok = bool(val) and not is_op_reference(val)
            print(f"  {k}: {'OK (loaded, value hidden)' if ok else 'MISSING/UNRESOLVED'}")
        if not (os.getenv("X_API_SECRET") and not is_op_reference(os.getenv("X_API_SECRET"))):
            return 1
        print("Startup secret check passed.")
        return 0
    except OnePasswordError as e:
        print("FAILED:", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
