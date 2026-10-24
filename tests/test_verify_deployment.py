import pytest

from scripts import verify_deployment


def test_verify_checks_health_and_rejects_unauthenticated_requests(monkeypatch):
    responses = iter(
        [
            verify_deployment.Response(200, {"status": "ok", "providerModel": "gpt-4o-mini"}),
            verify_deployment.Response(401, {"detail": "Invalid API key"}),
        ]
    )
    monkeypatch.setattr(verify_deployment, "request_json", lambda **_kwargs: next(responses))

    checks = verify_deployment.verify(
        service_url="https://moderation.example/",
        api_key="service-secret",
        run_live_moderation=False,
    )

    assert checks == [
        "health endpoint is ready",
        "unauthenticated moderation is rejected",
    ]


def test_verify_optionally_checks_a_live_structured_verdict(monkeypatch):
    responses = iter(
        [
            verify_deployment.Response(200, {"status": "ok", "providerModel": "gpt-4o-mini"}),
            verify_deployment.Response(401, {"detail": "Invalid API key"}),
            verify_deployment.Response(
                200,
                {
                    "violations": [],
                    "recommendation": "none",
                    "confidence": 0.1,
                    "rationale": "No violation",
                },
            ),
        ]
    )
    monkeypatch.setattr(verify_deployment, "request_json", lambda **_kwargs: next(responses))

    checks = verify_deployment.verify(
        service_url="https://moderation.example",
        api_key="service-secret",
        run_live_moderation=True,
    )

    assert checks[-1] == "authenticated live moderation returned a structured verdict"


@pytest.mark.parametrize(
    ("responses", "message"),
    [
        (
            [verify_deployment.Response(503, {"detail": "unavailable"})],
            "Health check failed with HTTP 503",
        ),
        (
            [
                verify_deployment.Response(200, {"status": "ok", "providerModel": "gpt-4o-mini"}),
                verify_deployment.Response(200, {}),
            ],
            "Unauthenticated moderation was not rejected",
        ),
    ],
)
def test_verify_fails_closed(monkeypatch, responses, message):
    queued = iter(responses)
    monkeypatch.setattr(verify_deployment, "request_json", lambda **_kwargs: next(queued))

    with pytest.raises(RuntimeError, match=message):
        verify_deployment.verify(
            service_url="https://moderation.example",
            api_key="service-secret",
            run_live_moderation=False,
        )


@pytest.mark.parametrize(
    "body",
    [
        {"recommendation": "none", "confidence": 0.1, "rationale": "ok"},
        {"violations": [], "recommendation": "maybe", "confidence": 0.1, "rationale": "ok"},
        {"violations": [], "recommendation": "none", "confidence": True, "rationale": "ok"},
        {"violations": [], "recommendation": "none", "confidence": 2, "rationale": "ok"},
        {"violations": [], "recommendation": "none", "confidence": 0.1},
    ],
)
def test_live_verdict_validation_fails_closed(body):
    with pytest.raises(RuntimeError):
        verify_deployment._validate_verdict(body)
