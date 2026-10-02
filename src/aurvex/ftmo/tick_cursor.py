"""Tick-cursor reference model — mirrors AurvexCollector.mq5 PollTicks() cursor logic.

The collector must keep the scan's START cursor (last_msc, count-at-last-msc) CONSTANT
while deciding what to write, and compute the NEW cursor separately, so that every tick
sharing the last millisecond is preserved and nothing is written twice on resume. This
Python mirror lets that logic be regression-tested without a terminal.
"""
from __future__ import annotations

from typing import List, Tuple


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
