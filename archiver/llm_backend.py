"""LLM backend abstraction layer.

This module provides a protocol/interface for LLM backends, allowing
the application to support different providers in the future while
maintaining a clean separation of concerns.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class LLMResponse:
    """Standardized response from an LLM backend."""

    text: str
    model: Optional[str] = None
    done: bool = True
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and self.done


@runtime_checkable
class LLMBackend(Protocol):
    """Protocol for LLM backend implementations.

    Any class that implements generate() with this signature can be used
    as an LLM backend.
    """

    def generate(
        self,
        *,
        prompt: str,
        model: str,
        timeout_s: float = 120.0,
        images_b64: Optional[list[str]] = None,
        response_format: str | dict[str, Any] | None = None,
        think: bool | str | None = None,
        keep_alive: str | int | None = None,
        options: Optional[dict[str, Any]] = None,
    ) -> LLMResponse:
        """Generate a response from the LLM.

        Args:
            prompt: The prompt text to send to the model.
            model: The model identifier to use.
            timeout_s: Timeout in seconds.
            images_b64: Optional list of base64-encoded images for vision models.
            response_format: Optional Ollama `format` value (`"json"` or schema).
            think: Optional Ollama `think` setting.
            keep_alive: Optional model keep-alive duration.
            options: Optional runtime generation options.

        Returns:
            LLMResponse with the generated text or an error.
        """
        ...


class BaseLLMBackend(ABC):
    """Abstract base class for LLM backends with common functionality."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    @abstractmethod
    def generate(
        self,
        *,
        prompt: str,
        model: str,
        timeout_s: float = 120.0,
        images_b64: Optional[list[str]] = None,
        response_format: str | dict[str, Any] | None = None,
        think: bool | str | None = None,
        keep_alive: str | int | None = None,
        options: Optional[dict[str, Any]] = None,
    ) -> LLMResponse:
        """Generate a response from the LLM."""
        ...

    def generate_with_image_file(
        self,
        *,
        prompt: str,
        model: str,
        image_path: str,
        timeout_s: float = 180.0,
    ) -> LLMResponse:
        """Generate a response using an image file.

        This is a convenience method that reads and encodes the image.
        """
        import base64

        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return self.generate(
            prompt=prompt,
            model=model,
            timeout_s=timeout_s,
            images_b64=[b64],
            keep_alive="5m",
        )
