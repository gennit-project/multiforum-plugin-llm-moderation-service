from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class RuleScope(str, Enum):
    SERVER = "server"
    CHANNEL = "channel"


class Recommendation(str, Enum):
    EDIT = "edit"
    REMOVE = "remove"
    NONE = "none"


class ContentInput(ApiModel):
    type: str = Field(pattern="^(comment|discussion)$")
    id: str = Field(min_length=1)
    title: str | None = None
    body: str = Field(min_length=1)


class RuleInput(ApiModel):
    scope: RuleScope
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class ModerationPolicy(ApiModel):
    model: str | None = None
    temperature: float = Field(default=0, ge=0, le=1)
    max_tokens: int = Field(default=800, ge=64, le=4000, alias="maxTokens")


class ModerationRequest(ApiModel):
    content: ContentInput
    rules: list[RuleInput] = Field(min_length=1)
    policy: ModerationPolicy = Field(default_factory=ModerationPolicy)

    @model_validator(mode="after")
    def unique_rule_keys(self) -> "ModerationRequest":
        keys = [(rule.scope, rule.id) for rule in self.rules]
        if len(keys) != len(set(keys)):
            raise ValueError("rule scope/id pairs must be unique")
        return self


class Violation(ApiModel):
    scope: RuleScope
    rule_id: str = Field(min_length=1, alias="ruleId")


class ModerationResponse(ApiModel):
    violations: list[Violation]
    recommendation: Recommendation
    confidence: float = Field(ge=0, le=1)
    rationale: str


class HealthResponse(ApiModel):
    status: str
    provider_model: str = Field(alias="providerModel")
