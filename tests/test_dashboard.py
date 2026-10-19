import ast
import datetime as dt
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from backend.server import Application, Server, Store, WEEK, digest, handler
from backend.reader import NAMES, Reader, KST


def fixture(root):
    (root/'data').mkdir(exist_ok=True)
    now=dt.datetime.now(KST).replace(tzinfo=None).isoformat(' ')
    db=sqlite3.connect(root/'data/trading_analytics.db')
    db.executescript('''CREATE TABLE events(id INTEGER PRIMARY KEY,ts TEXT,trade_id TEXT,strategy_name TEXT,event_type TEXT,payload_json TEXT);
    CREATE TABLE account_samples(ts TEXT PRIMARY KEY,equity REAL,deposit REAL,positions_json TEXT);
    CREATE TABLE sheet_trade_outbox(event_id TEXT PRIMARY KEY,created_at TEXT,payload_json TEXT);
    CREATE TABLE strategy_results(trade_id TEXT,strategy_name TEXT,stage TEXT,active INTEGER,return_pct REAL);''')
    positions=[dict(code=f'{i:06}',qty=2,average_cost=1000,account_price=1010) for i in range(1,7)]
    db.execute('INSERT INTO account_samples VALUES (?,?,?,?)',(now,20000,8000,json.dumps(positions)))
    db.execute('INSERT INTO events(ts,event_type,payload_json) VALUES (?,?,?)',(now,'RUNTIME_START',json.dumps(dict(sell_poll_sec=2,trailing=dict(start_rate=.03,gap_rate=.01)))))
    db.execute('INSERT INTO events(ts,event_type,payload_json) VALUES (?,?,?)',(now,'MONITOR_HEALTH',json.dumps(dict(max_cycle_gap_sec=2.8,poll_count=30))))
    for index,name in enumerate(NAMES):
        for tid,cohort in [('new','NEW_ENTRY'),('existing','EXISTING_FORWARD'),('open','NEW_ENTRY')]:
            db.execute('INSERT INTO events(ts,trade_id,strategy_name,event_type,payload_json) VALUES (?,?,?,?,?)',(now,tid,name,'COMPARISON_ENROLL',json.dumps(dict(cohort=cohort))))
            db.execute('INSERT INTO strategy_results VALUES (?,?,?,?,?)',(tid,name,'EXITED' if tid!='open' else '대기',0 if tid!='open' else 1,2+index if tid!='open' else None))
    for i in range(205):
        row=[now,'trade','SELL','000001','테스트',1010,2,1,20,'TRAIL_STOP','','KRX','test','']
        db.execute('INSERT INTO sheet_trade_outbox VALUES (?,?,?)',(str(i).zfill(4),now,json.dumps(row)))
    db.commit();db.close()
    source='KRX' if 540<=dt.datetime.now(KST).hour*60+dt.datetime.now(KST).minute<930 else 'NXT'
    saved={p['code']:dict(entry=1000,qty=2,name='테스트 종목 '+p['code'],last_current_price=1050,last_valid_quote_price=1050,last_valid_quote_at=now,last_valid_trade_at=now,quote_status='VALID',quote_reason='OK',price_source=source,last_update=now,stage='트레일중',trail_start_price=1030,trail_stop_price=1048,max_price=1055) for p in positions}
    (root/'trail_state.json').write_text(json.dumps(dict(positions=saved,dashboard_control=dict(request_id='confirmed',paused=False))),encoding='utf-8')


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);fixture(self.root)
    def tearDown(self):self.temp.cleanup()
    def test_password_sessions_last_exactly_seven_days_and_are_hashed(self):
        store=Store(self.root/'auth.db');store.setup('Test-password-123')
        result,error=store.login('Test-password-123','peer');self.assertIsNone(error)
        self.assertAlmostEqual(result['expires_at']-time.time(),WEEK,delta=2)
        self.assertTrue(store.valid(result['token']))
        with store.db() as db:self.assertEqual(db.execute('SELECT hash FROM sessions').fetchone()[0],digest(result['token']))
        with patch('backend.server.time.time',return_value=result['expires_at']+1):self.assertFalse(store.valid(result['token']))
    def test_sessions_survive_restart_and_logout_revokes(self):
        path=self.root/'auth.db';a=Store(path);a.setup('Test-password-123');session,_=a.login('Test-password-123','peer')
        b=Store(path);self.assertTrue(b.valid(session['token']));b.logout(session['token']);self.assertFalse(a.valid(session['token']))
    def test_change_password_revokes_every_session(self):
        a=Store(self.root/'auth.db');a.setup('Test-password-123');session,_=a.login('Test-password-123','peer');a.setup('Another-password-456');self.assertFalse(a.valid(session['token']))
    def test_login_rate_limit_persists_restart(self):
        path=self.root/'auth.db';a=Store(path);a.setup('Test-password-123')
        for _ in range(8):self.assertEqual(a.login('wrong','peer')[1],'password')
        self.assertEqual(Store(path).login('Test-password-123','peer')[1],'rate')
    def test_no_password_default(self):
        a=Store(self.root/'auth.db');self.assertFalse(a.initialized());self.assertEqual(a.login('anything','peer')[1],'setup')
        with self.assertRaises(ValueError):a.setup('short')
    def test_reader_preserves_all_six_holdings_and_actual_stop(self):
        s=Reader(self.root).snapshot(True);self.assertEqual(len(s['positions']),6);self.assertEqual(s['positions'][0]['stop_price'],1048)
        self.assertEqual(s['positions'][0]['pnl'],100);self.assertEqual(s['source']['target_sec'],2)
    def test_reader_does_not_write_production_database(self):
        path=self.root/'data/trading_analytics.db';before=path.read_bytes();Reader(self.root).snapshot(True);self.assertEqual(path.read_bytes(),before)
    def test_mismatched_state_never_claims_current_trail(self):
        path=self.root/'trail_state.json';data=json.loads(path.read_text());data['positions']['000001']['qty']=1;path.write_text(json.dumps(data))
        s=Reader(self.root).snapshot(True)['positions'][0];self.assertTrue(s['stale_state']);self.assertIsNone(s['stop_price']);self.assertEqual(s['price_source'],'KRX_ACCOUNT_FALLBACK');self.assertEqual(s['price'],1010)
    def test_fallback_is_not_mislabelled_nxt(self):
        path=self.root/'trail_state.json';data=json.loads(path.read_text());data['positions']['000001']['price_source']='NXT_UNAVAILABLE';path.write_text(json.dumps(data))
        s=Reader(self.root).snapshot(True)['positions'][0];self.assertEqual(s['price_source'],'KRX_ACCOUNT_FALLBACK');self.assertEqual(s['price'],1010)
    def test_recent_trade_limit_and_truthful_basis(self):
        data=Reader(self.root).snapshot(True);self.assertEqual(len(data['trades']),200);self.assertEqual(data['trade_count'],205);self.assertEqual(data['trades'][0]['basis'],'REFERENCE_ESTIMATE')
    def test_comparisons_use_only_common_completed_and_separate_cohorts(self):
        a,b=Reader(self.root).snapshot(True)['comparisons'];self.assertEqual(a['common_completed'],1);self.assertEqual(b['common_completed'],1)
        self.assertEqual(a['strategies'][0]['enrolled'],2);self.assertEqual(a['strategies'][3]['delta_pp'],3);self.assertEqual(a['strategies'][0]['active'],1)
    def test_pause_is_local_atomic_and_does_not_modify_bot_state(self):
        path=self.root/'trail_state.json';before=path.read_bytes();app=Application(self.root/'auth.db',self.root,self.root/'control/command.json',['http://test'],lambda:True)
        result=app.pause();self.assertTrue(result['paused']);self.assertEqual(json.loads(app.control.read_text())['id'],result['id']);self.assertEqual(path.read_bytes(),before)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        DashboardTests.setUp(self);self.app=Application(self.root/'auth.db',self.root,self.root/'control.json',['http://test'],lambda:True)
        self.app.store.setup('Test-password-123');self.server=Server(('127.0.0.1',0),handler(self.app));self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();DashboardTests.tearDown(self)
    def request(self,path,body=None,token='',origin='http://test'):
        request=urllib.request.Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Origin':origin,'Content-Type':'application/json','Authorization':'Bearer '+token})
        try:response=urllib.request.urlopen(request,timeout=5)
        except urllib.error.HTTPError as error:response=error
        with response:return response.status,json.loads(response.read()),dict(response.headers)
    def test_auth_required_for_snapshot_and_control(self):
        self.assertEqual(self.request('/bot-api/snapshot')[0],401);self.assertEqual(self.request('/bot-api/control',{'action':'pause'})[0],401)
        self.assertEqual(self.request('/bot-api/company/000001')[0],401)
    def test_company_lookup_is_private_only_held_symbols_and_does_not_block_snapshot(self):
        from backend.company_info import InfoCache
        self.app.info=InfoCache(self.root/'info')
        _,session,_=self.request('/bot-api/login',{'password':'Test-password-123'});token=session['token']
        status,data,_=self.request('/bot-api/company/000001',token=token)
        self.assertEqual(status,200);self.assertTrue(data['pending'])
        self.assertEqual(self.request('/bot-api/company/999999',token=token)[0],404)
        self.assertEqual(self.request('/bot-api/company/000001?url=http://example.com',token=token)[0],404)
        self.assertEqual(self.request('/bot-api/snapshot',token=token)[0],200)
    def test_cors_untrusted_origin_blocked(self):
        self.assertEqual(self.request('/bot-api/login',{'password':'Test-password-123'},origin='https://untrusted.invalid')[0],403)
    def test_login_snapshot_logout_and_replay(self):
        status,data,_=self.request('/bot-api/login',{'password':'Test-password-123'});self.assertEqual(status,200);token=data['token']
        status,snapshot,headers=self.request('/bot-api/snapshot',token=token);self.assertEqual(status,200);self.assertEqual(len(snapshot['positions']),6);self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(self.request('/bot-api/logout',{},token)[0],200);self.assertEqual(self.request('/bot-api/snapshot',token=token)[0],401)
    def test_pause_only_and_unacknowledged_until_bot_reads(self):
        _,session,_=self.request('/bot-api/login',{'password':'Test-password-123'});token=session['token']
        self.assertEqual(self.request('/bot-api/control',{'action':'resume'},token)[0],404)
        status,result,_=self.request('/bot-api/control',{'action':'pause'},token);self.assertEqual(status,200)
        _,data,_=self.request('/bot-api/snapshot',token=token);self.assertNotEqual(data['source']['control_id'],result['id']);self.assertFalse(data['source']['paused'])
    def test_control_unavailable_until_bot_is_integrated(self):
        path=self.root/'trail_state.json';data=json.loads(path.read_text());data.pop('dashboard_control');path.write_text(json.dumps(data))
        _,session,_=self.request('/bot-api/login',{'password':'Test-password-123'})
        self.assertEqual(self.request('/bot-api/control',{'action':'pause'},session['token'])[0],409);self.assertFalse(self.app.control.exists())
    def test_missing_source_returns_unavailable_not_fake_empty_account(self):
        (self.root/'trail_state.json').unlink();_,session,_=self.request('/bot-api/login',{'password':'Test-password-123'})
        self.assertEqual(self.request('/bot-api/snapshot',token=session['token'])[0],503)


if __name__=='__main__':unittest.main()
