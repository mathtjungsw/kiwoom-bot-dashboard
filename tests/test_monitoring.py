import datetime as dt
import unittest
from backend.reader import monitoring, KST


class MonitoringTests(unittest.TestCase):
    def saved(self, now):
        return dict(quote_status='VALID',quote_reason='OK',price_source='KRX',
                    last_update=now.isoformat(),last_valid_quote_at=now.isoformat(),
                    last_valid_trade_at=now.isoformat())

    def test_last_update_never_masquerades_as_valid_quote_time(self):
        now=dt.datetime(2026,10,19,10,tzinfo=KST)
        s=self.saved(now)
        s.pop('last_valid_quote_at');s.pop('last_valid_trade_at')
        result=monitoring(now,s,'KRX',True,False,None)
        self.assertIsNone(result['last_valid_quote_at'])
        self.assertEqual(result['monitor_status'],'UNAVAILABLE')

    def test_stale_quote_not_revived_by_reconciliation(self):
        now=dt.datetime(2026,10,19,10,tzinfo=KST)
        s=self.saved(now-dt.timedelta(minutes=5));s['last_update']=now.isoformat()
        result=monitoring(now,s,'KRX',True,False,None)
        self.assertEqual(result['monitor_status'],'UNAVAILABLE')
        self.assertEqual(result['monitor_reason'],'STALE_EXECUTION')

    def test_eligibility_and_api_failure_remain_distinct(self):
        now=dt.datetime(2026,10,19,8,20,tzinfo=KST)
        s=dict(nxt_eligible=False,quote_reason='NOT_ELIGIBLE')
        self.assertEqual(monitoring(now,s,'NXT',True,False,None)['monitor_status'],'NOT_ELIGIBLE')
        s=dict(nxt_eligible=None,quote_reason='API_ERROR')
        result=monitoring(now,s,'NXT',True,False,None)
        self.assertEqual(result['monitor_status'],'UNAVAILABLE')
        self.assertEqual(result['monitor_reason'],'API_ERROR')

    def test_auction_closed_off_pause_and_active(self):
        for hour,minute,expected in [(8,0,'TRACK_ONLY'),(8,5,'EARLY_NXT'),(8,10,'ACTIVE'),
                                    (8,50,'OFF'),(10,0,'ACTIVE'),(15,20,'AUCTION_TRACK'),
                                    (15,30,'OFF'),(20,0,'OFF')]:
            now=dt.datetime(2026,10,19,hour,minute,tzinfo=KST)
            s=self.saved(now);s['price_source']='KRX' if 540<=hour*60+minute<930 else 'NXT'
            self.assertEqual(monitoring(now,s,s['price_source'],True,False,None)['monitor_status'],expected)
        self.assertEqual(monitoring(now,s,'NXT',True,True,None)['monitor_status'],'PAUSED')
        self.assertEqual(monitoring(now,s,'NXT',False,False,None)['monitor_status'],'SERVICE_UNAVAILABLE')
        self.assertEqual(monitoring(now,s,'NXT',True,False,'2026-10-19')['monitor_status'],'CLOSED')

    def test_nxt_ineligible_does_not_block_krx_after_monitoring(self):
        now=dt.datetime(2026,10,19,16,5,tzinfo=KST)
        s=self.saved(now);s.update(nxt_eligible=False,quote_session='KRX_AFTER')
        result=monitoring(now,s,'NXT',True,False,None)
        self.assertEqual(result['monitor_status'],'ACTIVE')
        self.assertEqual(result['quote_session'],'KRX_AFTER')

    def test_fresh_bid_supports_exit_only_even_without_recent_trade(self):
        now=dt.datetime(2026,10,19,16,5,tzinfo=KST)
        s=self.saved(now);s.update(quote_basis='BID_ONLY',last_valid_bid_at=now.isoformat(),
                                 last_valid_trade_at=(now-dt.timedelta(minutes=10)).isoformat())
        self.assertEqual(monitoring(now,s,'NXT',True,False,None)['monitor_status'],'EXIT_ONLY_BID')
        s['last_valid_bid_at']=(now-dt.timedelta(seconds=31)).isoformat()
        self.assertEqual(monitoring(now,s,'NXT',True,False,None)['monitor_status'],'UNAVAILABLE')

    def test_pending_order_and_unknown_eligibility_are_not_claimed_as_normal_monitoring(self):
        now=dt.datetime(2026,10,19,16,5,tzinfo=KST)
        s=self.saved(now);s['bot_sell_pending']={'market':'KRX','qty':1}
        self.assertEqual(monitoring(now,s,'NXT',True,False,None)['monitor_status'],'ORDER_PENDING')
        s.update(quote_status='UNAVAILABLE',quote_reason='ELIGIBILITY_UNKNOWN')
        result=monitoring(now,s,'NXT',True,False,None)
        self.assertEqual(result['monitor_status'],'UNAVAILABLE')
        self.assertEqual(result['monitor_reason'],'ELIGIBILITY_UNKNOWN')

    def test_before_1600_krx_after_is_not_claimed_active(self):
        now=dt.datetime(2026,10,19,15,50,tzinfo=KST)
        s=self.saved(now);s.update(nxt_eligible=False,quote_session='KRX_REGULAR')
        self.assertEqual(monitoring(now,s,'NXT',True,False,None)['monitor_status'],'NOT_ELIGIBLE')

    def test_missing_executable_book_is_not_presented_as_normal_sell_monitoring(self):
        now=dt.datetime(2026,10,19,16,5,tzinfo=KST)
        s=self.saved(now);s['order_guard_reason']='ORDER_BOOK_UNAVAILABLE'
        self.assertEqual(monitoring(now,s,'NXT',True,False,None)['monitor_status'],'ORDER_BLOCKED')

    def test_venue_specific_order_rejection_is_visible_without_blocking_other_venue(self):
        now=dt.datetime(2026,10,19,16,5,tzinfo=KST)
        s=self.saved(now);s.update(sell_retry_after=(now+dt.timedelta(minutes=10)).isoformat(),last_sell_error={'market':'KRX'})
        self.assertEqual(monitoring(now,s,'NXT',True,False,None)['monitor_status'],'ORDER_BLOCKED')
        s['last_sell_error']['market']='NXT'
        self.assertEqual(monitoring(now,s,'NXT',True,False,None)['monitor_status'],'ACTIVE')


if __name__=='__main__':unittest.main()
