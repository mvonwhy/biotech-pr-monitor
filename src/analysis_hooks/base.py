"""Analysis hook Protocol / ABC. No LLM in the default path."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, MutableMapping, Protocol, runtime_checkable

Alert = MutableMapping[str, Any]


@runtime_checkable
class AnalysisHook(Protocol):
    """Transform or annotate an alert. Must be side-effect free aside from the alert dict."""

    name: str
    # If True, this hook may call an LLM / consume inference tokens.
    uses_inference: bool

    def run(self, alert: Alert) -> Alert: ...


class AnalysisHookBase(ABC):
    name: str = "base"
    uses_inference: bool = False

    @abstractmethod
    def run(self, alert: Alert) -> Alert:
        raise NotImplementedError


class NoOpHook(AnalysisHookBase):
    """Default hook — passes alert through unchanged. Zero inference tokens."""

    name = "noop"
    uses_inference = False

    def run(self, alert: Alert) -> Alert:
        return alert


def run_hooks(alert: Alert, hooks: list[AnalysisHook]) -> Alert:
    """Apply hooks in order. Skips inference hooks unless ALLOW_INFERENCE_HOOKS=1."""
    import os

    allow_inference = os.getenv("ALLOW_INFERENCE_HOOKS", "").lower() in ("1", "true", "yes")
    out: Alert = alert
    applied: list[str] = []
    for hook in hooks:
        if getattr(hook, "uses_inference", False) and not allow_inference:
            continue
        out = hook.run(out)
        applied.append(getattr(hook, "name", hook.__class__.__name__))
    out["analysis_hooks_applied"] = applied
    return out
