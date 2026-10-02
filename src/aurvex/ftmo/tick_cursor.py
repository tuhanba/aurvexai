"""Tick-cursor reference model — mirrors AurvexCollector.mq5 PollTicks() cursor logic.

The collector must keep the scan's START cursor (last_msc, count-at-last-msc) CONSTANT
while deciding what to write, and compute the NEW cursor separately, so that every tick
sharing the last millisecond is preserved and nothing is written twice on resume. This
Python mirror lets that logic be regression-tested without a terminal.
"""
from __future__ import annotations

from typing import List, Tuple


def collect_new_ticks(start_msc: int, start_cnt: int, tick_mscs: List[int]
                      ) -> Tuple[List[int], int, int]:
    """Given the resume cursor (start_msc, start_cnt) and the ascending tick millisecond
    stamps from CopyTicksRange, return (written, new_msc, new_cnt):
      * written      — the tick_mscs that should be written this scan,
      * (new_msc, new_cnt) — the advanced cursor to persist AFTER a verified write.
    The start cursor is read-only during the scan (the bug being fixed was mutating it)."""
    written: List[int] = []
    skip = start_cnt                 # same-ms ticks at start_msc already written
    new_msc, new_cnt = start_msc, start_cnt
    for msc in tick_mscs:
        if msc < start_msc:
            continue
        if msc == start_msc and skip > 0:
            skip -= 1
            continue
        written.append(msc)
        if msc > new_msc:
            new_msc, new_cnt = msc, 1
        else:                        # msc == new_msc -> another tick in the same ms
            new_cnt += 1
    return written, new_msc, new_cnt
