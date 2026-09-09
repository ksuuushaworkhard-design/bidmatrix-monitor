from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import html
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from .weekly import build_weekly_digest


class WeeklyEmailError(RuntimeError):
    """Raised when weekly email preview or test delivery cannot continue."""


WEEKLY_EMAIL_TARGET_ITEMS = 5


def build_weekly_email_preview(
    report_dir: str | Path,
    days: int = 7,
    *,
    run_date: date | None = None,
    source_report_dir: str | Path | None = None,
) -> tuple[Path, Path, Path, dict[str, Any]]:
    output_dir = Path(report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_date = run_date or date.today()

    digest_source_dir = Path(source_report_dir) if source_report_dir else output_dir
    digest = build_weekly_digest(digest_source_dir, days)
    digest = _prefer_pipeline_selected_digest_items(digest, digest_source_dir, days, output_date)
    digest = {**digest, "run_date": output_date.isoformat(), "email_subject": weekly_email_subject(digest)}

    stem = f"weekly-email-preview-{output_date.isoformat()}"
    html_path = output_dir / f"{stem}.html"
    text_path = output_dir / f"{stem}.txt"
    manifest_path = output_dir / f"{stem}.json"
    manifest = build_weekly_email_manifest(digest, output_date, html_path, text_path, days)
    digest = {**digest, "email_preview": manifest}

    html_path.write_text(render_weekly_email_html(digest), encoding="utf-8")
    text_path.write_text(render_weekly_email_text(digest), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return html_path, text_path, manifest_path, digest


def build_weekly_email_manifest(
    digest: dict[str, Any],
    output_date: date,
    html_path: Path,
    text_path: Path,
    days: int,
) -> dict[str, Any]:
    items = _top_items(digest)
    items_count = len(items)
    minimum_external_items = WEEKLY_EMAIL_TARGET_ITEMS
    external_send_ready = items_count >= minimum_external_items and not bool(digest.get("limited_signal_volume"))
    return {
        "status": "needs_review",
        "approval_required": True,
        "approved": False,
        "approved_by": None,
        "approved_at": None,
        "external_send_ready": external_send_ready,
        "recommended_audience": "internal_test",
        "run_date": str(digest.get("run_date") or output_date.isoformat()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "preview_files": {
            "html": str(html_path),
            "text": str(text_path),
        },
        "email_subject": str(digest.get("email_subject") or weekly_email_subject(digest)),
        "items_count": items_count,
        "minimum_external_items": minimum_external_items,
        "limited_signal_volume": bool(digest.get("limited_signal_volume")),
        "days": days,
        "selected_items": [
            {
                "company": _company(item),
                "event": _event(item),
                "source": _url_or_source(item),
            }
            for item in items[:WEEKLY_EMAIL_TARGET_ITEMS]
        ],
    }


def _prefer_pipeline_selected_digest_items(
    digest: dict[str, Any],
    report_dir: Path,
    days: int,
    output_date: date,
) -> dict[str, Any]:
    pipeline_items = _load_pipeline_selected_items(report_dir, days, output_date)
    if len(pipeline_items) <= len(_top_items(digest)):
        return digest

    pipeline_items = _distinct_pipeline_company_items(pipeline_items)
    developments = _email_developments_from_pipeline_items(pipeline_items[:WEEKLY_EMAIL_TARGET_ITEMS])
    if not developments:
        return digest

    diagnostics = dict(digest.get("diagnostics") or {})
    diagnostics.update(
        {
            "weekly_email_selection_source": "pipeline_selected_items",
            "weekly_email_selected_items_count": len(developments),
            "weekly_email_base_weekly_items_count": len(_top_items(digest)),
            "weekly_email_target_items": WEEKLY_EMAIL_TARGET_ITEMS,
        }
    )
    return {
        **digest,
        "item_count": len(developments),
        "limited_signal_volume": len(developments) < WEEKLY_EMAIL_TARGET_ITEMS,
        "week_in_one_line": _email_week_in_one_line(developments),
        "what_actually_happened": developments,
        "why_it_matters_for_bidmatrix": _unique_text(
            [_clean_sentence(item.get("why_it_matters") or item.get("market_context") or "", 220) for item in developments]
        )[:2],
        "diagnostics": diagnostics,
    }


def _load_pipeline_selected_items(report_dir: Path, days: int, output_date: date) -> list[dict[str, Any]]:
    cutoff = output_date - timedelta(days=max(1, days) - 1)
    selected: list[dict[str, Any]] = []
    for path in sorted(report_dir.glob("bidmatrix-monitor-*-curated.json"), reverse=True):
        report_date = _date_from_daily_curated_filename(path)
        if report_date is None or report_date < cutoff or report_date > output_date:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for key in (
            "daily_digest_items",
            "daily_signals",
            "top_news",
            "actually_new_today",
            "partner_signals",
            "competitor_moves",
            "adjacent_watchlist",
            "fresh_weak_confidence",
            "background_items",
        ):
            for item in data.get(key, []):
                if isinstance(item, dict):
                    enriched = dict(item)
                    enriched.setdefault("_weekly_email_source_report", str(path))
                    enriched.setdefault("_weekly_email_source_section", key)
                    selected.append(enriched)
    return _dedupe_pipeline_items(selected)


def _date_from_daily_curated_filename(path: Path) -> date | None:
    prefix = "bidmatrix-monitor-"
    suffix = "-curated.json"
    name = path.name
    if not name.startswith(prefix) or not name.endswith(suffix):
        return None
    try:
        return datetime.strptime(name[len(prefix) : -len(suffix)], "%Y-%m-%d").date()
    except ValueError:
        return None


def _dedupe_pipeline_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_company_topics: set[tuple[str, str]] = set()
    for item in items:
        url = str(item.get("url") or item.get("source_url") or "").split("?", 1)[0].rstrip("/").lower()
        company = _company_from_pipeline_item(item).lower()
        topic = _topic_key(item)
        key = (company, topic)
        if url and url in seen_urls:
            continue
        if company and topic and key in seen_company_topics:
            continue
        selected.append(item)
        if url:
            seen_urls.add(url)
        if company and topic:
            seen_company_topics.add(key)
    return selected


def _distinct_pipeline_company_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_companies: set[str] = set()
    for item in items:
        company_key = _company_dedupe_key(_company_from_pipeline_item(item))
        if company_key and company_key in seen_companies:
            continue
        selected.append(item)
        if company_key:
            seen_companies.add(company_key)
    return selected


def _email_developments_from_pipeline_items(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    developments = []
    for item in items:
        company = _company_from_pipeline_item(item)
        developments.append(
            {
                "company": company,
                "event": _clean_sentence(item.get("what_happened") or item.get("summary") or item.get("title"), 220),
                "source": _source_from_pipeline_item(item),
                "date": str(item.get("published_date") or "").strip() or None,
                "url": str(item.get("url") or item.get("source_url") or "").strip() or None,
                "summary": _clean_sentence(item.get("summary") or item.get("what_happened") or item.get("title"), 190),
                "why_now": _clean_sentence(item.get("why_now") or item.get("why_it_matters") or item.get("summary"), 170),
                "market_context": _clean_sentence(
                    item.get("market_context") or item.get("why_it_matters") or item.get("why_now") or item.get("summary"),
                    170,
                ),
                "why_it_matters": _clean_sentence(
                    item.get("why_it_matters_for_bidmatrix")
                    or item.get("bidmatrix_angle")
                    or item.get("why_it_matters")
                    or item.get("summary"),
                    170,
                ),
                "content_angle": _clean_sentence(
                    item.get("content_angle")
                    or item.get("linkedin_post_angle")
                    or item.get("partner_or_sales_action")
                    or item.get("concrete_action")
                    or item.get("summary"),
                    170,
                ),
                "pr_angle": _clean_sentence(item.get("pr_angle") or item.get("why_now") or item.get("summary"), 170),
                "watch": _clean_sentence(item.get("watch_next") or item.get("concrete_action") or item.get("summary"), 150),
            }
        )
    return [item for item in developments if item["event"]]


def _company_from_pipeline_item(item: dict[str, Any]) -> str:
    company = str(item.get("company_or_topic") or "").strip()
    companies = [str(value).strip() for value in item.get("mentioned_companies", []) if str(value).strip()]
    if company and not _looks_like_topic_subject(company):
        return _clean_sentence(company, 80).rstrip(".")
    if companies:
        return _clean_sentence(companies[0], 80).rstrip(".")
    if company:
        return _clean_sentence(company, 80).rstrip(".")
    return _clean_sentence(str(item.get("title") or "Company").split(" ", 1)[0], 80).rstrip(".")


def _looks_like_topic_subject(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    if "/" in text:
        return True
    topic_terms = (
        "automation",
        "measurement",
        "media buying",
        "creative",
        "agentic",
        "attribution",
        "fraud",
        "privacy",
        "programmatic",
    )
    return any(term in text for term in topic_terms)


def _source_from_pipeline_item(item: dict[str, Any]) -> str:
    return str(item.get("source_label") or item.get("source") or item.get("source_domain") or "source").strip()


def _topic_key(item: dict[str, Any]) -> str:
    text = " ".join(
        [
            str(item.get("signal_type") or ""),
            str(item.get("title") or ""),
            str(item.get("summary") or ""),
            str(item.get("why_now") or ""),
            " ".join(str(value) for value in item.get("hot_topics", []) or []),
        ]
    ).lower()
    for key, terms in (
        ("measurement", ("measurement", "attribution", "incrementality", "skan", "mmp")),
        ("fraud", ("fraud", "invalid traffic", "traffic quality", "brand safety")),
        ("ctv", ("ctv", "streaming", "tv")),
        ("ai", ("ai", "agentic", "automation", "optimization")),
        ("programmatic", ("programmatic", "dsp", "ssp", "inventory", "marketplace")),
        ("partnership", ("partner", "integration", "agency")),
    ):
        if any(term in text for term in terms):
            return key
    return "other"


def _email_week_in_one_line(developments: list[dict[str, str]]) -> str:
    companies = [item["company"] for item in developments[:3] if item.get("company")]
    if len(companies) >= 3:
        return f"This week's clearest moves came from {companies[0]}, {companies[1]}, and {companies[2]}."
    if companies:
        return f"This week's clearest moves came from {', '.join(companies)}."
    return "This week's clearest moves show where app growth and adtech teams are putting buyer attention."


def _unique_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = " ".join(str(value).split()).strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        result.append(text)
    return result


def send_weekly_email_test(
    manifest_path: str | Path,
    *,
    dry_run: bool = False,
    env_path: str | Path | None = None,
) -> dict[str, Any]:
    if env_path:
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()
    manifest_file = Path(manifest_path)
    manifest = _load_manifest(manifest_file)
    html_path = _manifest_preview_path(manifest_file, manifest, "html")
    text_path = _manifest_preview_path(manifest_file, manifest, "text")

    subject = f"TEST - {manifest.get('email_subject') or 'BidMatrix Weekly Growth Brief'}"
    skip_reason = _weekly_email_send_skip_reason(manifest)
    if skip_reason and not dry_run:
        return {
            "mode": "skipped",
            "skip_reason": skip_reason,
            "to": os.environ.get("WEEKLY_EMAIL_TEST_TO", "").strip(),
            "recipients": _optional_email_recipients(os.environ.get("WEEKLY_EMAIL_TEST_TO", "")),
            "from": os.environ.get("WEEKLY_EMAIL_FROM", "").strip(),
            "subject": subject,
            "manifest_path": str(manifest_file),
            "html_path": str(html_path),
            "text_path": str(text_path),
            "approval_required": bool(manifest.get("approval_required")),
            "approved": bool(manifest.get("approved")),
            "recommended_audience": manifest.get("recommended_audience"),
            "items_count": manifest.get("items_count"),
            "minimum_external_items": manifest.get("minimum_external_items"),
            "external_send_ready": manifest.get("external_send_ready"),
        }

    sender = _required_env("WEEKLY_EMAIL_FROM")
    recipients = _email_recipients(_required_env("WEEKLY_EMAIL_TEST_TO"))
    html_body = html_path.read_text(encoding="utf-8")
    text_body = text_path.read_text(encoding="utf-8")

    payload = {
        "from": sender,
        "to": recipients,
        "subject": subject,
        "html": html_body,
        "text": text_body,
    }
    result = {
        "mode": "dry_run" if dry_run else "sent",
        "to": ", ".join(recipients),
        "recipients": recipients,
        "from": sender,
        "subject": subject,
        "manifest_path": str(manifest_file),
        "html_path": str(html_path),
        "text_path": str(text_path),
        "approval_required": bool(manifest.get("approval_required")),
        "approved": bool(manifest.get("approved")),
        "recommended_audience": manifest.get("recommended_audience"),
        "items_count": manifest.get("items_count"),
        "minimum_external_items": manifest.get("minimum_external_items"),
        "external_send_ready": manifest.get("external_send_ready"),
    }
    if dry_run:
        return result

    response = _send_resend_email(payload)
    return {**result, "resend_response": response}


def _weekly_email_send_skip_reason(manifest: dict[str, Any]) -> str | None:
    items_count = _int_value(manifest.get("items_count"))
    minimum_items = _int_value(manifest.get("minimum_external_items")) or WEEKLY_EMAIL_TARGET_ITEMS
    if items_count is not None and items_count < minimum_items:
        return f"insufficient_items:{items_count}_of_{minimum_items}"
    if bool(manifest.get("limited_signal_volume")):
        return "limited_signal_volume"
    if manifest.get("external_send_ready") is False:
        return "external_send_not_ready"
    return None


def _int_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_and_send_weekly_email_test_run(
    report_dir: str | Path,
    days: int = 7,
    *,
    source_report_dir: str | Path | None = None,
    dry_run: bool = False,
    env_path: str | Path | None = None,
) -> dict[str, Any]:
    html_path, text_path, manifest_path, digest = build_weekly_email_preview(
        report_dir,
        days=days,
        source_report_dir=source_report_dir,
    )
    send_result = send_weekly_email_test(manifest_path, dry_run=dry_run, env_path=env_path)
    return {
        **send_result,
        "html_path": str(html_path),
        "text_path": str(text_path),
        "manifest_path": str(manifest_path),
        "items_count": digest.get("email_preview", {}).get("items_count"),
        "external_send_ready": digest.get("email_preview", {}).get("external_send_ready"),
    }


def weekly_email_subject(digest: dict[str, Any]) -> str:
    items = _top_items(digest)
    themes = _theme_labels(items)
    if themes:
        return f"BidMatrix Weekly Growth Brief: {', '.join(themes[:2])}"
    return "BidMatrix Weekly Growth Brief"


def render_weekly_email_text(digest: dict[str, Any]) -> str:
    subject = str(digest.get("email_subject") or weekly_email_subject(digest))
    items = _top_items(digest)
    run_date = str(digest.get("run_date") or date.today().isoformat())

    lines = [
        f"Subject: {subject}",
        "",
        f"BidMatrix Weekly Growth Brief - {run_date}",
        "",
        "This week's market story:",
        _takeaway(digest),
        "",
        "What this means for marketers:",
        _why_it_matters(digest),
        "",
        "Moves worth reading:",
    ]

    if items:
        for index, item in enumerate(items[:WEEKLY_EMAIL_TARGET_ITEMS], start=1):
            lines.extend(
                [
                    f"{index}. {_company(item)} - {_event(item)}",
                    f"What it means: {_item_why(item)}",
                    f"How to use it: {_item_angle(item)}",
                    f"Source: {_url_or_source(item)}",
                    "",
                ]
            )
    else:
        lines.extend(["No weekly moves were ready for this email preview.", ""])

    lines.extend(["Internal beta preview. Reply with feedback before this becomes the external weekly email."])
    return "\n".join(lines).rstrip() + "\n"


def render_weekly_email_html(digest: dict[str, Any]) -> str:
    subject = str(digest.get("email_subject") or weekly_email_subject(digest))
    items = _top_items(digest)
    run_date = str(digest.get("run_date") or date.today().isoformat())
    theme_line = _subject_theme(subject)
    item_blocks = "\n".join(
        _item_html(item, index) for index, item in enumerate(items[:WEEKLY_EMAIL_TARGET_ITEMS], start=1)
    )
    if not item_blocks:
        item_blocks = (
            '<p style="margin:0; font-size:15px; line-height:1.55; color:#000000;">'
            "No weekly moves were ready for this email preview.</p>"
        )
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(subject)}</title>
  </head>
  <body style="margin:0; padding:0; background:#D9D9D9; font-family:Roboto, Arial, Helvetica, sans-serif; color:#000000;">
    <div style="display:none; max-height:0; overflow:hidden; opacity:0; color:transparent;">
      {_email_preheader(digest)}
    </div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#D9D9D9; padding:28px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="640" cellspacing="0" cellpadding="0" style="width:640px; max-width:100%; background:#ffffff; border:1px solid #D9D9D9; border-radius:18px; overflow:hidden;">
            <tr>
              <td style="padding:30px 32px 24px; background:#000000;">
                {_logo_html()}
                <h1 style="margin:22px 0 0; font-family:Oswald, Oswaldo, Arial, Helvetica, sans-serif; font-weight:400; font-size:34px; line-height:1.12; color:#ffffff;">Weekly Growth Brief</h1>
                <p style="margin:12px 0 0; font-size:16px; line-height:1.45; color:#ffffff;">{html.escape(theme_line)}</p>
                <p style="margin:18px 0 0; color:#09CAB6; font-size:13px;">{html.escape(run_date)}</p>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 32px 8px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#ffffff; border:1px solid #D9D9D9; border-left:4px solid #09CAB6; border-radius:10px;">
                  <tr>
                    <td style="padding:18px 20px;">
                      <p style="margin:0 0 6px; color:#09CAB6; font-size:14px; font-weight:bold;">This week's market story</p>
                      <p style="font-size:16px; line-height:1.55; margin:0 0 14px; color:#000000;">{html.escape(_takeaway(digest))}</p>
                      <p style="margin:0 0 6px; color:#09CAB6; font-size:14px; font-weight:bold;">For marketers</p>
                      <p style="font-size:16px; line-height:1.55; margin:0; color:#000000;">{html.escape(_why_it_matters(digest))}</p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:12px 32px 4px;">
                <h2 style="font-family:Oswald, Oswaldo, Arial, Helvetica, sans-serif; font-weight:400; font-size:24px; margin:18px 0 14px; color:#000000;">Moves worth reading</h2>
                {item_blocks}
              </td>
            </tr>
            <tr>
              <td style="padding:8px 32px 30px;">
                <p style="font-size:13px; line-height:1.5; color:#000000; margin:18px 0 0;">Internal beta preview. Reply with feedback before this becomes an external weekly email.</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def _item_html(item: dict[str, Any], index: int) -> str:
    source = _url_or_source(item)
    return f"""
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-top:1px solid #D9D9D9;">
  <tr>
    <td style="padding:18px 0 20px;">
      <table role="presentation" cellspacing="0" cellpadding="0" style="margin:0 0 10px;">
        <tr>
          <td style="background:#09CAB6; color:#000000; border-radius:999px; font-size:14px; font-weight:bold; padding:6px 10px;">{index}</td>
          <td style="padding-left:12px; color:#000000; font-size:18px; font-weight:bold;">{html.escape(_company(item))}</td>
        </tr>
      </table>
      <h3 style="margin:0 0 12px; font-family:Oswald, Oswaldo, Arial, Helvetica, sans-serif; font-weight:400; font-size:22px; line-height:1.3; color:#000000;">{html.escape(_event(item))}</h3>
      <p style="margin:0 0 10px; font-size:15px; line-height:1.55; color:#000000;"><strong style="color:#000000;">What it means:</strong> {html.escape(_item_why(item))}</p>
      <p style="margin:0 0 14px; font-size:15px; line-height:1.55; color:#000000;"><strong style="color:#000000;">How to use it:</strong> {html.escape(_item_angle(item))}</p>
      {_source_link_html(item, source)}
    </td>
  </tr>
</table>
"""


def _top_items(digest: dict[str, Any]) -> list[dict[str, Any]]:
    items = digest.get("what_actually_happened") or []
    return _distinct_company_items([item for item in items if isinstance(item, dict)])


def _distinct_company_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_companies: set[str] = set()
    for item in items:
        company_key = _company_dedupe_key(_company(item))
        if company_key and company_key in seen_companies:
            continue
        selected.append(item)
        if company_key:
            seen_companies.add(company_key)
    return selected


def _company_dedupe_key(company: str) -> str:
    normalized = html.unescape(str(company or "")).lower().replace("&", " and ")
    normalized = re.split(r"\s+(?:and|with|x)\s+", normalized, maxsplit=1)[0]
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    return " ".join(normalized.split())


def _logo_html() -> str:
    return (
        '<p style="margin:0; color:#09CAB6; font-family:Oswald, Oswaldo, Arial, Helvetica, sans-serif; '
        'font-size:24px; line-height:1; font-weight:400;">BidMatrix</p>'
    )


def _email_preheader(digest: dict[str, Any]) -> str:
    return html.escape(_clean_sentence(_takeaway(digest), 140))


def _subject_theme(subject: str) -> str:
    if ":" not in subject:
        return "A short weekly read on the moves shaping mobile growth and performance marketing."
    theme = subject.split(":", 1)[1].strip()
    if not theme:
        return "A short weekly read on the moves shaping mobile growth and performance marketing."
    return f"This week's focus: {theme}."


def _takeaway(digest: dict[str, Any]) -> str:
    line = str(digest.get("week_in_one_line") or "").strip()
    if line:
        return _clean_sentence(line, 280)
    items = _top_items(digest)
    if items:
        companies = ", ".join(_company(item) for item in items[:3])
        return f"{companies} show where performance marketing companies are trying to move buyer attention this week."
    return "This week was quiet, so the preview stays focused on the few market moves worth watching."


def _why_it_matters(digest: dict[str, Any]) -> str:
    values = digest.get("why_it_matters_for_bidmatrix") or digest.get("what_this_suggests") or []
    if values:
        return _externalize_bidmatrix_copy(_clean_sentence(str(values[0]), 260))
    return "The useful part is not just the news, but how companies are framing growth, measurement, AI, and performance proof."


def _theme_labels(items: list[dict[str, Any]]) -> list[str]:
    text = " ".join(f"{_event(item)} {_item_why(item)} {_item_angle(item)}" for item in items).lower()
    labels: list[str] = []
    for label, terms in (
        ("AI in ad buying", ("ai", "agent", "automation", "autopilot")),
        ("measurement proof", ("measurement", "attribution", "incrementality", "mmp")),
        ("CTV performance", ("ctv", "streaming", "tv")),
        ("fraud and traffic quality", ("fraud", "traffic quality", "verified")),
        ("partner distribution", ("partner", "agency", "integration")),
    ):
        if any(term in text for term in terms):
            labels.append(label)
    return labels


def _company(item: dict[str, Any]) -> str:
    return _clean_sentence(str(item.get("company") or "Company"), 80).rstrip(".")


def _event(item: dict[str, Any]) -> str:
    return _clean_sentence(str(item.get("event") or item.get("summary") or "A relevant market move emerged."), 220)


def _item_why(item: dict[str, Any]) -> str:
    value = item.get("why_it_matters") or item.get("market_context") or item.get("why_now") or item.get("summary")
    return _externalize_bidmatrix_copy(
        _clean_sentence(str(value or "It points to how adtech companies are trying to make performance claims more credible."), 220)
    )


def _item_angle(item: dict[str, Any]) -> str:
    value = item.get("content_angle") or item.get("pr_angle") or item.get("watch")
    return _externalize_bidmatrix_copy(
        _clean_sentence(str(value or "Turn this into a short content or BD hook about measurable growth."), 220)
    )


def _url_or_source(item: dict[str, Any]) -> str:
    url = str(item.get("url") or "").strip()
    if url:
        return url
    return str(item.get("source") or "source unavailable").strip()


def _source_link_html(item: dict[str, Any], source: str) -> str:
    url = str(item.get("url") or "").strip()
    label = _clean_source_label(str(item.get("source") or source).strip())
    if url.startswith("http://") or url.startswith("https://"):
        return (
            f'<a href="{html.escape(url, quote=True)}" '
            'style="display:inline-block; background:#09CAB6; color:#000000; text-decoration:none; '
            'border-radius:999px; padding:9px 13px; font-size:13px; font-weight:bold;">'
            f"Read source: {html.escape(label)}</a>"
        )
    return (
        '<p style="margin:0; font-size:14px; line-height:1.5; color:#000000;">'
        f"<strong>Source:</strong> {html.escape(_clean_source_label(source))}</p>"
    )


def _clean_source_label(value: str) -> str:
    cleaned = value.replace("(high-signal)", "").replace("high-signal", "")
    cleaned = cleaned.replace("(medium-signal)", "").replace("medium-signal", "")
    cleaned = " ".join(cleaned.replace("()", "").split()).strip(" -")
    return cleaned or "source"


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        raise WeeklyEmailError(f"Weekly email manifest not found: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WeeklyEmailError(f"Weekly email manifest is invalid JSON: {manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise WeeklyEmailError("Weekly email manifest must be a JSON object.")
    return manifest


def _manifest_preview_path(manifest_path: Path, manifest: dict[str, Any], key: str) -> Path:
    value = (manifest.get("preview_files") or {}).get(key)
    if not value:
        raise WeeklyEmailError(f"Weekly email manifest is missing preview_files.{key}.")
    path = Path(str(value))
    if not path.is_absolute():
        path = manifest_path.parent / path.name
    if not path.exists():
        raise WeeklyEmailError(f"Weekly email {key} preview file not found: {path}")
    return path


def _required_env(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise WeeklyEmailError(f"Missing required environment variable: {key}")
    return value


def _email_recipients(value: str) -> list[str]:
    recipients = [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]
    if not recipients:
        raise WeeklyEmailError("WEEKLY_EMAIL_TEST_TO must include at least one recipient.")
    invalid = [recipient for recipient in recipients if "@" not in recipient or recipient.startswith("@")]
    if invalid:
        raise WeeklyEmailError(f"WEEKLY_EMAIL_TEST_TO contains invalid recipient(s): {', '.join(invalid)}")
    return recipients


def _optional_email_recipients(value: str) -> list[str]:
    if not value.strip():
        return []
    return _email_recipients(value)


def _send_resend_email(payload: dict[str, Any]) -> dict[str, Any]:
    api_key = _required_env("RESEND_API_KEY")
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        "https://api.resend.com/emails",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "bidmatrix-monitor-weekly-email/0.1",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise WeeklyEmailError(f"Resend API returned HTTP {exc.code}: {details}") from exc
    except URLError as exc:
        raise WeeklyEmailError(f"Resend API request failed: {exc.reason}") from exc
    return json.loads(raw) if raw else {}


def _clean_sentence(value: str, limit: int) -> str:
    cleaned = " ".join(str(value or "").replace("\n", " ").split()).strip(" -")
    if not cleaned:
        return ""
    if len(cleaned) <= limit:
        return cleaned.rstrip(".") + "."
    clipped = cleaned[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:")
    return clipped.rstrip(".") + "."


def _externalize_bidmatrix_copy(value: str) -> str:
    replacements = (
        ("BidMatrix can use this to ", "Marketers can use this to "),
        ("BidMatrix can use this ", "Marketers can use this "),
        ("BidMatrix can connect ", "Growth teams can connect "),
        ("BidMatrix can frame ", "Growth teams can frame "),
        ("BidMatrix can comment on ", "Marketing teams can comment on "),
        ("BidMatrix can ", "Growth teams can "),
        ("Gives BidMatrix a concrete angle on ", "Gives marketers a concrete way to discuss "),
        ("Creates a timely opening for BidMatrix to comment on ", "Creates a timely opening to discuss "),
        ("BidMatrix's ", "a growth team's "),
        ("BidMatrix positioning", "positioning"),
    )
    result = value
    for old, new in replacements:
        result = result.replace(old, new)
    return result
