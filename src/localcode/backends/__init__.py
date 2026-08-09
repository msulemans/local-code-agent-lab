"""Replaceable local model backends for LocalCode controllers."""

from .ollama import BackendError, OllamaBackend

__all__ = ["BackendError", "OllamaBackend"]
