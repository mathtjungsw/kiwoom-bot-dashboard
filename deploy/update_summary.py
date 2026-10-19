"""Update only dashboard code/config; never restart or modify the trading bot."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASELINE = {
    'backend/server.py': 'c92b6f52ef83ca2153feaacc58969ab074e3c26df1be46bb13459532ca1e1886',
    'backend/reader.py': '84b426bf4e5776fe9b7a00319b20347c404cf341b17137674a6362f3f27c7ef2',
}


def run(*args, **kwargs):
    return subprocess.run(args, check=True, timeout=90, **kwargs)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized_sha(path):
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--initial-capital', type=float, required=True)
    parser.add_argument('--net-external-flows', type=float, default=0)
    args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('Run with sudo')
    stage=Path(__file__).resolve().parent.parent
    target=Path('/opt/kiwoom-dashboard')
    bot=Path('/opt/bots/kiwoom-stock/main.py')
    auth=Path('/var/lib/kiwoom-dashboard/auth.db')
    python='/opt/bots/kiwoom-stock/.venv/bin/python3'
    for name, expected in BASELINE.items():
        if normalized_sha(target/name) not in (expected, normalized_sha(stage/name)):
            raise RuntimeError('Unreviewed server changes: '+name+'; inspect before applying')
    run(python,'-m','py_compile',str(stage/'backend/reader.py'),str(stage/'backend/server.py'))
    env=dict(os.environ,BOT_SOURCE=str(bot))
    run(python,'-m','unittest','discover','-s','tests','-v',cwd=stage,env=env)
    bot_sha=sha(bot)
    bot_pid=subprocess.check_output(['systemctl','show','kiwoom-stock','-p','MainPID','--value'],text=True).strip()
    backup=target/'backups'/dt.datetime.now().strftime('summary_%Y%m%d_%H%M%S')
    backup.mkdir(parents=True,mode=0o700)
    for name in ('server.py','reader.py'):
        shutil.copy2(target/'backend'/name,backup/name)
    # Stop only the web API while taking a consistent auth/config backup.
    run('systemctl','stop','kiwoom-dashboard')
    try:
        with sqlite3.connect(auth) as source, sqlite3.connect(backup/'auth.db') as dest:
            source.backup(dest)
        (backup/'auth.db').chmod(0o600)
        for name in ('server.py','reader.py'):
            shutil.copy2(stage/'backend'/name,target/'backend'/name)
        run('runuser','-u','ubuntu','--',python,'-m','backend.server','capital',
            '--initial-capital',str(args.initial_capital),'--net-external-flows',str(args.net_external_flows),cwd=target)
        run('systemctl','start','kiwoom-dashboard')
        time.sleep(2)
        run('systemctl','is-active','--quiet','kiwoom-dashboard')
        with urllib.request.urlopen('http://127.0.0.1:8880/bot-api/health',timeout=5) as response:
            assert json.load(response)['ok']
        try:
            urllib.request.urlopen('http://127.0.0.1:8880/bot-api/snapshot',timeout=5)
            raise RuntimeError('Authentication missing')
        except urllib.error.HTTPError as error:
            assert error.code==401
        sys.path.insert(0,str(target))
        from backend.server import Application
        app=Application(auth,'/opt/bots/kiwoom-stock','/var/lib/kiwoom-dashboard-control/command.json',[])
        data=app.snapshot()
        assert data['capital']['configured'] and data['capital']['initial_capital']==args.initial_capital
        assert 'purchase_amount' in data['account'] and 'valuation_amount' in data['account']
        assert sha(bot)==bot_sha,'Trading source unexpectedly changed'
        assert subprocess.check_output(['systemctl','show','kiwoom-stock','-p','MainPID','--value'],text=True).strip()==bot_pid,'Trading service changed during update'
        print('SUMMARY_UPDATED; AUTHENTICATION_OK; BOT_UNCHANGED; BACKUP='+str(backup),flush=True)
    except Exception:
        run('systemctl','stop','kiwoom-dashboard')
        for name in ('server.py','reader.py'):
            shutil.copy2(backup/name,target/'backend'/name)
        if (backup/'auth.db').exists():
            shutil.copy2(backup/'auth.db',auth)
            shutil.chown(auth,user='ubuntu',group='ubuntu')
            auth.chmod(0o600)
        run('systemctl','start','kiwoom-dashboard')
        print('DASHBOARD_ROLLED_BACK; BACKUP='+str(backup),flush=True)
        raise


if __name__=='__main__':main()
