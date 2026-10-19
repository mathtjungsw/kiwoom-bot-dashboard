"""Apply a locally reviewed private bot stage and dashboard reader with rollback."""
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
import urllib.request
from zoneinfo import ZoneInfo


BOT_BASELINE = 'b7c21bb40a79bd597eeb1b46e2b0c2311076e9929ec173cf4eeea3aee43d52f4'


def run(*args, **kwargs):
    return subprocess.run(args, check=True, timeout=180, **kwargs)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalized(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n',b'\n')).hexdigest()


def install(source, target):
    stat=target.stat()
    temp=target.with_name(target.name+'.quote-update')
    try:
        with temp.open('wb') as handle:
            handle.write(source.read_bytes());handle.flush();os.fsync(handle.fileno())
        os.chmod(temp,stat.st_mode & 0o777)
        os.chown(temp,stat.st_uid,stat.st_gid)
        os.replace(temp,target)
    finally:
        temp.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--bot-stage',type=Path,required=True)
    args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('Run with sudo')
    stage=args.bot_stage.resolve()
    repo=Path(__file__).resolve().parents[1]
    bot=Path('/opt/bots/kiwoom-stock/main.py')
    reader=Path('/opt/kiwoom-dashboard/backend/reader.py')
    python=bot.parent/'.venv/bin/python3'
    if sha(bot)!=BOT_BASELINE:raise RuntimeError('Bot source changed; review current code first')
    if sha(stage/'main.py.before')!=BOT_BASELINE:raise RuntimeError('Private stage baseline mismatch')
    old_reader=subprocess.check_output(['git','show','c31f2ce:backend/reader.py'],cwd=repo).replace(b'\r\n',b'\n')
    if normalized(reader)!=hashlib.sha256(old_reader).hexdigest():
        raise RuntimeError('Dashboard reader changed; review current code first')
    run(str(python),'-m','py_compile',str(stage/'main.py'),str(repo/'backend/reader.py'))
    run(str(python),'-m','unittest','test_execution_quotes','test_trailing','test_fixed_monitor','test_etf_guard','-v',cwd=stage)
    run(str(python),'-m','unittest','discover','-s','tests','-v',cwd=repo,
        env=dict(os.environ,BOT_SOURCE=str(stage/'main.py'),PYTHONUTF8='1'))
    now=dt.datetime.now(ZoneInfo('Asia/Seoul'))
    minute=now.hour*60+now.minute
    if now.weekday()<5 and 480<=minute<1200:
        raise RuntimeError('Apply outside trading hours; no live orders may be used for verification')
    for service in ('kiwoom-stock','kiwoom-dashboard'):
        run('systemctl','is-active','--quiet',service)
    backup=bot.parent/'backups'/now.strftime('execution_quotes_%Y%m%d_%H%M%S')
    backup.mkdir(parents=True,mode=0o700)
    shutil.copy2(bot,backup/'main.py')
    shutil.copy2(reader,backup/'reader.py')
    # Databases/auth/control settings are not replaced. State is backed up after the bot stops.
    run('systemctl','stop','kiwoom-stock')
    try:
        shutil.copy2(bot.parent/'trail_state.json',backup/'trail_state.json')
        run('systemctl','stop','kiwoom-dashboard')
        install(stage/'main.py',bot)
        install(repo/'backend/reader.py',reader)
        run(str(python),'-m','py_compile',str(bot),str(reader))
        run('systemctl','start','kiwoom-stock')
        run('systemctl','start','kiwoom-dashboard')
        deadline=time.monotonic()+90
        while True:
            run('systemctl','is-active','--quiet','kiwoom-stock')
            run('systemctl','is-active','--quiet','kiwoom-dashboard')
            with sqlite3.connect((bot.parent/'data/trading_analytics.db').as_uri()+'?mode=ro',uri=True,timeout=1) as db:
                row=db.execute("SELECT ts,payload_json FROM events WHERE event_type='RUNTIME_START' ORDER BY id DESC LIMIT 1").fetchone()
            state=json.loads((bot.parent/'trail_state.json').read_text())
            if (row and json.loads(row[1]).get('implementation_version')=='2026-10-19_EXECUTION_QUOTES'
                    and dt.datetime.fromisoformat(row[0]).replace(tzinfo=ZoneInfo('Asia/Seoul'))>=now
                    and state.get('dashboard_control',{}).get('paused') is False):
                break
            if time.monotonic()>deadline:raise RuntimeError('Fresh bot startup/control acknowledgement not confirmed')
            time.sleep(2)
        with urllib.request.urlopen('http://127.0.0.1:8880/bot-api/health',timeout=5) as response:
            assert json.load(response)['ok']
        sys.path.insert(0,str(reader.parents[1]))
        from backend.reader import Reader
        sample=Reader(bot.parent).snapshot(True)
        assert all('monitor_status' in p and 'last_valid_quote_at' in p for p in sample['positions'])
        assert sha(bot)==sha(stage/'main.py')
        assert normalized(reader)==normalized(repo/'backend/reader.py')
        print('EXECUTION_QUOTES_UPDATED; BACKUP='+str(backup),flush=True)
        print('STRATEGY_UNCHANGED; NO_TEST_ORDERS; POSITIONS='+str(len(sample['positions'])),flush=True)
    except BaseException:
        run('systemctl','stop','kiwoom-stock')
        run('systemctl','stop','kiwoom-dashboard')
        install(backup/'main.py',bot)
        install(backup/'reader.py',reader)
        # Keep compatible live state, including any fresh broker reconciliation; never rewind fills.
        run('systemctl','start','kiwoom-stock')
        run('systemctl','start','kiwoom-dashboard')
        print('EXECUTION_QUOTES_ROLLED_BACK; BACKUP='+str(backup),flush=True)
        raise


if __name__=='__main__':main()
