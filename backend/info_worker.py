"""On-demand low-priority worker, with no imports/access to trading code or DB."""
import argparse
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import json
from .company_info import (ROOT, MONTH, NEWS_TTL, KIND_URL, NEWS_URL, atomic_json,
                           read_json, parse_listing, news_items, quota)
from .official_site import introduction


def download(url, headers=None, limit=262144):
    request = urllib.request.Request(url, headers=headers or {'User-Agent': 'PrivateStockDashboard/1.0'})
    # Never follow redirects with a provider credential attached.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_):
            return None
    with urllib.request.build_opener(NoRedirect).open(request, timeout=4) as response:
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Response too large')
    return raw


class Worker:
    def __init__(self, root=ROOT, fetch=download, clock=time.time, site_lookup=None):
        self.root, self.fetch, self.clock = Path(root), fetch, clock
        self.site_lookup = site_lookup or introduction

    def profile(self, code):
        now = self.clock()
        path = self.root / 'listing.json'
        listing = read_json(path, 4000000)
        if now - listing.get('checked_at', 0) >= MONTH:
            retry = read_json(self.root / 'listing_retry.json').get('retry_at', 0)
            if now >= retry:
                try:
                    rows = parse_listing(self.fetch(KIND_URL, limit=3000000), now)
                    listing = dict(checked_at=now, rows=rows)
                    atomic_json(path, listing)
                except Exception:
                    atomic_json(self.root / 'listing_retry.json', dict(retry_at=now + 86400))
        found = listing.get('rows', {}).get(code)
        if found:
            found = dict(found)
            if now - found.get('checked_at', 0) >= MONTH:
                found = dict(found, refresh_at=now + 86400)
            previous = read_json(self.root / 'profiles' / (code + '.json'))
            # Profile lookups run only in this low-priority worker, never in the bot/API.
            if found.get('website') and quota(self.root, now, 'site_quota.json', 10, 100):
                try:
                    found.update(self.site_lookup(found['website']), overview_checked_at=now)
                except Exception:
                    found['overview_unavailable'] = True
                    if previous.get('overview'):
                        for key in ('overview', 'overview_source_url', 'overview_source_label',
                                    'overview_method', 'overview_checked_at'):
                            if key in previous:
                                found[key] = previous[key]
            else:
                found['overview_unavailable'] = True
            found['refresh_at'] = now + MONTH
            atomic_json(self.root / 'profiles' / (code + '.json'), found)
        else:
            atomic_json(self.root / 'profiles' / (code + '.json'),
                        dict(code=code, unavailable=True, checked_at=now, refresh_at=now + 3600,
                             source_url='https://kind.krx.co.kr/'))
        return found

    def news(self, code, name):
        now = self.clock()
        path = self.root / 'news' / (code + '.json')
        saved = read_json(path)
        if saved and now < saved.get('expires_at', 0):
            return
        key = read_json(self.root / 'provider.json')
        value = dict(state='SETUP_REQUIRED', items=[], fetched_at=now, expires_at=now + 300)
        if key.get('client_id') and key.get('client_secret'):
            if not quota(self.root, now):
                value['state'] = 'LIMIT'
            else:
                try:
                    url = NEWS_URL + '?' + urllib.parse.urlencode(dict(query='"' + name + '"', display=3, sort='date', format='json'))
                    data = json.loads(self.fetch(url, headers={'X-NCP-APIGW-API-KEY-ID': key['client_id'],
                                                               'X-NCP-APIGW-API-KEY': key['client_secret']}))
                    items = news_items(data)
                    value.update(state='READY' if items else 'EMPTY', items=items, expires_at=now + NEWS_TTL)
                except Exception:
                    value['state'] = 'ERROR'
        atomic_json(path, value)

    def run(self):
        now = self.clock()
        # Keep cache usage bounded, including companies that are no longer held.
        profiles = sorted((self.root / 'profiles').glob('*.json'), key=lambda p:p.stat().st_mtime, reverse=True)
        for path in profiles[200:]:
            path.unlink(missing_ok=True)
        # Hard purge even if the associated stock is no longer viewed/held.
        for path in (self.root / 'news').glob('*.json'):
            if now >= read_json(path).get('expires_at', 0):
                path.unlink(missing_ok=True)
        import re
        for path in sorted((self.root / 'queue').glob('*.json'))[:20]:
            try:
                job = read_json(path)
                code, name = job.get('code', ''), job.get('name', '')
                if not re.fullmatch(r'[0-9A-Z]{6}', code) or not isinstance(name, str) or not 1 <= len(name) <= 80:
                    continue
                profile = read_json(self.root / 'profiles' / (code + '.json'))
                if not profile or self.clock() >= profile.get('refresh_at', profile.get('checked_at', 0) + MONTH):
                    profile = self.profile(code)
                self.news(code, (profile or {}).get('name') or name)
            except Exception:
                print('Company lookup unavailable; trading remains independent', flush=True)
            finally:
                path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default=ROOT)
    Worker(parser.parse_args().root).run()


if __name__ == '__main__':
    main()
