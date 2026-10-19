"""Receive a bounded private code patch through the existing authenticated SSH terminal."""
import base64
import datetime as dt
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import termios

from update_quotes import BOT_BASELINE

FILES={'changes.diff','test_execution_quotes.py','test_trailing.py','test_fixed_monitor.py',
       'test_etf_guard.py','comparison_report.py'}


def main():
    bot=Path('/opt/bots/kiwoom-stock/main.py')
    if hashlib.sha256(bot.read_bytes()).hexdigest()!=BOT_BASELINE:
        raise RuntimeError('Bot source changed; review before transfer')
    saved=termios.tcgetattr(sys.stdin)
    hidden=list(saved);hidden[3]&=~termios.ECHO
    parts=[];size=0
    termios.tcsetattr(sys.stdin,termios.TCSANOW,hidden)
    try:
        print('PRIVATE_QUOTE_PATCH_READY; paste base64 lines then END',flush=True)
        for line in sys.stdin:
            line=line.strip()
            if line=='END':break
            parts.append(line);size+=len(line)
            if size>250000:raise ValueError('Payload too large')
        else:raise ValueError('Missing END marker')
    finally:
        termios.tcsetattr(sys.stdin,termios.TCSANOW,saved)
    packed=base64.b64decode(''.join(parts),validate=True)
    with gzip.GzipFile(fileobj=io.BytesIO(packed)) as handle:raw=handle.read(2000001)
    if len(raw)>2000000:raise ValueError('Payload too large')
    data=json.loads(raw)
    if set(data['files'])!=FILES:raise ValueError('Unexpected files')
    if any(not isinstance(v,str) or len(v)>500000 for v in data['files'].values()):raise ValueError('Invalid file')
    stage=Path.home()/dt.datetime.now().strftime('quote-stage-%Y%m%d-%H%M%S')
    stage.mkdir(mode=0o700)
    shutil.copy2(bot,stage/'main.py.before');shutil.copy2(bot,stage/'main.py')
    for name,value in data['files'].items():
        (stage/name).write_text(value,encoding='utf-8')
        (stage/name).chmod(0o600)
    subprocess.run(['patch','--batch','--fuzz=0','main.py','changes.diff'],cwd=stage,check=True,timeout=10)
    if hashlib.sha256((stage/'main.py').read_bytes()).hexdigest()!=data['result_sha256']:
        raise ValueError('Patched source hash mismatch; nothing deployed')
    (stage/'main.py').chmod(0o600)
    print('PRIVATE_QUOTE_PATCH_STAGED='+str(stage),flush=True)


if __name__=='__main__':main()
