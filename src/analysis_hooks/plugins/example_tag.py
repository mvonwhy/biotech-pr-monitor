"""Example non-LLM hook: tags alerts that already have a press_release_url."""

from __future__ import annotations

from src.analysis_hooks.base import Alert, AnalysisHookBase
from src.analysis_hooks.registry import register_hook


class TagHasPrLinkHook(AnalysisHookBase):
    name = "tag_has_pr_link"
    uses_inference = False

    def run(self, alert: Alert) -> Alert:
        alert["has_press_release"] = bool(alert.get("press_release_url"))
        return alert


register_hook(TagHasPrLinkHook(), replace_noop=True)
