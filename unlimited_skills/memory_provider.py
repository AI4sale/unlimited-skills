"""JSON-over-stdio adapter from Unlimited Skills context to Company Memory."""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from .memory import (
    REQUEST_SCHEMA,
    _load_state,
    _node_request,
    maintain_after_request,
    maintain_before_request,
    record_access_receipt,
)


RESPONSE_SCHEMA = "unlimited-skills.business-context-response.v1"


def provide(
    request: dict,
    state_path: Path,
    *,
    opener=None,
    env=None,
) -> dict:
    if not isinstance(request, dict) or request.get("schema_version") != REQUEST_SCHEMA:
        raise ValueError("invalid provider request")
    values = os.environ if env is None else env
    bundle = state_path.resolve().parent
    maintenance_kwargs = {"opener": opener} if opener is not None else {}
    maintain_before_request(state_path, **maintenance_kwargs)
    state = _load_state(bundle)
    operation = str(request.get("operation") or "")
    request_id = str(request.get("request_id") or f"provider:{uuid.uuid4().hex}")
    kwargs = {"opener": opener} if opener is not None else {}
    if operation == "doctor":
        result = _node_request(
            bundle,
            state,
            role="executor",
            path="/v1/health",
            request_id=request_id,
            **kwargs,
        )
    elif operation == "retrieve":
        task_id = str(
            request.get("task_id")
            or values.get("UNLIMITED_SKILLS_TASK_ID")
            or f"unlimited-skills:{request_id}"
        )
        role = str(values.get("UNLIMITED_SKILLS_MEMORY_ROLE") or "executor").casefold()
        if role not in {"executor", "checker"}:
            raise ValueError("invalid Company Memory role")
        result = _node_request(
            bundle,
            state,
            role=role,
            path="/v1/knowledge-requests",
            method="POST",
            payload={
                "schema_version": REQUEST_SCHEMA,
                "request_id": request_id,
                "operation": "retrieve",
                "task_id": task_id,
                "query": str(request.get("query") or ""),
            },
            request_id=request_id,
            **kwargs,
        )
        record_access_receipt(bundle, task_id=task_id, role=role, response=result)
        maintain_after_request(state_path, **maintenance_kwargs)
    else:
        result = {
            "schema_version": RESPONSE_SCHEMA,
            "request_id": request_id,
            "status": "ignored",
            "reason": "unsupported_operation",
        }
    result["schema_version"] = RESPONSE_SCHEMA
    result["request_id"] = request_id
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = provide(json.load(sys.stdin), args.state)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception:
        print(
            json.dumps(
                {
                    "schema_version": RESPONSE_SCHEMA,
                    "request_id": "invalid",
                    "status": "error",
                    "reason": "company_memory_provider_unavailable",
                },
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
