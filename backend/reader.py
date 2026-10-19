"""Read saved bot data only. No broker imports, orders, or database writes."""
import datetime as dt
import json
import math
from pathlib import Path
import sqlite3
import statistics
import time
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
NAMES = ("OCT15_ATR_BASELINE", "OCT15_PCT_2.5_1", "OCT15_PCT_3_1", "OCT15_PCT_3_1.5")
LABELS = ("기존 ATR", "2.5% / 1%", "3% / 1%", "3% / 1.5%")


def number(value, positive=False):
    try:
        result = float(value)
        return result if math.isfinite(result) and (not positive or result > 0) else None
    except (TypeError, ValueError):
        return None


def timestamp(value):
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)).isoformat()
    except ValueError:
        return None


def code(value):
    return str(value).removeprefix("A").zfill(6)


def capital_summary(equity, capital=None):
    capital = capital or {}
    initial = number(capital.get("initial_capital"), True)
    flows = number(capital.get("net_external_flows"))
    configured = initial is not None and flows is not None
    contributed = number(initial + flows) if configured else None
    configured = configured and contributed is not None
    assets = number(equity)
    pnl = number(assets - contributed) if configured and assets is not None else None
    return dict(configured=configured, initial_capital=initial, net_external_flows=flows,
                net_contributions=contributed, pnl=pnl,
                return_pct=number(pnl/contributed*100) if pnl is not None and contributed > 0 else None,
                basis="SIMPLE_NET_CONTRIBUTIONS")


def session(now, closed_date):
    minute = now.hour * 60 + now.minute
    if now.weekday() > 4 or closed_date == now.date().isoformat():
        return "휴장 / 마지막 관측"
    if 540 <= minute < 930:
        return "정규장"
    if 480 <= minute < 485:
        return "NXT 가격 추적"
    if 485 <= minute < 490:
        return "NXT 제한 매도 감시"
    if 490 <= minute < 530 or 940 <= minute < 1200:
        return "NXT 시간대"
    return "장외 / 마지막 관측"


class Reader:
    def __init__(self, root):
        self.root = Path(root)
        self.cached = None
        self.cached_at = 0
        self.enrollments = {}
        self.enrollment_cursor = 0

    def historical(self, conn):
        if self.cached is not None and time.monotonic() - self.cached_at < 60:
            return self.cached
        runtime = conn.execute("SELECT ts,payload_json FROM events WHERE event_type='RUNTIME_START' ORDER BY id DESC LIMIT 1").fetchone()
        trades = []
        for row in conn.execute("SELECT event_id,payload_json FROM sheet_trade_outbox ORDER BY created_at DESC,event_id DESC LIMIT 200"):
            p = json.loads(row["payload_json"])
            if len(p) < 14 or p[2] not in ("BUY", "SELL"):
                continue
            sell = p[2] == "SELL"
            trades.append(dict(id=row["event_id"], ts=timestamp(p[0]) or str(p[0]),
                               code=code(p[3]), name=str(p[4])[:80], side=p[2], reason=str(p[9])[:80],
                               qty=number(p[6]) or 0, price=number(p[5], True),
                               pnl=number(p[8]) if sell else None,
                               return_pct=number(p[7]) if sell else None,
                               basis="REFERENCE_ESTIMATE" if sell and "MANUAL" not in str(p[9]) else "RECORDED_UNCONFIRMED",
                               manual="MANUAL" in str(p[9])))
        latest_id = conn.execute("SELECT coalesce(max(id),0) FROM events").fetchone()[0]
        for row in conn.execute("SELECT trade_id,strategy_name,payload_json FROM events WHERE id>? AND id<=? AND event_type='COMPARISON_ENROLL' ORDER BY id", (self.enrollment_cursor, latest_id)):
            self.enrollments[(row["trade_id"], row["strategy_name"])] = json.loads(row["payload_json"]).get("cohort")
        self.enrollment_cursor = latest_id
        groups = {cohort: {name: {} for name in NAMES} for cohort in ("NEW_ENTRY", "EXISTING_FORWARD")}
        for row in conn.execute("SELECT trade_id,strategy_name,stage,active,return_pct FROM strategy_results WHERE strategy_name IN (?,?,?,?)", NAMES):
            cohort = self.enrollments.get((row["trade_id"], row["strategy_name"]))
            if cohort in groups:
                groups[cohort][row["strategy_name"]][row["trade_id"]] = dict(row)
        comparisons = []
        for cohort, strategies in groups.items():
            completed = {name: {tid for tid, row in rows.items() if row["active"] == 0 and row["stage"] == "EXITED" and number(row["return_pct"]) is not None} for name, rows in strategies.items()}
            common = set.intersection(*(completed[name] for name in NAMES))
            metrics = []
            for name, label in zip(NAMES, LABELS):
                values = [strategies[name][tid]["return_pct"] for tid in sorted(common)]
                deltas = [strategies[name][tid]["return_pct"] - strategies[NAMES[0]][tid]["return_pct"] for tid in sorted(common)]
                metrics.append(dict(name=name, label=label, enrolled=len(strategies[name]), completed=len(completed[name]),
                                    active=sum(bool(r["active"]) for r in strategies[name].values()),
                                    mean_pct=statistics.mean(values) if values else None,
                                    median_pct=statistics.median(values) if values else None,
                                    delta_pp=statistics.mean(deltas) if deltas else None))
            comparisons.append(dict(cohort=cohort, common_completed=len(common), strategies=metrics))
        self.cached = dict(trades=trades, trade_count=conn.execute("SELECT count(*) FROM sheet_trade_outbox").fetchone()[0],
                           comparisons=comparisons, runtime_at=timestamp(runtime["ts"]) if runtime else None,
                           runtime=json.loads(runtime["payload_json"]) if runtime else {})
        self.cached_at = time.monotonic()
        return self.cached

    def snapshot(self, active, capital=None):
        state_path = self.root / "trail_state.json"
        if state_path.stat().st_size > 40_000_000:
            raise ValueError("State exceeds expected size")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        conn = sqlite3.connect((self.root / "data/trading_analytics.db").resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            account = conn.execute("SELECT ts,equity,deposit,positions_json FROM account_samples ORDER BY ts DESC LIMIT 1").fetchone()
            if account is None:
                raise ValueError("No saved account sample")
            health = conn.execute("SELECT ts,payload_json FROM events WHERE event_type='MONITOR_HEALTH' ORDER BY id DESC LIMIT 1").fetchone()
            historical = self.historical(conn)
        finally:
            conn.close()
        now = dt.datetime.now(KST)
        minute = now.hour * 60 + now.minute
        expected = "KRX" if 540 <= minute < 930 else "NXT"
        positions = []
        for p in json.loads(account["positions_json"]):
            qty = int(number(p.get("qty")) or 0)
            entry = number(p.get("average_cost"), True)
            if qty <= 0:
                continue
            if entry is None:
                raise ValueError("Account holding has no valid average cost")
            symbol = code(p.get("code", ""))
            if len(symbol) != 6 or not symbol.isdigit():
                raise ValueError("Invalid holding code")
            saved = state.get("positions", {}).get(symbol, {})
            synced = number(saved.get("entry"), True) is not None and abs(float(saved["entry"]) - entry) <= max(.01, entry * .0001) and int(number(saved.get("qty")) or 0) == qty
            price_source = saved.get("price_source", "")
            quote = number(saved.get("last_current_price"), True) if price_source == expected and synced else None
            observed = timestamp(saved.get("last_update")) if quote is not None else timestamp(account["ts"])
            if quote is None:
                quote = number(p.get("account_price"), True)
                price_source = "KRX_ACCOUNT_FALLBACK"
            stage = str(saved.get("stage", "대기")) if synced else "동기화 확인"
            positions.append(dict(code=symbol, name=str(saved.get("name") or symbol)[:80], qty=qty, entry=entry,
                                  price=quote, price_source=str(price_source)[:40], observed_at=observed, stage=stage,
                                  start_price=number(saved.get("trail_start_price"), True) if synced else None,
                                  stop_price=number(saved.get("trail_stop_price"), True) if synced else None,
                                  hard_stop_price=entry * .9, peak_price=number(saved.get("max_price"), True) if synced else None,
                                  pnl=(quote-entry)*qty if quote is not None else None,
                                  return_pct=(quote/entry-1)*100 if quote is not None else None,
                                  opened_at=timestamp(saved.get("opened_at")) if synced else None, stale_state=not synced))
        hp = json.loads(health["payload_json"]) if health else {}
        runtime = historical["runtime"]
        trail = runtime.get("trailing", {})
        complete = all(p["pnl"] is not None for p in positions)
        pnl = sum(p["pnl"] for p in positions) if complete else None
        cost = sum(p["entry"]*p["qty"] for p in positions)
        valuation = sum(p["price"]*p["qty"] for p in positions) if complete else None
        return dict(schema_version=1, generated_at=now.isoformat(),
                    source=dict(control_id=state.get("dashboard_control", {}).get("request_id") or None,
                                account_at=timestamp(account["ts"]), state_at=dt.datetime.fromtimestamp(state_path.stat().st_mtime, KST).isoformat(),
                                health_at=timestamp(health["ts"]) if health else None, runtime_at=historical["runtime_at"],
                                service_active=active, paused=state.get("dashboard_control", {}).get("paused"), max_gap_sec=number(hp.get("max_cycle_gap_sec")), poll_count=number(hp.get("poll_count")),
                                target_sec=number(runtime.get("sell_poll_sec"), True) or 2,
                                start_rate=number(trail.get("start_rate")) or .03, gap_rate=number(trail.get("gap_rate")) or .01,
                                hard_stop_rate=.1, max_stocks=5, strategy=str(runtime.get("implementation_version", "saved state"))[:100],
                                session=session(now, state.get("market_closed_date"))),
                    capital=capital_summary(account["equity"], capital),
                    account=dict(equity=number(account["equity"]), deposit=number(account["deposit"]), pnl=pnl,
                                 purchase_amount=cost, valuation_amount=valuation,
                                 return_pct=pnl/cost*100 if pnl is not None and cost else None),
                    positions=positions, trades=historical["trades"], trade_count=historical["trade_count"], comparisons=historical["comparisons"])


