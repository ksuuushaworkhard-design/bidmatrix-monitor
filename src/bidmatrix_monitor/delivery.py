from __future__ import annotations

import html
import os
import re
import smtplib
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from .models import MonitorConfig


def maybe_deliver_report(config: MonitorConfig, markdown_path: Path, report_type: str) -> None:
    load_dotenv()
    if not _delivery_enabled(config, report_type):
        return

    channel = os.environ.get("BIDMATRIX_DELIVERY_CHANNEL", config.delivery.channel).strip().lower()
    subject = _subject(report_type, markdown_path)
    text = markdown_path.read_text(encoding="utf-8")

    if channel == "telegram":
        _send_telegram(subject, text, report_type)
    elif channel == "email":
        _send_email(subject, text)
    else:
        raise RuntimeError(f"Unsupported delivery channel: {channel}")


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


def _send_telegram(subject: str, text: str, report_type: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Telegram delivery requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")

    message = _telegram_message(subject, text, report_type)
    data = urlencode(
        {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
            "disable_notification": "false",
        }
    ).encode("utf-8")
    request = Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data, method="POST")
    with urlopen(request, timeout=30) as response:
        response.read()


def _telegram_message(subject: str, text: str, report_type: str) -> str:
    if report_type != "daily":
        return _telegram_weekly_message(subject, text)

    new_today = _summary_value(text, "New today count")
    new_week = _summary_value(text, "New this week count")
    items = _report_items(text)
    if _int_value(new_today) > 0:
        top_signals = _fresh_signals(items, limit=2, include_week=True)
        background_trend = None
    else:
        top_signals = _fresh_signals(items, limit=1, include_week=True)
        background_trend = _background_trend(items)

    date_label = _date_from_subject(subject)
    lines = [
        f"<b>BidMatrix Daily Brief — {html.escape(date_label)}</b>",
        "",
        f"<b>New today:</b> {html.escape(new_today)} | <b>New this week:</b> {html.escape(new_week)}",
    ]
    if top_signals:
        lines.extend(_telegram_item(top_signals[0], "TOP SIGNAL"))
    else:
        lines.extend(["", "<b>TOP SIGNAL</b>", "No strong fresh signal today."])

    if background_trend:
        lines.extend(
            [
                "",
                "<b>BACKGROUND</b>",
                html.escape(
                    _executive_line(
                        background_trend.get("why_it_matters")
                        or background_trend.get("summary")
                        or background_trend["title"],
                        105,
                    )
                ),
            ]
        )
    return _truncate("\n".join(lines), 1700)


def _telegram_weekly_message(subject: str, text: str) -> str:
    date_label = _date_from_subject(subject)
    sections = _weekly_sections(text)
    week_line = _first_bullet(sections.get("1. Week In One Line", []), "This was a light week with a small number of useful signals.")
    happened = sections.get("2. What Actually Happened This Week", [])[:2]
    suggests = sections.get("3. What This Suggests", [])[:2]
    matters = sections.get("4. Why It Matters For BidMatrix", [])[:2]
    watch = sections.get("7. Watch Next Week", [])[:2]

    lines = [f"<b>BidMatrix Weekly Brief — {html.escape(date_label)}</b>"]

    if "Signal volume was light this week" in text:
        lines.extend(["", "Signal volume was light this week."])

    lines.extend(["", "<b>Week in one line</b>", html.escape(_shorten(week_line, 120))])

    lines.append("")
    lines.append("<b>What happened</b>")
    if happened:
        for item in happened:
            lines.append(f"- {html.escape(_shorten(_strip_markdown_emphasis(item), 130))}")
    else:
        lines.append("- No strong weekly developments.")

    lines.append("")
    lines.append("<b>What this suggests</b>")
    for item in suggests or ["There was not enough evidence this week to support a broader conclusion."]:
        lines.append(f"- {html.escape(_shorten(item, 120))}")

    lines.append("")
    lines.append("<b>Why it matters for BidMatrix</b>")
    for item in matters or ["The best use of this week's signals is narrow positioning rather than a broad market claim."]:
        lines.append(f"- {html.escape(_shorten(item, 120))}")

    lines.append("")
    lines.append("<b>Watch next week</b>")
    for item in watch or ["Watch for stronger follow-up moves next week."]:
        lines.append(f"- {html.escape(_shorten(item, 100))}")

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


def _summary_value(text: str, label: str) -> str:
    match = re.search(rf"^- {re.escape(label)}:\s*(.+)$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else "unknown"


def _report_items(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    current_section = ""
    current: dict[str, str] | None = None
    seen_urls: set[str] = set()

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            current_section = stripped.removeprefix("## ").strip()
            continue

        heading = re.match(r"^### \[(?P<title>[^\]]+)\]\((?P<url>[^)]+)\)$", stripped)
        if heading:
            if current and current["url"] not in seen_urls:
                items.append(current)
                seen_urls.add(current["url"])
            current = {
                "section": current_section,
                "title": _clean_markdown_text(heading.group("title")),
                "url": heading.group("url").strip(),
                "meta": "",
                "summary": "",
                "why_it_matters": "",
                "bidmatrix_angle": "",
                "suggested_action": "",
            }
            continue

        if current is None:
            continue

        if stripped.startswith("_Source:"):
            current["meta"] = _clean_markdown_text(stripped)
        elif stripped.startswith("- Market move:"):
            current["summary"] = _clean_markdown_text(stripped.removeprefix("- Market move:").strip())
        elif stripped.startswith("- PR angle:"):
            current["why_it_matters"] = _clean_markdown_text(stripped.removeprefix("- PR angle:").strip())
        elif stripped.startswith("- LinkedIn angle:"):
            current["bidmatrix_angle"] = _clean_markdown_text(stripped.removeprefix("- LinkedIn angle:").strip())
        elif stripped.startswith("- Partner/sales action:"):
            current["suggested_action"] = _clean_markdown_text(
                stripped.removeprefix("- Partner/sales action:").strip()
            )

    if current and current["url"] not in seen_urls:
        items.append(current)
    return items


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


def _first_bullet(values: list[str], fallback: str) -> str:
    return values[0] if values else fallback


def _strip_markdown_emphasis(text: str) -> str:
    return text.replace("**", "")


def _fresh_signals(items: list[dict[str, str]], limit: int, include_week: bool = True) -> list[dict[str, str]]:
    allowed = {"new last 24h", "new last 7d"} if include_week else {"new last 24h"}
    fresh = [
        item
        for item in items
        if _freshness(item) in allowed
        and ("must read" in item.get("meta", "").lower() or item.get("section") in {"Actually New Today", "Fresh But Weak Confidence", "New This Week", "1. Top 5 Market Moves"})
    ]
    return _unique_items(fresh)[:limit]


def _background_trend(items: list[dict[str, str]]) -> dict[str, str] | None:
    for item in items:
        if item.get("section") == "Background Context":
            return item
    return None


def _telegram_item(item: dict[str, str], heading: str) -> list[str]:
    return [
        "",
        f"<b>{heading}</b>",
        html.escape(_executive_line(item.get("summary") or item["title"], 105)),
        "",
        "<b>Why it matters</b>",
        html.escape(_executive_line(item.get("why_it_matters") or item.get("summary") or item["title"], 105)),
        "",
        "<b>BidMatrix angle</b>",
        html.escape(_bidmatrix_angle_line(item)),
        "",
        "<b>Action</b>",
        html.escape(_action_line(item)),
        "",
        "<b>Source</b>",
        html.escape(_source_name(item)),
    ]


def _freshness(item: dict[str, str]) -> str:
    match = re.search(r"Freshness:\s*([^|]+)", item.get("meta", ""), flags=re.IGNORECASE)
    return match.group(1).strip().lower() if match else ""


def _unique_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    unique = []
    seen: set[str] = set()
    for item in items:
        url = item["url"]
        if url in seen:
            continue
        seen.add(url)
        unique.append(item)
    return unique


def _shorten(text: str, max_chars: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    for separator in [". ", "; ", ": ", ", while ", ", amid ", ", with ", ", and ", ", "]:
        head = cleaned.split(separator, 1)[0].strip()
        if 35 <= len(head) <= max_chars:
            return head.rstrip(",;:-.") + "."
    cut = cleaned[:max_chars].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(",;:-.") + "."


def _source_name(item: dict[str, str]) -> str:
    meta = item.get("meta", "")
    match = re.search(r"Source:\s*([^|]+)", meta, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    url_match = re.match(r"https?://([^/]+)", item["url"])
    return url_match.group(1).removeprefix("www.") if url_match else "source"


def _date_from_subject(subject: str) -> str:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", subject)
    return match.group(1) if match else subject


def _int_value(value: str) -> int:
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else 0


def _executive_line(text: str, max_chars: int) -> str:
    cleaned = _polish_sentence(text)
    cleaned = _naturalize_sentence(cleaned)
    return _shorten(cleaned, max_chars)


def _bidmatrix_angle_line(item: dict[str, str]) -> str:
    base = _polish_sentence(item.get("bidmatrix_angle") or "")
    lowered = base.lower()
    if any(term in lowered for term in ["brand safety", "traffic quality", "fraud"]):
        return "Strengthens the case for BidMatrix around safer, higher-quality ad inventory."
    if any(term in lowered for term in ["monetization", "yield", "ssp", "programmatic"]):
        return "Supports BidMatrix positioning around helping apps make more money from better ad demand."
    if any(term in lowered for term in ["ai", "creative", "measurement", "attribution"]):
        return "Supports BidMatrix's position on smarter growth, clearer measurement, and better-performing campaigns."
    if any(term in lowered for term in ["privacy", "sandbox", "skan"]):
        return "Supports BidMatrix positioning around privacy-safe growth and more reliable measurement."
    return _executive_line(base or item.get("why_it_matters") or item.get("summary") or item["title"], 105)


def _action_line(item: dict[str, str]) -> str:
    action = _polish_sentence(item.get("suggested_action") or "")
    companies = ", ".join(item.get("suggested_action", "").strip().rstrip(".").split(" with ")[-1].split(",")[:3]).strip()
    lowered = action.lower()
    if companies and companies != action:
        return _shorten(f"Watch follow-up moves from {companies}.", 95)
    if any(term in lowered for term in ["partner", "outreach", "sales"]):
        return "Use this signal in partner outreach and market positioning."
    if any(term in lowered for term in ["benchmark", "index", "report"]):
        return "Track whether similar benchmarks spread across other supply partners."
    if any(term in lowered for term in ["launch", "product", "release"]):
        return "Watch for follow-on launches, integrations, and partner responses."
    return _executive_line(action or "Use this signal in partner outreach and market positioning.", 95)


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
        (r"^Use this as\s+", ""),
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

    cleaned = cleaned.split(";")[0].strip()
    cleaned = cleaned.split(" using ", 1)[0].strip()
    cleaned = re.sub(r"\bchanges for mobile growth teams\b", "matters for mobile growth teams", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bwhat\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bbrand-safe supply\b", "safer, higher-quality ad inventory", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bbrand safety\b", "ad safety", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\btraffic quality\b", "traffic quality", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bARPU\b", "revenue", cleaned)
    cleaned = re.sub(r"\bpublisher monetization\b", "how apps make money from ads", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bmonetization\b", "how apps make money from ads", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bad inventory\b", "ad space", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bapp retention\b", "user retention", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bmalvertising\b", "harmful ads", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bintrusive ads\b", "disruptive ads", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bprogrammatic\b", "automated ad buying", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bbenchmarking\b", "ranking", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bad networks\b", "ad networks", cleaned, flags=re.IGNORECASE)
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


def _compact_markdown(text: str, max_chars: int) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# "):
            continue
        if stripped.startswith("## Background Context"):
            break
        lines.append(_clean_markdown_text(stripped))
        if len("\n".join(lines)) >= max_chars:
            break
    return _truncate("\n".join(lines), max_chars)


def _clean_markdown_text(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("_", "").replace("**", "")
    return text.strip()


def _naturalize_sentence(text: str) -> str:
    cleaned = text.strip()
    rewrites = [
        (
            r"^AppHarbr’s In-App Network Ad Quality Index release, ranking ad networks on safety, user-friendly\.$",
            "AppHarbr launched a new ranking that shows which ad networks are safer and more user-friendly.",
        ),
        (
            r"^AppHarbr’s In-App Network Ad Quality Index release, ranking ad networks on safety, user-friendly$",
            "AppHarbr launched a new ranking that shows which ad networks are safer and more user-friendly.",
        ),
        (
            r"^AppHarbr released its In-App Network Ad Quality Index, ranking ad networks on safety, user-friendly\.$",
            "AppHarbr launched a new ranking that shows which ad networks are safer and more user-friendly.",
        ),
        (
            r"^AppHarbr released its In-App Network Ad Quality Index, ranking ad networks on safety, user-friendly$",
            "AppHarbr launched a new ranking that shows which ad networks are safer and more user-friendly.",
        ),
        (
            r"^AppHarbr released its In-App Network Ad Quality Index, ranking ad networks on safety, user-friendly, and .*\.$",
            "AppHarbr launched a new ranking that shows which ad networks are safer and more user-friendly.",
        ),
        (
            r"^AppHarbr released its In-App Network Ad Quality Index, ranking ad networks on safety, user-friendly, and .*",
            "AppHarbr launched a new ranking that shows which ad networks are safer and more user-friendly.",
        ),
        (
            r"^Introduces first benchmark for in-app ad quality\.$",
            "It gives advertisers and app teams a clearer way to compare ad quality inside mobile apps.",
        ),
        (
            r"^Introduces first benchmark for in-app ad quality$",
            "It gives advertisers and app teams a clearer way to compare ad quality inside mobile apps.",
        ),
        (
            r"^Introduces first benchmark for in-app ad quality,.*",
            "It gives advertisers and app teams a clearer way to compare ad quality inside mobile apps.",
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


def _bool(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
