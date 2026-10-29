from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class SubscriberSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class Subscriber:
    email: str
    first_name: str = ""
    last_name: str = ""


def sync_subscribers_from_environment() -> dict[str, int]:
    spreadsheet_id = _required("GOOGLE_SHEETS_SPREADSHEET_ID")
    sheet_range = os.environ.get("GOOGLE_SHEETS_SUBSCRIBER_RANGE", "Newsletter Subscribers!A:C").strip()
    credentials_json = _required("GOOGLE_SERVICE_ACCOUNT_JSON")
    segment_id = _required("WEEKLY_EMAIL_SEGMENT_ID")
    api_key = _required("RESEND_API_KEY")

    subscribers = _load_sheet_subscribers(spreadsheet_id, sheet_range, credentials_json)
    existing = _list_segment_emails(segment_id, api_key)
    created = 0
    attached = 0
    skipped = 0
    for subscriber in subscribers:
        if subscriber.email.lower() in existing:
            skipped += 1
            continue
        try:
            _resend_json(
                "POST",
                "https://api.resend.com/contacts",
                api_key,
                {
                    "email": subscriber.email,
                    "first_name": subscriber.first_name,
                    "last_name": subscriber.last_name,
                    "segments": [{"id": segment_id}],
                },
            )
            created += 1
        except SubscriberSyncError as exc:
            if "HTTP 409" not in str(exc):
                raise
            _resend_json(
                "POST",
                f"https://api.resend.com/contacts/{quote(subscriber.email, safe='')}/segments/{quote(segment_id, safe='')}",
                api_key,
                {},
            )
            attached += 1
    return {"sheet_contacts": len(subscribers), "created": created, "attached": attached, "unchanged": skipped}


def _load_sheet_subscribers(spreadsheet_id: str, sheet_range: str, credentials_json: str) -> list[Subscriber]:
    try:
        from google.auth.transport.requests import Request as GoogleAuthRequest
        from google.oauth2 import service_account

        info = json.loads(credentials_json)
        credentials = service_account.Credentials.from_service_account_info(info, scopes=[SHEETS_SCOPE])
        credentials.refresh(GoogleAuthRequest())
    except Exception as exc:
        raise SubscriberSyncError(f"Google service-account authentication failed: {exc}") from exc
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{quote(spreadsheet_id, safe='')}/values/"
        f"{quote(sheet_range, safe='')}?majorDimension=ROWS"
    )
    payload = _request_json(Request(url, headers={"Authorization": f"Bearer {credentials.token}"}))
    rows = payload.get("values") or []
    if not rows:
        return []
    header = [str(value).strip().lower().replace(" ", "_") for value in rows[0]]
    email_index = _header_index(header, "email")
    first_index = _optional_header_index(header, "first_name", "firstname")
    last_index = _optional_header_index(header, "last_name", "lastname")
    subscribers: list[Subscriber] = []
    seen: set[str] = set()
    for row in rows[1:]:
        email = _cell(row, email_index).lower()
        if not EMAIL_RE.match(email) or email in seen:
            continue
        seen.add(email)
        subscribers.append(Subscriber(email, _cell(row, first_index), _cell(row, last_index)))
    return subscribers


def _list_segment_emails(segment_id: str, api_key: str) -> set[str]:
    emails: set[str] = set()
    after = ""
    for _ in range(100):
        query = urlencode({"limit": 100, **({"after": after} if after else {})})
        payload = _resend_json(
            "GET", f"https://api.resend.com/segments/{quote(segment_id, safe='')}/contacts?{query}", api_key
        )
        data = payload.get("data") or []
        emails.update(str(item.get("email") or "").strip().lower() for item in data if item.get("email"))
        if not payload.get("has_more") or not data:
            break
        after = str(data[-1].get("id") or "")
        if not after:
            break
    return emails


def _resend_json(method: str, url: str, api_key: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    return _request_json(request)


def _request_json(request: Request) -> dict:
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise SubscriberSyncError(f"API returned HTTP {exc.code}: {details}") from exc
    except URLError as exc:
        raise SubscriberSyncError(f"API request failed: {exc.reason}") from exc
    return json.loads(raw) if raw else {}


def _header_index(header: list[str], name: str) -> int:
    if name not in header:
        raise SubscriberSyncError(f"Google Sheet must include a '{name}' column")
    return header.index(name)


def _optional_header_index(header: list[str], *names: str) -> int | None:
    return next((header.index(name) for name in names if name in header), None)


def _cell(row: list, index: int | None) -> str:
    return "" if index is None or index >= len(row) else str(row[index]).strip()


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SubscriberSyncError(f"Missing required environment variable: {name}")
    return value


def main() -> None:
    result = sync_subscribers_from_environment()
    print("SUBSCRIBER_SYNC_SUCCEEDED " + " ".join(f"{key}={value}" for key, value in result.items()))


if __name__ == "__main__":
    main()
