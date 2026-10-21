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


def monitoring(now, saved, expected, active, paused, closed_date):
    minute = now.hour * 60 + now.minute
    after = 960 <= minute < 1200
    allowed = ("KRX", "NXT") if after else (expected,)
    eligible = saved.get("nxt_eligible")
    reason = "NOT_ELIGIBLE" if not after and expected == "NXT" and eligible is False else str(saved.get("quote_reason") or "NOT_VERIFIED")
    if after and reason == "NOT_ELIGIBLE":
        reason = "KRX_AFTER_NOT_VERIFIED"
    result = dict(monitor_reason=reason, nxt_eligible=eligible,
                  last_valid_quote_at=timestamp(saved.get("last_valid_quote_at")),
                  last_valid_trade_at=timestamp(saved.get("last_valid_trade_at")),
                  last_valid_bid_at=timestamp(saved.get("last_valid_bid_at")),
                  quote_basis=str(saved.get("last_valid_quote_basis") or saved.get("quote_basis") or "TRADE"),
                  quote_session=str(saved.get("last_valid_quote_session") or saved.get("quote_session") or ""),
                  order_guard_reason=str(saved.get("order_guard_reason") or ""),
                  quote_checked_at=timestamp(saved.get("quote_checked_at")))
    retry_at = timestamp(saved.get("sell_retry_after"))
    if (not result["order_guard_reason"] and retry_at and dt.datetime.fromisoformat(retry_at) > now
            and saved.get("last_sell_error", {}).get("market") == saved.get("price_source")):
        result["order_guard_reason"] = "ORDER_RETRY_WAIT"
    if not active or paused is not False:
        status = "PAUSED" if paused else "SERVICE_UNAVAILABLE"
    elif now.weekday() > 4 or closed_date == now.date().isoformat():
        status = "CLOSED"
    elif not (480 <= minute < 530 or 540 <= minute < 930 or 940 <= minute < 1200):
        status = "OFF"
    elif reason == "NOT_ELIGIBLE":
        status = "NOT_ELIGIBLE"
    else:
        at = result["last_valid_quote_at"]
        bid_only = result["quote_basis"] == "BID_ONLY"
        reference = result["last_valid_bid_at"] if bid_only else result["last_valid_trade_at"]
        fresh = bool(at and reference and 0 <= (now-dt.datetime.fromisoformat(at)).total_seconds() <= 120
                     and 0 <= (now-dt.datetime.fromisoformat(reference)).total_seconds() <= (30 if bid_only else 120))
        if saved.get("quote_status") != "VALID" or saved.get("price_source") not in allowed or not fresh:
            status = "UNAVAILABLE"
            if saved.get("quote_status") == "VALID" and not fresh:
                result["monitor_reason"] = "STALE_EXECUTION" if at else "NOT_VERIFIED"
        elif 920 <= minute < 930:
            status = "AUCTION_TRACK"
        elif 480 <= minute < 485:
            status = "TRACK_ONLY"
        elif 485 <= minute < 490:
            status = "EARLY_NXT"
        elif saved.get("bot_sell_pending") or result["order_guard_reason"] in ("UNFILLED_SELL", "UNFILLED_UNKNOWN", "UNFILLED_UNKNOWN_OR_PENDING"):
            status = "ORDER_PENDING"
        elif result["order_guard_reason"]:
            status = "ORDER_BLOCKED"
        elif bid_only:
            status = "UNAVAILABLE"
            result["monitor_reason"] = "WAITING_FOR_EXECUTION"
        else:
            status = "ACTIVE"
    return dict(result, monitor_status=status)


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
        return "KRX·NXT 애프터마켓" if minute >= 960 else "NXT 시간대"
    return "장외 / 마지막 관측"


class Reader:
    def __init__(self, root):
        self.root = Path(root)
        self.cached = None
        self.cached_at = 0
        self.enrollments = {}
        self.enrollment_cursor = 0

    def trade_history(self, conn):
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        records = []
        lifecycle = [json.loads(r[0]) for r in conn.execute(
            "SELECT payload_json FROM sell_order_lifecycle ORDER BY ordered_at DESC,order_key DESC LIMIT 200")
            ] if 'sell_order_lifecycle' in tables else []
        replaced = {(o['trade_id'], o['ordered_at']) for o in lifecycle}
        for row in conn.execute("SELECT event_id,payload_json FROM sheet_trade_outbox ORDER BY created_at DESC,event_id DESC LIMIT 200"):
            p = json.loads(row['payload_json'])
            if len(p) < 14 or p[2] not in ('BUY', 'SELL') or (p[2] == 'SELL' and (p[1], p[0]) in replaced):
                continue
            sell = p[2] == 'SELL'
            item = dict(id=row['event_id'], ts=timestamp(p[0]) or str(p[0]),
                        code=code(p[3]), name=str(p[4])[:80], side=p[2], reason=str(p[9])[:80],
                        qty=number(p[6]) or 0, price=number(p[5], True),
                        pnl=number(p[8]) if sell else None, return_pct=number(p[7]) if sell else None,
                        basis='REFERENCE_ESTIMATE' if sell and 'MANUAL' not in str(p[9]) else 'RECORDED_UNCONFIRMED',
                        manual='MANUAL' in str(p[9]))
            if sell and not item['manual'] and 'execution_observations' in tables:
                fills = conn.execute("SELECT sold_qty,fill_price,gross_pnl,account_entry FROM execution_observations "
                                     "WHERE trade_id=? AND ordered_at=? AND price_source='KIWOOM_FILL'", (p[1], p[0])).fetchall()
                if fills and item['qty'] > 0 and sum(r[0] for r in fills) == item['qty'] and all(number(r[1], True) is not None and number(r[2]) is not None and number(r[3], True) is not None for r in fills):
                    cost = sum(r[3]*r[0] for r in fills)
                    item.update(price=sum(r[0]*r[1] for r in fills)/item['qty'], pnl=sum(r[2] for r in fills),
                                basis='FILL_CONFIRMED', execution_status='FILLED')
                    item['return_pct'] = item['pnl']/cost*100 if cost > 0 else None
            records.append(item)
        for o in lifecycle:
            qty = int(number(o.get('filled_qty')) or 0)
            value = number(o.get('fill_value')) or 0
            entry = number(o.get('entry'), True)
            pnl = value-entry*qty if qty > 0 and entry is not None else None
            records.append(dict(id=o['order_key'], ts=timestamp(o['ordered_at']), code=code(o['code']),
                                name=str(o.get('name') or o['code'])[:80], side='SELL', reason=o['reason'],
                                qty=qty, requested_qty=o['qty'], filled_qty=qty, execution_status=o['status'],
                                price=value/qty if qty else None, limit_price=number(o.get('limit_price'), True),
                                reference_price=number(o.get('reference_price'), True), pnl=pnl,
                                return_pct=pnl/(entry*qty)*100 if pnl is not None else None,
                                basis='FILL_CONFIRMED' if qty else 'ORDER_PENDING', manual=False,
                                corrected=bool(o.get('correction')), market=o['market']))
        records.sort(key=lambda r: (r['ts'] or '', r['id']), reverse=True)
        count = conn.execute('SELECT count(*) FROM sheet_trade_outbox').fetchone()[0]
        if 'sell_order_lifecycle' in tables:
            count += conn.execute('SELECT count(*) FROM sell_order_lifecycle').fetchone()[0]
            count -= conn.execute("SELECT count(*) FROM sheet_trade_outbox s WHERE json_extract(s.payload_json,'$[2]')='SELL' "
                                  "AND EXISTS (SELECT 1 FROM sell_order_lifecycle o WHERE o.trade_id=json_extract(s.payload_json,'$[1]') "
                                  "AND o.ordered_at=json_extract(s.payload_json,'$[0]'))").fetchone()[0]
        return dict(trades=records[:200], trade_count=count)

    def historical(self, conn):
        history = self.trade_history(conn)
        if self.cached is not None and time.monotonic() - self.cached_at < 60:
            return dict(self.cached, **history)
        runtime = conn.execute("SELECT ts,payload_json FROM events WHERE event_type='RUNTIME_START' ORDER BY id DESC LIMIT 1").fetchone()
        latest_id = conn.execute("SELECT coalesce(max(id),0) FROM events").fetchone()[0]
        for row in conn.execute("SELECT trade_id,strategy_name,payload_json FROM events WHERE id>? AND id<=? AND event_type='COMPARISON_ENROLL' ORDER BY id", (self.enrollment_cursor, latest_id)):
            self.enrollments[(row["trade_id"], row["strategy_name"])] = json.loads(row["payload_json"]).get("cohort")
        self.enrollment_cursor = latest_id
        groups = {cohort: {name: {} for name in NAMES} for cohort in ("NEW_ENTRY", "EXISTING_FORWARD")}
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        excluded = {r[0] for r in conn.execute('SELECT trade_id FROM analysis_exclusions')} if 'analysis_exclusions' in tables else set()
        for row in conn.execute("SELECT trade_id,strategy_name,stage,active,return_pct FROM strategy_results WHERE strategy_name IN (?,?,?,?)", NAMES):
            if row['trade_id'] in excluded:
                continue
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
        self.cached = dict(comparisons=comparisons, analysis_excluded_count=len(excluded), runtime_at=timestamp(runtime["ts"]) if runtime else None,
                           runtime=json.loads(runtime["payload_json"]) if runtime else {})
        self.cached_at = time.monotonic()
        return dict(self.cached, **history)

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
        hp = json.loads(health["payload_json"]) if health else {}
        health_at = timestamp(health["ts"]) if health else None
        health_fresh = bool(health_at and 0 <= (now-dt.datetime.fromisoformat(health_at)).total_seconds() <= 120)
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
            # Reconciliation updates last_update without fetching a quote. Never use it as quote time.
            monitor = monitoring(now, saved if synced else {}, expected,
                                 active and health_fresh and hp.get("account_valid") is not False,
                                 state.get("dashboard_control", {}).get("paused"), state.get("market_closed_date"))
            observed = monitor["last_valid_quote_at"]
            allowed = ("KRX", "NXT") if minute >= 960 else (expected,)
            quote = number(saved.get("last_valid_quote_price"), True) if price_source in allowed and synced and observed else None
            if quote is None:
                quote = number(p.get("account_price"), True)
                price_source = "KRX_ACCOUNT_FALLBACK"
                observed = timestamp(account["ts"])
            stage = str(saved.get("stage", "대기")) if synced else "동기화 확인"
            positions.append(dict(code=symbol, name=str(saved.get("name") or symbol)[:80], qty=qty, entry=entry,
                                  price=quote, price_source=str(price_source)[:40], observed_at=observed, stage=stage,
                                  start_price=number(saved.get("trail_start_price"), True) if synced else None,
                                  stop_price=number(saved.get("trail_stop_price"), True) if synced else None,
                                  hard_stop_price=entry * .9, peak_price=number(saved.get("max_price"), True) if synced else None,
                                  pnl=(quote-entry)*qty if quote is not None else None,
                                  return_pct=(quote/entry-1)*100 if quote is not None else None,
                                  opened_at=timestamp(saved.get("opened_at")) if synced else None, stale_state=not synced,
                                  **monitor))
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
                    positions=positions, trades=historical["trades"], trade_count=historical["trade_count"], comparisons=historical["comparisons"],
                    analysis_excluded_count=historical["analysis_excluded_count"])


