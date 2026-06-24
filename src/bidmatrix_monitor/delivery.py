from __future__ import annotations

import html
import json
import os
import re
import time
import smtplib
from socket import timeout as socket_timeout
from datetime import date
from email.message import EmailMessage
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from .models import MonitorConfig


class DeliveryError(RuntimeError):
    """Raised when report generation succeeds but delivery fails."""


def maybe_deliver_report(config: MonitorConfig, markdown_path: Path, report_type: str) -> None:
    load_dotenv()
    if not _delivery_enabled(config, report_type):
        print(f"DELIVERY_SKIPPED report_type={report_type} reason=disabled")
        return

    channel = os.environ.get("BIDMATRIX_DELIVERY_CHANNEL", config.delivery.channel).strip().lower()
    subject = _subject(report_type, markdown_path)
    text = markdown_path.read_text(encoding="utf-8")
    state_path = _delivery_state_path(markdown_path)
    run_date = _subject_date(subject)

    if report_type == "daily" and channel == "telegram" and _daily_delivery_already_sent(state_path, channel, run_date):
        print(f"DAILY_DELIVERY_SKIPPED reason=already_sent_today date={run_date.isoformat()}")
        return

    print(f"DELIVERY_ATTEMPT report_type={report_type} channel={channel}")

    try:
        if channel == "telegram":
            status = _send_telegram(subject, text, report_type)
        elif channel == "email":
            _send_email(subject, text)
            status = "sent"
        else:
            raise RuntimeError(f"Unsupported delivery channel: {channel}")
    except Exception as exc:
        print(
            f"DELIVERY_FAILED report_type={report_type} channel={channel} "
            f"error_type={type(exc).__name__} error={exc}"
        )
        raise DeliveryError(f"{channel} delivery failed for {report_type} report") from exc

    if status == "skipped_quality_gate":
        print(f"DELIVERY_SKIPPED report_type={report_type} channel={channel} reason=quality_gate")
    else:
        if report_type == "daily" and channel == "telegram":
            _mark_daily_delivery_sent(state_path, channel, run_date)
        print(f"DELIVERY_SUCCEEDED report_type={report_type} channel={channel}")


def maybe_deliver_marketing_insights_report(config: MonitorConfig, markdown_path: Path) -> None:
    load_dotenv()
    if not _delivery_enabled(config, "daily"):
        print("MARKETING_INSIGHTS_DELIVERY_SKIPPED reason=disabled")
        return

    channel = os.environ.get("BIDMATRIX_DELIVERY_CHANNEL", config.delivery.channel).strip().lower()
    state_path = _delivery_state_path(markdown_path)
    run_date = _marketing_insights_run_date(markdown_path)

    if channel == "telegram" and _marketing_insights_delivery_already_sent(state_path, channel, run_date):
        print(f"MARKETING_INSIGHTS_DELIVERY_SKIPPED reason=already_sent_today date={run_date.isoformat()}")
        return

    print(f"MARKETING_INSIGHTS_DELIVERY_ATTEMPT channel={channel}")

    try:
        if channel != "telegram":
            raise RuntimeError(f"Unsupported Marketing Insights Radar delivery channel: {channel}")
        _send_marketing_insights_telegram(markdown_path.read_text(encoding="utf-8"), run_date)
    except Exception as exc:
        print(
            "MARKETING_INSIGHTS_DELIVERY_FAILED "
            f"channel={channel} error_type={type(exc).__name__} error={exc}"
        )
        raise DeliveryError("telegram delivery failed for Marketing Insights Radar report") from exc

    _mark_marketing_insights_delivery_sent(state_path, channel, run_date)
    print(f"MARKETING_INSIGHTS_DELIVERY_SUCCEEDED channel={channel}")


def _delivery_state_path(markdown_path: Path) -> Path:
    return markdown_path.parent / "delivery-state.json"


def _load_delivery_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_delivery_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _daily_delivery_already_sent(path: Path, channel: str, run_date: date) -> bool:
    state = _load_delivery_state(path)
    return (
        state.get("daily", {})
        .get(channel, {})
        .get(run_date.isoformat(), {})
        .get("status")
        == "sent"
    )


def _mark_daily_delivery_sent(path: Path, channel: str, run_date: date) -> None:
    state = _load_delivery_state(path)
    daily = state.setdefault("daily", {})
    by_channel = daily.setdefault(channel, {})
    by_channel[run_date.isoformat()] = {
        "status": "sent",
        "sent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _save_delivery_state(path, state)


def _marketing_insights_delivery_already_sent(path: Path, channel: str, run_date: date) -> bool:
    state = _load_delivery_state(path)
    return (
        state.get("daily", {})
        .get("marketing_insights_radar", {})
        .get(channel, {})
        .get(run_date.isoformat(), {})
        .get("status")
        == "sent"
    )


def _mark_marketing_insights_delivery_sent(path: Path, channel: str, run_date: date) -> None:
    state = _load_delivery_state(path)
    daily = state.setdefault("daily", {})
    product = daily.setdefault("marketing_insights_radar", {})
    by_channel = product.setdefault(channel, {})
    by_channel[run_date.isoformat()] = {
        "status": "sent",
        "sent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _save_delivery_state(path, state)


def _delivery_enabled(config: MonitorConfig, report_type: str) -> bool:
    env_value = os.environ.get("BIDMATRIX_DELIVERY_ENABLED")
    enabled = _bool(env_value) if env_value is not None else config.delivery.enabled
    if not enabled:
        return False
    if report_type == "daily":
        return config.delivery.send_daily
    if report_type == "weekly":
        return config.delivery.send_weekly
    return False


def _send_telegram(subject: str, text: str, report_type: str) -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("Telegram delivery requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")

    message = _telegram_message(subject, text, report_type)
    if report_type == "daily":
        reasons = _telegram_quality_gate_reasons(message)
        if reasons:
            print(f"QUALITY_GATE_FAILED: {'; '.join(reasons)}")
            return "skipped_quality_gate"
    _post_telegram_message(token, chat_id, message)
    return "sent"


def _send_marketing_insights_telegram(text: str, run_date: date) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("Telegram delivery requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")

    _post_telegram_message(token, chat_id, _marketing_insights_telegram_message(text, run_date))


def _post_telegram_message(token: str, chat_id: str, message: str) -> None:
    data = urlencode(
        {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
            "disable_notification": "false",
        }
    ).encode("utf-8")
    for attempt in range(2):
        request = Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data, method="POST")
        try:
            with urlopen(request, timeout=30) as response:
                response.read()
            return
        except Exception as exc:
            if attempt == 0 and _is_retryable_delivery_error(exc):
                print(
                    "DELIVERY_RETRY "
                    f"channel=telegram attempt=2 error_type={type(exc).__name__} error={exc}"
                )
                time.sleep(2)
                continue
            raise


def _is_retryable_delivery_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, socket_timeout, URLError)):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, (TimeoutError, socket_timeout))


def _telegram_quality_gate_reasons(message: str) -> list[str]:
    item_count = len(re.findall(r"^\d+\.\s+", message, flags=re.MULTILINE))
    if not item_count:
        return []

    reasons: list[str] = []
    old_format_markers = (
        "<b>Today's useful signals</b>",
        "<b>Top market news</b>",
        "<b>Market signal to watch</b>",
        "<b>Market Watch</b>",
        "<b>What happened</b>",
        "<b>How BidMatrix can use it</b>",
        "<b>Source</b>",
    )
    if any(marker in message for marker in old_format_markers):
        reasons.append("old_format_verbose_labels")
    if "<b>What it affects</b>" in message:
        reasons.append("old_format_what_it_affects")
    if "<b>Why it matters for BidMatrix</b>" in message:
        reasons.append("old_format_why_it_matters_for_bidmatrix")
    if len(re.findall(r"https?://", message)) < item_count:
        reasons.append("missing_source_url")
    if re.search(r"^\d+\.\s+.*\bbidmatrix\b", message, flags=re.IGNORECASE | re.MULTILINE):
        reasons.append("bidmatrix_self_item")
    if "Date: 2025-" in message:
        reasons.append("contains_2025_item")
    broken_patterns = (
        r"\bto enable\.",
        r"\be\.g\.",
        r"\(e\.g\.",
        r"\(\s*$",
    )
    if any(re.search(pattern, message, flags=re.IGNORECASE | re.MULTILINE) for pattern in broken_patterns):
        reasons.append("broken_fragment")
    return reasons


def _telegram_message(subject: str, text: str, report_type: str) -> str:
    if report_type != 'daily':
        return _telegram_weekly_message(subject, text)

    date_label = _date_from_subject(subject)
    run_date = _subject_date(subject)
    title = f'<b>BidMatrix Daily Brief — {html.escape(date_label)}</b>'
    if 'Daily brief skipped: not enough relevant market signals found today.' in text:
        return '\n'.join([title, '', 'Daily brief skipped: not enough relevant market signals found today.'])

    items = _report_items(text)
    all_top_items = [item for item in items if item.get('section') == 'top']
    adjacent_items = [item for item in items if item.get('section') == 'adjacent']
    lines = [title]
    top_items, top_stats = _filter_telegram_daily_items(all_top_items, run_date)
    adjacent, adjacent_stats = _filter_telegram_daily_items(adjacent_items, run_date)
    digest_items, selection_meta = _select_telegram_daily_items(top_items, adjacent, target=3, limit=4)

    if digest_items:
        lines.append("")
        for index, item in enumerate(digest_items[:4], start=1):
            lines.extend(_telegram_daily_news_item(item, index))
    else:
        intro_chunks = _daily_intro_paragraphs(text)
        if any("no Exa results were available" in chunk for chunk in intro_chunks):
            lines.extend(["", "<b>Monitor error</b>", "Market brief monitor ran, but no Exa results were available. Please check EXA_API_KEY, Exa response logs, or source/query configuration."])
        else:
            lines.extend(["", "No strong fresh market signals found today. The monitor will keep watching mobile UA, measurement, fraud, CTV, AI campaign ops, and app growth."])

    return _truncate_daily('\n'.join(lines), 3800)


def _marketing_insights_telegram_message(text: str, run_date: date) -> str:
    pattern = _marketing_insights_pattern(text)
    items = _marketing_insights_items(text)
    watchlist = _marketing_insights_watchlist(text)
    title = f"<b>Marketing Insights Radar — {html.escape(run_date.isoformat())}</b>"
    lines = [title]

    if pattern:
        lines.extend(["", "<b>Today’s marketing pattern</b>", html.escape(_shorten(pattern, 360))])

    lines.extend(["", "<b>Company insights</b>"])
    if items:
        for index, item in enumerate(items[:5], start=1):
            lines.append(f"{index}. {html.escape(_shorten(item['action'], 220))}")
            idea = item.get("content_bd_idea") or item.get("bidmatrix_use") or item.get("marketing_insight")
            if idea:
                lines.append(f"Use: {html.escape(_shorten(idea, 180))}")
            lines.append("")
    else:
        lines.append("No strong marketing insight signals passed the quality gate.")

    if watchlist:
        if lines[-1] != "":
            lines.append("")
        lines.append("<b>Watchlist</b>")
        for item in watchlist[:3]:
            lines.append(f"- {html.escape(_shorten(item, 160))}")

    return _truncate("\n".join(lines).rstrip(), 3800)

def _telegram_weekly_message(subject: str, text: str) -> str:
    date_label = _date_from_subject(subject)
    lines = [f"<b>BidMatrix Weekly Brief — {html.escape(date_label)}</b>"]
    weekly_items = _select_telegram_weekly_items(_weekly_telegram_items(text), _subject_date(subject))
    if not weekly_items:
        lines.extend(
            [
                "",
                "Not enough strong weekly signals for a useful recap this week. The monitor will keep watching mobile UA, measurement, fraud, CTV, AI campaign ops, and app growth.",
            ]
        )
        return _truncate("\n".join(lines), 1800)

    lines.append("")
    for index, item in enumerate(weekly_items[:4], start=1):
        lines.extend(_telegram_weekly_news_item(item, index))

    takeaway = _weekly_takeaway_line(text, weekly_items)
    if takeaway:
        lines.extend(["Weekly takeaway:", html.escape(takeaway)])

    return _truncate("\n".join(lines), 1800)


def _send_email(subject: str, text: str) -> None:
    host = os.environ.get("EMAIL_SMTP_HOST")
    username = os.environ.get("EMAIL_SMTP_USERNAME")
    password = os.environ.get("EMAIL_SMTP_PASSWORD")
    sender = os.environ.get("EMAIL_FROM")
    recipient = os.environ.get("EMAIL_TO")
    port = int(os.environ.get("EMAIL_SMTP_PORT", "587"))

    missing = [
        name
        for name, value in {
            "EMAIL_SMTP_HOST": host,
            "EMAIL_SMTP_USERNAME": username,
            "EMAIL_SMTP_PASSWORD": password,
            "EMAIL_FROM": sender,
            "EMAIL_TO": recipient,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"Email delivery missing required env vars: {', '.join(missing)}")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(text)

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(message)


def _subject(report_type: str, markdown_path: Path) -> str:
    label = "Daily" if report_type == "daily" else "Weekly"
    match = re.search(r"(\d{4}-\d{2}-\d{2})", markdown_path.stem)
    date_label = match.group(1) if match else markdown_path.stem
    return f"BidMatrix {label} Market Brief - {date_label}"


def _report_items(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    section = ''

    for line in text.splitlines():
        stripped = line.strip()
        if stripped in {'## Top Signal', '## Top Signals', '## Top Market Signal', '## Top Market Signals'}:
            section = 'top'
            continue
        if stripped in {'## Adjacent Watchlist', '## Market Watch'}:
            section = 'adjacent'
            continue
        if stripped.startswith('## '):
            section = ''
        heading = re.match(r'^### (?P<rank>\d+)\.\s+(?P<title>.+)$', stripped)
        if heading:
            if current:
                items.append(current)
            current = {
                'section': section,
                'title': _clean_markdown_text(heading.group('title')),
                'url': '',
                'what_happened': '',
                'why_it_matters': '',
                'bidmatrix_angle': '',
                'content_angle': '',
                'action': '',
                'watch_next': '',
                'source': '',
                'confidence': 'medium',
            }
            continue

        if current is None:
            continue

        if stripped.startswith('- What happened:'):
            current['what_happened'] = _clean_markdown_text(stripped.removeprefix('- What happened:').strip())
        elif stripped.startswith('- Why it matters:') or stripped.startswith('- Why it may matter:'):
            current['why_it_matters'] = _clean_markdown_text(stripped.split(':', 1)[1].strip())
        elif stripped.startswith('- BidMatrix angle:') or stripped.startswith('- BidMatrix use:'):
            current['bidmatrix_angle'] = _clean_markdown_text(stripped.split(':', 1)[1].strip())
        elif stripped.startswith('- Content angle:'):
            current['content_angle'] = _clean_markdown_text(stripped.removeprefix('- Content angle:').strip())
        elif stripped.startswith('- Action:'):
            current['action'] = _clean_markdown_text(stripped.removeprefix('- Action:').strip())
        elif stripped.startswith('- Watch next:'):
            current['watch_next'] = _clean_markdown_text(stripped.removeprefix('- Watch next:').strip())
        elif stripped.startswith('- Source:'):
            current['source'] = _clean_markdown_text(stripped.removeprefix('- Source:').strip())
            url_match = re.search(r'\((https?://[^)]+)\)', stripped)
            if url_match:
                current['url'] = url_match.group(1)
            confidence_match = re.search(r'confidence:\s*(high|medium|low)', stripped, flags=re.IGNORECASE)
            if confidence_match:
                current['confidence'] = confidence_match.group(1).lower()

    if current:
        items.append(current)
    return items


def _marketing_insights_run_date(markdown_path: Path) -> date:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", markdown_path.stem)
    if match:
        try:
            return date.fromisoformat(match.group(1))
        except ValueError:
            pass
    return date.today()


def _marketing_insights_pattern(text: str) -> str:
    return _section_body(text, "Today’s marketing pattern")


def _marketing_insights_items(text: str) -> list[dict[str, str]]:
    body = _section_body(text, "What companies are doing")
    if not body:
        return []
    items: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in body.splitlines():
        stripped = line.strip()
        heading = re.match(r"^(?P<rank>\d+)\.\s+(?P<action>.+)$", stripped)
        if heading:
            if current:
                items.append(current)
            current = {
                "action": _clean_markdown_text(heading.group("action")),
                "marketing_insight": "",
                "bidmatrix_use": "",
                "content_bd_idea": "",
            }
            continue
        if current is None:
            continue
        if stripped.startswith("Marketing insight:"):
            current["marketing_insight"] = _clean_markdown_text(stripped.split(":", 1)[1].strip())
        elif stripped.startswith("What BidMatrix can use:"):
            current["bidmatrix_use"] = _clean_markdown_text(stripped.split(":", 1)[1].strip())
        elif stripped.startswith("Content / BD idea:"):
            current["content_bd_idea"] = _clean_markdown_text(stripped.split(":", 1)[1].strip())
    if current:
        items.append(current)
    return items


def _marketing_insights_watchlist(text: str) -> list[str]:
    body = _section_body(text, "Watchlist")
    if not body:
        return []
    items: list[str] = []
    seen: set[str] = set()
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        item = _clean_markdown_text(stripped.removeprefix("- ").strip())
        if not item or item.lower().startswith("no watchlist"):
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items


def _section_body(text: str, heading: str) -> str:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == f"## {heading}":
            start = index + 1
            break
    if start is None:
        return ""
    body: list[str] = []
    for line in lines[start:]:
        if line.strip().startswith("## "):
            break
        body.append(line)
    return "\n".join(body).strip()

def _weekly_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            current = stripped.removeprefix("## ").strip()
            sections.setdefault(current, [])
            continue
        if not current or not stripped:
            continue
        if stripped.startswith("- "):
            sections[current].append(stripped[2:].strip())
    return sections


def _weekly_telegram_items(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    section = ""

    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "## 2. What Actually Happened This Week":
            section = "happened"
            continue
        if stripped == "## Background Watchlist":
            section = "background"
            continue
        if stripped.startswith("## "):
            section = ""
            current = None
            continue

        if section not in {"happened", "background"}:
            continue

        if stripped.startswith("- "):
            if "No strong fresh weekly developments were found." in stripped:
                current = None
                continue
            if "No older background items were promoted to the watchlist." in stripped:
                current = None
                continue
            raw_line = stripped.removeprefix("- ").strip()
            current = {
                "section": section,
                "line": _clean_weekly_event_line(raw_line),
                "url": "",
                "source": "",
                "date": "",
                "company": "",
            }
            company_match = re.match(r"\*\*(?P<company>.+?)\*\*:\s*(?P<event>.+)$", raw_line)
            if company_match:
                current["company"] = _clean_markdown_text(company_match.group("company"))
                current["line"] = _clean_weekly_event_line(company_match.group("event"))
            items.append(current)
            continue

        if current and stripped.startswith("Source:"):
            current["source"] = _clean_markdown_text(stripped.removeprefix("Source:").strip())
            url_match = re.search(r"URL:\s*(https?://\S+)", stripped)
            if url_match:
                current["url"] = url_match.group(1).rstrip(")")
            date_match = re.search(r"Date:\s*(\d{4}-\d{2}-\d{2})", stripped)
            if date_match:
                current["date"] = date_match.group(1)

    return items


def _clean_weekly_event_line(value: str) -> str:
    line = _clean_markdown_text(value)
    if line.lower().startswith("background context, not a new weekly signal."):
        line = line.split(".", 1)[1].strip() if "." in line else ""
    return _clean_trailing_fragment(_shorten(line, 180))


def _select_telegram_weekly_items(items: list[dict[str, str]], run_date: date | None) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    seen_companies: set[str] = set()
    seen_lines: set[str] = set()

    def date_quality(item: dict[str, str]) -> tuple[int, int]:
        value = (item.get("date") or "").strip()
        if not value:
            return (3, 999)
        try:
            published = date.fromisoformat(value)
        except ValueError:
            return (3, 999)
        if published.year < 2026:
            return (4, 999)
        if run_date is None:
            return (0, 0)
        age_days = (run_date - published).days
        if age_days < 0:
            return (4, 999)
        if age_days <= 7:
            return (0, age_days)
        if age_days <= 30:
            return (2, age_days)
        return (4, age_days)

    ranked = sorted(
        items,
        key=lambda item: (
            date_quality(item),
            1 if item.get("section") == "background" else 0,
            (item.get("company") or item.get("line") or "").lower(),
        ),
    )

    for item in ranked:
        if len(selected) >= 4:
            break
        url = (item.get("url") or "").strip().lower()
        line = (item.get("line") or "").strip().lower()
        company = (item.get("company") or "").strip().lower()
        if not line or not url:
            continue
        if "bidmatrix" in " ".join([line, company, url]):
            continue
        if "2025-" in (item.get("date") or ""):
            continue
        if re.search(r"\bto enable\.|\be\.g\.|\(e\.g\.|\(\s*$", item.get("line") or "", flags=re.IGNORECASE):
            continue
        quality_rank, _ = date_quality(item)
        if quality_rank >= 4:
            continue
        if url in seen_urls or line in seen_lines:
            continue
        if company and company in seen_companies:
            continue
        selected.append(item)
        seen_urls.add(url)
        seen_lines.add(line)
        if company:
            seen_companies.add(company)

    return selected


def _telegram_weekly_news_item(item: dict[str, str], index: int) -> list[str]:
    return [f"{index}. {html.escape(item['line'])}", html.escape(item["url"]), ""]


def _weekly_takeaway_line(text: str, weekly_items: list[dict[str, str]]) -> str:
    themes = {_weekly_takeaway_theme(item) for item in weekly_items}
    themes.discard("")

    if {"supply", "subscription_measurement", "economics"} <= themes or {"supply", "measurement", "economics"} <= themes:
        return "This week's signals point to a more performance-driven app-growth ecosystem: cleaner programmatic supply, better subscription measurement, and stronger platform economics."
    if {"web_to_app", "economics", "leadership"} <= themes:
        return "This week's signals point to a more mature app-growth ecosystem: better web-to-app journeys, stronger platform economics, and experienced leadership around performance advertising."
    if "ai" in themes and "ctv" in themes:
        return "This week's strongest pattern: AI workflows and CTV execution are moving closer to measurable performance marketing."
    if "measurement" in themes and "fraud" in themes:
        return "This week's strongest pattern: measurement and traffic-quality signals continue to converge around cleaner, more accountable growth."
    if "measurement" in themes and "ctv" in themes:
        return "This week's strongest pattern: measurement, verified supply, and CTV automation are moving closer to performance marketing."
    if "web_to_app" in themes and "measurement" in themes:
        return "This week's signals show more pressure on marketers to connect web-to-app journeys with cleaner measurement and conversion accountability."
    if "economics" in themes and "leadership" in themes:
        return "This week's signals point to a market that is getting more disciplined: stronger platform economics and experienced leadership remain central to ad-growth execution."

    sections = _weekly_sections(text)
    suggests = sections.get("3. What This Suggests", [])
    if suggests:
        candidate = _clean_markdown_text(suggests[0])
        if "ai" not in " ".join(item.get("line", "").lower() for item in weekly_items) and re.search(r"\bai\b", candidate, flags=re.IGNORECASE):
            candidate = ""
        if candidate:
            return _clean_trailing_fragment(_shorten(candidate, 160))
    week_line = _first_bullet(sections.get("1. Week In One Line", []), "")
    if week_line:
        candidate = _clean_markdown_text(week_line)
        if "ai" not in " ".join(item.get("line", "").lower() for item in weekly_items) and re.search(r"\bai\b", candidate, flags=re.IGNORECASE):
            candidate = ""
        if candidate:
            return _clean_trailing_fragment(_shorten(candidate, 160))
    if weekly_items:
        return "This week's signals point to continued movement across measurement, platform execution, and app-growth infrastructure."
    return ""


def _weekly_takeaway_theme(item: dict[str, str]) -> str:
    text = " ".join(
        [
            item.get("line", ""),
            item.get("source", ""),
            item.get("company", ""),
        ]
    ).lower()
    if any(term in text for term in ("deep linking", "deep link", "short links", "qr codes", "web-to-app", "branded domains", "truelink")):
        return "web_to_app"
    if any(term in text for term in ("programmatic", "inventory", "supply", "media.net", "ssp", "reliable inventory")):
        return "supply"
    if any(term in text for term in ("subscription", "superwall", "stripe", "lifecycle", "subscription events")):
        return "subscription_measurement"
    if any(term in text for term in ("financial results", "revenue", "profit", "earnings", "economics", "guidance")):
        return "economics"
    if any(term in text for term in ("appointed", "board of directors", "board", "leadership", "chief executive", "ceo")):
        return "leadership"
    if any(term in text for term in ("ctv", "streaming", "tv", "video inventory")):
        return "ctv"
    if any(term in text for term in ("measurement", "attribution", "signal hub", "privacy sandbox", "mmp")):
        return "measurement"
    if any(term in text for term in ("fraud", "ivt", "traffic quality", "verified traffic")):
        return "fraud"
    if any(term in text for term in ("ai", "agentic", "automation", "autopilot")):
        return "ai"
    return ""


def _first_bullet(values: list[str], fallback: str) -> str:
    return values[0] if values else fallback


def _strip_markdown_emphasis(text: str) -> str:
    return text.replace("**", "")


def _daily_intro_line(text: str) -> str:
    match = re.search(
        r"## Today's Useful Signal(?:s)?\s+(.+?)(?:\s+## Top Signal(?:s)?|\s+## Top Market Signal(?:s)?|\s+## Market Watch|\s+## Adjacent Watchlist|\s+## Strategic Context|\s+## What This Suggests|\Z)",
        text,
        flags=re.DOTALL,
    )
    if not match:
        return "Today's brief uses the best relevant market signals available."
    return _clean_markdown_text(match.group(1).strip())


def _daily_intro_paragraphs(text: str) -> list[str]:
    intro = _daily_intro_line(text)
    parts = [part.strip() for part in re.split(r"\n\s*\n", intro) if part.strip()]
    return [_shorten(part, 280) for part in parts] or ["Today's brief uses the best relevant market signals available."]


def _background_trend(text: str) -> str | None:
    lines = text.splitlines()
    start = None
    for heading in ("## Strategic Context", "## Background / Context"):
        try:
            start = lines.index(heading)
            break
        except ValueError:
            continue
    if start is None:
        return None
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if stripped.startswith("- "):
            cleaned = _clean_markdown_text(stripped.removeprefix("- ").strip())
            if cleaned.lower().startswith("background context, not a fresh daily signal."):
                return None
            return cleaned
    return None


def _section_bullets(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    try:
        start = lines.index(heading)
    except ValueError:
        return []
    values: list[str] = []
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if stripped.startswith("- "):
            values.append(_clean_markdown_text(stripped[2:].strip()))
    return values


def _telegram_item(item: dict[str, str], index: int) -> list[str]:
    lines = [
        f"{index}. {html.escape(_clean_trailing_fragment(_shorten(item['title'], 180)))}",
        "<b>Why it matters</b>",
        html.escape(_executive_line(item.get("why_it_matters") or item["title"], 220)),
        "<b>BidMatrix angle</b>",
        html.escape(_executive_line((item.get("bidmatrix_angle") or item.get("content_angle") or item["title"]).replace(": ", " — "), 200)),
        "<b>Action</b>",
        html.escape(_executive_line(item.get("action") or item.get("watch_next") or "Keep monitoring this signal for follow-up moves.", 180)),
        "<b>Source</b>",
        html.escape(_source_name(item)),
    ]
    if item.get("url"):
        lines.append(html.escape(item["url"]))
    lines.append("")
    return lines


def _telegram_watchlist_item(item: dict[str, str], index: int) -> list[str]:
    lines = [
        f"{index}. {html.escape(_clean_trailing_fragment(_shorten(item['title'], 180)))}",
        "<b>Why it may matter</b>",
        html.escape(_executive_line(item.get("why_it_matters") or item["title"], 220)),
        "<b>BidMatrix use</b>",
        html.escape(_executive_line(item.get("bidmatrix_angle") or "Relevance to BidMatrix is indirect; keep as watchlist only.", 200)),
        "<b>Action</b>",
        html.escape(_executive_line(item.get("action") or item.get("watch_next") or "Keep monitoring this signal for follow-up moves.", 160)),
        "<b>Source</b>",
        html.escape(_source_name(item)),
    ]
    if item.get("url"):
        lines.append(html.escape(item["url"]))
    lines.append("")
    return lines

def _shorten(text: str, max_chars: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    for separator in [". ", "; ", ": ", ", while ", ", amid ", ", with ", ", and ", ", "]:
        head = cleaned.split(separator, 1)[0].strip()
        if 35 <= len(head) <= max_chars:
            return _clean_trailing_fragment(head)
    cut = cleaned[:max_chars].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return _clean_trailing_fragment(cut)


def _sync_intro_count(intro: str, count: int) -> str:
    lowered = intro.lower()
    if (
        "supplemented with" in lowered
        or "fresh signals were limited" in lowered
        or "fresh high-confidence signals were limited" in lowered
    ):
        return intro
    noun = "signal" if count == 1 else "signals"
    updated = re.sub(r"^Found\s+\d+\s+", f"Found {count} ", intro, count=1)
    updated = re.sub(r"\bsignal\(s\)\b", noun, updated)
    if count == 1:
        updated = re.sub(r"\bsignals\b", "signal", updated, count=1)
    else:
        updated = re.sub(r"\bsignal\b", "signals", updated, count=1)
    return updated


def _source_name(item: dict[str, str]) -> str:
    return item.get("source") or item.get("url") or "source"


def _telegram_daily_news_item(item: dict[str, str], index: int) -> list[str]:
    sentence = _telegram_compact_daily_line(item)
    lines = [
        f"{index}. {html.escape(sentence)}",
    ]
    if item.get("url"):
        lines.append(html.escape(item["url"]))
    lines.append("")
    return lines


def _telegram_compact_daily_line(item: dict[str, str]) -> str:
    happened = _telegram_what_happened_line(item)
    return _clean_trailing_fragment(_shorten(happened, 180))


def _filter_telegram_daily_items(items: list[dict[str, str]], run_date: date | None) -> tuple[list[dict[str, str]], dict[str, int | dict[str, int]]]:
    filtered: list[dict[str, str]] = []
    low_confidence_fresh_trusted: list[dict[str, str]] = []
    stats = {
        "fresh_7d_count": 0,
        "recent_14d_count": 0,
        "recent_30d_count": 0,
        "unknown_trusted_count": 0,
        "future_date_rejected_count": 0,
        "confidence_relaxation_used": False,
        "date_quality_breakdown": {},
    }
    breakdown: dict[str, int] = {}
    for item in items:
        if _telegram_is_self_item(item):
            continue
        status = _telegram_date_status(item, run_date)
        quality = status["quality"]
        breakdown[quality] = breakdown.get(quality, 0) + 1
        if quality == "future_invalid":
            stats["future_date_rejected_count"] += 1
            continue
        if quality == "old_2025_or_earlier":
            continue
        if quality == "older_than_30d":
            continue
        if item.get("confidence") == "low":
            if _telegram_can_relax_low_confidence(item, quality):
                relaxed_item = dict(item)
                relaxed_item["_telegram_date_quality"] = quality
                relaxed_item["_telegram_confidence_relaxed"] = True
                low_confidence_fresh_trusted.append(relaxed_item)
            continue
        if quality == "unknown_trusted":
            if not _telegram_is_trusted_unknown(item):
                continue
            stats["unknown_trusted_count"] += 1
        elif quality == "fresh_7d":
            stats["fresh_7d_count"] += 1
        elif quality == "recent_14d":
            stats["recent_14d_count"] += 1
        elif quality == "recent_30d":
            stats["recent_30d_count"] += 1
        else:
            continue
        item = dict(item)
        item["_telegram_date_quality"] = quality
        filtered.append(item)
    if not filtered and low_confidence_fresh_trusted:
        low_confidence_fresh_trusted.sort(
            key=lambda item: (-_telegram_daily_priority(item), item.get("title", "").lower())
        )
        filtered = low_confidence_fresh_trusted[:2]
        stats["fresh_7d_count"] = len(filtered)
        stats["confidence_relaxation_used"] = True
    stats["date_quality_breakdown"] = breakdown
    return filtered, stats


def _select_telegram_daily_items(
    top_items: list[dict[str, str]],
    adjacent_items: list[dict[str, str]],
    *,
    target: int = 3,
    limit: int = 4,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    selected: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    seen_companies: set[str] = set()
    seen_buckets: set[str] = set()
    ranked_top = sorted(top_items, key=lambda item: (-_telegram_daily_priority(item), item.get("title", "").lower()))
    ranked_adjacent = sorted(adjacent_items, key=lambda item: (-_telegram_daily_priority(item), item.get("title", "").lower()))
    meta = {
        "fresh_7d_count": 0,
        "recent_14d_count": 0,
        "recent_30d_count": 0,
        "unknown_trusted_count": 0,
        "confidence_relaxation_used": False,
    }

    def add_candidates(candidates: list[dict[str, str]], *, unique_bucket: bool, allowed_qualities: set[str]) -> None:
        for item in candidates:
            if len(selected) >= target:
                return
            if item.get("_telegram_date_quality") not in allowed_qualities:
                continue
            url = (item.get("url") or "").strip().lower()
            title = (item.get("title") or "").strip().lower()
            company = _telegram_item_company(item).strip().lower()
            bucket = _telegram_daily_bucket(item)
            if url and url in seen_urls:
                continue
            if title and title in seen_titles:
                continue
            if company and company in seen_companies:
                continue
            if unique_bucket and bucket in seen_buckets:
                continue
            selected.append(item)
            if url:
                seen_urls.add(url)
            if title:
                seen_titles.add(title)
            if company:
                seen_companies.add(company)
            if bucket:
                seen_buckets.add(bucket)
            quality = item.get("_telegram_date_quality")
            if quality == "fresh_7d":
                meta["fresh_7d_count"] += 1
            elif quality == "recent_14d":
                meta["recent_14d_count"] += 1
            elif quality == "recent_30d":
                meta["recent_30d_count"] += 1
            elif quality == "unknown_trusted":
                meta["unknown_trusted_count"] += 1
            if item.get("_telegram_confidence_relaxed"):
                meta["confidence_relaxation_used"] = True

    for allowed in (
        {"fresh_7d"},
        {"recent_14d"},
        {"unknown_trusted"},
        {"recent_30d"},
    ):
        add_candidates(ranked_top, unique_bucket=True, allowed_qualities=allowed)
        if len(selected) < target:
            add_candidates(ranked_adjacent, unique_bucket=True, allowed_qualities=allowed)
    if len(selected) < 2:
        for allowed in (
            {"fresh_7d"},
            {"recent_14d"},
            {"unknown_trusted"},
            {"recent_30d"},
        ):
            add_candidates(ranked_top, unique_bucket=False, allowed_qualities=allowed)
            if len(selected) < 2:
                add_candidates(ranked_adjacent, unique_bucket=False, allowed_qualities=allowed)
    return selected[:limit], meta


def _telegram_item_date(item: dict[str, str]) -> date | None:
    source = item.get("source", "")
    match = re.search(r"Date:\s*(\d{4}-\d{2}-\d{2})", source)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _telegram_is_self_item(item: dict[str, str]) -> bool:
    text = " ".join([item.get("title", ""), item.get("source", ""), item.get("url", "")]).lower()
    return "bidmatrix" in text


def _telegram_date_status(item: dict[str, str], run_date: date | None) -> dict[str, str | int | None]:
    published = _telegram_item_date(item)
    if run_date is None:
        return {"quality": "missing_or_unknown_date", "age_days": None}
    if published is None:
        return {"quality": "unknown_trusted" if _telegram_is_trusted_unknown(item) else "missing_or_unknown_date", "age_days": None}
    if published.year < 2026:
        return {"quality": "old_2025_or_earlier", "age_days": None}
    age_days = (run_date - published).days
    if age_days < 0:
        return {"quality": "future_invalid", "age_days": age_days}
    if age_days <= 7:
        return {"quality": "fresh_7d", "age_days": age_days}
    if age_days <= 14:
        return {"quality": "recent_14d", "age_days": age_days}
    if age_days <= 30:
        return {"quality": "recent_30d", "age_days": age_days}
    return {"quality": "older_than_30d", "age_days": age_days}


def _telegram_is_trusted_unknown(item: dict[str, str]) -> bool:
    source = (item.get("source") or "").lower()
    title = (item.get("title") or "").lower()
    body = " ".join([item.get("what_happened", ""), item.get("why_it_matters", ""), item.get("bidmatrix_angle", "")]).lower()
    if "high-signal" not in source:
        return False
    if item.get("confidence") == "low":
        return False
    recent_markers = ("launch", "launched", "update", "updated", "announced", "report", "guidance", "privacy", "fraud", "ctv", "measurement", "attribution")
    return any(term in title or term in body for term in recent_markers)


def _telegram_can_relax_low_confidence(item: dict[str, str], quality: str) -> bool:
    if quality != "fresh_7d":
        return False
    if _telegram_is_self_item(item):
        return False
    source = (item.get("source") or "").lower()
    if "high-signal" not in source:
        return False
    if _telegram_daily_bucket(item) in {"general", "cross_screen"}:
        return False
    text = " ".join(
        [
            item.get("title", ""),
            item.get("what_happened", ""),
            item.get("why_it_matters", ""),
            item.get("bidmatrix_angle", ""),
            source,
        ]
    ).lower()
    low_quality_markers = (
        "product updates",
        "latest features",
        "release notes",
        "roundup",
        "highlights",
        "weekly roundup",
    )
    return not any(marker in text for marker in low_quality_markers)


def _telegram_item_counts_as_core(item: dict[str, str]) -> bool:
    angle = " ".join(
        [
            item.get("bidmatrix_angle", ""),
            item.get("content_angle", ""),
            item.get("why_it_matters", ""),
        ]
    ).lower()
    adjacent_markers = (
        "broad cross-screen context",
        "relevant only if",
        "indirect",
        "watchlist only",
    )
    if any(marker in angle for marker in adjacent_markers):
        return False
    return item.get("section") == "top"


def _telegram_daily_bucket(item: dict[str, str]) -> str:
    text = " ".join(
        [
            item.get("title", ""),
            item.get("what_happened", ""),
            item.get("why_it_matters", ""),
            item.get("bidmatrix_angle", ""),
            item.get("source", ""),
        ]
    ).lower()
    if any(term in text for term in ("ctv", "connected tv", "streaming", "total tv")):
        return "ctv"
    if any(term in text for term in ("agent hub", "agentic", "ai media buying", "campaign optimization", "automation")):
        return "ai_ops"
    if any(term in text for term in ("attribution", "skan", "privacy sandbox", "mmp", "measurement", "conversion rules")):
        return "measurement"
    if any(term in text for term in ("fraud", "ivt", "invalid traffic", "traffic quality", "verified traffic")):
        return "fraud"
    if any(term in text for term in ("dsp", "ssp", "programmatic", "in-app inventory", "marketplace", "supply", "bidder")):
        return "programmatic_supply"
    if any(term in text for term in ("app growth", "user acquisition", "ua ", "installs")):
        return "ua_growth"
    if any(term in text for term in ("dooh", "out-of-home", "billboards", "cross-screen")):
        return "cross_screen"
    return "general"


def _telegram_daily_priority(item: dict[str, str]) -> int:
    bucket = _telegram_daily_bucket(item)
    score = {"high": 12, "medium": 8, "low": 4}.get(item.get("confidence", "medium"), 6)
    score += {
        "measurement": 7,
        "fraud": 6,
        "ctv": 6,
        "ai_ops": 5,
        "programmatic_supply": 5,
        "ua_growth": 5,
        "cross_screen": 2,
        "general": 3,
    }.get(bucket, 3)
    text = " ".join([item.get("title", ""), item.get("what_happened", ""), item.get("source", "")]).lower()
    if any(term in text for term in ("sdk", "release notes", "ipv6", "release")):
        score -= 4
    quality = item.get("_telegram_date_quality")
    if quality == "fresh_7d":
        score += 8
    elif quality == "recent_14d":
        score += 4
    elif quality == "unknown_trusted":
        score -= 2
    elif quality == "recent_30d":
        score -= 4
    return score


def _telegram_affects_line(item: dict[str, str]) -> str:
    bucket = _telegram_daily_bucket(item)
    title = item.get("title", "").lower()
    happened = item.get("what_happened", "").lower()
    source = item.get("source", "").lower()
    text = " ".join([title, happened, source])
    if "kochava" in text and any(term in text for term in ("yahoo dsp", "stationone", "agentic dsp", "dsp workflow")):
        return "MMP-connected DSP workflows, agentic media buying, campaign optimization, and attribution-based decision support."
    if "meta" in text and any(term in text for term in ("ctv", "streaming", "tv oem", "freewheel", "magnite", "ssp")):
        return "CTV, premium video inventory, cross-screen media buying, and performance measurement."
    if any(term in text for term in ("openai", "chatgpt")) and any(term in text for term in ("conversion", "tracking", "pixel")):
        return "Ad measurement, conversion tracking, and performance accountability for AI-native ad platforms."
    if any(term in text for term in ("tiktok", "vistar", "dooh", "billboard", "out-of-home")):
        return "Cross-screen creative execution, DOOH media, and potential future app-campaign measurement."
    if any(term in text for term in ("fraud report", "state of fraud", "ivt", "invalid traffic", "fraud")):
        return "Traffic quality, fraud detection, IVT risk, channel quality, and verified acquisition sources."
    affects = {
        "measurement": "Attribution, MMP workflows, and privacy-safe measurement.",
        "fraud": "Traffic quality, fraud detection, IVT risk, channel quality, and verified acquisition sources.",
        "ctv": "CTV as performance media for app marketers and cross-screen measurement.",
        "ai_ops": "AI media buying, campaign optimization, and automated decision support.",
        "programmatic_supply": "Programmatic supply paths, in-app inventory access, and DSP or SSP infrastructure.",
        "ua_growth": "Mobile user acquisition, app growth, and performance marketing execution.",
        "cross_screen": "Cross-screen campaign execution; adjacent context unless it becomes measurable for app campaigns.",
        "general": "Mobile adtech strategy and partner or competitor positioning.",
    }.get(bucket, "Mobile adtech strategy and partner or competitor positioning.")
    if item.get("section") == "adjacent" and not affects.endswith("Adjacent context."):
        return f"{affects} Adjacent context."
    return affects


def _telegram_bidmatrix_line(item: dict[str, str]) -> str:
    title = item.get("title", "").lower()
    happened = item.get("what_happened", "").lower()
    source = item.get("source", "").lower()
    text = " ".join([title, happened, source])
    if "google" in text and any(term in text for term in ("incrementality", "data manager", "meridian", "geox")):
        return "Use this as a sales and content angle around incrementality: more advertisers are looking beyond last-click reporting and need cleaner ways to prove whether media spend actually drives lift."
    if "appsflyer" in text and any(term in text for term in ("state of fraud", "fraud report")):
        return "Use this as support for content and sales conversations around verified traffic, fraud risk, and why clean acquisition sources matter for ROAS."
    if "moloco" in text and any(term in text for term in ("ctv", "performance ctv")):
        return "Use this in CTV positioning and BD conversations: app marketers increasingly expect TV inventory to work like measurable performance media, not just awareness."
    if "kochava" in text and any(term in text for term in ("yahoo dsp", "stationone", "agentic dsp", "dsp workflow")):
        return "Use this as partner and competitor monitoring: MMP and DSP workflows are moving closer together through AI-assisted media buying."
    if "meta" in text and any(term in text for term in ("ctv", "streaming", "tv oem", "freewheel", "magnite", "ssp")):
        return "Use this as broader CTV context in BD and positioning work: major ad platforms are exploring TV inventory as a performance and reach extension, but advertisers will still need measurable outcomes and verified environments."
    if any(term in text for term in ("openai", "chatgpt")) and any(term in text for term in ("conversion", "tracking", "pixel")):
        return "Use this as broader context for content and sales: AI-native ad platforms are moving toward measurable advertising, which reinforces the need for attribution clarity and performance safeguards."
    base = _executive_line(item.get("bidmatrix_angle") or item.get("content_angle") or item["title"], 170)
    if re.match(r"^(Supports|Strengthens) BidMatrix positioning around\b", base):
        return re.sub(r"^(Supports|Strengthens) BidMatrix positioning around\s*", "Use this in positioning and sales conversations around ", base, count=1)
    return base


def _telegram_what_happened_line(item: dict[str, str]) -> str:
    title = item.get("title", "").lower()
    happened = item.get("what_happened") or item.get("title") or ""
    source = item.get("source", "").lower()
    text = " ".join([title, happened.lower(), source])
    if "appsflyer" in text and any(term in text for term in ("state of fraud", "fraud report")):
        return "The report highlights where fraud pressure is concentrating across channels, verticals, and acquisition patterns."
    return _executive_line(happened, 180)


def _is_market_watch_intro(intro: str) -> bool:
    lowered = intro.lower()
    return (
        "no direct core bidmatrix signal dominated today" in lowered
        or "no core bidmatrix-relevant signals found today" in lowered
        or "strongest adjacent industry signals" in lowered
        or lowered.startswith("exa returned results, but no fresh bidmatrix-core items passed the filters")
    )


def _select_telegram_digest_items(items: list[dict[str, str]], limit: int = 3) -> list[dict[str, str]]:
    if not items:
        return []
    scored = [
        (_telegram_item_priority(item), item)
        for item in items
    ]
    filtered = [
        item for score, item in scored
        if score >= 8
    ] or [item for _, item in scored]
    ranked = sorted(
        filtered,
        key=lambda item: (-_telegram_item_priority(item), _telegram_item_company(item).lower(), item.get("title", "").lower()),
    )
    selected: list[dict[str, str]] = []
    seen_companies: set[str] = set()
    for item in ranked:
        company = _telegram_item_company(item).lower()
        if company and company in seen_companies:
            continue
        selected.append(item)
        if company:
            seen_companies.add(company)
        if len(selected) >= limit:
            return selected
    for item in ranked:
        if item in selected:
            continue
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def _telegram_item_company(item: dict[str, str]) -> str:
    title = item.get("title", "")
    for separator in (" — ", " – ", " - "):
        if separator in title:
            return title.split(separator, 1)[0].strip()
    return title.split(":", 1)[0].strip()


def _telegram_item_priority(item: dict[str, str]) -> int:
    text = " ".join(
        [
            item.get("title", ""),
            item.get("why_it_matters", ""),
            item.get("bidmatrix_angle", ""),
            item.get("action", ""),
            item.get("source", ""),
        ]
    ).lower()
    score = {"high": 12, "medium": 8, "low": 4}.get(item.get("confidence", "medium"), 6)
    if any(term in text for term in ("attribution", "skan", "privacy sandbox", "measurement", "mmp")):
        score += 6
    if any(term in text for term in ("fraud", "invalid traffic", "verified traffic", "traffic-quality", "traffic quality")):
        score += 5
    if any(term in text for term in ("ctv", "connected tv", "streaming inventory")):
        score += 5
    if any(term in text for term in ("ai-driven agents", "agent hub", "agentic", "optimization")):
        score += 4
    if any(term in text for term in ("dooh", "out-of-home", "billboards", "cross-screen")):
        score += 1
    if "older context" in text:
        score -= 6
    if any(term in text for term in ("android sdk", "sdk version", "release notes", "ipv6")):
        score -= 7
    return score

def _clean_trailing_fragment(text: str) -> str:
    original = text.rstrip()
    terminal = '?' if original.endswith('?') else '!' if original.endswith('!') else ''
    cleaned = text.rstrip(',;:.!?- ')
    cleaned = re.sub(r"\(\s*e\.?g\.?\s*$", "", cleaned, flags=re.IGNORECASE).rstrip(' ,;:.!?-')
    cleaned = re.sub(r"\(\s*$", "", cleaned).rstrip(' ,;:.!?-')
    cleaned = re.sub(r"\be\.?g\.?\s*$", "", cleaned, flags=re.IGNORECASE).rstrip(' ,;:.!?-')
    trailing_phrases = [
        'built on', 'based on', 'real-time', 'real time', 'using', 'allowing',
        'including', 'against', 'across', 'into', 'for', 'with', 'but', 'and',
        'to enable', 'to support', 'to help', 'such as', 'like'
    ]
    lower = cleaned.lower()
    removed_fragment = False
    for phrase in trailing_phrases:
        if lower.endswith(phrase):
            cleaned = cleaned[: -len(phrase)].rstrip(' ,;:.!?-')
            removed_fragment = True
            break
    if cleaned.count('(') > cleaned.count(')') and '(' in cleaned:
        cleaned = cleaned.rsplit('(', 1)[0].rstrip(' ,;:.!?-')
        removed_fragment = True
    if not cleaned:
        return ''
    if terminal and not removed_fragment:
        return cleaned + terminal
    if cleaned[-1] not in '.!?':
        cleaned += '.'
    return cleaned

def _date_from_subject(subject: str) -> str:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", subject)
    return match.group(1) if match else subject


def _subject_date(subject: str) -> date | None:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", subject)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _executive_line(text: str, max_chars: int) -> str:
    cleaned = _polish_sentence(text)
    cleaned = _naturalize_sentence(cleaned)
    cleaned = _clean_trailing_fragment(cleaned)
    return _shorten(cleaned, max_chars)


def _polish_sentence(text: str) -> str:
    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return ""

    replacements = [
        (r"^[A-Z][A-Za-z0-9&' .-]+ article discusses\s+", ""),
        (r"^Explain what\s+", ""),
        (r"^Frame BidMatrix as\s+", "BidMatrix can position around "),
        (r"^Position BidMatrix as\s+", "BidMatrix can position around "),
        (r"^Use this as a sales or partner conversation starter with\s+", "Discuss with "),
        (r"^A sales or partner conversation starter with\s+", "Discuss with "),
        (r"^Share\s+", ""),
        (r"^Sponsor or attend\s+", "Attend "),
        (r"^LinkedIn post/PR on\s+", ""),
        (r"^LinkedIn posts? on\s+", ""),
        (r"^Post about\s+", ""),
        (r"^Review for\s+", "Review "),
    ]
    for pattern, replacement in replacements:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

    cleaned = cleaned.replace(";", " — ").strip()
    cleaned = re.sub(r"\bchanges for mobile growth teams\b", "matters for mobile growth teams", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bbrand-safe supply\b", "safer, higher-quality ad inventory", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bbrand safety\b", "ad safety", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bARPU\b", "revenue", cleaned)
    cleaned = re.sub(r"\bpublisher monetization\b", "app monetization", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?<!in-app )\bmonetization economics\b", "in-app monetization economics", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?<!app )\bmonetization partners\b", "app monetization partners", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?<!app )(?<!in-app )(?<!publisher )\bmonetization\b", "app monetization", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bad inventory\b", "ad space", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bapp retention\b", "user retention", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bmalvertising\b", "harmful ads", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bintrusive ads\b", "disruptive ads", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bprogrammatic\b", "automated ad buying", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bbenchmarking\b", "ranking", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\buser experience\b", "user-friendly", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bsupply\b", "inventory", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bpublisher yield\b", "app ad revenue", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;:-")

    if not cleaned:
        return ""

    cleaned = cleaned[0].upper() + cleaned[1:]
    if cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned


def _clean_markdown_text(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "")
    return text.strip()


def _naturalize_sentence(text: str) -> str:
    cleaned = text.strip()
    rewrites = [
        (
            r"^AppHarbr.*ranking ad networks on safety, user-friendly.*$",
            "AppHarbr launched a new ranking that shows which ad networks are safer and more user-friendly.",
        ),
        (
            r"^Introduces first benchmark for in-app ad quality.*$",
            "It gives advertisers and app teams a clearer way to compare ad quality inside mobile apps.",
        ),
        (
            r"^Meta is holding exploratory meetings with SSPs like Magnite and FreeWheel, TV OEMs.*$",
            "Meta is exploring CTV expansion through talks with SSPs, TV OEMs, and streaming partners.",
        ),
    ]
    for pattern, replacement in rewrites:
        if re.match(pattern, cleaned, flags=re.IGNORECASE):
            return replacement
    return cleaned


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 80].rstrip() + "\n\n[Truncated. Open the local Markdown report for the full brief.]"

def _truncate_daily(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    marker = "<b>Source</b>"
    idx = -1
    start = 0
    for _ in range(3):
        found = text.find(marker, start)
        if found == -1:
            break
        idx = found
        start = found + len(marker)
    if idx != -1:
        next_break = text.find("\n\n", idx)
        if next_break != -1 and next_break < max_chars:
            text = text[:next_break].rstrip()
            if len(text) <= max_chars:
                return text
    return _truncate(text, max_chars)


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
