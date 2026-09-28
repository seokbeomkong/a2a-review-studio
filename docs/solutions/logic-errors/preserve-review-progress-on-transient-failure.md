---
title: Preserve review progress on transient failure
date: 2026-09-28
category: logic-errors
module: Review run recovery
problem_type: logic_error
component: service_object
symptoms:
  - "Deadline reported total failure despite three usable expert drafts"
  - "A transient reload error erased the saved run ID"
root_cause: logic_error
resolution_type: code_fix
severity: medium
tags: ["a2a", "partial-results", "recovery", "timeouts"]
---

# Preserve review progress on transient failure

## Problem

Error handling treated incomplete work as missing work. This hid the distinction between usable partial reviews and total failure, and prevented recovery after a temporary server error.

## Symptoms

- Three drafts existed when the revision deadline expired, but the run was marked failed.
- The initial reload request returned HTTP500 and the browser deleted its only saved run ID.

## What Didn't Work

Unconditional failure status and unconditional session cleanup both lost information. The original tests covered a deadline before any result and normal reload, but not these two intermediate states.

## Solution

In `review_studio/runs.py`, timeout and synthesis failure preserve a partial status when reviews exist:

```python
run.status = "partial" if run.reviews else "failed"
```

Do not start more work after the deadline. Keep any completed drafts even without a final synthesis.

In `review_studio/static/app.js`, the fetch helper carries HTTP status on errors. Reload recovery removes the saved ID only for a confirmed HTTP404. A timeout or HTTP500 keeps the ID and tells the user to retry after checking connectivity.

## Why This Works

The status now describes the result available to the user. A network failure does not prove a remote result is absent. Partial output and the identifier needed to retrieve it remain useful after an execution failure.

## Prevention

- Test deadlines both before and after the first successful draft.
- Assert partial results remain downloadable without inventing a summary.
- Test a reload where configuration succeeds but the saved-run request fails, then succeeds on another reload.
- Clear browser recovery state only when absence is confirmed, not for every exception.

Both regressions were observed failing before their fixes. The backend suite passed with 16 tests; the Chromium smoke script verified transient-error recovery.

## Related Issues

- [Protocol and execution states](../../architecture.md)
- [Verification record](../../verification.md)

No earlier solution document existed in this repository; no consolidation was needed.

