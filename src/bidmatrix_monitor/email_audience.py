from __future__ import annotations

import csv
from collections import Counter
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


class EmailAudienceError(RuntimeError):
    """Raised when an external email audience cannot be prepared safely."""


ACTIVE_CONSENT_STATUSES = {"subscribed", "opted_in", "explicit_opt_in", "yes", "true"}
SUPPRESSED_STATUSES = {"unsubscribed", "suppressed", "bounced", "complained", "spam_complaint"}
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
REQUIRED_COLUMNS = {"email", "consent_status", "consent_source", "consent_at"}


def prepare_email_audience(
    input_path: str | Path,
    output_dir: str | Path,
) -> tuple[Path, Path, Path, dict[str, Any]]:
    source = Path(input_path)
    if not source.exists():
        raise EmailAudienceError(f"Audience CSV not found: {source}")

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    accepted_path = destination / "accepted.csv"
    rejected_path = destination / "rejected.csv"
    summary_path = destination / "summary.json"

    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    rejection_reasons: Counter[str] = Counter()
    seen_emails: set[str] = set()

    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = {str(value).strip() for value in (reader.fieldnames or [])}
        missing = sorted(REQUIRED_COLUMNS - columns)
        if missing:
            raise EmailAudienceError(f"Audience CSV is missing required columns: {', '.join(missing)}")

        for row_number, raw_row in enumerate(reader, start=2):
            row = {str(key).strip(): str(value or "").strip() for key, value in raw_row.items() if key is not None}
            normalized, reason = _validate_audience_row(row, seen_emails)
            if reason:
                rejection_reasons[reason] += 1
                rejected.append({**row, "rejection_reason": reason, "source_row": str(row_number)})
                continue
            seen_emails.add(normalized["email"])
            accepted.append(normalized)

    fieldnames = ["email", "first_name", "company", "segment", "consent_status", "consent_source", "consent_at"]
    _write_csv(accepted_path, accepted, fieldnames)
    rejected_fields = sorted({key for row in rejected for key in row}) or ["rejection_reason", "source_row"]
    _write_csv(rejected_path, rejected, rejected_fields)

    summary = {
        "status": "ready_for_resend_import" if accepted else "blocked_no_eligible_contacts",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": source.name,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "rejection_reasons": dict(sorted(rejection_reasons.items())),
        "segments": dict(sorted(Counter(row["segment"] for row in accepted).items())),
        "contains_contact_data": False,
        "accepted_file": str(accepted_path),
        "rejected_file": str(rejected_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return accepted_path, rejected_path, summary_path, summary


def prepare_external_campaign_manifest(
    preview_manifest_path: str | Path,
    audience_summary_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    preview = _load_json_object(Path(preview_manifest_path), "Preview manifest")
    audience = _load_json_object(Path(audience_summary_path), "Audience summary")
    if audience.get("status") != "ready_for_resend_import" or int(audience.get("accepted_count") or 0) < 1:
        raise EmailAudienceError("External campaign requires at least one consented audience contact.")

    campaign = {
        **preview,
        "campaign_type": "external_weekly_email",
        "recommended_audience": "external_subscribers",
        "approval_required": True,
        "approved": False,
        "approved_by": None,
        "approved_at": None,
        "audience": {
            "accepted_count": int(audience["accepted_count"]),
            "segments": audience.get("segments") or {},
            "summary_file": str(Path(audience_summary_path)),
        },
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(campaign, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return campaign


def approve_external_campaign_manifest(
    manifest_path: str | Path,
    *,
    approved_by: str,
) -> dict[str, Any]:
    path = Path(manifest_path)
    campaign = _load_json_object(path, "External campaign manifest")
    if campaign.get("campaign_type") != "external_weekly_email":
        raise EmailAudienceError("Only an external weekly email campaign can be approved with this command.")
    approver = approved_by.strip()
    if not approver:
        raise EmailAudienceError("An approver name or email is required.")
    campaign.update(
        {
            "approval_required": True,
            "approved": True,
            "approved_by": approver,
            "approved_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    path.write_text(json.dumps(campaign, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return campaign


def _validate_audience_row(row: dict[str, str], seen_emails: set[str]) -> tuple[dict[str, str], str | None]:
    email = row.get("email", "").strip().lower()
    if not EMAIL_PATTERN.fullmatch(email):
        return row, "invalid_email"
    if email in seen_emails:
        return row, "duplicate_email"

    status = row.get("consent_status", "").strip().lower().replace("-", "_").replace(" ", "_")
    if status in SUPPRESSED_STATUSES:
        return row, f"suppressed:{status}"
    if status not in ACTIVE_CONSENT_STATUSES:
        return row, "missing_explicit_consent"
    if not row.get("consent_source", "").strip():
        return row, "missing_consent_source"
    if not _valid_consent_date(row.get("consent_at", "")):
        return row, "invalid_consent_date"

    return {
        "email": email,
        "first_name": row.get("first_name", "").strip(),
        "company": row.get("company", "").strip(),
        "segment": row.get("segment", "").strip() or "external_weekly",
        "consent_status": "subscribed",
        "consent_source": row["consent_source"].strip(),
        "consent_at": row["consent_at"].strip(),
    }, None


def _valid_consent_date(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    try:
        parsed = date.fromisoformat(text[:10])
    except ValueError:
        return False
    return parsed <= date.today()


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        raise EmailAudienceError(f"{label} not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EmailAudienceError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise EmailAudienceError(f"{label} must be a JSON object: {path}")
    return value
