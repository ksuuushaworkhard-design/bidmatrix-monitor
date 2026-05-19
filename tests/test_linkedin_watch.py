from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

from bidmatrix_monitor import cli as cli_module
from bidmatrix_monitor.linkedin_watch import (
    build_linkedin_watch_preview,
    load_linkedin_posts_input,
    load_linkedin_watchlist,
    render_linkedin_watch_markdown,
    score_linkedin_posts,
    _short_insight,
)


def _watchlist() -> dict:
    return {
        "experts": [
            {
                "name": "Gadi Eliashiv",
                "linkedin_url": "https://www.linkedin.com/in/gadie",
                "priority": "high",
                "topic_tags": ["measurement", "analytics", "fraud"],
                "expected_use": ["content idea", "sales talking point"],
            },
            {
                "name": "Jason Fairchild",
                "linkedin_url": "https://www.linkedin.com/in/jasonfairchild",
                "priority": "high",
                "topic_tags": ["ctv", "app growth"],
                "expected_use": ["deck/positioning angle"],
            },
        ],
        "companies": [
            {
                "name": "Adjust",
                "linkedin_url": "https://www.linkedin.com/company/adjustcom/",
                "priority": "high",
                "topic_tags": ["mmp", "attribution", "subscriptions"],
                "expected_use": ["BD outreach", "sales talking point"],
            }
        ],
        "communities": [
            {
                "name": "App Growth Summit®",
                "linkedin_url": "https://www.linkedin.com/company/app-growth-summit/",
                "priority": "medium",
                "topic_tags": ["mobile growth", "community"],
                "expected_use": ["market trend"],
            }
        ],
        "mvp_shortlist": {
            "daily": ["Adjust", "Gadi Eliashiv", "Jason Fairchild"],
            "twice_weekly": ["App Growth Summit®"],
            "weekly": [],
        },
    }


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_load_linkedin_watchlist_validates_expected_top_level_keys(tmp_path: Path) -> None:
    path = _write_json(tmp_path / "watchlist.json", {"experts": [], "companies": []})

    with pytest.raises(ValueError, match="unexpected top-level structure"):
        load_linkedin_watchlist(path)


def test_load_linkedin_posts_input_requires_supported_url_and_dates(tmp_path: Path) -> None:
    watchlist = _watchlist()
    path = _write_json(
        tmp_path / "posts.json",
        {
            "posts": [
                {
                    "source_name": "Adjust",
                    "post_url": "not-a-url",
                    "post_text": "Adjust launched something useful.",
                    "published_at": "2026-05-19",
                    "collected_at": "2026-05-19T09:00:00Z",
                    "topic_tags": ["mmp"],
                }
            ]
        },
    )

    with pytest.raises(ValueError, match="post_url"):
        load_linkedin_posts_input(path, watchlist)


def test_load_linkedin_posts_input_rejects_unknown_source_by_default(tmp_path: Path) -> None:
    watchlist = _watchlist()
    path = _write_json(
        tmp_path / "posts.json",
        {
            "posts": [
                {
                    "source_name": "Unknown Source",
                    "post_url": "https://www.linkedin.com/posts/example_unknown",
                    "post_text": "Unknown source posted about attribution changes.",
                    "published_at": "2026-05-19",
                    "collected_at": "2026-05-19T09:00:00Z",
                    "topic_tags": ["attribution"],
                }
            ]
        },
    )

    with pytest.raises(ValueError, match="was not found"):
        load_linkedin_posts_input(path, watchlist)


def test_load_linkedin_posts_input_allows_unknown_source_only_when_explicitly_marked_for_verification(
    tmp_path: Path,
) -> None:
    watchlist = _watchlist()
    path = _write_json(
        tmp_path / "posts.json",
        {
            "posts": [
                {
                    "source_name": "Unknown Source",
                    "source_url": "https://www.linkedin.com/company/example-source/",
                    "post_url": "https://www.linkedin.com/posts/example_unknown",
                    "post_text": "Unknown source posted about attribution changes.",
                    "published_at": "2026-05-19",
                    "collected_at": "2026-05-19T09:00:00Z",
                    "topic_tags": ["attribution"],
                    "needs_verification": True,
                }
            ]
        },
    )

    posts = load_linkedin_posts_input(path, watchlist)

    assert posts[0]["needs_verification"] is True
    assert posts[0]["source_config"] is None


def test_load_linkedin_posts_input_validates_source_url_when_present(tmp_path: Path) -> None:
    watchlist = _watchlist()
    path = _write_json(
        tmp_path / "posts.json",
        {
            "posts": [
                {
                    "source_name": "Adjust",
                    "source_url": "not-a-url",
                    "post_url": "https://www.linkedin.com/posts/adjustcom_example",
                    "post_text": "Adjust announced a new subscriptions measurement integration.",
                    "published_at": "2026-05-19",
                    "collected_at": "2026-05-19T09:00:00Z",
                    "topic_tags": ["mmp", "subscriptions"],
                }
            ]
        },
    )

    with pytest.raises(ValueError, match="source_url"):
        load_linkedin_posts_input(path, watchlist)


def test_load_linkedin_posts_input_enriches_source_url_from_watchlist(tmp_path: Path) -> None:
    watchlist = _watchlist()
    path = _write_json(
        tmp_path / "posts.json",
        {
            "posts": [
                {
                    "source_name": "Adjust",
                    "source_url": "",
                    "post_url": "https://www.linkedin.com/posts/adjustcom_example",
                    "post_text": "Adjust announced a new subscriptions measurement integration.",
                    "published_at": "2026-05-19",
                    "collected_at": "2026-05-19T09:00:00Z",
                    "topic_tags": ["mmp", "subscriptions"],
                }
            ]
        },
    )

    posts = load_linkedin_posts_input(path, watchlist)

    assert posts[0]["source_url"] == "https://www.linkedin.com/company/adjustcom/"
    assert posts[0]["source_config"]["name"] == "Adjust"


def test_score_linkedin_posts_prefers_fresh_high_priority_relevant_posts() -> None:
    watchlist = _watchlist()
    posts = [
        {
            "source_name": "Adjust",
            "post_url": "https://www.linkedin.com/posts/adjustcom_a",
            "post_text": "Adjust announced a subscriptions measurement integration for cleaner attribution and optimization.",
            "published_at": "2026-05-19",
            "collected_at": "2026-05-19T10:00:00Z",
            "topic_tags": ["mmp", "attribution", "subscriptions"],
            "source_config": watchlist["companies"][0],
        },
        {
            "source_name": "App Growth Summit®",
            "post_url": "https://www.linkedin.com/posts/appgrowthsummit_b",
            "post_text": "Join us next week for speaker sessions and networking at App Growth Summit.",
            "published_at": "2026-04-20",
            "collected_at": "2026-05-19T10:00:00Z",
            "topic_tags": ["community", "event"],
            "source_config": watchlist["communities"][0],
        },
    ]

    scored = score_linkedin_posts(posts, watchlist, run_date=date(2026, 5, 19))

    assert scored[0]["source_name"] == "Adjust"
    assert scored[0]["scores"]["total_score"] > scored[1]["scores"]["total_score"]


def test_render_linkedin_watch_markdown_uses_minimal_preview_format() -> None:
    markdown = render_linkedin_watch_markdown(
        [
            {
                "source_name": "Adjust",
                "post_url": "https://www.linkedin.com/posts/adjustcom_a",
                "short_insight": "Adjust announced a subscriptions measurement integration.",
            },
            {
                "source_name": "Gadi Eliashiv",
                "post_url": "https://www.linkedin.com/posts/gadie_b",
                "short_insight": "Gadi Eliashiv argued that incrementality is becoming a budget-planning requirement.",
            },
        ],
        run_date=date(2026, 5, 19),
    )

    assert markdown.startswith("BidMatrix LinkedIn Watch — 2026-05-19")
    assert "1. Adjust — Adjust announced a subscriptions measurement integration." in markdown
    assert "2. Gadi Eliashiv — Gadi Eliashiv argued that incrementality is becoming a budget-planning requirement." in markdown
    assert "What happened" not in markdown
    assert "How BidMatrix can use it" not in markdown
    assert "Source" not in markdown


def test_short_insight_strips_emojis_and_hype_markers_from_preview() -> None:
    insight = _short_insight(
        "🚨 Major announcement - Singular AI - our platform for marketing agents 🚨 "
        "The best data wins, and Singular's customers get the best data."
    )

    assert "🚨" not in insight
    assert "Major announcement" not in insight
    assert "Singular is positioning AI agents" in insight


def test_short_insight_does_not_keep_raw_hype_headline_for_gadi_example() -> None:
    insight = _short_insight(
        "🚨 Major announcement - Singular AI - our platform for marketing agents 🚨 "
        "The best data wins, and Singular's customers get the best data. "
        "Singular AI is our platform for building AI agents that think and acts like your best employee."
    )

    assert insight == (
        "Singular is positioning AI agents as a way for marketers to turn granular attribution data "
        "into autonomous campaign workflows."
    )


def test_short_insight_generates_clean_transparency_angle_for_jason_example() -> None:
    insight = _short_insight(
        "Performance advertising today boils down to trust. "
        "One theme came up quickly: a lot of buyers are frustrated by what Heather calls "
        "\"opacity disguised as performance.\" Automation and AI are essential for modern advertising, "
        "but they shouldn't hide how decisions are made. Advertisers need visibility into how signals "
        "drive optimization, validate outcomes, and influence strategy."
    )

    assert insight == "Performance platforms are being pushed to make AI-driven optimization more transparent, not just more automated."
    assert "boils down to trust" not in insight


def test_render_linkedin_watch_markdown_caps_output_at_five_items() -> None:
    posts = [
        {
            "source_name": f"Source {index}",
            "post_url": f"https://www.linkedin.com/posts/example_{index}",
            "short_insight": f"Insight {index}.",
        }
        for index in range(1, 8)
    ]

    markdown = render_linkedin_watch_markdown(posts, run_date=date(2026, 5, 19))

    assert "1. Source 1 — Insight 1." in markdown
    assert "5. Source 5 — Insight 5." in markdown
    assert "6. Source 6" not in markdown
    assert markdown.count("https://www.linkedin.com/posts/example_") == 5


def test_build_linkedin_watch_preview_writes_expected_report(tmp_path: Path) -> None:
    watchlist_path = _write_json(tmp_path / "watchlist.json", _watchlist())
    input_path = _write_json(
        tmp_path / "posts.json",
        {
            "posts": [
                {
                    "source_name": "Jason Fairchild",
                    "post_url": "https://www.linkedin.com/posts/jasonfairchild_ctv",
                    "post_text": "Jason Fairchild said app marketers increasingly expect CTV to behave like measurable performance media.",
                    "published_at": "2026-05-18",
                    "collected_at": "2026-05-19T09:00:00Z",
                    "topic_tags": ["ctv", "app growth"],
                },
                {
                    "source_name": "Gadi Eliashiv",
                    "post_url": "https://www.linkedin.com/posts/gadie_measurement",
                    "post_text": "Gadi Eliashiv wrote that incrementality is becoming a budget-planning question across app growth teams.",
                    "published_at": "2026-05-17",
                    "collected_at": "2026-05-19T09:10:00Z",
                    "topic_tags": ["measurement", "incrementality"],
                },
                {
                    "source_name": "Adjust",
                    "post_url": "https://www.linkedin.com/posts/adjustcom_subscriptions",
                    "post_text": "Adjust announced a Superwall integration for subscription lifecycle measurement.",
                    "published_at": "2026-05-19",
                    "collected_at": "2026-05-19T09:20:00Z",
                    "topic_tags": ["mmp", "subscriptions", "attribution"],
                },
            ]
        },
    )

    output_path = build_linkedin_watch_preview(
        input_path=input_path,
        watchlist_path=watchlist_path,
        report_dir=tmp_path / "reports",
        run_date=date(2026, 5, 19),
    )

    assert output_path.name == "linkedin-watch-preview-2026-05-19.md"
    markdown = output_path.read_text(encoding="utf-8")
    assert markdown.startswith("BidMatrix LinkedIn Watch — 2026-05-19")
    assert markdown.count("https://www.linkedin.com/posts/") == 3


def test_manual_examples_produce_clean_preview_insights() -> None:
    watchlist = _watchlist()
    posts = [
        {
            "source_name": "Gadi Eliashiv",
            "post_url": "https://www.linkedin.com/posts/gadie_example",
            "post_text": (
                "🚨 Major announcement - Singular AI - our platform for marketing agents 🚨 "
                "The best data wins, and Singular's customers get the best data. "
                "Singular AI is our platform for building AI agents that think and acts like your best employee."
            ),
            "published_at": "2026-05-19",
            "collected_at": "2026-05-19T09:00:00Z",
            "topic_tags": ["mmp", "attribution", "AI media buying", "agentic workflows", "measurement"],
            "source_config": watchlist["experts"][0],
        },
        {
            "source_name": "Jason Fairchild",
            "post_url": "https://www.linkedin.com/posts/jasonfairchild_example",
            "post_text": (
                "Performance advertising today boils down to trust. "
                "One theme came up quickly: a lot of buyers are frustrated by what Heather calls "
                "\"opacity disguised as performance.\" Automation and AI are essential for modern advertising, "
                "but they shouldn't hide how decisions are made. Advertisers need visibility into how signals "
                "drive optimization, validate outcomes, and influence strategy."
            ),
            "published_at": "2026-05-18",
            "collected_at": "2026-05-19T09:00:00Z",
            "topic_tags": ["CTV", "performance TV", "AI media buying", "programmatic", "traffic quality", "measurement"],
            "source_config": watchlist["experts"][1],
        },
    ]

    scored = score_linkedin_posts(posts, watchlist, run_date=date(2026, 5, 19))

    by_name = {item["source_name"]: item["short_insight"] for item in scored}
    assert by_name["Gadi Eliashiv"] == (
        "Singular is positioning AI agents as a way for marketers to turn granular attribution data "
        "into autonomous campaign workflows."
    )
    assert by_name["Jason Fairchild"] == (
        "Performance platforms are being pushed to make AI-driven optimization more transparent, not just more automated."
    )


def test_cli_linkedin_watch_preview_path_skips_normal_monitoring_and_delivery(monkeypatch, tmp_path: Path, capsys) -> None:
    output_path = tmp_path / "linkedin-watch-preview-2026-05-19.md"
    calls: list[str] = []

    def fake_build_linkedin_watch_preview(input_path):
        calls.append(f"preview:{input_path}")
        output_path.write_text("BidMatrix LinkedIn Watch — 2026-05-19\n", encoding="utf-8")
        return output_path

    def fail_load_config(*args, **kwargs):
        raise AssertionError("load_config should not be called for --linkedin-watch-preview")

    def fail_maybe_deliver(*args, **kwargs):
        raise AssertionError("maybe_deliver_report should not be called for --linkedin-watch-preview")

    monkeypatch.setattr(cli_module, "build_linkedin_watch_preview", fake_build_linkedin_watch_preview)
    monkeypatch.setattr(cli_module, "load_config", fail_load_config)
    monkeypatch.setattr(cli_module, "maybe_deliver_report", fail_maybe_deliver)
    monkeypatch.setattr(
        sys,
        "argv",
        ["bidmatrix-monitor", "--linkedin-watch-preview", "data/linkedin_posts_input.sample.json"],
    )

    cli_module.main()

    captured = capsys.readouterr()
    assert calls == ["preview:data/linkedin_posts_input.sample.json"]
    assert f"Wrote {output_path}" in captured.out
