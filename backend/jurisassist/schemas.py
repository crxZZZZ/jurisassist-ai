from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginInput(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=256)


class ConversationInput(BaseModel):
    title: str = Field(default="Nova consulta", min_length=1, max_length=120)


class MessageInput(BaseModel):
    content: str = Field(min_length=3, max_length=4000)


class AnalyzeInput(BaseModel):
    document_id: str


class FeedbackInput(BaseModel):
    message_id: str
    rating: Literal[-1, 1]
    comment: str = Field(default="", max_length=2000)


class ReviewInput(BaseModel):
    decision: Literal["pending", "approved", "disagreed"]
    note: str = Field(default="", max_length=2000)


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2500)
    citation_ids: list[str] = Field(min_length=1, max_length=5)


class LegalAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["answered", "clarification", "insufficient"]
    summary: str = Field(max_length=1200)
    claims: list[Claim] = Field(default_factory=list, max_length=8)
    questions: list[str] = Field(default_factory=list, max_length=3)


class QueryIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["research", "clarification", "out_of_scope"]
    questions: list[str] = Field(default_factory=list, max_length=3)


class ContractFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(max_length=200)
    detail: str = Field(max_length=1500)
    priority: Literal["low", "medium", "high"]
    contract_chunk_id: str
    quote: str = Field(default="", max_length=1000)
    citation_ids: list[str] = Field(min_length=1, max_length=5)
    checklist: str = Field(max_length=300)


class ContractAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(max_length=2000)
    obligations: list[Claim] = Field(default_factory=list, max_length=10)
    deadlines: list[Claim] = Field(default_factory=list, max_length=10)
    findings: list[ContractFinding] = Field(default_factory=list, max_length=12)


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)


class ArticleArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    article: str = Field(min_length=1, max_length=30, pattern=r"^[\dA-Za-z .º°-]+$")


class DocumentsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    query: str = Field(min_length=1, max_length=500)


class ExperimentInput(BaseModel):
    mode: Literal["text", "vector", "hybrid"] = "hybrid"

    @field_validator("mode")
    @classmethod
    def valid_mode(cls, value):
        return value
