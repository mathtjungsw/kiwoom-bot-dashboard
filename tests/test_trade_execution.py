import json
import sqlite3
import unittest
from backend.reader import Reader, NAMES


class TradeExecutionTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.executescript('''
        CREATE TABLE sheet_trade_outbox(event_id TEXT,created_at TEXT,payload_json TEXT);
        CREATE TABLE sell_order_lifecycle(order_key TEXT,trade_id TEXT,code TEXT,ordered_at TEXT,status TEXT,payload_json TEXT);
        CREATE TABLE execution_observations(trade_id TEXT,ordered_at TEXT,price_source TEXT,sold_qty INT,fill_price REAL,gross_pnl REAL,account_entry REAL);
        CREATE TABLE events(id INTEGER PRIMARY KEY,ts TEXT,trade_id TEXT,strategy_name TEXT,event_type TEXT,payload_json TEXT);
        CREATE TABLE strategy_results(trade_id TEXT,strategy_name TEXT,stage TEXT,active INT,return_pct REAL);
        CREATE TABLE analysis_exclusions(trade_id TEXT);
        ''')
        self.reader=Reader('.')

    def tearDown(self):self.db.close()

    def legacy(self):
        p=['2026-10-21 16:00:24','trade','SELL','000001','테스트 종목',700,10,-30,-3000,'STOP_LOSS','','KRX','test','']
        self.db.execute('INSERT INTO sheet_trade_outbox VALUES (?,?,?)',('old',p[0],json.dumps(p)))

    def order(self,status='FILLED',qty=10,value=10200):
        p=dict(order_key='new',trade_id='trade',code='000001',name='테스트 종목',ordered_at='2026-10-21 16:00:24',status=status,
               filled_qty=qty,fill_value=value,entry=1000,qty=10,reference_price=700,limit_price=699,reason='STOP_LOSS',market='KRX',correction=True)
        self.db.execute('INSERT OR REPLACE INTO sell_order_lifecycle VALUES (?,?,?,?,?,?)',('new','trade','000001',p['ordered_at'],status,json.dumps(p)))

    def test_confirmed_correction_replaces_display_without_deleting_original(self):
        self.legacy();self.order();data=self.reader.trade_history(self.db)
        self.assertEqual(len(data['trades']),1);self.assertEqual(data['trade_count'],1)
        t=data['trades'][0];self.assertEqual(t['price'],1020);self.assertEqual(t['pnl'],200)
        self.assertAlmostEqual(t['return_pct'],2.0);self.assertEqual(t['basis'],'FILL_CONFIRMED')
        self.assertEqual(json.loads(self.db.execute('SELECT payload_json FROM sheet_trade_outbox').fetchone()[0])[5],700)

    def test_pending_order_has_no_invented_price_or_profit(self):
        self.order('OPEN',0,0);t=self.reader.trade_history(self.db)['trades'][0]
        self.assertIsNone(t['price']);self.assertIsNone(t['pnl']);self.assertEqual(t['filled_qty'],0)

    def test_partial_profit_is_only_for_confirmed_quantity(self):
        self.order('PARTIAL',4,4080);t=self.reader.trade_history(self.db)['trades'][0]
        self.assertEqual(t['qty'],4);self.assertEqual(t['requested_qty'],10);self.assertEqual(t['pnl'],80)

    def test_verified_legacy_audit_overrides_reference_estimate(self):
        self.legacy()
        self.db.execute('INSERT INTO execution_observations VALUES (?,?,?,?,?,?,?)',('trade','2026-10-21 16:00:24','KIWOOM_FILL',10,1020,200,1000))
        t=self.reader.trade_history(self.db)['trades'][0];self.assertEqual(t['price'],1020);self.assertEqual(t['basis'],'FILL_CONFIRMED')

    def test_incomplete_fill_does_not_pretend_full_legacy_execution(self):
        self.legacy()
        self.db.execute('INSERT INTO execution_observations VALUES (?,?,?,?,?,?,?)',('trade','2026-10-21 16:00:24','KIWOOM_FILL',4,1020,80,1000))
        self.assertEqual(self.reader.trade_history(self.db)['trades'][0]['basis'],'REFERENCE_ESTIMATE')

    def test_order_status_updates_even_while_comparison_cache_is_warm(self):
        self.order('OPEN',0,0);self.assertIsNone(self.reader.historical(self.db)['trades'][0]['price'])
        self.db.execute('DELETE FROM sell_order_lifecycle');self.order()
        self.assertEqual(self.reader.historical(self.db)['trades'][0]['price'],1020)

    def test_corrupt_shadow_path_is_excluded_from_common_comparison(self):
        for name in NAMES:
            self.db.execute('INSERT INTO events(ts,trade_id,strategy_name,event_type,payload_json) VALUES (?,?,?,?,?)',
                            ('2026-10-21','bad',name,'COMPARISON_ENROLL',json.dumps(dict(cohort='NEW_ENTRY'))))
            self.db.execute('INSERT INTO strategy_results VALUES (?,?,?,?,?)',('bad',name,'EXITED',0,-30))
        self.db.execute('INSERT INTO analysis_exclusions VALUES (?)',('bad',))
        data=self.reader.historical(self.db)
        self.assertEqual(data['analysis_excluded_count'],1);self.assertEqual(data['comparisons'][0]['common_completed'],0)


if __name__=='__main__':unittest.main()
