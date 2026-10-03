# Test run report — 2026-10-03 (updated after correctness pass)

Recorded honestly: **test outcomes and the process exit code are reported separately, and this
run is NOT marked fully successful** because the pytest process intermittently crashes at
interpreter shutdown.

## Test outcomes (all green)

| Scope | Result |
|---|---|
| Full suite (`pytest -q`) | **0 FAILED, 0 ERROR** on every run (progress reaches `[100%]`; ~1085 tests) |
| Research pipeline only (`pytest tests/test_ftmo_research.py`) | **28 passed**, process exit code **0** (deterministic, every run) |

The 28 research-tool tests cover: MT5 HTML parsing (UTF-16 / Turkish labels / paired in-out
deals), **net incl. commission + swap reconciled against the report summary**, unparseable
deals rejected (not published as zero), DST-aware offset validation (**reject 999**, scan all
transitions), data-quality checks, **per-cell grouping that keeps different validation periods
separate**, numeric normalisation, ledger dedup + columns, the read-only collector analyser
(**schema-version guard**, zero-open vs no-snapshot), and batch generation (v3.14 EA default,
candidate label, pending future windows, ledger-based examination status).

## Process exit code (intermittent crash — NOT clean)

The **full-suite process exit code is unstable**:

| Metric | Value |
|---|---|
| Full-suite exit code | **139 (SIGSEGV)** on 4 of 6 runs; **0** on 2 of 6 |
| Research-only exit code | **0** on every run |
| Failing/erroring tests | **none** — the crash is after `[100%]`, during teardown |

### Diagnosis

The crash is a **segmentation fault in `markupsafe._speedups`** (a C extension pulled in via
Jinja2/Flask, used by the dashboard) firing during Python interpreter shutdown. Evidence:

- It occurs *after* every test has run and the progress bar has reached `[100%]`; no test is
  implicated and there are 0 failures/errors.
- It reproduces with the new research test file **excluded**, so it predates and is unrelated
  to this change.
- The research test module does not import Flask/markupsafe and exits 0 deterministically.
- On crashing runs the fault message names `Extension modules: markupsafe._speedups`.

### Consequence for "definition of done"

- The functional DoD is met: 0 failures, 0 errors; offline `python main.py demo` completes
  (exit 0); parity/decision tests pass.
- The **operational DoD is flagged**: a CI gate keyed on the pytest *process exit code* will go
  red ~2 out of 3 runs because of this teardown segfault, not because of any test. This is a
  separate, pre-existing environment/dependency defect to fix (e.g. pin/patch markupsafe or
  disable its C speedups in the test environment) and is **not** resolved by this change.

**This run is therefore recorded as: tests green, process exit code unstable (teardown
segfault), overall NOT fully successful.**
