from __future__ import annotations

from bidmatrix_monitor import subscriber_sync


def test_sync_adds_only_new_contacts_without_resubscribing(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_SHEETS_SPREADSHEET_ID", "sheet")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "{}")
    monkeypatch.setenv("WEEKLY_EMAIL_SEGMENT_ID", "segment")
    monkeypatch.setenv("RESEND_API_KEY", "key")
    monkeypatch.setattr(
        subscriber_sync,
        "_load_sheet_subscribers",
        lambda *args: [
            subscriber_sync.Subscriber("existing@example.com", "Existing", "Person"),
            subscriber_sync.Subscriber("new@example.com", "New", "Person"),
        ],
    )
    monkeypatch.setattr(subscriber_sync, "_list_segment_emails", lambda *args: {"existing@example.com"})
    calls = []
    monkeypatch.setattr(
        subscriber_sync,
        "_resend_json",
        lambda method, url, key, payload=None: calls.append((method, url, payload)) or {"id": "contact"},
    )

    result = subscriber_sync.sync_subscribers_from_environment()

    assert result == {"sheet_contacts": 2, "created": 1, "attached": 0, "unchanged": 1}
    assert len(calls) == 1
    assert calls[0][2]["email"] == "new@example.com"
    assert "unsubscribed" not in calls[0][2]


def test_sync_attaches_existing_global_contact_without_changing_subscription(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_SHEETS_SPREADSHEET_ID", "sheet")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "{}")
    monkeypatch.setenv("WEEKLY_EMAIL_SEGMENT_ID", "segment")
    monkeypatch.setenv("RESEND_API_KEY", "key")
    monkeypatch.setattr(
        subscriber_sync,
        "_load_sheet_subscribers",
        lambda *args: [subscriber_sync.Subscriber("known@example.com")],
    )
    monkeypatch.setattr(subscriber_sync, "_list_segment_emails", lambda *args: set())
    calls = []

    def fake_resend(method, url, key, payload=None):
        calls.append((method, url, payload))
        if url.endswith("/contacts"):
            raise subscriber_sync.SubscriberSyncError("API returned HTTP 409: contact exists")
        return {"id": "segment"}

    monkeypatch.setattr(subscriber_sync, "_resend_json", fake_resend)

    result = subscriber_sync.sync_subscribers_from_environment()

    assert result["attached"] == 1
    assert calls[-1][1].endswith("/contacts/known%40example.com/segments/segment")
    assert calls[-1][2] == {}
