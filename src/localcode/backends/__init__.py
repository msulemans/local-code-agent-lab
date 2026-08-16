"""Replaceable local model backends for LocalCode controllers."""

from .ollama import BackendError, OllamaBackend
from .ollama_loop import OllamaLoopBackend

__all__ = ["BackendError", "OllamaBackend", "OllamaLoopBackend"]
