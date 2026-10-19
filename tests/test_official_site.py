import unittest
from unittest.mock import patch
from backend.official_site import introduction, public_addresses, request

DESCRIPTION = '공식 기업 홈페이지에서 제공하는 소개문입니다. 산업용 부품을 제조하고 판매하는 회사입니다.'


class OfficialSiteTests(unittest.TestCase):
    def fetch(self, url, host):
        self.assertEqual(host, 'example.com')
        if url.endswith('/robots.txt'):
            return 404, {}, b''
        raw = ('<html><meta charset="utf-8"><meta name="description" content="'+DESCRIPTION+'"></html>').encode()
        return 200, {'Content-Type':'text/html; charset=utf-8'}, raw

    def test_short_official_metadata_no_ai_or_article_fetch(self):
        value = introduction('http://www.example.com', self.fetch)
        self.assertEqual(value['overview'], DESCRIPTION)
        self.assertEqual(value['overview_source_url'], 'https://www.example.com/')
        self.assertEqual(value['overview_method'], 'site_metadata')

    def test_robots_denial_never_fetches_homepage(self):
        calls=[]
        def fetch(url, host):
            calls.append(url)
            return 200, {}, b'User-agent: *\nDisallow: /\n'
        with self.assertRaises(ValueError): introduction('https://example.com', fetch)
        self.assertEqual(calls,['https://example.com/robots.txt'])

    def test_robots_network_failure_is_not_permission(self):
        with self.assertRaises(ValueError):
            introduction('https://example.com', lambda *args:(403, {}, b''))

    def test_redirect_to_private_or_third_party_host_is_not_followed(self):
        calls=[]
        def fetch(url, host):
            calls.append(url)
            return 302, {'Location':'https://127.0.0.1/internal'}, b''
        with self.assertRaises(ValueError): introduction('https://example.com',fetch)
        self.assertEqual(len(calls),1)

    def test_redirect_disallowed_path_is_not_fetched(self):
        calls=[]
        def fetch(url, host):
            calls.append(url)
            if url.endswith('robots.txt'):
                return 200, {}, b'User-agent: *\nDisallow: /private\n'
            return 302, {'Location':'/private'}, b''
        with self.assertRaises(ValueError): introduction('https://example.com',fetch)
        self.assertEqual(len(calls),2)

    def test_private_dns_or_mixed_public_private_dns_denied(self):
        for addresses in [('127.0.0.1',),('169.254.169.254',),('8.8.8.8','10.0.0.1')]:
            records=[(2,1,6,'',(address,443)) for address in addresses]
            with patch('socket.getaddrinfo',return_value=records):
                with self.assertRaises(ValueError):public_addresses('example.com')

    def test_destination_and_credentials_checked_before_dns(self):
        with patch('socket.getaddrinfo',side_effect=AssertionError('Must not resolve')):
            for url in ['https://attacker.example/x','http://example.com','https://user:pass@example.com','https://example.com:8880']:
                with self.assertRaises(ValueError):request(url,'example.com')

    def test_generic_short_slogan_not_misrepresented_as_description(self):
        def fetch(url,host):
            if url.endswith('robots.txt'):return 404,{},b''
            return 200,{'content-type':'text/html'},b'<meta name="description" content="Welcome">'
        with self.assertRaises(ValueError):introduction('https://example.com',fetch)


if __name__=='__main__':unittest.main()
