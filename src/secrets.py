"""Resolve secrets via 1Password CLI (`op`). No plaintext API keys required on disk.

Values that look like `op://Vault/Item/field` (or `op://Vault/Item-UUID/field`)
are fetched at runtime with `op read`. Prefer a Grok Bot secret-request for
`OP_SERVICE_ACCOUNT_TOKEN` (persists in the box secret store). Do not put the
service-account token in `.env` — shell exports get wiped. Plain non-secret
config may still live in `.env`.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("x_pr_monitor.secrets")

OP_PREFIX = "op://"

# Env keys that must never be stored as plaintext in .env for production.
SECRET_ENV_KEYS: tuple[str, ...] = (
    "X_API_KEY",
    "X_API_SECRET",
    "X_BEARER_TOKEN",
    "X_ACCESS_TOKEN",
    "X_ACCESS_TOKEN_SECRET",
)


class OnePasswordError(RuntimeError):
    pass


BOX_SECRETS_PATH = Path("/home/box/sand-data/box-secrets.json")


def ensure_op_service_account_token() -> bool:
    """Load OP_SERVICE_ACCOUNT_TOKEN from Grok Bot secret card if not already in env.

    Plain shell exports are wiped between sessions; the secret-request card persists
    under box-secrets.json. Never logs or returns the token value.
    """
    if os.environ.get("OP_SERVICE_ACCOUNT_TOKEN"):
        return True
    try:
        raw = BOX_SECRETS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        token = (data.get("card") or {}).get("OP_SERVICE_ACCOUNT_TOKEN")
        if token:
            os.environ["OP_SERVICE_ACCOUNT_TOKEN"] = token
            logger.info("Loaded OP_SERVICE_ACCOUNT_TOKEN from Grok Bot secret store")
            return True
    except (OSError, json.JSONDecodeError, TypeError) as e:
        logger.debug("Could not load box secrets: %s", e)
    return False


def op_cli_available() -> bool:
    return shutil.which("op") is not None


def is_op_reference(value: str | None) -> bool:
    return bool(value) and value.strip().startswith(OP_PREFIX)


def op_read(reference: str, *, timeout: float = 30.0) -> str:
    """Read one secret. Requires an active `op` session (`op signin` / desktop app)."""
    ensure_op_service_account_token()
    if not op_cli_available():
        raise OnePasswordError(
            "1Password CLI (`op`) not found on PATH. Install from "
            "https://developer.1password.com/docs/cli/get-started/ then `op signin`."
        )
    ref = reference.strip()
    if not ref.startswith(OP_PREFIX):
        raise OnePasswordError(f"Not an op:// reference: {ref!r}")
    try:
        proc = subprocess.run(
            ["op", "read", ref],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as e:
        raise OnePasswordError(f"Timed out reading {ref}") from e
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise OnePasswordError(
            f"op read failed for {ref}: {err}. "
            "Run `op signin` (or unlock the 1Password desktop app) and confirm the item id/field."
        )
    value = proc.stdout.rstrip("\n")
    if not value:
        raise OnePasswordError(f"op read returned empty value for {ref}")
    return value


def resolve_value(raw: str | None) -> str | None:
    """Return plaintext env value, or resolve op:// via CLI. Never logs the secret."""
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    if is_op_reference(stripped):
        return op_read(stripped)
    return stripped


def inject_op_secrets(keys: Iterable[str] = SECRET_ENV_KEYS) -> list[str]:
    """Resolve op:// values for known secret keys into os.environ (in-memory only).

    Returns list of keys that were resolved from 1Password (names only, never values).
    """
    ensure_op_service_account_token()
    resolved: list[str] = []
    for key in keys:
        raw = os.getenv(key)
        if not is_op_reference(raw):
            continue
        value = op_read(raw)  # type: ignore[arg-type]
        os.environ[key] = value
        resolved.append(key)
        logger.info("Injected secret from 1Password for %s", key)
    return resolved


def verify_startup_secrets(*, require_secret: bool = True) -> dict[str, str]:
    """Confirm X_API_SECRET (and optionally key/bearer) are available after injection.

    Returns status map of key -> 'op' | 'env' | 'missing' (never the secret itself).
    """
    inject_op_secrets()
    status: dict[str, str] = {}
    for key in ("X_API_KEY", "X_API_SECRET", "X_BEARER_TOKEN"):
        raw_before = os.getenv(key)
        # After inject, getenv is plaintext if resolved; we cannot tell op vs env
        # unless we tracked it — check whether original .env had op:// via dotenv
        # already loaded into environ. Track via presence only.
        val = os.getenv(key)
        if not val:
            status[key] = "missing"
        elif is_op_reference(val):
            # inject failed to replace
            status[key] = "unresolved_op_ref"
        else:
            status[key] = "present"
    if require_secret and status.get("X_API_SECRET") != "present":
        raise OnePasswordError(
            "X_API_SECRET is missing. Set it to an op:// reference in .env "
            "(e.g. op://Private/<item-id>/credential) and ensure `op` is signed in."
        )
    return status
