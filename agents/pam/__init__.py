# agents/pam/__init__.py
"""PAM (Programme Architecture Manager) configuration constants."""

PAM_NAME = "PAM"
# No PAM_MODEL. PAM's model comes from agents/model_registry.py like every other agent's: it
# is the "deep" tier, and a sensitive project routes it locally. A constant here had no reader
# left, and it is exactly the thing a maintainer would wire back in believing it authoritative
# - restoring the always-hosted exemption this branch removed. tests/test_model_registry.py
# fails if a model name reappears in this file.
PAM_ROLE = "Programme Architecture Manager"
PAM_GOAL = (
    "Orchestrate the end-to-end delivery of AI-assisted strategy consulting, "
    "coordinating specialist crews and ensuring quality outputs at each stage."
)
