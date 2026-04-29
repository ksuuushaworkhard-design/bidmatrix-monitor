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

    date_label = _date_from_subject(subject)
    if "Daily brief skipped: not enough relevant market signals found today." in text:
        return "\n".join(
            [
                f"<b>BidMatrix Daily Brief — {html.escape(date_label)}</b>",
                "",
                "Daily brief skipped: not enough relevant market signals found today.",
            ]
        )

    items = _report_items(text)
    intro = _daily_intro_line(text)
    background = _background_trend(text)
    lines = [
        f"<b>BidMatrix Daily Brief — {html.escape(date_label)}</b>",
        "",
        "<b>Today's useful signals</b>",
        html.escape(_shorten(intro, 180)),
    ]

    if items:
        lines.extend(["", "<b>Top signal</b>" if len(items) == 1 else "<b>Top signals</b>"])
        for index, item in enumerate(items[:2], start=1):
            lines.extend(_telegram_item(item, index))

    if background and background != "No useful background context was kept.":
        lines.extend(["", "<b>Strategic context</b>", html.escape(_executive_line(background, 140))])

    return _truncate_daily("\n".join(lines), 3200)


def _telegram_weekly_message(subject: str, text: str) -> str:
    date_label = _date_from_subject(subject)
    sections = _weekly_sections(text)
    week_line = _first_bullet(
        sections.get("1. Week In One Line", []),
        "This was a light week with a small number of useful signals.",
    )
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


def _report_items(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    for line in text.splitlines():
        stripped = line.strip()
        heading = re.match(r"^### (?P<rank>\d+)\.\s+(?P<title>.+)$", stripped)
        if heading:
            if current:
                items.append(current)
            current = {
                "title": _clean_markdown_text(heading.group("title")),
                "url": "",
                "what_happened": "",
                "why_it_matters": "",
                "bidmatrix_angle": "",
                "content_angle": "",
                "action": "",
                "watch_next": "",
                "source": "",
            }
            continue

        if current is None:
            continue

        if stripped.startswith("- What happened:"):
            current["what_happened"] = _clean_markdown_text(stripped.removeprefix("- What happened:").strip())
        elif stripped.startswith("- Why it matters:"):
            current["why_it_matters"] = _clean_markdown_text(stripped.removeprefix("- Why it matters:").strip())
        elif stripped.startswith("- BidMatrix angle:"):
            current["bidmatrix_angle"] = _clean_markdown_text(stripped.removeprefix("- BidMatrix angle:").strip())
        elif stripped.startswith("- Content angle:"):
            current["content_angle"] = _clean_markdown_text(stripped.removeprefix("- Content angle:").strip())
        elif stripped.startswith("- Action:"):
            current["action"] = _clean_markdown_text(stripped.removeprefix("- Action:").strip())
        elif stripped.startswith("- Watch next:"):
            current["watch_next"] = _clean_markdown_text(stripped.removeprefix("- Watch next:").strip())
        elif stripped.startswith("- Source:"):
            current["source"] = _clean_markdown_text(stripped.removeprefix("- Source:").strip())
            url_match = re.search(r"\((https?://[^)]+)\)", stripped)
            if url_match:
                current["url"] = url_match.group(1)

    if current:
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


def _daily_intro_line(text: str) -> str:
    match = re.search(
        r"## Today's Useful Signal(?:s)?\s+(.+?)(?:\s+## Top Signal(?:s)?|\s+## Strategic Context|\Z)",
        text,
        flags=re.DOTALL,
    )
    if not match:
        return "Today's brief uses the best relevant market signals available."
    return _clean_markdown_text(match.group(1).strip())


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
            return _clean_markdown_text(stripped.removeprefix("- ").strip())
    return None


def _telegram_item(item: dict[str, str], index: int) -> list[str]:
    lines = [
        f"{index}. {html.escape(_shorten(item['title'], 180))}",
        "<b>What happened</b>",
        html.escape(_executive_line(item.get("what_happened") or item["title"], 260)),
        "<b>Why it matters</b>",
        html.escape(_executive_line(item.get("why_it_matters") or item["title"], 500)),
        "<b>BidMatrix angle</b>",
        html.escape(_executive_line((item.get("bidmatrix_angle") or item.get("content_angle") or item["title"]).replace(": ", " — "), 320)),
    ]
    if item.get("content_angle"):
        lines.extend([
            "<b>Content angle</b>",
            html.escape(_executive_line(item.get("content_angle"), 180)),
        ])
    lines.extend([
        "<b>Action</b>",
        html.escape(_executive_line(item.get("action") or item.get("watch_next") or "Keep monitoring this signal for follow-up moves.", 180)),
        "<b>Source</b>",
        html.escape(_source_name(item)),
    ])
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


def _source_name(item: dict[str, str]) -> str:
    return item.get("source") or item.get("url") or "source"

def _clean_trailing_fragment(text: str) -> str:
    cleaned = text.rstrip(',;:- ')
    cleaned = re.sub(r"\b(and|but|with|for|into|across|against|including|allowing|using)$", "", cleaned, flags=re.IGNORECASE).strip(' ,;:-')
    if cleaned and cleaned[-1] not in '.!?':
        cleaned += '.'
    return cleaned


def _date_from_subject(subject: str) -> str:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", subject)
    return match.group(1) if match else subject


def _executive_line(text: str, max_chars: int) -> str:
    cleaned = _polish_sentence(text)
    cleaned = _naturalize_sentence(cleaned)
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
    cleaned = re.sub(r"\bchanges for mobile growth teams\b", "matters for mobile growth teams", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bbrand-safe supply\b", "safer, higher-quality ad inventory", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bbrand safety\b", "ad safety", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bARPU\b", "revenue", cleaned)
    cleaned = re.sub(r"\bpublisher monetization\b", "how apps make money from ads", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bmonetization\b", "how apps make money from ads", cleaned, flags=re.IGNORECASE)
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
    text = text.replace("_", "").replace("**", "")
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
    idx = text.find(marker)
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
