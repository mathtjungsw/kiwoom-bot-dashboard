import concurrent.futures
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from backend.company_info import (InfoCache, MONTH, NEWS_TTL, KIND_URL, NEWS_URL,
                                  atomic_json, read_json, parse_listing, news_items, safe_url, quota)
from backend.info_worker import Worker
from backend.server import Application

NOW = 2_000_000_000
LISTING = '''<table><tr><th>회사명</th><th>시장구분</th><th>종목코드</th><th>업종</th><th>주요제품</th><th>홈페이지</th></tr>
<tr><td>테스트전자</td><td>유가증권</td><td>005930</td><td>전자부품 제조업</td><td>부품 &amp; 센서</td><td><a href="https://example.com">홈페이지</a></td></tr>
<tr><td>두번째기업</td><td>코스닥</td><td>000001</td><td>화학</td><td>화학 소재</td><td>https://example.org</td></tr></table>'''.encode('cp949')
NEWS = dict(items=[dict(title='<b>테스트전자</b> &amp; 생산 확대', link='https://n.news.naver.com/article/1', originallink='https://example.com/article/1', pubDate='Mon, 19 Oct 2026 16:00:00 +0900')])


class CompanyInfoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cache = InfoCache(self.root, lambda:NOW)

    def tearDown(self):
        self.temp.cleanup()

    def fetch(self, url, **kwargs):
        if url == KIND_URL:
            return LISTING
        self.assertTrue(url.startswith(NEWS_URL + '?'))
        self.assertEqual(kwargs['headers']['X-NCP-APIGW-API-KEY-ID'], 'test-client')
        self.assertNotIn('qty', url)
        return json.dumps(NEWS).encode()

    def key(self):
        atomic_json(self.root/'provider.json', dict(client_id='test-client', client_secret='test-secret'))

    def test_kind_headers_not_column_offsets_and_stock_code_padding(self):
        data=parse_listing(LISTING,NOW)
        self.assertEqual(data['005930']['products'],'부품 & 센서')
        self.assertEqual(data['005930']['website'],'https://example.com')
        self.assertEqual(data['000001']['industry'],'화학')

    def test_invalid_listing_never_becomes_a_fake_profile(self):
        with self.assertRaises(ValueError):parse_listing(b'<html>unavailable</html>',NOW)

    def test_route_only_queues_without_any_network(self):
        with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('network not allowed')):
            data=self.cache.get('005930','테스트전자')
        self.assertTrue(data['pending']);self.assertIsNone(data['profile'])
        self.assertEqual(set(read_json(self.root/'queue/005930.json')),{'code','name','created_at'})

    def test_repeated_clicks_create_one_job(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _:self.cache.get('005930','테스트전자'),range(8)))
        self.assertEqual(len(list((self.root/'queue').glob('*.json'))),1)

    def test_worker_profile_and_news_then_cache_hit(self):
        self.key();self.cache.get('005930','테스트전자')
        worker=Worker(self.root,self.fetch,lambda:NOW);worker.run()
        value=self.cache.get('005930','테스트전자')
        self.assertFalse(value['pending']);self.assertEqual(value['news']['state'],'READY')
        self.assertEqual(value['profile']['industry'],'전자부품 제조업')
        self.assertEqual(value['news']['items'][0]['title'],'테스트전자 & 생산 확대')
        self.assertNotIn('test-secret',json.dumps(value))
        self.assertEqual(read_json(self.root/'quota.json')['daily'],1)

    def test_second_stock_reuses_monthly_kind_download(self):
        self.key();self.cache.get('005930','테스트전자');self.cache.get('000001','두번째기업')
        calls=[]
        def fetch(url,**kwargs):calls.append(url);return self.fetch(url,**kwargs)
        Worker(self.root,fetch,lambda:NOW).run()
        self.assertEqual(calls.count(KIND_URL),1)

    def test_unconfigured_news_does_not_prevent_company_info(self):
        self.cache.get('005930','테스트전자');Worker(self.root,self.fetch,lambda:NOW).run()
        value=self.cache.get('005930','테스트전자')
        self.assertEqual(value['news']['state'],'SETUP_REQUIRED');self.assertTrue(value['profile'])
        self.assertFalse(value['pending'])

    def test_network_failure_returns_error_and_retries_only_after_cooldown(self):
        self.key();self.cache.get('005930','테스트전자')
        def fail(*args,**kwargs):raise TimeoutError('private secret must not leak')
        Worker(self.root,fail,lambda:NOW).run()
        result=self.cache.get('005930','테스트전자')
        self.assertEqual(result['news']['state'],'ERROR');self.assertFalse(result['pending'])
        self.assertNotIn('private secret',json.dumps(result))

    def test_expired_news_is_removed_and_not_served_as_latest(self):
        atomic_json(self.root/'news/005930.json',dict(state='READY',items=[{'title':'old'}],expires_at=NOW-1))
        value=self.cache.get('005930','테스트전자')
        self.assertFalse((self.root/'news/005930.json').exists())
        self.assertEqual(value['news']['items'],[])

    def test_purge_without_any_new_view_or_job(self):
        atomic_json(self.root/'news/005930.json',dict(items=[{'title':'old'}],expires_at=NOW-1))
        Worker(self.root,self.fetch,lambda:NOW).run()
        self.assertFalse((self.root/'news/005930.json').exists())

    def test_provider_order_preserved_max_three_no_full_article(self):
        data=news_items(dict(items=[dict(NEWS['items'][0],title=str(i)) for i in range(5)]))
        self.assertEqual([item['title'] for item in data],['0','1','2'])
        self.assertNotIn('description',data[0])

    def test_unsafe_links_and_invalid_response_rejected(self):
        for url in ['javascript:alert(1)','https://localhost/x','https://127.0.0.1/x','https://user:pass@example.com','https://example.com:8880/','https://bad.local/']:
            self.assertIsNone(safe_url(url),url)
        with self.assertRaises(ValueError):news_items(dict(items=[dict(NEWS['items'][0],link='javascript:alert(1)')]))
        with self.assertRaises(ValueError):news_items(dict(items='invalid'))

    def test_daily_quota_survives_worker_restarts_and_resets_in_seoul(self):
        for _ in range(90):self.assertTrue(quota(self.root,NOW))
        self.assertFalse(quota(self.root,NOW))
        self.assertTrue(quota(self.root,NOW+86400))

    def test_monthly_quota_is_a_hard_second_guard(self):
        quota(self.root,NOW)
        data=read_json(self.root/'quota.json');data.update(daily=0,monthly=2700)
        atomic_json(self.root/'quota.json',data)
        self.assertFalse(quota(self.root,NOW))

    def test_arbitrary_url_and_path_cannot_be_queued(self):
        for value in ['../x','https://example.com','005930?url=abc','005930/../']:
            with self.assertRaises(ValueError):self.cache.get(value,'name')

    def test_application_only_exposes_current_holdings(self):
        app=Application(self.root/'auth.db',self.root,self.root/'control.json',[],lambda:True,info_root=self.root/'info')
        app.cache=dict(positions=[dict(code='005930',name='테스트전자')])
        self.assertTrue(app.company('005930')['pending'])
        with self.assertRaises(ValueError):app.company('000001')

    def test_busy_worker_does_not_block_queue_or_account_cache(self):
        app=Application(self.root/'auth.db',self.root,self.root/'control.json',[],lambda:True,info_root=self.root/'info')
        app.cache=dict(positions=[dict(code='005930',name='테스트전자')]);app.cache_at=time.monotonic()
        app.company('005930')
        entered,release=threading.Event(),threading.Event()
        def slow(*args,**kwargs):
            entered.set();release.wait(3);return LISTING
        worker=threading.Thread(target=Worker(self.root/'info',slow).run)
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            started=time.monotonic();app.company('005930');self.assertIs(app.snapshot(),app.cache)
            self.assertLess(time.monotonic()-started,.3)
        finally:
            release.set();worker.join(4)

    def test_worker_unit_limits_resources_and_denies_all_bot_files(self):
        unit=(Path(__file__).resolve().parents[1]/'deploy/kiwoom-company-info.service').read_text()
        for text in ['CPUQuota=10%','MemoryMax=64M','Nice=19','InaccessiblePaths=/opt/bots/kiwoom-stock','NoNewPrivileges=yes']:
            self.assertIn(text,unit)


if __name__=='__main__':unittest.main()
