from __future__ import annotations

import json

import httpx
import pytest

from scripts.production_smoke import (
    CONFIRMATION,
    SmokeConfig,
    SmokeFailure,
    assert_issue,
    diagnostics,
    run_smoke,
)


def config(**overrides: object) -> SmokeConfig:
    values = {
        "endpoint": "https://forum.example/graphql",
        "forum": "smoke-forum",
        "author_username": "smoke-user",
        "expected_rule": "No promotional spam",
        "violation_text": "synthetic violation",
        "token_url": "https://auth.example/oauth/token",
        "oauth_client_id": "client",
        "oauth_client_secret": "secret",
        "oauth_audience": "audience",
        "oauth_realm": "realm",
        "login": "smoke@example.com",
        "password": "password",
        "run_id": "123",
        "timeout_seconds": 60,
        "poll_seconds": 0,
        "settle_seconds": 0,
    }
    values.update(overrides)
    return SmokeConfig(**values)  # type: ignore[arg-type]


def action(identifier: str) -> dict[str, object]:
    return {
        "id": identifier,
        "actionType": "report",
        "recommendedAction": "REMOVE",
        "recommendationConfidence": 0.94,
        "recommendationRationale": "Synthetic content violates the rule.",
        "ModerationProfile": {
            "displayName": "bot-smoke-forum-llm-moderator",
            "User": {"username": "bot-smoke-forum-llm-moderator", "isBot": True},
        },
        "User": None,
        "Comment": {"text": "Cited server rule: No promotional spam"},
    }


def issue(count: int) -> dict[str, object]:
    return {
        "id": "issue-1",
        "issueNumber": 7,
        "flaggedServerRuleViolation": True,
        "ActivityFeed": [action(f"action-{number}") for number in range(count)],
    }


def response(data: dict[str, object], status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"data": data})


@pytest.mark.asyncio
async def test_full_create_edit_and_settle_path() -> None:
    issue_reads = 0
    bodies: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal issue_reads
        if request.url.host == "auth.example":
            assert b"synthetic+violation" not in request.content
            return httpx.Response(200, json={"access_token": "token"})
        body = json.loads(request.content)
        bodies.append(body)
        query = body["query"]
        if "SmokeCreate" in query:
            return response({"createDiscussionWithChannelConnections": [{"id": "discussion-1"}]})
        if "SmokeEdit" in query:
            return response({"updateDiscussionWithChannelConnections": {"id": "discussion-1"}})
        if "SmokeIssue" in query:
            issue_reads += 1
            return response({"issues": [issue(1 if issue_reads == 1 else 2)]})
        raise AssertionError(query)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await run_smoke(config(), client)

    assert result == {
        "status": "passed",
        "discussionId": "discussion-1",
        "issueId": "issue-1",
        "issueNumber": 7,
        "createReportVerified": True,
        "editReportVerified": True,
        "duplicateReportActions": 0,
        "retention": "retained-and-labelled",
        "moderationEvents": 2,
        "maximumProviderAttempts": 220,
    }
    assert bodies[0]["variables"]["input"][0]["channelConnections"] == ["smoke-forum"]
    assert "[LLM-SMOKE][RETAINED]" in bodies[0]["variables"]["input"][0][
        "discussionCreateInput"
    ]["title"]


def test_config_requires_fixed_values_https_and_bounded_timeout() -> None:
    env = {
        "MULTIFORUM_GRAPHQL_URL": "https://forum.example/graphql",
        "MULTIFORUM_SMOKE_FORUM": "forum",
        "MULTIFORUM_SMOKE_AUTHOR_USERNAME": "user",
        "MULTIFORUM_SMOKE_EXPECTED_RULE": "rule",
        "MULTIFORUM_SMOKE_VIOLATION_TEXT": "text",
        "MULTIFORUM_OAUTH_TOKEN_URL": "https://auth.example/token",
        "MULTIFORUM_OAUTH_CLIENT_ID": "id",
        "MULTIFORUM_OAUTH_CLIENT_SECRET": "secret",
        "MULTIFORUM_OAUTH_AUDIENCE": "audience",
        "MULTIFORUM_SMOKE_LOGIN": "login",
        "MULTIFORUM_SMOKE_PASSWORD": "password",
        "GITHUB_RUN_ID": "1",
    }
    loaded = SmokeConfig.from_env(env, 60)
    assert loaded.oauth_realm == "Username-Password-Authentication"
    assert loaded.bot_username == "bot-forum-llm-moderator"

    with pytest.raises(SmokeFailure, match="Missing production configuration"):
        SmokeConfig.from_env({**env, "MULTIFORUM_SMOKE_FORUM": ""}, 60)
    with pytest.raises(SmokeFailure, match="absolute HTTPS"):
        SmokeConfig.from_env({**env, "MULTIFORUM_GRAPHQL_URL": "http://forum"}, 60)
    with pytest.raises(SmokeFailure, match="between 60 and 900"):
        SmokeConfig.from_env(env, 30)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"flaggedServerRuleViolation": False}, "server rule"),
        ({"ActivityFeed": []}, "Expected 1"),
        ({"ActivityFeed": [{**action("a"), "recommendedAction": None}]}, "recommendation"),
        (
            {"ActivityFeed": [{**action("a"), "recommendationConfidence": 2}]},
            "confidence",
        ),
        (
            {"ActivityFeed": [{**action("a"), "recommendationRationale": ""}]},
            "rationale",
        ),
        ({"ActivityFeed": [{**action("a"), "Comment": {"text": "other"}}]}, "canonical"),
    ],
)
def test_issue_assertions(change: dict[str, object], message: str) -> None:
    value = {**issue(1), **change}
    with pytest.raises(SmokeFailure, match=message):
        assert_issue(config(), value, 1)


@pytest.mark.asyncio
async def test_diagnostics_returns_only_bounded_status_metadata() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return response(
            {
                "getPipelineSummary": {
                    "attempts": [
                        {
                            "pipelineId": "pipeline-1",
                            "eventType": "discussionChannel.created",
                            "status": "FAILED",
                            "trigger": "EVENT",
                            "attemptNumber": 1,
                            "jobs": [
                                {
                                    "pluginId": "llm-moderation",
                                    "status": "FAILED",
                                    "skippedReason": None,
                                    "message": "must not be logged",
                                }
                            ],
                        }
                    ]
                }
            }
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        from scripts.production_smoke import MultiforumClient

        client = MultiforumClient(config(), raw)
        client.token = "token"
        result = await diagnostics(client, "discussion-1")
    assert "must not be logged" not in result
    assert "llm-moderation" in result


def test_graphql_error_messages_redact_submitted_content_and_credentials() -> None:
    from scripts.production_smoke import MultiforumClient

    client = MultiforumClient(config(), None)  # type: ignore[arg-type]
    client.token = "access-token"
    message = client.safe_message(
        "synthetic violation secret smoke@example.com password access-token"
    )
    assert message == "[redacted] [redacted] [redacted] [redacted] [redacted]"


def test_confirmation_constant_is_deliberately_explicit() -> None:
    assert CONFIRMATION == "RUN PRODUCTION LLM SMOKE"
