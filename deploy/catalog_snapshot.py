"""Transfer an official public KIND export over an existing admin SSH terminal."""
import argparse
import base64
import gzip
import io
import json
from pathlib import Path
import re
import sys
import time
from backend.company_info import KIND_URL, ROOT, atomic_json, parse_listing
from backend.info_worker import download


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['download','import'])
    parser.add_argument('--output')
    args=parser.parse_args()
    if args.action=='download':
        rows=parse_listing(download(KIND_URL,limit=3000000),time.time())
        if len(rows)<100:raise ValueError('Incomplete source export')
        value=dict(checked_at=time.time(),rows=rows)
        packed=gzip.compress(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode())
        Path(args.output).write_bytes(packed)
        print('KIND_SNAPSHOT_READY; ROWS='+str(len(rows))+'; BYTES='+str(len(packed)))
    else:
        import termios
        saved=termios.tcgetattr(sys.stdin)
        hidden=list(saved)
        hidden[3]&=~termios.ECHO
        termios.tcsetattr(sys.stdin,termios.TCSANOW,hidden)
        print('KIND_SNAPSHOT_INPUT_READY; paste base64 lines, then END (input hidden):',flush=True)
        parts=[]
        try:
            for line in sys.stdin:
                if line.strip()=='END':break
                parts.append(line.strip())
                if sum(map(len,parts))>1000000:raise ValueError('Snapshot too large')
            else:raise ValueError('Missing end marker')
        finally:
            termios.tcsetattr(sys.stdin,termios.TCSANOW,saved)
        text=''.join(parts)
        if len(text)>1000000:raise ValueError('Snapshot too large')
        packed=base64.b64decode(text,validate=True)
        with gzip.GzipFile(fileobj=io.BytesIO(packed)) as handle:raw=handle.read(4000001)
        if len(raw)>4000000:raise ValueError('Snapshot too large')
        value=json.loads(raw)
        rows=value['rows']
        if not isinstance(rows,dict) or not 100<=len(rows)<=10000:raise ValueError('Invalid snapshot')
        for code,item in rows.items():
            if not re.fullmatch(r'[0-9A-Z]{6}',code) or item.get('code')!=code:raise ValueError('Invalid code')
        if not 0<=time.time()-value['checked_at']<=86400:raise ValueError('Use a current source export')
        root=Path(ROOT)
        atomic_json(root/'listing.json',value)
        (root/'listing_retry.json').unlink(missing_ok=True)
        for path in (root/'profiles').glob('*.json'):
            if path.stem in rows:atomic_json(path,rows[path.stem])
        print('KIND_SNAPSHOT_IMPORTED; ROWS='+str(len(rows))+'; TRADING_BOT_UNCHANGED',flush=True)


if __name__=='__main__':main()
