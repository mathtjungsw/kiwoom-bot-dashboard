"""Small file queue/cache. Web requests never perform an external lookup."""
import datetime as dt
from html.parser import HTMLParser
import ipaddress
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import urllib.parse

ROOT = '/var/lib/kiwoom-dashboard-info'
MONTH = 30 * 86400
NEWS_TTL = 1800
KIND_URL = 'https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13'
KIND_PAGE = 'https://kind.krx.co.kr/corpgeneral/corpList.do?method=loadInitPage'
NEWS_URL = 'https://naverapihub.apigw.ntruss.com/search/v1/news'


def read_json(path, limit=32768):
    try:
        with Path(path).open('rb') as handle:
            raw = handle.read(limit + 1)
        return json.loads(raw) if len(raw) <= limit else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=path.name + '.tmp-', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def safe_url(value):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 33 for c in value):
        return None
    try:
        url = urllib.parse.urlsplit(value)
        host = url.hostname or ''
        if url.scheme not in ('https', 'http') or not host or url.username or url.password:
            return None
        if host == 'localhost' or '.' not in host or host.endswith(('.local', '.internal')):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        if url.port not in (None, 80, 443):
            return None
        return value
    except ValueError:
        return None


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(value, limit=1000):
    parser = Text()
    parser.feed(str(value or '')[:10000])
    return ' '.join(''.join(parser.parts).split())[:limit]


class ListingTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = []
        elif tag == 'a' and self.cell is not None:
            href = dict(attrs).get('href', '')
            if href.startswith(('https://', 'http://')):
                self.cell.append(href + ' ')

    def handle_data(self, value):
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def parse_listing(raw, now):
    parser = ListingTable()
    parser.feed(raw.decode('cp949'))
    if not parser.rows:
        raise ValueError('Empty listing')
    headers = parser.rows[0]
    required = ['회사명', '종목코드', '업종', '주요제품', '홈페이지']
    columns = {key: headers.index(key) for key in required}
    result = {}
    for row in parser.rows[1:]:
        if len(row) != len(headers):
            continue
        item = {key: row[index].strip() for key, index in columns.items()}
        code = item['종목코드'].zfill(6)
        if not re.fullmatch(r'[0-9A-Z]{6}', code) or not item['회사명']:
            continue
        website = re.search(r'https?://[^\s]+', item['홈페이지'])
        # Worker destinations come only from the official catalog, not web request input.
        result[code] = dict(code=code, name=item['회사명'][:80], industry=item['업종'][:200],
                            products=item['주요제품'][:1500], website=safe_url(website[0]) if website else None,
                            source_url=KIND_PAGE, checked_at=now)
    if not result:
        raise ValueError('Invalid listing columns/data')
    return result


def news_items(data):
    result = []
    if not isinstance(data.get('items'), list):
        raise ValueError('Invalid news response')
    # Preserve provider order and headline wording; no AI rewriting or reranking.
    for item in data['items'][:3]:
        if not isinstance(item, dict):
            raise ValueError('Invalid news item')
        link = safe_url(item.get('link'))
        original = safe_url(item.get('originallink'))
        if not link or not item.get('title'):
            raise ValueError('Invalid news link/title')
        try:
            from email.utils import parsedate_to_datetime
            provided_at = parsedate_to_datetime(item.get('pubDate', '')).isoformat()
        except (ValueError, TypeError, AttributeError):
            provided_at = None
        result.append(dict(title=plain(item['title'], 500), url=link, original_url=original,
                           publisher=urllib.parse.urlsplit(original or link).hostname,
                           provided_at=provided_at))
    return result


class InfoCache:
    def __init__(self, root=ROOT, clock=time.time):
        self.root, self.clock = Path(root), clock
        self.lock = threading.Lock()

    def get(self, code, name):
        with self.lock:
            return self._get(code, name)

    def _get(self, code, name):
        if not re.fullmatch(r'[0-9A-Z]{6}', code):
            raise ValueError('Invalid code')
        now = self.clock()
        profile = read_json(self.root / 'profiles' / (code + '.json'))
        news_path = self.root / 'news' / (code + '.json')
        news = read_json(news_path)
        # Expired search results are never retained as historical data.
        if news and now >= news.get('expires_at', 0):
            news_path.unlink(missing_ok=True)
            news = {}
        legacy = profile and not profile.get('unavailable') and not (
            profile.get('overview_method') or 'overview_unavailable' in profile)
        profile_due = not profile or legacy or now >= profile.get('refresh_at', profile.get('checked_at', 0) + MONTH)
        news_due = not news
        queue = self.root / 'queue'
        job = queue / (code + '.json')
        if profile_due or news_due:
            queue.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not job.exists() and len(list(queue.glob('*.json'))) < 20:
                atomic_json(job, dict(code=code, name=str(name)[:80], created_at=now))
        return dict(code=code, name=name, profile=profile if profile.get('code') == code else None,
                    profile_stale=bool(profile) and now - profile.get('checked_at', 0) >= MONTH, pending=job.exists(),
                    news=news or dict(state='WAITING', items=[], fetched_at=None))


def quota(root, now, filename='quota.json', daily_limit=90, monthly_limit=2700):
    path = Path(root) / filename
    local = dt.datetime.fromtimestamp(now, dt.timezone(dt.timedelta(hours=9)))
    day, month = local.strftime('%Y-%m-%d'), local.strftime('%Y-%m')
    saved = read_json(path)
    daily = saved.get('daily', 0) if saved.get('day') == day else 0
    monthly = saved.get('monthly', 0) if saved.get('month') == month else 0
    if daily >= daily_limit or monthly >= monthly_limit:
        return False
    atomic_json(path, dict(day=day, month=month, daily=daily + 1, monthly=monthly + 1))
    return True
