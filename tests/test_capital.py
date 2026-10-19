import json
import math
import unittest
import test_dashboard as fixtures
from backend.reader import Reader, capital_summary
from backend.server import Store, Application


class CapitalTests(unittest.TestCase):
    def setUp(self):fixtures.DashboardTests.setUp(self)
    def tearDown(self):fixtures.DashboardTests.tearDown(self)
    def test_total_return_is_not_current_holdings_return(self):
        data=Reader(self.root).snapshot(True,capital=dict(initial_capital=25000,net_external_flows=0))
        self.assertEqual(data['capital']['pnl'],-5000);self.assertEqual(data['capital']['return_pct'],-20)
        self.assertEqual(data['account']['purchase_amount'],12000);self.assertEqual(data['account']['valuation_amount'],12600)
        self.assertEqual(data['account']['pnl'],600);self.assertEqual(data['account']['return_pct'],5)
    def test_orderable_cash_is_not_added_to_broker_assets_again(self):
        data=Reader(self.root).snapshot(True,capital=dict(initial_capital=25000,net_external_flows=0))
        self.assertEqual(data['account']['equity'],20000);self.assertEqual(data['account']['deposit'],8000)
        self.assertEqual(data['capital']['pnl'],-5000)
    def test_sales_and_rebuys_do_not_increase_contributed_capital(self):
        data=Reader(self.root).snapshot(True,capital=dict(initial_capital=25000,net_external_flows=0))
        self.assertEqual(data['trade_count'],205);self.assertEqual(data['capital']['net_contributions'],25000)
    def test_net_external_flows_and_withdrawals(self):
        self.assertEqual(capital_summary(30000,dict(initial_capital=20000,net_external_flows=5000))['return_pct'],20)
        self.assertEqual(capital_summary(18000,dict(initial_capital=20000,net_external_flows=-5000))['return_pct'],20)
    def test_cash_only_account_still_has_cumulative_return(self):
        result=capital_summary(30000,dict(initial_capital=25000,net_external_flows=0));self.assertEqual(result['return_pct'],20)
    def test_unconfigured_capital_never_defaults_to_zero_loss(self):
        result=capital_summary(20000);self.assertFalse(result['configured']);self.assertIsNone(result['pnl']);self.assertIsNone(result['return_pct'])
    def test_invalid_initial_capital_is_not_used(self):
        for initial in [0,-1,None,'bad',math.inf,math.nan]:
            result=capital_summary(20000,dict(initial_capital=initial,net_external_flows=0));self.assertIsNone(result['return_pct'])
    def test_missing_equity_is_not_treated_as_zero(self):
        result=capital_summary(None,dict(initial_capital=25000,net_external_flows=0));self.assertIsNone(result['pnl'])
    def test_zero_assets_means_full_loss(self):
        self.assertEqual(capital_summary(0,dict(initial_capital=25000,net_external_flows=0))['return_pct'],-100)
    def test_zero_net_contribution_does_not_divide_by_zero(self):
        self.assertIsNone(capital_summary(100,dict(initial_capital=100,net_external_flows=-100))['return_pct'])
    def test_missing_quote_does_not_show_partial_valuation(self):
        path=self.root/'trail_state.json';saved=json.loads(path.read_text());saved['positions']['000001']['last_current_price']=None;path.write_text(json.dumps(saved))
        import sqlite3
        conn=sqlite3.connect(self.root/'data/trading_analytics.db');positions=json.loads(conn.execute('SELECT positions_json FROM account_samples').fetchone()[0]);positions[0]['account_price']=None;conn.execute('UPDATE account_samples SET positions_json=?',(json.dumps(positions),));conn.commit();conn.close()
        data=Reader(self.root).snapshot(True);self.assertIsNone(data['account']['valuation_amount']);self.assertEqual(data['account']['purchase_amount'],12000)
    def test_capital_settings_persist_without_revoking_login(self):
        store=Store(self.root/'auth.db');store.setup('Test-password-123');session,_=store.login('Test-password-123','peer')
        store.set_capital(25000,0);restored=Store(self.root/'auth.db');self.assertEqual(restored.capital()['initial_capital'],25000)
        self.assertTrue(restored.valid(session['token']))
    def test_application_uses_private_settings_and_preserves_position_returns(self):
        app=Application(self.root/'auth.db',self.root,self.root/'command.json',['http://test'],lambda:True)
        before=app.snapshot();app.store.set_capital(25000);app.cache_at=0;after=app.snapshot()
        self.assertEqual(after['capital']['return_pct'],-20);self.assertEqual(before['positions'],after['positions'])
    def test_reject_nonfinite_capital_configuration(self):
        store=Store(self.root/'auth.db')
        for initial,flows in [(0,0),(-1,0),(math.nan,0),(100,math.inf)]:
            with self.assertRaises(ValueError):store.set_capital(initial,flows)


if __name__=='__main__':unittest.main()
