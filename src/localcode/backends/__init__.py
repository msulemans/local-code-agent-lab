"""Replaceable local model backends for LocalCode controllers."""

from .ollama import BackendError, OllamaBackend
from .ollama_loop import OllamaLoopBackend
from .openai_responses import OpenAIResponsesLoopBackend

__all__ = ["BackendError", "OllamaBackend", "OllamaLoopBackend", "OpenAIResponsesLoopBackend"]
