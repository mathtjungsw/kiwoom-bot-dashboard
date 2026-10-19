"""Enter an existing NAVER API HUB key privately on the server terminal."""
import getpass
import json
import os
from pathlib import Path
import pwd
import urllib.error
import urllib.parse
import urllib.request


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo on the server terminal')
    client = getpass.getpass('NAVER API HUB Client ID (hidden): ').strip()
    secret = getpass.getpass('NAVER API HUB Client Secret (hidden): ').strip()
    if not all(8 <= len(value) <= 256 and value.isascii() and not any(c.isspace() for c in value)
               for value in (client, secret)):
        raise SystemExit('Invalid key format; nothing saved')
    request = urllib.request.Request(
        'https://naverapihub.apigw.ntruss.com/search/v1/news?' +
        urllib.parse.urlencode(dict(query='삼성전자', display=1, sort='date')),
        headers={'X-NCP-APIGW-API-KEY-ID': client, 'X-NCP-APIGW-API-KEY': secret})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.loads(response.read(65537))
            if not isinstance(data.get('items'), list):
                raise ValueError('Invalid response')
    except urllib.error.HTTPError as error:
        raise SystemExit('Key verification failed, HTTP ' + str(error.code) + '; nothing saved') from None
    except Exception:
        raise SystemExit('Key verification unavailable; nothing saved') from None
    root = Path('/var/lib/kiwoom-dashboard-info')
    root.mkdir(mode=0o700, exist_ok=True)
    owner = pwd.getpwnam('ubuntu')
    os.chown(root, owner.pw_uid, owner.pw_gid)
    path = root / 'provider.json'
    temp = root / 'provider.tmp'
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(dict(client_id=client, client_secret=secret), handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.chown(temp, owner.pw_uid, owner.pw_gid)
    temp.replace(path)
    print('NEWS_KEY_SAVED; VERIFIED; TRADING_BOT_UNCHANGED', flush=True)


if __name__ == '__main__':
    main()
