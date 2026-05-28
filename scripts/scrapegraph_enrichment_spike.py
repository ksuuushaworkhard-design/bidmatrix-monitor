from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any


TEST_URLS = [
    {
        "label": "business_of_apps",
        "url": "https://www.businessofapps.com/news/mau-vegas-2026-is-happening-next-week/",
    },
    {
        "label": "digiday",
        "url": "https://digiday.com/media-buying/ad-tech-briefing-yahoo-pairs-with-kochava-to-pitch-agentic-dsp-workflows/",
    },
    {
        "label": "appsflyer",
        "url": "https://www.appsflyer.com/resources/reports/state-fraud-marketers/",
    },
    {
        "label": "moloco",
        "url": "https://www.moloco.com/press-releases/dawn-ostroff",
    },
]

EXTRACTION_PROMPT = """
Extract a concise structured summary for a BidMatrix market-brief enrichment spike.
Focus on factual public-web information only.
Return:
- title
- published_date
- company_names
- product_or_update
- one_sentence_summary
- topic_bucket
- source_url
Use null if a field is not available.
Keep one_sentence_summary short and clean.
"""

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": ["string", "null"]},
        "published_date": {"type": ["string", "null"]},
        "company_names": {
            "type": ["array", "null"],
            "items": {"type": "string"},
        },
        "product_or_update": {"type": ["string", "null"]},
        "one_sentence_summary": {"type": ["string", "null"]},
        "topic_bucket": {"type": ["string", "null"]},
        "source_url": {"type": ["string", "null"]},
    },
}


@dataclass
class EnrichmentResult:
    label: str
    source_url: str
    status: str
    data: dict[str, Any] | None = None
    error: str | None = None


def load_input_urls(path: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, list):
        raise ValueError("Input JSON must be a list of objects with label and url fields.")

    urls: list[dict[str, str]] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Input item #{index} must be an object.")

        label = item.get("label")
        url = item.get("url")

        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"Input item #{index} is missing a valid label.")

        if not isinstance(url, str) or not url.strip():
            raise ValueError(f"Input item #{index} is missing a valid url.")

        urls.append({"label": label.strip(), "url": url.strip()})

    return urls


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a manual ScrapeGraphAI enrichment spike for selected public URLs."
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Optional JSON file with a list of {label, url} objects.",
    )
    args = parser.parse_args()

    output_date = dt.date.today().isoformat()
    report_dir = Path("reports")
    report_dir.mkdir(parents=True, exist_ok=True)

    urls = load_input_urls(args.input) if args.input else TEST_URLS
    results = run_spike(urls)

    json_path = report_dir / f"scrapegraph-enrichment-spike-{output_date}.json"
    markdown_path = report_dir / f"scrapegraph-enrichment-spike-{output_date}.md"

    write_json_report(results, json_path, output_date)
    write_markdown_report(results, markdown_path, output_date)

    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")


if __name__ == "__main__":
    main()
