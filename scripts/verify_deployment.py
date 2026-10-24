#!/usr/bin/env python3
"""Verify a deployed moderation service without exposing credentials."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Response:
    status: int
    body: dict[str, Any]


def _decode_body(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object response")
    return parsed


def request_json(
    *,
    url: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    api_key: str | None = None,
) -> Response:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"content-type": "application/json", "user-agent": "multiforum-deploy-check"}
    if api_key is not None:
        headers["x-api-key"] = api_key
        headers["x-correlation-id"] = "deployment-smoke-check"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=130) as response:
            return Response(response.status, _decode_body(response.read()))
    except HTTPError as error:
        return Response(error.code, _decode_body(error.read()))
    except URLError as error:
        raise RuntimeError(f"Could not reach moderation service: {error.reason}") from error


def moderation_payload() -> dict[str, Any]:
    return {
        "content": {
            "type": "comment",
            "id": "deployment-smoke-check",
            "body": "This is a harmless deployment verification message.",
        },
        "rules": [
            {
                "scope": "server",
                "id": "server:deployment-smoke-check",
                "text": "Do not include instructions for manufacturing explosives.",
            }
        ],
        "policy": {"temperature": 0, "maxTokens": 300},
    }


def _validate_verdict(body: dict[str, Any]) -> None:
    if not isinstance(body.get("violations"), list):
        raise RuntimeError("Live moderation response is missing violations")
    if body.get("recommendation") not in {"edit", "remove", "none"}:
        raise RuntimeError("Live moderation response has an invalid recommendation")
    confidence = body.get("confidence")
    if not isinstance(confidence, int | float) or isinstance(confidence, bool):
        raise RuntimeError("Live moderation response has an invalid confidence")
    if not 0 <= confidence <= 1:
        raise RuntimeError("Live moderation response confidence is outside 0..1")
    if not isinstance(body.get("rationale"), str):
        raise RuntimeError("Live moderation response is missing a rationale")


def verify(*, service_url: str, api_key: str, run_live_moderation: bool) -> list[str]:
    base_url = service_url.rstrip("/")
    checks: list[str] = []

    health = request_json(url=f"{base_url}/health")
    if health.status != 200 or health.body.get("status") != "ok":
        raise RuntimeError(f"Health check failed with HTTP {health.status}")
    if not isinstance(health.body.get("providerModel"), str):
        raise RuntimeError("Health check did not report the provider model")
    checks.append("health endpoint is ready")

    unauthorized = request_json(
        url=f"{base_url}/moderate",
        method="POST",
        payload=moderation_payload(),
    )
    if unauthorized.status != 401:
        raise RuntimeError(
            "Unauthenticated moderation was not rejected; expected HTTP 401, "
            f"received HTTP {unauthorized.status}"
        )
    checks.append("unauthenticated moderation is rejected")

    if run_live_moderation:
        live = request_json(
            url=f"{base_url}/moderate",
            method="POST",
            payload=moderation_payload(),
            api_key=api_key,
        )
        if live.status != 200:
            raise RuntimeError(f"Authenticated live moderation failed with HTTP {live.status}")
        _validate_verdict(live.body)
        checks.append("authenticated live moderation returned a structured verdict")

    return checks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--run-live-moderation", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        checks = verify(
            service_url=args.service_url,
            api_key=args.api_key,
            run_live_moderation=args.run_live_moderation,
        )
    except (RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"Verification failed: {error}", file=sys.stderr)
        return 1

    for check in checks:
        print(f"PASS: {check}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
