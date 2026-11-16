"""Licensed feed adapters: Coresignal and People Data Labs (PLAN §7 source mix).

Both are thin, fixture-pinned mappers over env-keyed REST clients. v0 delivers
ORG fields (employee_count, description, funding) — PERSON streams flow in W7–8
with the job-change detector, anchored by exact email only. Keys arrive via
SUBSTRATE_CORESIGNAL_API_KEY / SUBSTRATE_PDL_API_KEY — never in code (invariant).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError

from substrate.sources.writer import ClaimDraft

_CORESIGNAL_COMPANY_URL = "https://api.coresignal.com/cdapi/v1/company_explorer/company"
_PDL_COMPANY_URL = "https://api.peopledatalabs.com/v5/company/enrich"


class CoresignalCompany(BaseModel):
    """Fixture-pinned projection of Coresignal's company payload."""

    website: str | None = None
    company_name: str | None = None
    employees_count: int | None = None
    hq_country: str | None = None
    hq_city: str | None = None
    industry: str | None = None
    description: str | None = None


class PdlCompany(BaseModel):
    website: str | None = None
    name: str | None = None
    employee_count: int | None = None
    industry: str | None = None
    summary: str | None = None


def _require_key(env_name: str) -> str:
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise SystemExit(f"{env_name} is required for this feed (secrets via env only)")
    return key


def coresignal_company_claims(
    payload: object,
    *,
    org_id: UUID,
    retrieved_at: datetime | None = None,
) -> list[ClaimDraft]:
    """Map a Coresignal company payload → org claim drafts."""
    try:
        company = CoresignalCompany.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"coresignal: payload shape changed: {exc}") from exc

    retrieved = retrieved_at or datetime.now(UTC)
    url = _CORESIGNAL_COMPANY_URL  # the API resource the payload actually came from
    drafts: list[ClaimDraft] = []
    if company.employees_count is not None:
        drafts.append(
            ClaimDraft(
                entity_type="organization", field="employee_count",
                value_norm=str(company.employees_count),
                source_type="coresignal", source_id=company.website, url=url,
                retrieved_at=retrieved, entity_id=org_id,
            )
        )
    if company.description:
        drafts.append(
            ClaimDraft(
                entity_type="organization", field="description",
                value_norm=company.description[:500],
                source_type="coresignal", source_id=company.website, url=url,
                retrieved_at=retrieved, entity_id=org_id,
            )
        )
    if company.industry:
        drafts.append(
            ClaimDraft(
                entity_type="organization", field="industry",
                value_norm=company.industry,
                source_type="coresignal", source_id=company.website, url=url,
                retrieved_at=retrieved, entity_id=org_id,
            )
        )
    return drafts


def pdl_company_claims(
    payload: object,
    *,
    org_id: UUID,
    retrieved_at: datetime | None = None,
) -> list[ClaimDraft]:
    try:
        company = PdlCompany.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"pdl: payload shape changed: {exc}") from exc

    retrieved = retrieved_at or datetime.now(UTC)
    url = _PDL_COMPANY_URL  # the API resource the payload actually came from
    drafts: list[ClaimDraft] = []
    if company.employee_count is not None:
        drafts.append(
            ClaimDraft(
                entity_type="organization", field="employee_count",
                value_norm=str(company.employee_count),
                source_type="pdl", source_id=company.website, url=url,
                retrieved_at=retrieved, entity_id=org_id,
            )
        )
    if company.summary:
        drafts.append(
            ClaimDraft(
                entity_type="organization", field="description",
                value_norm=company.summary[:500],
                source_type="pdl", source_id=company.website, url=url,
                retrieved_at=retrieved, entity_id=org_id,
            )
        )
    if company.industry:
        drafts.append(
            ClaimDraft(
                entity_type="organization", field="industry",
                value_norm=company.industry,
                source_type="pdl", source_id=company.website, url=url,
                retrieved_at=retrieved, entity_id=org_id,
            )
        )
    return drafts


def fetch_coresignal_company(
    domain: str,
    *,
    transport: Any = None,
) -> dict[str, Any]:
    """Live fetch. Transport injection mirrors the crawler layer; tests mock it."""
    import json
    import urllib.request

    key = _require_key("SUBSTRATE_CORESIGNAL_API_KEY")
    body = json.dumps({"website_domain": domain.strip().lower(), "size": 1}).encode()
    request = urllib.request.Request(
        _CORESIGNAL_COMPANY_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "API-KEY": key,
        },
        method="POST",
    )
    if transport is not None:
        status, raw = transport(request)
    else:
        with urllib.request.urlopen(request, timeout=30) as resp:  # noqa: S310 — fixed https host
            status, raw = resp.status, resp.read()
    if status != 200:
        raise RuntimeError(f"coresignal returned HTTP {status} for {domain}")
    payload = json.loads(raw)
    if isinstance(payload, list):
        return payload[0] if payload else {}
    return payload


def fetch_pdl_company(
    domain: str,
    *,
    transport: Any = None,
) -> dict[str, Any]:
    import json
    import urllib.parse
    import urllib.request

    key = _require_key("SUBSTRATE_PDL_API_KEY")
    url = f"{_PDL_COMPANY_URL}?website={urllib.parse.quote(domain)}"
    request = urllib.request.Request(url, headers={"X-Api-Key": key})
    if transport is not None:
        status, raw = transport(request)
    else:
        with urllib.request.urlopen(request, timeout=30) as resp:  # noqa: S310 — fixed https host
            status, raw = resp.status, resp.read()
    if status != 200:
        raise RuntimeError(f"pdl returned HTTP {status} for {domain}")
    payload = json.loads(raw)
    return payload if isinstance(payload, dict) else {}
