"""LLM-orchestrated testing framework for pytest."""

from .models import TestSpec, Verdict, StepResult, Step, TestMeta, VerdictSpec
from .plugin_base import LLMPlugin
from .runner import run_llm_test

__version__ = "0.1.0"

__all__ = [
    # Models
    "TestSpec",
    "Verdict",
    "StepResult",
    "Step",
    "TestMeta",
    "VerdictSpec",
    # Plugin system
    "LLMPlugin",
    # Runner
    "run_llm_test",
]
