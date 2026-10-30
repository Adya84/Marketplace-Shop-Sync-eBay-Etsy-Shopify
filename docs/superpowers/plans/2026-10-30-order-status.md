# Order Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show trustworthy save, scan and next-scan feedback.

**Architecture:** Persist a separate latest-run summary in OrderStore settings. Extend status polling and use a dedicated results fragment so settings and the browser are preserved.

**Tech Stack:** Existing Python FastAPI, SQLite, vanilla JavaScript.

**Spec:** ../specs/2026-10-30-order-status-design.md

## Global Constraints

- Preserve duplicate protection and current completion-based scheduling.
- Preview counts must distinguish ready orders from imported orders.
- Use Europe/London for displayed timestamps.
- Clear results must not delete order records.

## Review Focus

- Failed or interrupted runs must not retain an apparent successful result.
- Between-scan browser refresh must not overwrite completion feedback.
- Unsaved settings must survive result updates.
- Countdown must stop when automatic import is disabled.
- Clearing results must retain exact source-order deduplication.

### Task 1: Durable scan feedback and schedule

**Files:** Modify marketplace_bridge/app/order_web.py; test marketplace_bridge/app/tests/test_order_web.py.

**Interfaces:** Status returns latest run summary and next scan delay; existing settings and import endpoints remain compatible.

- [ ] Add failing tests for successful preview, import outcomes, failed scans, disabled countdown and completion-based next scan.
- [ ] Run focused tests and observe failures.
- [ ] Record start/completion/outcomes separately from last_message; expose delay calculated from last_completed and monotonic clock.
- [ ] Run focused tests.

### Task 2: Save feedback and current results

**Files:** Modify marketplace_bridge/app/order_web.py; test marketplace_bridge/app/tests/test_order_web.py.

**Interfaces:** A protected clear-display action preserves all order records; results refresh independently of the editable form.

- [ ] Add tests for clear-display retaining records, save timestamps and result rendering.
- [ ] Implement persistent saving/saved/error states and unsaved-edit indicator; use safe DOM text for messages.
- [ ] Render completion summaries and countdown; refresh result fragment on run completion without reloading browser or form.
- [ ] Run full Python suite and applicable frontend checks, review diff, and release using the next available version only after verification.
