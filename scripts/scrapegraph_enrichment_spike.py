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
        import requests
    except Exception as exc:
        return [
            EnrichmentResult(
                label=item["label"],
                source_url=item["url"],
                status="error",
                error=f"requests is not available: {exc}",
            )
            for item in urls
        ]

    base_url = os.getenv("SGAI_API_BASE_URL", "https://v2-api.scrapegraphai.com/api").rstrip("/")
    endpoint = f"{base_url}/extract"
    headers = {
        "SGAI-APIKEY": api_key,
        "Content-Type": "application/json",
    }

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

        payload = {
            "website_url": url,
            "url": url,
            "prompt": prompt,
        }

        try:
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=30,
            )

            if response.status_code >= 400:
                results.append(
                    EnrichmentResult(
                        label=label,
                        source_url=url,
                        status="error",
                        error=f"[{response.status_code}] {response.text[:500]}",
                    )
                )
                continue

            try:
                response_payload = response.json()
            except Exception:
                response_payload = {"raw_response": response.text}

            if isinstance(response_payload, dict):
                payload_data = response_payload
            else:
                payload_data = {"raw_response": str(response_payload)}

            payload_data["source_url"] = payload_data.get("source_url") or url

            results.append(
                EnrichmentResult(
                    label=label,
                    source_url=url,
                    status="success",
                    data=payload_data,
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


def _extract_payload(data: dict[str, Any] | None) -> dict[str, Any]:
    if not data:
        return {}

    nested_json = data.get("json")
    if isinstance(nested_json, dict):
        return nested_json

    return data


def write_markdown_report(results: list[EnrichmentResult], path: Path, output_date: str) -> None:
    lines = [f"# ScrapeGraph Enrichment Spike - {output_date}", ""]

    for index, result in enumerate(results, start=1):
        lines.append(f"## {index}. {result.label}")
        lines.append(f"- URL: {result.source_url}")
        lines.append(f"- Status: {result.status}")

        if result.status == "success" and result.data:
            payload = _extract_payload(result.data)

            company_names = payload.get("company_names") or []
            if isinstance(company_names, list):
                company_names_text = ", ".join(str(item) for item in company_names)
            else:
                company_names_text = str(company_names)

            lines.append(f"- Title: {payload.get('title')}")
            lines.append(f"- Published date: {payload.get('published_date')}")
            lines.append(f"- Company names: {company_names_text}")
            lines.append(f"- Product or update: {payload.get('product_or_update')}")
            lines.append(f"- One-sentence summary: {payload.get('one_sentence_summary')}")
            lines.append(f"- Topic bucket: {payload.get('topic_bucket')}")
        else:
            lines.append(f"- Error: {result.error}")

        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
