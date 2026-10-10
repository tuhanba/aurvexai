"""Tick-cursor reference model — mirrors AurvexCollector.mq5 PollTicks() cursor logic.

The collector must keep the scan's START cursor (last_msc, count-at-last-msc) CONSTANT
while deciding what to write, and compute the NEW cursor separately, so that every tick
sharing the last millisecond is preserved and nothing is written twice on resume. This
Python mirror lets that logic be regression-tested without a terminal.
"""
from __future__ import annotations

from typing import Dict, List, Tuple


def collect_new_ticks(start_msc: int, start_cnt: int, tick_mscs: List[int]
                      ) -> Tuple[List[Tuple[int, int]], int, int]:
    """Given the resume cursor (start_msc, start_cnt) and the ascending tick millisecond
    stamps from CopyTicksRange, return (written, new_msc, new_cnt):
      * written      — list of (tick_msc, seq) to write this scan; seq is the 0-based
                       index of the tick within its millisecond, so (symbol, msc, seq) is
                       a stable identity that dedupes crash-replayed re-writes while
                       keeping legitimately distinct same-ms (even same-price) ticks,
      * (new_msc, new_cnt) — the advanced cursor to persist AFTER a verified write.
    The start cursor is read-only during the scan (the bug being fixed was mutating it)."""
    written: List[Tuple[int, int]] = []
    skip = start_cnt                 # same-ms ticks at start_msc already written
    new_msc, new_cnt = start_msc, start_cnt
    for msc in tick_mscs:
        if msc < start_msc:
            continue
        if msc == start_msc and skip > 0:
            skip -= 1
            continue
        if msc > new_msc:            # new ms -> seq restarts at 0
            new_msc, new_cnt = msc, 0
        seq = new_cnt                # 0-based index within this ms
        new_cnt += 1
        written.append((msc, seq))
    return written, new_msc, new_cnt


def resume_coverage(start_msc: int, now_msc: int, broker_mscs: List[int], gap_warn_ms: int
                    ) -> Tuple[List[int], List[Dict[str, int]]]:
    """Mirror of the collector's resume back-read + gap reporting (AurvexCollector.mq5
    PollTicksWindow / OnInit resume_gap). After a restart the cursor sits at the last written
    tick; the collector re-reads forward in bounded windows, writing whatever the broker still
    holds. This returns:

      * recovered — the broker-held tick stamps at/after the cursor, in [start_msc, now_msc]
        (what the back-read fills in),
      * gaps      — the UNRECOVERABLE leading hole, if any, as a one-item list of
        {"start","end","dur_ms","kind":"unrecoverable"}: the span between the cursor and the
        broker's EARLIEST served tick (or the whole span to now if the broker serves nothing
        at/after the cursor). Those ticks are gone for good — e.g. after a machine reset — so the
        collector advances past the hole and reports it rather than inventing data.

    This mirrors the collector's write-path report (firstMsc - startMsc > GapWarnSec). Interior
    "empty window" gaps are a separate, window-level concern in the collector and are not derived
    from inter-tick spacing here (normal low tick cadence is NOT a gap)."""
    recovered = [m for m in broker_mscs if start_msc <= m <= now_msc]
    gaps: List[Dict[str, int]] = []
    if start_msc <= 0:
        return recovered, gaps                      # fresh start: no cursor, nothing to back-read
    if recovered:
        lead = recovered[0] - start_msc
        if lead > gap_warn_ms:
            gaps.append({"start": start_msc, "end": recovered[0], "dur_ms": lead,
                         "kind": "unrecoverable"})
    elif now_msc - start_msc > gap_warn_ms:
        # broker has nothing at/after the cursor — the whole span is an unfilled hole
        gaps.append({"start": start_msc, "end": now_msc, "dur_ms": now_msc - start_msc,
                     "kind": "unrecoverable"})
    return recovered, gaps


def empty_window_gaps(events: List, gap_warn_ms: int) -> List[int]:
    """Mirror of the collector's ACCUMULATED empty-window gap detection (PollTicksWindow).
    A single bounded window (e.g. 300s) can never exceed a 300s GapWarn on its own, so empty
    windows accumulate across consecutive polls; when the running empty span passes gap_warn_ms
    a gap of that accumulated size is reported and the accumulator resets. A window that WROTE
    ticks (None) ends the run and resets. Returns the list of reported accumulated gap durations."""
    gaps: List[int] = []
    accum = 0
    for e in events:
        if e is None:               # a window that wrote ticks -> empty run ends
            accum = 0
        else:                        # an empty window of span `e` ms
            accum += e
            if accum > gap_warn_ms:
                gaps.append(accum)
                accum = 0
    return gaps
