"""Official World Bank Projects API client and deterministic normalization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping

import httpx

from app.services.projects import normalize_project_identifier


WORLD_BANK_PROJECTS_API_URL = "https://search.worldbank.org/api/v2/projects"
WORLD_BANK_PROJECT_DETAIL_URL = (
    "https://projects.worldbank.org/en/projects-operations/project-detail/{project_id}"
)
WORLD_BANK_PROJECT_SOURCE_FIELD = "teamleadname"
WORLD_BANK_PROJECT_NATIVE_TEAM_ROLE = "teamleadname"

TASK_TEAM_LEADER = "TASK_TEAM_LEADER"
CO_TASK_TEAM_LEADER = "CO_TASK_TEAM_LEADER"
PROJECT_TASK_MANAGER = "PROJECT_TASK_MANAGER"
OTHER_PROJECT_ROLE = "OTHER_PROJECT_ROLE"


class WorldBankProjectSourceError(RuntimeError):
    """Classified official-source failure safe for bounded worker retries."""

    def __init__(
        self,
        message: str,
        *,
        failure_class: str,
        retryable: bool,
        status: str,
    ) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.retryable = retryable
        self.status = status


class WorldBankProjectIdentityMismatch(WorldBankProjectSourceError):
    def __init__(self) -> None:
        super().__init__(
            "World Bank project response identity did not match the request",
            failure_class="identity_mismatch",
            retryable=False,
            status="failed",
        )


@dataclass(frozen=True)
class WorldBankProjectRoleObservation:
    display_name: str
    native_role: str
    canonical_role: str
    source_person_id: str | None
    email: str | None
    phone: str | None
    source_document_id: str | None
    provenance: dict[str, Any]


@dataclass(frozen=True)
class WorldBankProjectSnapshot:
    external_project_id: str
    name: str | None
    country: str | None
    region: str | None
    project_status: str | None
    approval_date: date | None
    closing_date: date | None
    borrower: str | None
    implementing_agencies: list[str] | None
    source_url: str
    source_updated_at: datetime | None
    retrieved_at: datetime
    fields_obtained: tuple[str, ...]
    fields_missing: tuple[str, ...]
    roles: tuple[WorldBankProjectRoleObservation, ...]
    roles_complete: bool
    raw_record: dict[str, Any]


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned or None


def _parse_date(value: object) -> date | None:
    text = _clean_text(value)
    if not text:
        return None
    if text.endswith("Z"):
        try:
            return datetime.fromisoformat(text[:-1] + "+00:00").date()
        except ValueError:
            pass
    for pattern in (
        "%m/%d/%Y %I:%M:%S %p",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _parse_datetime(value: object) -> datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonical_project_role(native_role: str) -> str:
    """Map exact authoritative role terminology without semantic guessing."""
    normalized = " ".join(str(native_role).split()).casefold()
    if normalized == "task team leader":
        return TASK_TEAM_LEADER
    if normalized in {"co-task team leader", "co task team leader"}:
        return CO_TASK_TEAM_LEADER
    if normalized == "task manager":
        return PROJECT_TASK_MANAGER
    return OTHER_PROJECT_ROLE


def _country(record: Mapping[str, Any]) -> str | None:
    short_name = _clean_text(record.get("countryshortname"))
    if short_name:
        return short_name
    names = record.get("countryname")
    if isinstance(names, list):
        cleaned = [value for item in names if (value := _clean_text(item))]
        return "; ".join(cleaned) or None
    return _clean_text(names)


def _implementing_agencies(record: Mapping[str, Any]) -> list[str] | None:
    value = record.get("impagency")
    if isinstance(value, list):
        cleaned = [item for raw in value if (item := _clean_text(raw))]
        return cleaned or None
    cleaned = _clean_text(value)
    # The API's string is retained as one authoritative value because commas
    # can occur within an agency name and are not a documented delimiter.
    return [cleaned] if cleaned else None


def _team_names(value: object) -> list[str]:
    if isinstance(value, list):
        candidates = value
    elif isinstance(value, str):
        candidates = value.split(",")
    else:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        name = _clean_text(candidate)
        if not name or name.casefold() in {"nil", "n/a", "none"} or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def normalize_world_bank_project_record(
    requested_project_id: str,
    record: Mapping[str, Any],
    *,
    retrieved_at: datetime | None = None,
    endpoint_url: str = WORLD_BANK_PROJECTS_API_URL,
) -> WorldBankProjectSnapshot:
    """Validate identity and normalize one official Projects API record."""
    requested = normalize_project_identifier("world_bank", requested_project_id)
    returned = normalize_project_identifier("world_bank", record.get("id"))
    if (
        not requested.is_valid
        or not returned.is_valid
        or requested.normalized_value != returned.normalized_value
        or returned.normalized_value is None
    ):
        raise WorldBankProjectIdentityMismatch()

    observed_at = retrieved_at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    observed_at = observed_at.astimezone(timezone.utc)
    project_id = returned.normalized_value
    source_url = _clean_text(record.get("url")) or WORLD_BANK_PROJECT_DETAIL_URL.format(
        project_id=project_id
    )

    tracked_fields = {
        "project_name": _clean_text(record.get("project_name")),
        "countryshortname": _country(record),
        "regionname": _clean_text(record.get("regionname")),
        "projectstatusdisplay": _clean_text(
            record.get("projectstatusdisplay") or record.get("status")
        ),
        "boardapprovaldate": _parse_date(record.get("boardapprovaldate")),
        "closingdate": _parse_date(record.get("closingdate")),
        "borrower": _clean_text(record.get("borrower")),
        "impagency": _implementing_agencies(record),
        "url": source_url,
        WORLD_BANK_PROJECT_SOURCE_FIELD: record.get(WORLD_BANK_PROJECT_SOURCE_FIELD),
    }
    fields_obtained = tuple(
        sorted(key for key, value in tracked_fields.items() if value not in (None, "", []))
    )
    fields_missing = tuple(sorted(set(tracked_fields) - set(fields_obtained)))

    roles_complete = WORLD_BANK_PROJECT_SOURCE_FIELD in record and isinstance(
        record.get(WORLD_BANK_PROJECT_SOURCE_FIELD),
        (str, list),
    )
    raw_team_value = record.get(WORLD_BANK_PROJECT_SOURCE_FIELD)
    roles = tuple(
        WorldBankProjectRoleObservation(
            display_name=name,
            native_role=WORLD_BANK_PROJECT_NATIVE_TEAM_ROLE,
            canonical_role=canonical_project_role(WORLD_BANK_PROJECT_NATIVE_TEAM_ROLE),
            source_person_id=None,
            email=None,
            phone=None,
            source_document_id=None,
            provenance={
                "source_system": "world_bank",
                "source_endpoint": endpoint_url,
                "source_url": source_url,
                "external_project_id": project_id,
                "source_field": WORLD_BANK_PROJECT_SOURCE_FIELD,
                "native_role": WORLD_BANK_PROJECT_NATIVE_TEAM_ROLE,
                "raw_source_value": raw_team_value,
                "source_value": name,
                "retrieved_at": observed_at.isoformat(),
                "source_update_time": _clean_text(record.get("p2a_updated_date")),
                "source_record_identifier": project_id,
            },
        )
        for name in _team_names(raw_team_value)
    )
    return WorldBankProjectSnapshot(
        external_project_id=project_id,
        name=tracked_fields["project_name"],
        country=tracked_fields["countryshortname"],
        region=tracked_fields["regionname"],
        project_status=tracked_fields["projectstatusdisplay"],
        approval_date=tracked_fields["boardapprovaldate"],
        closing_date=tracked_fields["closingdate"],
        borrower=tracked_fields["borrower"],
        implementing_agencies=tracked_fields["impagency"],
        source_url=source_url,
        source_updated_at=_parse_datetime(record.get("p2a_updated_date")),
        retrieved_at=observed_at,
        fields_obtained=fields_obtained,
        fields_missing=fields_missing,
        roles=roles,
        roles_complete=roles_complete,
        raw_record=dict(record),
    )


class WorldBankProjectsClient:
    """Bounded client for one known canonical World Bank Project at a time."""

    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 60.0))

    async def fetch_project(self, external_project_id: str) -> dict[str, Any]:
        identifier = normalize_project_identifier("world_bank", external_project_id)
        if not identifier.is_valid or identifier.normalized_value is None:
            raise WorldBankProjectSourceError(
                "Invalid World Bank project identifier",
                failure_class="invalid_project_id",
                retryable=False,
                status="failed",
            )
        params = {
            "format": "json",
            "id": identifier.normalized_value,
            "rows": "1",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": "PlasmaOS/1.2 project-enrichment"},
            ) as client:
                response = await client.get(WORLD_BANK_PROJECTS_API_URL, params=params)
                response.raise_for_status()
        except httpx.RequestError as exc:
            raise WorldBankProjectSourceError(
                "World Bank Projects API unavailable",
                failure_class=type(exc).__name__,
                retryable=True,
                status="source_unavailable",
            ) from exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            retryable = status_code == 429 or status_code >= 500
            raise WorldBankProjectSourceError(
                f"World Bank Projects API HTTP {status_code}",
                failure_class=f"http_{status_code}",
                retryable=retryable,
                status="source_unavailable" if retryable else "failed",
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise WorldBankProjectSourceError(
                "Malformed World Bank Projects API JSON",
                failure_class="malformed_response",
                retryable=False,
                status="failed",
            ) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("projects"), dict):
            raise WorldBankProjectSourceError(
                "Malformed World Bank Projects API payload",
                failure_class="malformed_response",
                retryable=False,
                status="failed",
            )
        projects = payload["projects"]
        if not projects:
            raise WorldBankProjectSourceError(
                "World Bank Projects API returned no authoritative project record",
                failure_class="empty_authoritative_response",
                retryable=False,
                status="failed",
            )
        record = projects.get(identifier.normalized_value)
        if record is None and len(projects) == 1:
            record = next(iter(projects.values()))
        if not isinstance(record, dict):
            raise WorldBankProjectSourceError(
                "Malformed World Bank project record",
                failure_class="malformed_response",
                retryable=False,
                status="failed",
            )
        return dict(record)
