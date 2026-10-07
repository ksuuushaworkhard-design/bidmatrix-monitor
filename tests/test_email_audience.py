from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from bidmatrix_monitor.email_audience import (
    EmailAudienceError,
    approve_external_campaign_manifest,
    prepare_email_audience,
    prepare_external_campaign_manifest,
)


def test_prepare_email_audience_keeps_only_consented_unique_contacts(tmp_path: Path) -> None:
    source = tmp_path / "audience.csv"
    source.write_text(
        "email,first_name,company,segment,consent_status,consent_source,consent_at\n"
        "Good@Example.com,Good,One,customers,opted_in,website_form,2026-10-01\n"
        "good@example.com,Duplicate,One,customers,opted_in,website_form,2026-10-01\n"
        "bad-email,Bad,Two,leads,opted_in,website_form,2026-10-01\n"
        "old@example.com,Old,Three,customers,unsubscribed,website_form,2026-09-01\n"
        "unknown@example.com,Unknown,Four,leads,customer,crm,2026-09-01\n",
        encoding="utf-8",
    )

    accepted_path, rejected_path, summary_path, summary = prepare_email_audience(source, tmp_path / "private")

    with accepted_path.open(newline="", encoding="utf-8") as handle:
        accepted = list(csv.DictReader(handle))
    assert [row["email"] for row in accepted] == ["good@example.com"]
    assert summary["accepted_count"] == 1
    assert summary["rejected_count"] == 4
    assert summary["rejection_reasons"] == {
        "duplicate_email": 1,
        "invalid_email": 1,
        "missing_explicit_consent": 1,
        "suppressed:unsubscribed": 1,
    }
    assert "good@example.com" not in summary_path.read_text(encoding="utf-8")
    assert "old@example.com" in rejected_path.read_text(encoding="utf-8")


def test_prepare_email_audience_requires_auditable_consent_columns(tmp_path: Path) -> None:
    source = tmp_path / "audience.csv"
    source.write_text("email,consent_status\na@example.com,opted_in\n", encoding="utf-8")

    with pytest.raises(EmailAudienceError, match="consent_at, consent_source"):
        prepare_email_audience(source, tmp_path / "private")


def test_external_campaign_is_blocked_until_explicit_approval(tmp_path: Path) -> None:
    preview_path = tmp_path / "preview.json"
    preview_path.write_text(
        json.dumps(
            {
                "run_date": "2026-10-12",
                "email_subject": "Weekly",
                "preview_files": {"html": "preview.html", "text": "preview.txt"},
                "items_count": 5,
                "minimum_external_items": 5,
                "external_send_ready": True,
            }
        ),
        encoding="utf-8",
    )
    audience_path = tmp_path / "summary.json"
    audience_path.write_text(
        json.dumps(
            {
                "status": "ready_for_resend_import",
                "accepted_count": 1200,
                "segments": {"active_customers": 1200},
            }
        ),
        encoding="utf-8",
    )
    campaign_path = tmp_path / "external.json"

    campaign = prepare_external_campaign_manifest(preview_path, audience_path, campaign_path)

    assert campaign["campaign_type"] == "external_weekly_email"
    assert campaign["recommended_audience"] == "external_subscribers"
    assert campaign["approval_required"] is True
    assert campaign["approved"] is False
    assert campaign["audience"]["accepted_count"] == 1200

    approved = approve_external_campaign_manifest(campaign_path, approved_by="ksenia@bid-matrix.com")
    assert approved["approved"] is True
    assert approved["approved_by"] == "ksenia@bid-matrix.com"
    assert approved["approved_at"]


def test_external_campaign_rejects_empty_audience(tmp_path: Path) -> None:
    preview_path = tmp_path / "preview.json"
    preview_path.write_text("{}", encoding="utf-8")
    audience_path = tmp_path / "summary.json"
    audience_path.write_text(
        json.dumps({"status": "blocked_no_eligible_contacts", "accepted_count": 0}),
        encoding="utf-8",
    )

    with pytest.raises(EmailAudienceError, match="consented audience"):
        prepare_external_campaign_manifest(preview_path, audience_path, tmp_path / "campaign.json")
