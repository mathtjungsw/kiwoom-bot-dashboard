"""Bounded public-site metadata lookup; no AI, browser, or trading dependencies."""
from html.parser import HTMLParser
import http.client
import ipaddress
import re
import socket
import ssl
import urllib.parse
import urllib.robotparser

AGENT = 'PrivateStockDashboard'
PAGE_LIMIT = 262144


def public_addresses(host):
    addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError('Non-public company website')
    return addresses


def request(url, allowed_host):
    """Pin a validated public IP while retaining TLS hostname verification."""
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or '').encode('idna').decode('ascii').lower()
    if (parsed.scheme != 'https' or host.removeprefix('www.') != allowed_host
            or parsed.port not in (None, 443) or parsed.username or parsed.password):
        raise ValueError('Unapproved website destination')
    address = public_addresses(host)[0]
    connection = http.client.HTTPSConnection(host, timeout=4)
    try:
        raw_socket = socket.create_connection((address, 443), timeout=4)
        try:
            connection.sock = ssl.create_default_context().wrap_socket(raw_socket, server_hostname=host)
        except Exception:
            raw_socket.close()
            raise
        path = urllib.parse.urlunsplit(('', '', parsed.path or '/', parsed.query, ''))
        connection.request('GET', path, headers={'User-Agent': AGENT + '/1.0', 'Accept': 'text/html,text/plain'})
        response = connection.getresponse()
        body = response.read(PAGE_LIMIT + 1)
        if len(body) > PAGE_LIMIT:
            raise ValueError('Company page too large')
        return response.status, dict(response.getheaders()), body
    finally:
        connection.close()


def page(url, allowed_host, fetch=request, permitted=lambda url:True):
    for _ in range(3):
        if not permitted(url):
            raise ValueError('Company website disallows automatic lookup')
        status, headers, body = fetch(url, allowed_host)
        headers = {key.lower(): value for key, value in headers.items()}
        if status in (301, 302, 303, 307, 308):
            target = urllib.parse.urljoin(url, headers.get('location', ''))
            parsed = urllib.parse.urlsplit(target)
            if parsed.scheme != 'https' or (parsed.hostname or '').lower().removeprefix('www.') != allowed_host:
                raise ValueError('Company redirect outside approved host')
            url = target
            continue
        return url, status, headers, body
    raise ValueError('Too many company redirects')


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values = {}

    def handle_starttag(self, tag, attrs):
        if tag == 'meta':
            attrs = dict(attrs)
            name = (attrs.get('name') or attrs.get('property') or '').lower()
            if name in ('description', 'og:description'):
                self.values.setdefault(name, ' '.join((attrs.get('content') or '').split()))


def introduction(website, fetch=request):
    parsed = urllib.parse.urlsplit(website)
    host = (parsed.hostname or '').encode('idna').decode('ascii').lower()
    if parsed.username or parsed.password or parsed.port not in (None, 80, 443) or not host:
        raise ValueError('Invalid official website')
    allowed = host.removeprefix('www.')
    url = urllib.parse.urlunsplit(('https', host, parsed.path or '/', parsed.query, ''))
    robots_url = urllib.parse.urlunsplit(('https', host, '/robots.txt', '', ''))
    _, status, _, body = page(robots_url, allowed, fetch)
    if status == 200:
        robots = urllib.robotparser.RobotFileParser()
        robots.parse(body.decode('utf-8', errors='replace').splitlines())
        if not robots.can_fetch(AGENT, url):
            raise ValueError('Company website disallows automatic lookup')
    elif status != 404:
        raise ValueError('Company website permission unavailable')
    permitted = (lambda target:robots.can_fetch(AGENT, target)) if status == 200 else (lambda target:True)
    final_url, status, headers, raw = page(url, allowed, fetch, permitted)
    if status != 200 or 'text/html' not in headers.get('content-type', '').lower():
        raise ValueError('Company introduction unavailable')
    charset = re.search(rb'charset\s*=\s*["\']?([\w-]+)', raw[:8192], re.I)
    encoding = charset[1].decode('ascii') if charset else 'utf-8'
    parser = Metadata()
    try:
        parser.feed(raw.decode(encoding, errors='replace'))
    except LookupError:
        raise ValueError('Unknown company page encoding') from None
    description = parser.values.get('description') or parser.values.get('og:description', '')
    if not 30 <= len(description) <= 500:
        raise ValueError('No useful short company description')
    return dict(overview=description, overview_source_url=final_url,
                overview_source_label='공식 홈페이지 소개문', overview_method='site_metadata')
