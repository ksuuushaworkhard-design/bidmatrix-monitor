from __future__ import annotations

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


def main() -> None:
    output_date = date.today().isoformat()
    report_dir = Path("reports")
    report_dir.mkdir(parents=True, exist_ok=True)

    json_path = report_dir / f"scrapegraph-enrichment-spike-{output_date}.json"
    md_path = report_dir / f"scrapegraph-enrichment-spike-{output_date}.md"

    results = run_spike(TEST_URLS)
    write_json_report(results, json_path, output_date)
    write_markdown_report(results, md_path, output_date)

    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")


def run_spike(urls: list[dict[str, str]]) -> list[EnrichmentResult]:
    api_key = os.getenv("SGAI_API_KEY")
    if not api_key:
        return [
            EnrichmentResult(
                label=item["label"],
                source_url=item["url"],
                status="error",
                error="SGAI_API_KEY is not set; skipping ScrapeGraphAI extraction.",
            )
            for item in urls
        ]

    try:
        from scrapegraph_py import SyncClient  # type: ignore
    except Exception as exc:
        return [
            EnrichmentResult(
                label=item["label"],
                source_url=item["url"],
                status="error",
                error=f"scrapegraph_py is not available: {exc}",
            )
            for item in urls
        ]

    try:
        client = SyncClient(api_key=api_key, timeout=30)
    except Exception as exc:
        return [
            EnrichmentResult(
                label=item["label"],
                source_url=item["url"],
                status="error",
                error=f"ScrapeGraphAI client initialization failed: {exc}",
            )
            for item in urls
        ]

    results: list[EnrichmentResult] = []

    prompt = (
        EXTRACTION_PROMPT
        + "\nReturn the answer as a JSON-like object with these keys: "
        "title, published_date, company_names, product_or_update, "
        "one_sentence_summary, topic_bucket, source_url."
    )

    for item in urls:
        url = item["url"]
        label = item["label"]

        try:
            response = client.smartscraper(
                website_url=url,
                user_prompt=prompt,
            )

            payload: dict[str, Any]
            if isinstance(response, dict):
                payload = response
            else:
                payload = {"raw_response": str(response)}

            payload["source_url"] = payload.get("source_url") or url

            results.append(
                EnrichmentResult(
                    label=label,
                    source_url=url,
                    status="success",
                    data=payload,
                )
            )

        except Exception as exc:
            results.append(EnrichmentResult(label, url, "error", error=str(exc)))

    return results


def write_json_report(results: list[EnrichmentResult], path: Path, output_date: str) -> None:
    payload = {
        "run_date": output_date,
        "tool": "ScrapeGraphAI enrichment spike",
        "results": [asdict(result) for result in results],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_markdown_report(results: list[EnrichmentResult], path: Path, output_date: str) -> None:
    lines = [f"# ScrapeGraph Enrichment Spike - {output_date}", ""]

    for index, result in enumerate(results, start=1):
        lines.append(f"## {index}. {result.label}")
        lines.append(f"- URL: {result.source_url}")
        lines.append(f"- Status: {result.status}")

        if result.status == "success" and result.data:
            lines.append(f"- Title: {result.data.get('title')}")
            lines.append(f"- Published date: {result.data.get('published_date')}")
            lines.append(f"- Company names: {', '.join(result.data.get('company_names') or [])}")
            lines.append(f"- Product or update: {result.data.get('product_or_update')}")
            lines.append(f"- One-sentence summary: {result.data.get('one_sentence_summary')}")
            lines.append(f"- Topic bucket: {result.data.get('topic_bucket')}")
        else:
            lines.append(f"- Error: {result.error}")

        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
