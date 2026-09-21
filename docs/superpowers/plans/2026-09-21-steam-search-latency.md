# Steam Search Latency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Bound synchronous Steam request latency while preserving item/effect identity and existing degraded-data behavior.

**Architecture:** Configure the Steam API and Steam market-page clients with a shorter interactive timeout and one retry after transient transport, 429, or 5xx failures. Keep the existing limiter and cooldown semantics, and emit sanitized per-attempt diagnostics through the existing module logger.

**Tech Stack:** Python 3.12+, httpx, FastAPI, pytest.

## Global Constraints

- No network access from imports or tests.
- Preserve item+effect identity; never substitute another effect's price/listing.
- Keep SQLAlchemy transactions closed during external I/O.
- Preserve UTC-naive persistence and visible data age.

### Task 1: Bound Steam API client latency

**Files:** `tf2price/sources/steam.py`, `tests/sources/test_steam.py`

- [ ] Add failing tests proving the default HTTP timeout is interactive-safe and persistent transient failures stop after two attempts.
- [ ] Run the focused tests and observe failure against the current 30-second/six-attempt policy.
- [ ] Add named constants and constructor options for timeout and retry count, defaulting to 10 seconds and one retry; retain injectable client behavior.
- [ ] Log only endpoint category, attempt, status/error class, and duration.
- [ ] Run all Steam source tests.

### Task 2: Apply the same bound to Steam market pages

**Files:** `tf2price/sources/steam_page.py`, `tests/sources/test_steam_page.py`

- [ ] Add failing tests for persistent 429/transport failures stopping after two attempts.
- [ ] Apply the same timeout/retry constants and sanitized diagnostics without changing parsing or cache semantics.
- [ ] Run focused page-source tests.

### Task 3: Regression verification

**Files:** no new production files

- [ ] Run the complete pytest suite.
- [ ] Run `git diff --check` and inspect the final diff for secrets or generated artifacts.

