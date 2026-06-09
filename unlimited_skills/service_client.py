from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any


class ServiceClientError(RuntimeError):
    """Raised when a hosted service request fails."""


class ServiceResponseError(ServiceClientError):
    """Raised when a hosted service returns an HTTP error."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class ServiceUnavailableError(ServiceClientError):
    """Raised when a hosted service cannot be reached after retries."""


def configured_timeout(default: float = 30.0) -> float:
    value = os.environ.get("UNLIMITED_SKILLS_SERVICE_TIMEOUT", "")
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return max(1.0, parsed)


def configured_retries(default: int = 0) -> int:
    value = os.environ.get("UNLIMITED_SKILLS_SERVICE_RETRIES", "")
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(0, min(parsed, 5))


def _retry_delay(attempt: int) -> float:
    return min(0.25 * (2 ** max(0, attempt - 1)), 2.0)


def request_json(
    url: str,
    *,
    body: bytes,
    headers: dict[str, str],
    method: str = "POST",
    timeout: float = 30.0,
    retry_safe: bool = False,
    max_retries: int | None = None,
    redactor: Any | None = None,
) -> dict[str, Any]:
    effective_timeout = configured_timeout(timeout)
    retries = configured_retries(2 if retry_safe else 0) if max_retries is None else max(0, min(int(max_retries), 5))
    attempts = retries + 1 if retry_safe else 1
    redactor = redactor or str
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=effective_timeout) as response:
                raw = response.read().decode("utf-8")
            try:
                data = json.loads(raw or "{}")
            except json.JSONDecodeError as exc:
                raise ServiceClientError("Registration service returned invalid JSON.") from exc
            if not isinstance(data, dict):
                raise ServiceClientError("Registration service returned a non-object JSON payload.")
            return data
        except urllib.error.HTTPError as exc:
            message = redactor(exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc))
            if retry_safe and exc.code in {429, 500, 502, 503, 504} and attempt < attempts:
                last_error = exc
                time.sleep(_retry_delay(attempt))
                continue
            raise ServiceResponseError(exc.code, f"Registration service returned HTTP {exc.code}: {message}") from exc
        except urllib.error.URLError as exc:
            last_error = exc
            if retry_safe and attempt < attempts:
                time.sleep(_retry_delay(attempt))
                continue
            raise ServiceUnavailableError(f"Registration service is unreachable: {redactor(exc.reason)}") from exc

    if last_error is not None:
        raise ServiceUnavailableError(f"Registration service is unreachable: {redactor(last_error)}") from last_error
    raise ServiceUnavailableError("Registration service is unreachable.")
