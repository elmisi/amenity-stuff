from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Optional
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class OllamaGenerateResult:
    response: str
    model: Optional[str] = None
    done: Optional[bool] = None
    error: Optional[str] = None


def _post_json(url: str, payload: dict[str, Any], *, timeout_s: float) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def generate(
    *,
    model: str,
    prompt: str,
    base_url: str = "http://localhost:11434",
    timeout_s: float = 120.0,
    images_b64: Optional[list[str]] = None,
    options: Optional[dict[str, Any]] = None,
    response_format: Optional[str] = None,
) -> OllamaGenerateResult:
    url = base_url.rstrip("/") + "/api/generate"
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if response_format:
        payload["format"] = response_format
    if images_b64:
        payload["images"] = images_b64
    if options:
        payload["options"] = options
    data = _post_json(url, payload, timeout_s=timeout_s)
    return OllamaGenerateResult(
        response=str(data.get("response", "")),
        model=data.get("model"),
        done=data.get("done"),
        error=data.get("error") if isinstance(data.get("error"), str) else None,
    )


def generate_with_image_file(
    *,
    model: str,
    prompt: str,
    image_path: str,
    base_url: str = "http://localhost:11434",
    timeout_s: float = 180.0,
) -> OllamaGenerateResult:
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return generate(
        model=model,
        prompt=prompt,
        base_url=base_url,
        timeout_s=timeout_s,
        images_b64=[b64],
    )
