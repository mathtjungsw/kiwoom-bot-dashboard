"""Exercise the bot control class without importing broker code or issuing orders."""
import ast
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

SOURCE=Path(os.getenv('BOT_SOURCE',str(Path(__file__).resolve().parents[2]/'dashboard_20261016/main.py')))


@unittest.skipUnless(SOURCE.exists(),'Production bot source is supplied only for release verification')
class BotControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'command.json';self.clock=0.0
        tree=ast.parse(SOURCE.read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='PriceMonitor')
        self.ns=dict(os=os,json=json,dt=dt,time=types.SimpleNamespace(monotonic=lambda:self.clock),SELL_POLL_SEC=2.0,CONTROL_REFRESH_SEC=5.0,DISPLAY_REFRESH_SEC=30.0,ACCOUNT_REFRESH_SEC=10.0,LIVE_STRATEGY_NAME='test',REST_MIN_INTERVAL_SEC=.25,
                     now_str=lambda:'2026-10-16 10:00:00',log=Mock(),save_state=Mock(),fetch_account=Mock(return_value=(100,1000,[])),reconcile_state_with_account=Mock(),analytics_account_sample=Mock(),sell_mode_now=lambda:'FULL',is_buy_time_now=lambda:True,run_sell_logic=Mock(),update_shadow_tracking=Mock(),print_dashboard=Mock(),analytics_event=Mock())
        self.ns.update(is_nxt_price_time_now=lambda:False,store_quote_observation=Mock())
        self.ns.update(sync_sell_orders=Mock(),unsettled_sell_orders=lambda:False)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(SOURCE),'exec'),self.ns)
        self.monitor=self.ns['PriceMonitor'](types.SimpleNamespace(),None,{'positions':{}})
        self.env=patch.dict(os.environ,{'DASHBOARD_CONTROL_FILE':str(self.path)});self.env.start()
    def tearDown(self):self.env.stop();self.temp.cleanup()
    def command(self,paused):self.path.write_text(json.dumps({'id':'test-request','paused':paused}))
    def test_missing_control_is_fail_closed(self):self.assertTrue(self.monitor.local_stop_requested())
    def test_corrupt_control_is_fail_closed(self):self.path.write_text('broken');self.assertTrue(self.monitor.local_stop_requested())
    def test_string_false_is_not_accepted(self):self.path.write_text('{"paused":"false"}');self.assertTrue(self.monitor.local_stop_requested())
    def test_running_command_keeps_existing_monitor_active(self):
        self.command(False);self.assertTrue(self.monitor.checkpoint());self.ns['fetch_account'].assert_called_once();self.ns['run_sell_logic'].assert_called_once()
    def test_paused_command_prevents_buys_and_sells(self):
        self.command(True);self.assertFalse(self.monitor.checkpoint());self.ns['fetch_account'].assert_not_called();self.ns['run_sell_logic'].assert_not_called()
    def test_pause_acknowledgement_is_saved(self):
        self.command(True);self.monitor.tick();ack=self.monitor.state['dashboard_control'];self.assertEqual(ack['request_id'],'test-request');self.assertTrue(ack['paused']);self.ns['save_state'].assert_called()
    def test_live_pause_is_observed_at_next_control_checkpoint(self):
        self.command(False);self.monitor.tick();self.command(True);self.clock=6;self.assertFalse(self.monitor.checkpoint());self.assertEqual(self.ns['run_sell_logic'].call_count,1)
    def test_runtime_does_not_call_google_sheets(self):
        tree=ast.parse(SOURCE.read_text(encoding='utf-8'))
        scopes=[node for node in tree.body if getattr(node,'name','') in ('main','PriceMonitor','sheet_append_trade_log')]
        forbidden={'connect_control_sheet','sheet_stop_requested','sheet_update_status','sheet_flush_trade_outbox','sheet_ensure_trade_log_header','update_sheet_positions'}
        called={node.func.id for scope in scopes for node in ast.walk(scope) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name)}
        self.assertFalse(called&forbidden)


if __name__=='__main__':unittest.main()
