"""Run a bounded, opt-in smoke test through the production Multiforum API."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx

CONFIRMATION = "RUN PRODUCTION LLM SMOKE"
CREATE_MUTATION = """
mutation SmokeCreate($input: [DiscussionCreateInputWithChannels!]!) {
  createDiscussionWithChannelConnections(input: $input) { id }
}
"""
UPDATE_MUTATION = """
mutation SmokeEdit($where: DiscussionWhere!, $update: DiscussionUpdateInput!) {
  updateDiscussionWithChannelConnections(
    where: $where
    discussionUpdateInput: $update
    channelConnections: []
    channelDisconnections: []
  ) { id }
}
"""
ISSUE_QUERY = """
query SmokeIssue($discussionId: ID!, $forum: String!) {
  issues(where: { relatedDiscussionId: $discussionId, channelUniqueName: $forum }) {
    id
    issueNumber
    flaggedServerRuleViolation
    ActivityFeed(options: { sort: { createdAt: ASC } }) {
      id
      actionType
      recommendedAction
      recommendationConfidence
      recommendationRationale
      ModerationProfile { displayName User { username isBot } }
      User { username isBot }
      Comment { text }
    }
  }
}
"""
PIPELINE_QUERY = """
query SmokePipeline($discussionId: ID!) {
  getPipelineSummary(targetId: $discussionId, targetType: "Discussion") {
    attempts {
      pipelineId eventType status trigger attemptNumber
      jobs { pluginId status skippedReason message }
    }
  }
}
"""


class SmokeFailure(RuntimeError):
    """A concise failure safe to print in workflow logs."""


@dataclass(frozen=True)
class SmokeConfig:
    endpoint: str
    forum: str
    author_username: str
    expected_rule: str
    violation_text: str
    token_url: str
    oauth_client_id: str
    oauth_client_secret: str
    oauth_audience: str
    oauth_realm: str
    login: str
    password: str
    run_id: str
    timeout_seconds: int = 300
    poll_seconds: float = 5
    settle_seconds: float = 30

    @classmethod
    def from_env(cls, env: dict[str, str], timeout_seconds: int) -> SmokeConfig:
        names = {
            "endpoint": "MULTIFORUM_GRAPHQL_URL",
            "forum": "MULTIFORUM_SMOKE_FORUM",
            "author_username": "MULTIFORUM_SMOKE_AUTHOR_USERNAME",
            "expected_rule": "MULTIFORUM_SMOKE_EXPECTED_RULE",
            "violation_text": "MULTIFORUM_SMOKE_VIOLATION_TEXT",
            "token_url": "MULTIFORUM_OAUTH_TOKEN_URL",
            "oauth_client_id": "MULTIFORUM_OAUTH_CLIENT_ID",
            "oauth_client_secret": "MULTIFORUM_OAUTH_CLIENT_SECRET",
            "oauth_audience": "MULTIFORUM_OAUTH_AUDIENCE",
            "login": "MULTIFORUM_SMOKE_LOGIN",
            "password": "MULTIFORUM_SMOKE_PASSWORD",
            "run_id": "GITHUB_RUN_ID",
        }
        missing = [source for source in names.values() if not env.get(source, "").strip()]
        if missing:
            raise SmokeFailure("Missing production configuration: " + ", ".join(missing))
        if not 60 <= timeout_seconds <= 900:
            raise SmokeFailure("Timeout must be between 60 and 900 seconds.")
        values = {target: env[source].strip() for target, source in names.items()}
        values["oauth_realm"] = env.get(
            "MULTIFORUM_OAUTH_REALM", "Username-Password-Authentication"
        ).strip()
        for field in ("endpoint", "token_url"):
            url = httpx.URL(values[field])
            if url.scheme != "https" or not url.host or url.userinfo:
                raise SmokeFailure(f"{names[field]} must be an absolute HTTPS URL.")
        return cls(**values, timeout_seconds=timeout_seconds)

    @property
    def bot_username(self) -> str:
        normalized = re.sub(r"-+", "-", re.sub(r"[^a-z0-9_-]", "-", self.forum.lower()))
        return f"bot-{normalized.strip('-_')}-llm-moderator"


class MultiforumClient:
    def __init__(self, config: SmokeConfig, client: httpx.AsyncClient):
        self.config = config
        self.client = client
        self.token = ""

    def safe_message(self, value: object) -> str:
        message = str(value)
        for secret in (
            self.config.violation_text,
            self.config.oauth_client_secret,
            self.config.login,
            self.config.password,
            self.token,
        ):
            if secret:
                message = message.replace(secret, "[redacted]")
        return message

    async def authenticate(self) -> None:
        response = await self.client.post(
            self.config.token_url,
            data={
                "grant_type": "http://auth0.com/oauth/grant-type/password-realm",
                "client_id": self.config.oauth_client_id,
                "client_secret": self.config.oauth_client_secret,
                "audience": self.config.oauth_audience,
                "realm": self.config.oauth_realm,
                "username": self.config.login,
                "password": self.config.password,
                "scope": "openid profile email",
            },
        )
        if response.status_code != 200:
            raise SmokeFailure(
                f"Automation identity authentication failed (HTTP {response.status_code})."
            )
        try:
            self.token = response.json()["access_token"]
        except (KeyError, TypeError, ValueError) as error:
            raise SmokeFailure(
                "Authentication response did not contain an access token."
            ) from error

    async def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.post(
            self.config.endpoint,
            headers={"authorization": f"Bearer {self.token}"},
            json={"query": query, "variables": variables},
        )
        if response.status_code != 200:
            raise SmokeFailure(f"Multiforum GraphQL returned HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as error:
            raise SmokeFailure("Multiforum GraphQL returned invalid JSON.") from error
        errors = payload.get("errors") if isinstance(payload, dict) else None
        if errors:
            messages = [
                self.safe_message(item.get("message", "GraphQL request failed"))
                for item in errors
            ]
            raise SmokeFailure("; ".join(messages))
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise SmokeFailure("Multiforum GraphQL response did not contain data.")
        return data


def report_actions(issue: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        action
        for action in issue.get("ActivityFeed", [])
        if action.get("actionType") == "report"
    ]


def assert_issue(config: SmokeConfig, issue: dict[str, Any], expected_reports: int) -> None:
    actions = report_actions(issue)
    if len(actions) != expected_reports:
        raise SmokeFailure(
            f"Expected {expected_reports} bot report action(s), found {len(actions)}."
        )
    if not issue.get("flaggedServerRuleViolation"):
        raise SmokeFailure("The smoke issue did not cite a server rule violation.")
    for action in actions:
        profile = action.get("ModerationProfile") or {}
        user = profile.get("User") or action.get("User") or {}
        actor = profile.get("displayName") or user.get("username")
        if actor != config.bot_username or user.get("isBot") is not True:
            raise SmokeFailure("A report action was not authored by the expected bot identity.")
        if action.get("recommendedAction") not in {"EDIT", "REMOVE"}:
            raise SmokeFailure("A report action did not contain an edit/remove recommendation.")
        confidence = action.get("recommendationConfidence")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise SmokeFailure("A report action did not contain valid recommendation confidence.")
        if not str(action.get("recommendationRationale") or "").strip():
            raise SmokeFailure("A report action did not contain recommendation rationale.")
        comment = action.get("Comment") or {}
        if config.expected_rule not in str(comment.get("text") or ""):
            raise SmokeFailure("A report action did not cite the expected canonical rule.")


async def read_issue(client: MultiforumClient, discussion_id: str) -> dict[str, Any] | None:
    data = await client.graphql(
        ISSUE_QUERY, {"discussionId": discussion_id, "forum": client.config.forum}
    )
    issues = data.get("issues") or []
    if len(issues) > 1:
        raise SmokeFailure("More than one moderation issue exists for the smoke discussion.")
    return issues[0] if issues else None


async def diagnostics(client: MultiforumClient, discussion_id: str) -> str:
    try:
        data = await client.graphql(PIPELINE_QUERY, {"discussionId": discussion_id})
    except SmokeFailure as error:
        return f"pipeline diagnostics unavailable: {error}"
    summary = data.get("getPipelineSummary") or {}
    attempts = summary.get("attempts") or []
    safe = [
        {
            "event": attempt.get("eventType"),
            "status": attempt.get("status"),
            "trigger": attempt.get("trigger"),
            "attempt": attempt.get("attemptNumber"),
            "jobs": [
                {
                    "plugin": job.get("pluginId"),
                    "status": job.get("status"),
                    "skipped": job.get("skippedReason"),
                }
                for job in attempt.get("jobs") or []
            ],
        }
        for attempt in attempts
    ]
    return json.dumps(safe, separators=(",", ":"))


async def wait_for_reports(
    client: MultiforumClient, discussion_id: str, expected_reports: int
) -> dict[str, Any]:
    deadline = time.monotonic() + client.config.timeout_seconds
    last_count = 0
    while time.monotonic() < deadline:
        issue = await read_issue(client, discussion_id)
        if issue:
            last_count = len(report_actions(issue))
            if last_count >= expected_reports:
                assert_issue(client.config, issue, expected_reports)
                return issue
        await asyncio.sleep(client.config.poll_seconds)
    detail = await diagnostics(client, discussion_id)
    raise SmokeFailure(
        f"Timed out waiting for {expected_reports} report(s); observed {last_count}. {detail}"
    )


async def run_smoke(config: SmokeConfig, client: httpx.AsyncClient) -> dict[str, Any]:
    api = MultiforumClient(config, client)
    await api.authenticate()
    marker = f"llm-smoke-{config.run_id}"
    created = await api.graphql(
        CREATE_MUTATION,
        {
            "input": [
                {
                    "discussionCreateInput": {
                        "title": f"[LLM-SMOKE][RETAINED] {marker}",
                        "body": config.violation_text,
                        "hasDownload": False,
                        "Author": {
                            "connect": {
                                "where": {"node": {"username": config.author_username}}
                            }
                        },
                    },
                    "channelConnections": [config.forum],
                }
            ]
        },
    )
    discussions = created.get("createDiscussionWithChannelConnections") or []
    discussion_id = discussions[0].get("id") if discussions else None
    if not discussion_id:
        raise SmokeFailure("Smoke discussion creation did not return an ID.")

    first_issue = await wait_for_reports(api, discussion_id, 1)
    await api.graphql(
        UPDATE_MUTATION,
        {
            "where": {"id": discussion_id},
            "update": {"body": config.violation_text + "\n\n[edited smoke event]"},
        },
    )
    second_issue = await wait_for_reports(api, discussion_id, 2)
    await asyncio.sleep(config.settle_seconds)
    settled_issue = await read_issue(api, discussion_id)
    if not settled_issue:
        raise SmokeFailure("The moderation issue disappeared during the settle check.")
    assert_issue(config, settled_issue, 2)
    return {
        "status": "passed",
        "discussionId": discussion_id,
        "issueId": second_issue["id"],
        "issueNumber": second_issue["issueNumber"],
        "createReportVerified": first_issue["id"] == second_issue["id"],
        "editReportVerified": True,
        "duplicateReportActions": 0,
        "retention": "retained-and-labelled",
        "moderationEvents": 2,
        "maximumProviderAttempts": 220,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    return parser.parse_args(argv)


async def async_main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.confirm != CONFIRMATION:
        raise SmokeFailure(f"Confirmation must exactly match: {CONFIRMATION}")
    config = SmokeConfig.from_env(dict(os.environ), args.timeout_seconds)
    async with httpx.AsyncClient(timeout=30) as client:
        result = await run_smoke(config, client)
    print(json.dumps(result, separators=(",", ":")))
    return 0


def main() -> int:
    try:
        return asyncio.run(async_main(sys.argv[1:]))
    except SmokeFailure as error:
        print(f"production smoke failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
