"""
SQLite storage layer.

One small, explicit persistence module. WAL mode is enabled so the engine
process (writer) and the dashboard process (reader) can share the same file
safely. SQLite is intentionally chosen for the MVP: zero extra services, easy
backups, and more than fast enough for a single-account scalp engine. The
schema is written so a future Postgres migration is mechanical.

Tables:
  trades         - every paper/live trade (open + closed)
  signal_events  - every decision the engine made (ALLOW/REJECT/WATCH)
  funnel         - per-cycle observability counts
  shadows        - shadow-learner tracked outcomes (paper + rejected-high-score)
  shadow_ab      - champion/challenger A/B ledger (W3-T3, never applied)
  heartbeat      - component liveness (engine/scanner) + last status
  balance_ledger - balance changes over time
  meta           - small key/value store (current paper balance, etc.)
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

from .models import (CLOSED, OPEN, Trade, TPTarget, FunnelStats, Decision, new_id)


SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    mode TEXT, symbol TEXT, side TEXT, setup_type TEXT,
    score REAL, threshold REAL,
    entry REAL, stop_loss REAL,
    tp_targets TEXT, position_size REAL, risk_pct REAL, leverage INTEGER,
    max_loss REAL, status TEXT,
    open_time INTEGER, close_time INTEGER, close_price REAL, close_reason TEXT,
    remaining_fraction REAL, realized_pnl REAL, realized_pnl_pct REAL,
    fees_paid REAL, metadata TEXT, margin_used REAL DEFAULT 0,
    target_risk_amount REAL DEFAULT 0, actual_risk_amount REAL DEFAULT 0,
    risk_utilisation_pct REAL DEFAULT 0, clip_reason TEXT DEFAULT 'none'
);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_open_time ON trades(open_time);

CREATE TABLE IF NOT EXISTS signal_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER, symbol TEXT, side TEXT, setup_type TEXT,
    score REAL, threshold REAL, decision TEXT,
    failed_stage TEXT, reject_reason TEXT, metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_sig_ts ON signal_events(ts);

CREATE TABLE IF NOT EXISTS funnel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER, scanned INTEGER, candidates INTEGER, setups_detected INTEGER,
    score_pass INTEGER, risk_pass INTEGER, decision_allow INTEGER,
    executed INTEGER, rejected INTEGER, watch INTEGER,
    top_reject_reasons TEXT, last_trade_minutes_ago REAL, cycle_ms REAL
);
CREATE INDEX IF NOT EXISTS idx_funnel_ts ON funnel(ts);

CREATE TABLE IF NOT EXISTS shadows (
    id TEXT PRIMARY KEY,
    ts INTEGER, source TEXT, symbol TEXT, side TEXT, setup_type TEXT,
    score REAL, entry REAL, stop_loss REAL, tp1 REAL,
    outcome TEXT, outcome_time INTEGER, r_multiple REAL, bars INTEGER,
    signal_bar_ts INTEGER DEFAULT 0, last_bar_ts INTEGER DEFAULT 0,
    epoch TEXT DEFAULT 'legacy'
);
CREATE INDEX IF NOT EXISTS idx_shadow_outcome ON shadows(outcome);
-- idx_shadow_epoch is created in _migrate() after the epoch column is guaranteed
-- to exist on legacy DBs.
-- The dedup UNIQUE INDEX is created in Storage._migrate (after the columns are
-- guaranteed to exist on legacy DBs); INSERT OR IGNORE relies on it.

CREATE TABLE IF NOT EXISTS shadow_ab (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    resolved_ts INTEGER,
    epoch TEXT DEFAULT 'legacy',
    setup_type TEXT,
    source TEXT,
    score REAL,
    risk_multiplier_would_be REAL,
    score_delta_would_be REAL,
    actual_outcome TEXT,
    actual_net_r REAL
);
CREATE INDEX IF NOT EXISTS idx_shadow_ab_shadow_id ON shadow_ab(shadow_id);

CREATE TABLE IF NOT EXISTS heartbeat (
    component TEXT PRIMARY KEY,
    ts INTEGER, status TEXT
);

CREATE TABLE IF NOT EXISTS balance_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER, mode TEXT, balance REAL, change REAL, reason TEXT, trade_id TEXT
);

CREATE TABLE IF NOT EXISTS coin_profiles (
    symbol TEXT PRIMARY KEY,
    total_signals INTEGER DEFAULT 0,
    total_trades INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    total_r REAL DEFAULT 0.0,
    last_seen_ms INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def _trade_to_row(t: Trade) -> tuple:
    meta = t.metadata
    return (
        t.id, t.mode, t.symbol, t.side, t.setup_type, t.score, t.threshold,
        t.entry, t.stop_loss,
        json.dumps([[tp.price, tp.fraction, tp.hit] for tp in t.tp_targets]),
        t.position_size, t.risk_pct, t.leverage, t.max_loss, t.status,
        t.open_time, t.close_time, t.close_price, t.close_reason,
        t.remaining_fraction, t.realized_pnl, t.realized_pnl_pct,
        t.fees_paid, json.dumps(meta), t.margin_used,
        meta.get("target_risk_amount", 0.0),
        meta.get("actual_risk_amount", 0.0),
        meta.get("risk_utilisation_pct", 0.0),
        meta.get("clip_reason", "none"),
    )


def _row_to_trade(r: sqlite3.Row) -> Trade:
    targets = [TPTarget(price=p, fraction=f, hit=bool(h))
               for p, f, h in json.loads(r["tp_targets"])]
    keys = r.keys()
    margin_used = r["margin_used"] if "margin_used" in keys and r["margin_used"] is not None else 0.0
    metadata = json.loads(r["metadata"])
    # W3-T1: backfill instrumentation fields from dedicated columns into metadata
    # so callers can read them uniformly from trade.metadata.
    if "target_risk_amount" in keys and r["target_risk_amount"] is not None:
        metadata.setdefault("target_risk_amount", r["target_risk_amount"])
    if "actual_risk_amount" in keys and r["actual_risk_amount"] is not None:
        metadata.setdefault("actual_risk_amount", r["actual_risk_amount"])
    if "risk_utilisation_pct" in keys and r["risk_utilisation_pct"] is not None:
        metadata.setdefault("risk_utilisation_pct", r["risk_utilisation_pct"])
    if "clip_reason" in keys and r["clip_reason"] is not None:
        metadata.setdefault("clip_reason", r["clip_reason"])
    return Trade(
        id=r["id"], mode=r["mode"], symbol=r["symbol"], side=r["side"],
        setup_type=r["setup_type"], score=r["score"], threshold=r["threshold"],
        entry=r["entry"], stop_loss=r["stop_loss"], tp_targets=targets,
        position_size=r["position_size"], risk_pct=r["risk_pct"],
        leverage=r["leverage"], max_loss=r["max_loss"], status=r["status"],
        open_time=r["open_time"], close_time=r["close_time"],
        close_price=r["close_price"], close_reason=r["close_reason"],
        remaining_fraction=r["remaining_fraction"], realized_pnl=r["realized_pnl"],
        realized_pnl_pct=r["realized_pnl_pct"], fees_paid=r["fees_paid"],
        metadata=metadata, margin_used=margin_used,
    )


class Storage:
    def __init__(self, db_path: str):
        self.db_path = db_path
        d = os.path.dirname(db_path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Idempotent, additive schema migrations for pre-existing databases.

        CREATE TABLE IF NOT EXISTS does not add columns to a table that already
        exists, so a server DB created before a column was introduced must be
        patched here. Only ever ADDs columns (never drops/renames) so it is safe
        to run on every startup.
        """
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(trades)").fetchall()}
        if "margin_used" not in cols:
            self.conn.execute("ALTER TABLE trades ADD COLUMN margin_used REAL DEFAULT 0")
            # Backfill a sensible value for legacy rows: notional / leverage.
            self.conn.execute(
                "UPDATE trades SET margin_used = position_size / leverage "
                "WHERE (margin_used IS NULL OR margin_used = 0) AND leverage > 0")
            self.conn.commit()

        # W3-T1: sizing instrumentation columns.
        if "target_risk_amount" not in cols:
            self.conn.execute(
                "ALTER TABLE trades ADD COLUMN target_risk_amount REAL DEFAULT 0")
        if "actual_risk_amount" not in cols:
            self.conn.execute(
                "ALTER TABLE trades ADD COLUMN actual_risk_amount REAL DEFAULT 0")
        if "risk_utilisation_pct" not in cols:
            self.conn.execute(
                "ALTER TABLE trades ADD COLUMN risk_utilisation_pct REAL DEFAULT 0")
        if "clip_reason" not in cols:
            self.conn.execute(
                "ALTER TABLE trades ADD COLUMN clip_reason TEXT DEFAULT 'none'")
            # Backfill pre-T1 rows so they are distinguishable from post-T1 rows.
            self.conn.execute(
                "UPDATE trades SET clip_reason='legacy' WHERE clip_reason IS NULL OR clip_reason='none'")
        self.conn.commit()

        # IF-3: quality/capacity reject split columns in funnel table.
        funnel_cols = {r["name"] for r in
                       self.conn.execute("PRAGMA table_info(funnel)").fetchall()}
        if "quality_reject" not in funnel_cols:
            self.conn.execute(
                "ALTER TABLE funnel ADD COLUMN quality_reject INTEGER DEFAULT 0")
        if "capacity_reject" not in funnel_cols:
            self.conn.execute(
                "ALTER TABLE funnel ADD COLUMN capacity_reject INTEGER DEFAULT 0")
        # Buğra primary gate: candidates that qualified but lost the slot race.
        if "ranked_out" not in funnel_cols:
            self.conn.execute(
                "ALTER TABLE funnel ADD COLUMN ranked_out INTEGER DEFAULT 0")
        self.conn.commit()

        # Shadow dedup columns + unique index (Wave 1 / T3). Additive only.
        shadow_cols = {r["name"] for r in
                       self.conn.execute("PRAGMA table_info(shadows)").fetchall()}
        if "signal_bar_ts" not in shadow_cols:
            self.conn.execute("ALTER TABLE shadows ADD COLUMN signal_bar_ts INTEGER DEFAULT 0")
        if "last_bar_ts" not in shadow_cols:
            self.conn.execute("ALTER TABLE shadows ADD COLUMN last_bar_ts INTEGER DEFAULT 0")
        # W3-T2: epoch column. Backfill: rows at/after current epoch start → epoch
        # label; rows before → 'legacy'. New rows are tagged at insert.
        if "epoch" not in shadow_cols:
            self.conn.execute("ALTER TABLE shadows ADD COLUMN epoch TEXT DEFAULT 'legacy'")
            epoch_meta = self.get_meta("epoch")
            if epoch_meta and epoch_meta.get("started_ms") and epoch_meta.get("label"):
                label = epoch_meta["label"]
                started = int(epoch_meta["started_ms"])
                self.conn.execute(
                    "UPDATE shadows SET epoch=? WHERE ts >= ?", (label, started))
            # Index can only be created after the column exists.
            try:
                self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_shadow_epoch ON shadows(epoch)")
            except sqlite3.Error:
                pass
            self.conn.commit()
        # W3-T3: champion/challenger A/B table (always additive — create if not exists).
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS shadow_ab (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shadow_id TEXT NOT NULL,
                resolved_ts INTEGER,
                epoch TEXT DEFAULT 'legacy',
                setup_type TEXT,
                source TEXT,
                score REAL,
                risk_multiplier_would_be REAL,
                score_delta_would_be REAL,
                actual_outcome TEXT,
                actual_net_r REAL
            );
            CREATE INDEX IF NOT EXISTS idx_shadow_ab_shadow_id ON shadow_ab(shadow_id);
        """)
        # Observe-only reject-reason side table (additive; mirrors the shadow_ab
        # pattern). Keyed by shadow id so the dashboard can group resolved
        # rejected shadows by reason (no_free_margin / exposure_cap / min_notional)
        # without changing the shadows column layout.
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS shadow_reject_reason (
                shadow_id TEXT PRIMARY KEY,
                reason TEXT
            );
        """)
        # The unique index dedups new-epoch rows. Legacy rows have signal_bar_ts=0
        # but SQLite treats every NULL/0 group key independently only for NULLs;
        # to avoid a build failure on a contaminated legacy table we create the
        # index IF NOT EXISTS and tolerate failure (legacy duplicates predate it).
        try:
            self.conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_shadow_dedup "
                "ON shadows(symbol, side, setup_type, signal_bar_ts)")
        except sqlite3.Error:
            # Pre-existing duplicate (legacy epoch) rows block a unique index.
            # Leave them; a clean epoch (fresh DB) builds the index and dedups via
            # INSERT OR IGNORE. History is never deleted.
            pass
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    # -- meta / balance ----------------------------------------------------
    def set_meta(self, key: str, value: Any) -> None:
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)))
        self.conn.commit()

    def get_meta(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def ensure_balance(self, initial: float) -> float:
        bal = self.get_meta("balance")
        if bal is None:
            self.set_meta("balance", initial)
            self.append_ledger(mode="paper", balance=initial, change=0.0,
                               reason="init", trade_id=None)
            return initial
        return float(bal)

    def reset_for_new_epoch(self, initial_balance: float,
                            label: str = "wave2") -> Dict[str, Any]:
        """Reset trading data for a clean forward-test, preserving shadow rows.

        Keeps  : shadows (resolved learning history — most valuable data)
        Clears : trades, signal_events, funnel, balance_ledger, heartbeat, meta
        Seeds  : new balance + new epoch stamp.

        Engine must be stopped before calling; restart it after.
        """
        shadow_count = self.conn.execute(
            "SELECT COUNT(*) AS n FROM shadows").fetchone()["n"]
        for table in ("trades", "signal_events", "funnel",
                      "balance_ledger", "heartbeat", "meta"):
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.commit()

        self.set_meta("balance", initial_balance)
        self.append_ledger(mode="paper", balance=initial_balance, change=0.0,
                           reason="reset_init", trade_id=None)
        epoch = {"label": label, "started_ms": int(time.time() * 1000),
                 "id": new_id()}
        self.set_meta("epoch", epoch)

        return {
            "shadows_kept": shadow_count,
            "tables_cleared": ["trades", "signal_events", "funnel",
                                "balance_ledger", "heartbeat"],
            "new_balance": initial_balance,
            "new_epoch": epoch,
        }

    def reset_balance_only(self, initial_balance: float) -> Dict[str, Any]:
        """Reset only the paper balance. Keeps ALL trade, shadow, and funnel data.

        Use this when you want a clean balance without losing historical trade
        records. Engine should be stopped before calling; restart after.
        """
        old_balance = self.get_balance()
        self.set_meta("balance", initial_balance)
        self.append_ledger(mode="paper", balance=initial_balance,
                           change=initial_balance - old_balance,
                           reason="balance_reset_only", trade_id=None)
        trade_count = self.conn.execute(
            "SELECT COUNT(*) AS n FROM trades").fetchone()["n"]
        shadow_count = self.conn.execute(
            "SELECT COUNT(*) AS n FROM shadows").fetchone()["n"]
        return {
            "old_balance": old_balance,
            "new_balance": initial_balance,
            "trades_kept": trade_count,
            "shadows_kept": shadow_count,
        }

    def ensure_epoch(self, label: str = "wave1") -> Dict[str, Any]:
        """Stamp this DB with an epoch marker the first time it is opened.

        A clean paper run after the Wave 1 integrity fixes is a NEW epoch: Wave 2
        comparisons must be made against it, never the contaminated legacy
        history. The stamp is written once and never overwritten (history is
        never deleted)."""
        epoch = self.get_meta("epoch")
        if epoch is None:
            epoch = {"label": label, "started_ms": int(time.time() * 1000),
                     "id": new_id()}
            self.set_meta("epoch", epoch)
        return epoch

    def get_balance(self, default: float = 0.0) -> float:
        bal = self.get_meta("balance")
        return float(bal) if bal is not None else default

    def adjust_balance(self, change: float, mode: str, reason: str,
                       trade_id: Optional[str]) -> float:
        bal = self.get_balance() + change
        self.set_meta("balance", bal)
        self.append_ledger(mode=mode, balance=bal, change=change,
                           reason=reason, trade_id=trade_id)
        return bal

    def append_ledger(self, mode: str, balance: float, change: float,
                      reason: str, trade_id: Optional[str]) -> None:
        self.conn.execute(
            "INSERT INTO balance_ledger(ts,mode,balance,change,reason,trade_id) "
            "VALUES(?,?,?,?,?,?)",
            (int(time.time() * 1000), mode, balance, change, reason, trade_id))
        self.conn.commit()

    def get_ledger(self, limit: int = 200) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM balance_ledger ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # -- trades ------------------------------------------------------------
    def upsert_trade(self, t: Trade) -> None:
        cols = ("id,mode,symbol,side,setup_type,score,threshold,entry,stop_loss,"
                "tp_targets,position_size,risk_pct,leverage,max_loss,status,"
                "open_time,close_time,close_price,close_reason,remaining_fraction,"
                "realized_pnl,realized_pnl_pct,fees_paid,metadata,margin_used,"
                "target_risk_amount,actual_risk_amount,risk_utilisation_pct,clip_reason")
        placeholders = ",".join(["?"] * 29)
        update = ",".join(f"{c}=excluded.{c}" for c in cols.split(","))
        self.conn.execute(
            f"INSERT INTO trades({cols}) VALUES({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {update}",
            _trade_to_row(t))
        self.conn.commit()

    def get_open_trades(self, mode: Optional[str] = None) -> List[Trade]:
        if mode:
            rows = self.conn.execute(
                "SELECT * FROM trades WHERE status=? AND mode=? ORDER BY open_time",
                (OPEN, mode)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM trades WHERE status=? ORDER BY open_time", (OPEN,)).fetchall()
        return [_row_to_trade(r) for r in rows]

    def get_closed_trades(self, limit: int = 500, mode: Optional[str] = None) -> List[Trade]:
        if mode:
            rows = self.conn.execute(
                "SELECT * FROM trades WHERE status=? AND mode=? ORDER BY close_time DESC LIMIT ?",
                (CLOSED, mode, limit)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM trades WHERE status=? ORDER BY close_time DESC LIMIT ?",
                (CLOSED, limit)).fetchall()
        return [_row_to_trade(r) for r in rows]

    def get_all_trades(self, limit: int = 1000) -> List[Trade]:
        rows = self.conn.execute(
            "SELECT * FROM trades ORDER BY open_time DESC LIMIT ?", (limit,)).fetchall()
        return [_row_to_trade(r) for r in rows]

    def last_trade_times(self) -> Dict[str, int]:
        rows = self.conn.execute(
            "SELECT symbol, MAX(open_time) AS t FROM trades GROUP BY symbol").fetchall()
        return {r["symbol"]: r["t"] for r in rows if r["t"] is not None}

    def daily_realized_pnl(self, since_ms: int) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(realized_pnl),0) AS p FROM trades "
            "WHERE status=? AND close_time>=?", (CLOSED, since_ms)).fetchone()
        return float(row["p"] or 0.0)

    # -- signal events -----------------------------------------------------
    def insert_signal_event(self, d: Decision) -> None:
        self.conn.execute(
            "INSERT INTO signal_events(ts,symbol,side,setup_type,score,threshold,"
            "decision,failed_stage,reject_reason,metadata) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (d.ts, d.symbol, d.side, d.setup_type, d.score, d.threshold,
             d.decision, d.failed_stage, d.reject_reason, json.dumps(d.metadata, default=str)))
        self.conn.commit()

    def recent_signals(self, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM signal_events ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # -- funnel ------------------------------------------------------------
    def insert_funnel(self, f: FunnelStats) -> None:
        self.conn.execute(
            "INSERT INTO funnel(ts,scanned,candidates,setups_detected,score_pass,"
            "risk_pass,decision_allow,executed,rejected,watch,top_reject_reasons,"
            "last_trade_minutes_ago,cycle_ms,quality_reject,capacity_reject,ranked_out) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f.ts, f.scanned_count, f.candidate_count, f.setup_detected_count,
             f.score_pass_count, f.risk_pass_count, f.decision_allow_count,
             f.executed_count, f.rejected_count, f.watch_count,
             json.dumps(f.top_reject_reasons()), f.last_trade_minutes_ago, f.cycle_ms,
             f.quality_reject_count, f.capacity_reject_count, f.ranked_out_count))
        self.conn.commit()

    def latest_funnel(self) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM funnel ORDER BY ts DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def recent_funnels(self, limit: int = 30) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM funnel ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # -- shadows -----------------------------------------------------------
    def insert_shadow(self, row: Dict[str, Any]) -> bool:
        # INSERT OR IGNORE dedups on idx_shadow_dedup
        # (symbol, side, setup_type, signal_bar_ts): a second row for the same
        # signalled bar is silently dropped. Returns True iff a row was inserted.
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO shadows(id,ts,source,symbol,side,setup_type,score,"
            "entry,stop_loss,tp1,outcome,outcome_time,r_multiple,bars,"
            "signal_bar_ts,last_bar_ts,epoch) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["id"], row["ts"], row["source"], row["symbol"], row["side"],
             row["setup_type"], row["score"], row["entry"], row["stop_loss"],
             row["tp1"], row.get("outcome", OPEN), row.get("outcome_time"),
             row.get("r_multiple"), row.get("bars", 0),
             row.get("signal_bar_ts", 0), row.get("last_bar_ts", 0),
             row.get("epoch", "legacy")))
        inserted = cur.rowcount > 0
        # Observe-only: record the engine's reject reason in an ADDITIVE side
        # table (keyed by shadow id) so the dashboard can break missed-opportunity
        # counts down by reason. Kept out of the shadows table so its column
        # layout — relied on by positional inserts elsewhere — is unchanged.
        # Never affects sizing; it is metadata copied from an existing Decision.
        if inserted:
            reason = (row.get("reject_reason") or "").strip()
            if reason:
                self.conn.execute(
                    "INSERT OR REPLACE INTO shadow_reject_reason(shadow_id, reason) "
                    "VALUES(?,?)", (row["id"], reason))
        self.conn.commit()
        return inserted

    def insert_shadow_ab(self, row: Dict[str, Any]) -> None:
        """Log a champion/challenger A/B entry for a resolved shadow episode."""
        self.conn.execute(
            "INSERT INTO shadow_ab(shadow_id,resolved_ts,epoch,setup_type,source,"
            "score,risk_multiplier_would_be,score_delta_would_be,"
            "actual_outcome,actual_net_r) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (row["shadow_id"], row.get("resolved_ts"), row.get("epoch", "legacy"),
             row.get("setup_type"), row.get("source"), row.get("score"),
             row.get("risk_multiplier_would_be"), row.get("score_delta_would_be"),
             row.get("actual_outcome"), row.get("actual_net_r")))
        self.conn.commit()

    def update_shadow(self, shadow_id: str, outcome: str, outcome_time: int,
                      r_multiple: float, bars: int,
                      last_bar_ts: Optional[int] = None) -> None:
        if last_bar_ts is None:
            self.conn.execute(
                "UPDATE shadows SET outcome=?,outcome_time=?,r_multiple=?,bars=? WHERE id=?",
                (outcome, outcome_time, r_multiple, bars, shadow_id))
        else:
            self.conn.execute(
                "UPDATE shadows SET outcome=?,outcome_time=?,r_multiple=?,bars=?,"
                "last_bar_ts=? WHERE id=?",
                (outcome, outcome_time, r_multiple, bars, last_bar_ts, shadow_id))
        self.conn.commit()

    def open_shadows(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM shadows WHERE outcome=?", (OPEN,)).fetchall()
        return [dict(r) for r in rows]

    def shadow_stats(self) -> Dict[str, Any]:
        rows = self.conn.execute(
            "SELECT source, setup_type, outcome, COUNT(*) AS n, "
            "COALESCE(AVG(r_multiple),0) AS avg_r FROM shadows "
            "GROUP BY source, setup_type, outcome").fetchall()
        return {"breakdown": [dict(r) for r in rows]}

    # -- heartbeat ---------------------------------------------------------
    def set_heartbeat(self, component: str, status: Dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO heartbeat(component,ts,status) VALUES(?,?,?) "
            "ON CONFLICT(component) DO UPDATE SET ts=excluded.ts,status=excluded.status",
            (component, int(time.time() * 1000), json.dumps(status)))
        self.conn.commit()

    def get_heartbeat(self, component: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM heartbeat WHERE component=?", (component,)).fetchone()
        if not row:
            return None
        return {"component": row["component"], "ts": row["ts"],
                "status": json.loads(row["status"])}

    def all_heartbeats(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM heartbeat").fetchall()
        return [{"component": r["component"], "ts": r["ts"],
                 "status": json.loads(r["status"])} for r in rows]

    # -- coin profile library -----------------------------------------------

    def coin_signal_seen(self, symbol: str, ts_ms: int) -> None:
        self.conn.execute(
            "INSERT INTO coin_profiles(symbol, total_signals, last_seen_ms) VALUES(?,1,?) "
            "ON CONFLICT(symbol) DO UPDATE SET "
            "total_signals=total_signals+1, last_seen_ms=MAX(last_seen_ms,?)",
            (symbol, ts_ms, ts_ms))
        self.conn.commit()

    def coin_trade_closed(self, symbol: str, win: bool, r_multiple: float) -> None:
        self.conn.execute(
            "INSERT INTO coin_profiles(symbol, total_trades, wins, total_r) VALUES(?,1,?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET "
            "total_trades=total_trades+1, "
            "wins=wins+?, "
            "total_r=total_r+?",
            (symbol, int(win), r_multiple, int(win), r_multiple))
        self.conn.commit()

    def get_coin_profile(self, symbol: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM coin_profiles WHERE symbol=?", (symbol,)).fetchone()
        if not row:
            return None
        return {k: row[k] for k in row.keys()}

    def all_coin_profiles(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM coin_profiles ORDER BY total_trades DESC").fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]
