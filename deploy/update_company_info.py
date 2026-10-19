"""Install optional information services without modifying/restarting the bot."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

MODULES = ('backend/server.py', 'backend/company_info.py', 'backend/info_worker.py')
UNITS = ('kiwoom-company-info.service', 'kiwoom-company-info.path', 'kiwoom-company-info.timer')


def run(*args, **kwargs):
    return subprocess.run(args, check=True, timeout=150, **kwargs)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo')
    stage=Path(__file__).resolve().parent.parent
    target=Path('/opt/kiwoom-dashboard')
    root=Path('/var/lib/kiwoom-dashboard-info')
    bot=Path('/opt/bots/kiwoom-stock/main.py')
    python='/opt/bots/kiwoom-stock/.venv/bin/python3'
    baseline=subprocess.check_output(['git','show','99bbe23:backend/server.py'],cwd=stage).replace(b'\r\n',b'\n')
    if sha(target/'backend/server.py') not in (hashlib.sha256(baseline).hexdigest(),sha(stage/'backend/server.py')):
        raise RuntimeError('Unreviewed API server changes; inspect before applying')
    for name in MODULES[1:]:
        if (target/name).exists() and sha(target/name)!=sha(stage/name):
            raise RuntimeError('Unreviewed module changes: '+name)
    for name in UNITS:
        installed=Path('/etc/systemd/system')/name
        if installed.exists() and sha(installed)!=sha(stage/'deploy'/name):
            raise RuntimeError('Unreviewed service unit: '+name)
    run(python,'-m','py_compile',*(str(stage/name) for name in MODULES))
    run(python,'-m','unittest','discover','-s','tests','-v',cwd=stage,env=dict(os.environ,BOT_SOURCE=str(bot)))
    bot_hash=sha(bot)
    bot_pid=subprocess.check_output(['systemctl','show','kiwoom-stock','-p','MainPID','--value'],text=True).strip()
    sys.path.insert(0,str(target))
    # Read-only baseline sample from the currently installed API reader.
    from backend.reader import Reader
    before=Reader(bot.parent).snapshot(True)['source']['max_gap_sec']
    backup=target/'backups'/dt.datetime.now().strftime('company_%Y%m%d_%H%M%S')
    backup.mkdir(parents=True,mode=0o700)
    originals={}
    files=[(target/name,stage/name) for name in MODULES]
    files.extend((Path('/etc/systemd/system')/name,stage/'deploy'/name) for name in UNITS)
    for index,(dest,source) in enumerate(files):
        originals[dest]=backup/str(index) if dest.exists() else None
        if dest.exists():shutil.copy2(dest,originals[dest])
    root.mkdir(mode=0o700,exist_ok=True)
    shutil.chown(root,user='ubuntu',group='ubuntu')
    for name in ('queue','profiles','news'):
        (root/name).mkdir(mode=0o700,exist_ok=True)
        shutil.chown(root/name,user='ubuntu',group='ubuntu')
    run('systemctl','stop','kiwoom-dashboard')
    try:
        for dest,source in files:shutil.copy2(source,dest)
        run('systemctl','daemon-reload')
        run('systemctl','enable','--now','kiwoom-company-info.path','kiwoom-company-info.timer')
        run('systemctl','start','kiwoom-dashboard')
        time.sleep(2)
        run('systemctl','is-active','--quiet','kiwoom-dashboard','kiwoom-stock')
        with urllib.request.urlopen('http://127.0.0.1:8880/bot-api/health',timeout=5) as response:
            assert json.load(response)['ok']
        for path in ('snapshot','company/005930'):
            try:
                urllib.request.urlopen('http://127.0.0.1:8880/bot-api/'+path,timeout=5)
                raise RuntimeError('Authentication missing')
            except urllib.error.HTTPError as error:
                assert error.code==401
        from backend.server import Application
        app=Application('/var/lib/kiwoom-dashboard/auth.db',str(bot.parent),'/var/lib/kiwoom-dashboard-control/command.json',[])
        data=app.snapshot()
        if data['positions']:
            code=data['positions'][0]['code']
            # The validation process is root; queue ownership must match the web service.
            app.company(code)
            for path in (root/'queue').glob('*.json'):shutil.chown(path,user='ubuntu',group='ubuntu')
            run('systemctl','start','kiwoom-company-info.service')
            sample=app.company(code)
            assert sample['profile'] and not sample['profile'].get('unavailable'),'Company source unavailable'
            assert sample['news']['state'] in ('READY','EMPTY'),'News verification unavailable'
            print('LIVE_COMPANY_OK; NEWS='+sample['news']['state']+'; COUNT='+str(len(sample['news']['items'])),flush=True)
        assert sha(bot)==bot_hash,'Bot source changed'
        assert subprocess.check_output(['systemctl','show','kiwoom-stock','-p','MainPID','--value'],text=True).strip()==bot_pid,'Bot PID changed'
        after=Reader(bot.parent).snapshot(True)['source']['max_gap_sec']
        print('COMPANY_INFO_UPDATED; AUTHENTICATION_OK; BOT_UNCHANGED; GAP_BEFORE='+str(before)+'; GAP_AFTER='+str(after)+'; BACKUP='+str(backup),flush=True)
    except Exception:
        subprocess.run(['systemctl','disable','--now','kiwoom-company-info.path','kiwoom-company-info.timer'],check=False)
        subprocess.run(['systemctl','stop','kiwoom-company-info.service'],check=False)
        run('systemctl','stop','kiwoom-dashboard')
        for dest,saved in originals.items():
            if saved:shutil.copy2(saved,dest)
            else:dest.unlink(missing_ok=True)
        run('systemctl','daemon-reload')
        run('systemctl','start','kiwoom-dashboard')
        print('COMPANY_INFO_ROLLED_BACK; BOT_UNCHANGED; BACKUP='+str(backup),flush=True)
        raise


if __name__=='__main__':main()
