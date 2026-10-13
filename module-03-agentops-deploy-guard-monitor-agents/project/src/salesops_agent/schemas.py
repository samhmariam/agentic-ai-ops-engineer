"""Versioned data and tool schemas.

Two kinds of schema live here:
  - CRM record schemas: the dataset is validated against these on load, so a
    malformed or drifted data file fails at startup rather than inside a tool call.
  - Tool input schemas: each tool's arguments are validated before the tool runs,
    and their field descriptions are what the model sees.

Bump DATA_SCHEMA_VERSION when a record schema changes and a tool's `version` in
tools.py when its input schema or behaviour changes.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Literal, Optional, Type

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DATA_SCHEMA_VERSION = "1.0"

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
OPEN_STAGES = ("Discovery", "Qualification", "Proposal", "Negotiation", "Stalled")


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


# -- CRM records ------------------------------------------------------------

class Account(_Record):
    account_id: str = Field(pattern=r"^A\d{3}$")
    name: str
    account_status: Literal["prospect", "qualified_lead", "customer", "former_customer"]
    segment: Literal["SMB", "Mid-Market", "Enterprise", "Strategic"]
    industry: str
    region: str
    account_owner: str
    health_score: Optional[int] = Field(default=None, ge=0, le=100)
    contract_start: Optional[date] = None
    contract_end: Optional[date] = None
    arr_usd: int = Field(ge=0)
    created_at: date
    notes: str


class Contact(_Record):
    contact_id: str
    account_id: str
    first_name: str
    last_name: str
    title: str
    email: str = Field(pattern=EMAIL_PATTERN)
    is_primary: bool
    relationship_status: Literal["champion", "engaged", "neutral", "unresponsive"]


class Opportunity(_Record):
    opportunity_id: str
    account_id: str
    name: str
    type: Literal["new_business", "renewal", "expansion"]
    stage: Literal["Discovery", "Qualification", "Proposal", "Negotiation", "Stalled", "Closed Won", "Closed Lost"]
    amount_usd: int = Field(ge=0)
    close_date: date
    probability: int = Field(ge=0, le=100)
    next_step: str
    notes: str


class Activity(_Record):
    activity_id: str
    account_id: str
    date: date
    type: Literal["call", "demo", "email", "meeting", "note"]
    owner: str
    summary: str
    sentiment: Literal["positive", "neutral", "negative"]


class SupportTicket(_Record):
    ticket_id: str
    account_id: str
    created_at: date
    severity: Literal["low", "medium", "high", "critical"]
    status: Literal["open", "in_progress", "resolved"]
    category: str
    summary: str


class ProductUsage(_Record):
    usage_id: str
    account_id: str
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    active_users: int = Field(ge=0)
    monthly_logins: int = Field(ge=0)
    usage_trend: Literal["up", "flat", "down"]
    feature_adoption_score: int = Field(ge=0, le=100)


class RestrictedDocument(BaseModel):
    """Internal HR/financial files: only the classification label is enforced."""

    model_config = ConfigDict(extra="allow")
    classification: Literal["restricted_internal", "confidential_internal"]


class DataValidationError(ValueError):
    pass


def validate_records(model: Type[BaseModel], records: List[Dict[str, Any]], source: str) -> None:
    for i, record in enumerate(records):
        try:
            model.model_validate(record)
        except ValidationError as exc:
            raise DataValidationError(f"{source}[{i}] does not match {model.__name__}:\n{exc}") from exc


# -- tool inputs ------------------------------------------------------------

class AccountQuery(BaseModel):
    account_name_or_id: str = Field(
        min_length=1, max_length=200,
        description="Account ID (e.g. A003) or account name (e.g. 'TechStart Inc').",
    )


class OpportunityFilter(BaseModel):
    stage: Optional[str] = Field(
        default=None, max_length=50,
        description=f"Optional open stage to filter by: one of {', '.join(OPEN_STAGES)}.",
    )


class NoArgs(BaseModel):
    pass


class InternalDataQuery(BaseModel):
    query: str = Field(min_length=1, max_length=500, description="What to look up.")


class DraftEmailInput(AccountQuery):
    purpose: str = Field(min_length=1, max_length=500, description="What the follow-up is about.")


class SendEmailInput(BaseModel):
    to: str = Field(pattern=EMAIL_PATTERN, max_length=254, description="Recipient email address.")
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
