"""Drop-in analysis plugins. Modules here may call register_hook() on import.

LLM-based analyzers MUST set uses_inference=True and remain disabled unless
ALLOW_INFERENCE_HOOKS=1. Core monitoring uses zero inference tokens by default.
"""
