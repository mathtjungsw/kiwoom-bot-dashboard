"""Install reviewed artifacts only; always preserve previous bot and proxy code."""
import argparse
import ast
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.error
import urllib.request

EXPECTED = "c84bbc99a04826e4eb433f8ae9909f5e60b5a8ddcbc9b98623985d20a71cb229"


def run(*args):
    subprocess.run(args, check=True, timeout=60)


def assert_strategy_unchanged(before, after):
    def functions(text):
        return {node.name: ast.dump(node, include_attributes=False) for node in ast.parse(text).body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name not in ('main','sheet_append_trade_log')}
    if functions(before) != functions(after):
        raise RuntimeError("Unexpected changes outside dashboard/main/log-dispatch functions")


def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage');parser.add_argument('--bot',action='store_true');args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('Run with sudo')
    stage=Path(args.stage).resolve();target=Path('/opt/kiwoom-dashboard');bot=Path('/opt/bots/kiwoom-stock/main.py')
    backup=Path('/opt/bots/kiwoom-stock/backups')/('web_dashboard_'+dt.datetime.now().strftime('%Y%m%d_%H%M%S'));backup.mkdir(parents=True)
    caddy=Path('/etc/caddy/Caddyfile')
    if args.bot:
        old=bot.read_bytes();new=(stage/'bot-main.py').read_bytes()
        if hashlib.sha256(old).hexdigest()!=EXPECTED:raise RuntimeError('Bot changed; inspect before applying')
        assert_strategy_unchanged(old.decode('utf-8'),new.decode('utf-8'))
        compile(new,str(bot),'exec')
        # Do not silently resume an already paused old bot.
        import sqlite3
        conn=sqlite3.connect('file:/opt/bots/kiwoom-stock/data/trading_analytics.db?mode=ro',uri=True)
        stamp=conn.execute('SELECT ts FROM account_samples ORDER BY ts DESC LIMIT 1').fetchone()[0];conn.close()
        from zoneinfo import ZoneInfo
        age=time.time()-dt.datetime.fromisoformat(stamp).replace(tzinfo=ZoneInfo('Asia/Seoul')).timestamp()
        if age>180:raise RuntimeError('Account source not fresh; verify previous pause state before migration')
        shutil.copy2(bot,backup/'main.py');shutil.copy2('/opt/bots/kiwoom-stock/trail_state.json',backup/'trail_state.json')
        control=Path('/var/lib/kiwoom-dashboard-control/command.json')
        if not control.exists():
            control.write_text(json.dumps({'id':'initial-migration-running','paused':False}));control.chmod(0o600);shutil.chown(control,user='ubuntu',group='ubuntu')
        try:
            temp=bot.with_suffix('.dashboard-next');shutil.copy2(stage/'bot-main.py',temp);shutil.chown(temp,user='ubuntu',group='ubuntu');temp.replace(bot)
            run('/opt/bots/kiwoom-stock/.venv/bin/python3','-m','py_compile',str(bot))
            run('systemctl','restart','kiwoom-stock')
            time.sleep(7)
            run('systemctl','is-active','--quiet','kiwoom-stock')
            state=json.loads(Path('/opt/bots/kiwoom-stock/trail_state.json').read_text())
            if 'dashboard_control' not in state:raise RuntimeError('Bot did not acknowledge local control')
        except Exception:
            shutil.copy2(backup/'main.py',bot);run('systemctl','restart','kiwoom-stock');print('BOT_ROLLBACK',str(backup),flush=True);raise
        print('BOT_APPLIED',hashlib.sha256(bot.read_bytes()).hexdigest(),'BACKUP',str(backup),flush=True)
        return
    for directory in ('/var/lib/kiwoom-dashboard','/var/lib/kiwoom-dashboard-control'):
        Path(directory).mkdir(exist_ok=True);shutil.chown(directory,user='ubuntu',group='ubuntu');Path(directory).chmod(0o700)
    target.mkdir(exist_ok=True)
    for name in ('backend','docs'):
        if (target/name).exists():shutil.copytree(target/name,backup/name)
        shutil.copytree(stage/name,target/name,dirs_exist_ok=True)
    unit=Path('/etc/systemd/system/kiwoom-dashboard.service')
    if unit.exists():shutil.copy2(unit,backup/unit.name)
    shutil.copy2(stage/'deploy/kiwoom-dashboard.service',unit)
    shutil.copy2(caddy,backup/'Caddyfile')
    old=caddy.read_text();anchor='    handle /api/* {'
    if old.count(anchor)!=1:raise RuntimeError('Proxy changed; inspect first')
    new=old if 'handle /bot-api/*' in old else old.replace(anchor,'    handle /bot-api/* {\n        reverse_proxy 127.0.0.1:8880\n    }\n'+anchor,1)
    try:
        run('systemctl','daemon-reload');run('systemctl','enable','--now','kiwoom-dashboard')
        time.sleep(2)
        with urllib.request.urlopen('http://127.0.0.1:8880/bot-api/health',timeout=5) as response:assert json.load(response)['ok']
        try:urllib.request.urlopen('http://127.0.0.1:8880/bot-api/snapshot',timeout=5);raise RuntimeError('Anonymous data access unexpectedly allowed')
        except urllib.error.HTTPError as error:assert error.code==401
        caddy.write_text(new);run('caddy','validate','--config',str(caddy));run('systemctl','reload','caddy')
    except Exception:
        shutil.copy2(backup/'Caddyfile',caddy);run('systemctl','reload','caddy');print('PROXY_ROLLBACK',str(backup),flush=True);raise
    print('API_INSTALLED',str(target),'BACKUP',str(backup),flush=True)


if __name__=='__main__':main()
