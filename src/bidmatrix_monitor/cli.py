from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .delivery import maybe_deliver_report
from .intelligence import build_report
from .render import write_report
from .weekly import write_weekly_digest


def main() -> None:
    parser = argparse.ArgumentParser(description="Run BidMatrix news monitoring with Exa.")
    parser.add_argument("--config", default="config/monitoring.json", help="Path to monitoring config.")
    parser.add_argument("--dry-run", action="store_true", help="Validate config without calling Exa.")
    parser.add_argument("--weekly", action="store_true", help="Build a weekly digest from recent curated reports.")
    parser.add_argument("--days", type=int, default=7, help="Number of days to include for --weekly.")
    parser.add_argument("--diagnostics", action="store_true", help="Print curation diagnostics after a daily run.")
    parser.add_argument("--debug-exa", action="store_true", help="Print detailed Exa query timing logs.")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.dry_run:
        print(f"Loaded {len(config.topics)} topics for {config.brand_name}.")
        return

    if args.weekly:
        markdown_path, json_path = write_weekly_digest(Path(config.outputs.report_dir), days=args.days)
        print(f"Wrote {markdown_path}")
        print(f"Wrote {json_path}")
        maybe_deliver_report(config, markdown_path, "weekly")
        return

    from .exa_client import ExaMonitorClient

    client = ExaMonitorClient(config, debug_exa=args.debug_exa)
    items = []
    exa_errors: list[str] = []
    for topic in config.topics:
        print(f"Searching: {topic.label}")
        try:
            items.extend(client.search_topic(topic))
        except Exception as exc:
            message = f"{topic.label}: {exc}"
            exa_errors.append(message)
            print(f"Exa error for {topic.label}: {exc}")
        exa_errors.extend(client.pop_errors())

    if client.should_run_market_watch_recent():
        print("Searching: Market Watch fallback")
        try:
            items.extend(client.search_market_watch_recent())
        except Exception as exc:
            message = f"market_watch_recent: {exc}"
            exa_errors.append(message)
            print(f"Exa error for market_watch_recent: {exc}")
        exa_errors.extend(client.pop_errors())

    report = build_report(items, config, exa_errors=exa_errors)
    report.diagnostics.update(client.collection_stats())
    markdown_path, json_path, curated_json_path = write_report(report, Path(config.outputs.report_dir))
    print(f"Wrote {markdown_path}")
    print(f"Wrote {json_path}")
    print(f"Wrote {curated_json_path}")
    client.print_collection_summary()
    _print_pipeline_state(report.diagnostics)
    if args.diagnostics:
        _print_diagnostics(report.diagnostics)
    maybe_deliver_report(config, markdown_path, "daily")


def _print_diagnostics(diagnostics: dict) -> None:
    print("Diagnostics:")
    print(f"  sensitivity: {diagnostics.get('sensitivity')}")
    print(f"  raw items found: {diagnostics.get('raw_items_found')}")
    print(f"  raw daily_fresh_signals: {diagnostics.get('raw_daily_fresh_signals')}")
    print(f"  raw strategic_background: {diagnostics.get('raw_strategic_background')}")
    print(f"  filtered out by freshness: {diagnostics.get('filtered_out_by_freshness')}")
    print(f"  filtered out by source quality: {diagnostics.get('filtered_out_by_source_quality')}")
    print(f"  filtered out by score: {diagnostics.get('filtered_out_by_score')}")
    print(f"  kept new_last_24h: {diagnostics.get('kept_new_last_24h')}")
    print(f"  kept new_last_7d: {diagnostics.get('kept_new_last_7d')}")
    print(f"  kept background_context: {diagnostics.get('kept_background_context')}")
    print(f"  page_type counts: {diagnostics.get('page_type_counts')}")
    print(f"  source_type counts: {diagnostics.get('source_type_counts')}")


def _print_pipeline_state(diagnostics: dict) -> None:
    print("Daily pipeline state:")
    print(f"  raw_results_count: {diagnostics.get('raw_items_found', 0)}")
    print(f"  parsed_signals_count: {diagnostics.get('parsed_signals_count', 0)}")
    print(f"  core_count: {diagnostics.get('core_count', 0)}")
    print(f"  adjacent_count: {diagnostics.get('adjacent_count', 0)}")
    print(f"  background_count: {diagnostics.get('background_count', 0)}")
    print(f"  ignored_count: {diagnostics.get('ignored_count', 0)}")
    print(f"  fallback_level_used: {diagnostics.get('fallback_level_used', 'unknown')}")
    print(f"  selected_top_signals_count: {diagnostics.get('selected_top_signals_count', 0)}")
    print(f"  telegram_message_state: {diagnostics.get('telegram_message_state', 'unknown')}")
    print(f"  curated_signals_kept: {diagnostics.get('curated_items_kept', 0)}")
    print(f"  exa_errors: {diagnostics.get('exa_errors') or []}")


if __name__ == "__main__":
    main()
