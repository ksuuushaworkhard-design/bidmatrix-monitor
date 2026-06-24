from __future__ import annotations

import argparse
from pathlib import Path

from .audit import write_daily_audit_report
from .competitor_radar import build_competitor_radar_preview
from .config import load_config
from .delivery import DeliveryError, maybe_deliver_report
from .intelligence import build_report
from .linkedin_watch import build_linkedin_watch_preview
from .market_brief_v2 import build_market_brief_v2_preview
from .marketing_insights_radar import build_marketing_insights_radar_preview
from .render import write_report
from .weekly import build_weekly_digest, write_weekly_digest


def main() -> None:
    parser = argparse.ArgumentParser(description="Run BidMatrix news monitoring with Exa.")
    parser.add_argument("--config", default="config/monitoring.json", help="Path to monitoring config.")
    parser.add_argument("--dry-run", action="store_true", help="Validate config without calling Exa.")
    parser.add_argument("--weekly", action="store_true", help="Build a weekly digest from recent curated reports.")
    parser.add_argument("--days", type=int, default=7, help="Number of days to include for --weekly.")
    parser.add_argument("--diagnostics", action="store_true", help="Print curation diagnostics after a daily run.")
    parser.add_argument("--debug-exa", action="store_true", help="Print detailed Exa query timing logs.")
    parser.add_argument(
        "--competitor-radar-preview",
        action="store_true",
        help="Build a preview-only Competitor Marketing Radar report from a capped source list.",
    )
    parser.add_argument(
        "--competitor-radar-config",
        default="config/competitor_radar_sources.json",
        help="Path to competitor radar sources config.",
    )
    parser.add_argument(
        "--competitor-radar-max-companies",
        type=int,
        default=None,
        help="Optional max companies to check for the competitor radar preview.",
    )
    parser.add_argument(
        "--marketing-insights-radar-preview",
        action="store_true",
        help="Build a preview-only Marketing Insights Radar report from the company source list.",
    )
    parser.add_argument(
        "--marketing-insights-radar-config",
        default="config/marketing_insights_radar_sources.json",
        help="Path to Marketing Insights Radar sources config.",
    )
    parser.add_argument(
        "--marketing-insights-radar-max-companies",
        type=int,
        default=None,
        help="Optional max companies to check for the Marketing Insights Radar preview.",
    )
    parser.add_argument(
        "--linkedin-watch-preview",
        help="Build a local LinkedIn Watch markdown preview from a manual input JSON file.",
    )
    parser.add_argument(
        "--market-brief-v2-preview",
        action="store_true",
        help="Build a preview-only Market Brief v2 report without Telegram delivery.",
    )
    parser.add_argument(
        "--market-brief-v2-max-queries",
        type=int,
        default=20,
        help="Maximum Exa queries for the Market Brief v2 preview, capped internally at 20.",
    )
    args = parser.parse_args()

    if args.market_brief_v2_preview:
        markdown_path, json_path, audit_path, payload = build_market_brief_v2_preview(
            max_queries=args.market_brief_v2_max_queries
        )
        print(f"Wrote {markdown_path}")
        print(f"Wrote {json_path}")
        print(f"Wrote {audit_path}")
        print(
            "MARKET_BRIEF_V2_PREVIEW "
            f"exa_total_queries={payload['exa_total_queries']} "
            f"exa_errors_count={payload['exa_errors_count']} "
            f"exa_timeouts_count={payload['exa_timeouts_count']} "
            f"raw_results_count={payload['raw_results_count']} "
            f"kept_signals_count={payload['kept_signals_count']} "
            f"watchlist_signals_count={payload['watchlist_signals_count']}"
        )
        return

    if args.competitor_radar_preview:
        markdown_path, json_path, payload = build_competitor_radar_preview(
            args.competitor_radar_config,
            max_companies=args.competitor_radar_max_companies,
        )
        print(f"Wrote {markdown_path}")
        print(f"Wrote {json_path}")
        print(
            "COMPETITOR_RADAR_PREVIEW "
            f"companies_checked={payload['companies_checked']} "
            f"companies_with_useful_signals={payload['companies_with_useful_signals']} "
            f"exa_total_queries={payload['exa_total_queries']} "
            f"exa_errors_count={payload['exa_errors_count']}"
        )
        return

    if args.marketing_insights_radar_preview:
        markdown_path, json_path, payload = build_marketing_insights_radar_preview(
            args.marketing_insights_radar_config,
            max_companies=args.marketing_insights_radar_max_companies,
        )
        print(f"Wrote {markdown_path}")
        print(f"Wrote {json_path}")
        print(
            "MARKETING_INSIGHTS_RADAR_PREVIEW "
            f"companies_checked={payload['companies_checked']} "
            f"kept_signals={payload['companies_with_useful_signals']} "
            f"watchlist_signals={payload['watchlist_signals_count']} "
            f"exa_total_queries={payload['exa_total_queries']} "
            f"exa_errors_count={payload['exa_errors_count']} "
            f"exa_timeouts_count={payload['exa_timeouts_count']}"
        )
        return

    if args.linkedin_watch_preview:
        output_path = build_linkedin_watch_preview(args.linkedin_watch_preview)
        print(f"Wrote {output_path}")
        return

    config = load_config(args.config)
    if args.dry_run:
        print(f"Loaded {len(config.topics)} topics for {config.brand_name}.")
        return

    if args.weekly:
        print("RUN_START mode=weekly")
        report_dir = Path(config.outputs.report_dir)
        weekly_digest = build_weekly_digest(report_dir, days=args.days)
        if int(weekly_digest.get("diagnostics", {}).get("weekly_selected_items_count", 0)) == 0:
            report, _client = _build_daily_report(config, debug_exa=args.debug_exa)
            write_report(report, report_dir)
        markdown_path, json_path = write_weekly_digest(report_dir, days=args.days)
        print(f"Wrote {markdown_path}")
        print(f"Wrote {json_path}")
        print(
            f"REPORTS_WRITTEN mode=weekly markdown={markdown_path} json={json_path}"
        )
        try:
            maybe_deliver_report(config, markdown_path, "weekly")
        except DeliveryError:
            print("RUN_FINISHED mode=weekly status=delivery_failed")
            raise SystemExit(2)
        print("RUN_FINISHED mode=weekly status=success")
        return

    print("RUN_START mode=daily")
    report, client = _build_daily_report(config, debug_exa=args.debug_exa)
    report_dir = Path(config.outputs.report_dir)
    markdown_path, json_path, curated_json_path = write_report(report, report_dir)
    audit_json_path = write_daily_audit_report(report, report_dir)
    print(f"Wrote {markdown_path}")
    print(f"Wrote {json_path}")
    print(f"Wrote {curated_json_path}")
    print(f"Wrote {audit_json_path}")
    print(
        "REPORTS_WRITTEN mode=daily "
        f"markdown={markdown_path} json={json_path} curated={curated_json_path} audit={audit_json_path}"
    )
    client.print_collection_summary()
    _print_pipeline_state(report.diagnostics)
    if args.diagnostics:
        _print_diagnostics(report.diagnostics)
    try:
        maybe_deliver_report(config, markdown_path, "daily")
    except DeliveryError:
        print("RUN_FINISHED mode=daily status=delivery_failed")
        raise SystemExit(2)
    print("RUN_FINISHED mode=daily status=success")


def _build_daily_report(config, debug_exa: bool = False):
    from .exa_client import ExaMonitorClient

    client = ExaMonitorClient(config, debug_exa=debug_exa)
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

    report = build_report(items, config, exa_errors=exa_errors, exa_meta=client.collection_stats())

    if report.diagnostics.get("selected_top_signals_count", 0) == 0 and not report.adjacent_watchlist and client.should_run_market_watch_recent():
        print("Searching: Market Watch fallback")
        try:
            items.extend(client.search_market_watch_recent())
        except Exception as exc:
            message = f"market_watch_recent: {exc}"
            exa_errors.append(message)
            print(f"Exa error for market_watch_recent: {exc}")
        exa_errors.extend(client.pop_errors())
        report = build_report(items, config, exa_errors=exa_errors, exa_meta=client.collection_stats())
    elif report.diagnostics.get("selected_top_signals_count", 0) == 0 and not report.adjacent_watchlist and client.collection_stats().get("exa_budget_exceeded"):
        report = build_report(items, config, exa_errors=exa_errors, exa_meta=client.collection_stats())

    report.diagnostics.update(client.collection_stats())
    return report, client


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
    print(f"  market_watch_candidates_count: {diagnostics.get('market_watch_candidates_count', 0)}")
    print(f"  selected_top_signals_count: {diagnostics.get('selected_top_signals_count', 0)}")
    print(f"  selected_digest_items_count: {diagnostics.get('selected_digest_items_count', 0)}")
    print(f"  telegram_message_state: {diagnostics.get('telegram_message_state', 'unknown')}")
    print(f"  curated_signals_kept: {diagnostics.get('curated_items_kept', 0)}")
    print(f"  exa_errors: {diagnostics.get('exa_errors') or []}")


if __name__ == "__main__":
    main()
