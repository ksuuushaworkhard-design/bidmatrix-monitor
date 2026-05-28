# ScrapeGraphAI Enrichment Spike

## Goal

Evaluate whether ScrapeGraphAI can improve extraction quality for BidMatrix Market Brief without changing the current production daily/weekly workflow.

This is a research spike only. It should not send Telegram messages, change schedules, or modify the existing Exa discovery, scoring, ranking, daily, or weekly delivery logic.

## Where it fits

Current flow:

```text
Exa discovery -> filtering/ranking -> Telegram daily/weekly digest
