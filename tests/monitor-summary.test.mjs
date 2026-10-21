import test from 'node:test';
import assert from 'node:assert/strict';
import {monitorSummary} from '../docs/monitor-summary.js';
const fmt={stamp:value=>value?'10:20':'—'};

test('stored trailing stage never implies live monitoring',()=>{
  const html=monitorSummary({stage:'트레일중',monitor_status:'NOT_ELIGIBLE',nxt_eligible:false},fmt);
  assert.ok(html.includes('NXT 거래 대상 아님'));
  assert.ok(!html.includes('매도 감시 중'));
  assert.ok(html.includes('마지막 유효 시세 —'));
});
test('API failure is not called ineligibility',()=>{
  const html=monitorSummary({monitor_status:'UNAVAILABLE',monitor_reason:'API_ERROR'},fmt);
  assert.ok(html.includes('시세 API 조회 실패'));
  assert.ok(!html.includes('NXT 거래 대상 아님'));
});
test('auction is clearly no-orders and timestamps are separate',()=>{
  const html=monitorSummary({monitor_status:'AUCTION_TRACK',last_valid_quote_at:'a',last_valid_trade_at:'b'},fmt);
  assert.ok(html.includes('종가 단일가 · 주문 없음'));
  assert.ok(html.includes('마지막 유효 시세 10:20 · 체결 10:20'));
});
test('untrusted server reason cannot inject markup',()=>{
  assert.ok(!monitorSummary({monitor_status:'<script>',monitor_reason:'<script>'},fmt).includes('<script>'));
});
test('KRX after remains active for an NXT-ineligible stock',()=>{
  const html=monitorSummary({monitor_status:'ACTIVE',quote_session:'KRX_AFTER',price_source:'KRX',nxt_eligible:false},fmt);
  assert.ok(html.includes('KRX 애프터 · 매도 감시 중'));
  assert.ok(!html.includes('감시 불가'));
});
test('bid-only quotes explicitly wait for execution and show book time',()=>{
  const html=monitorSummary({monitor_status:'EXIT_ONLY_BID',quote_session:'KRX_AFTER',quote_basis:'BID_ONLY',last_valid_bid_at:'a'},fmt);
  assert.ok(html.includes('체결 확인 대기'));
  assert.ok(html.includes('매수호가 10:20'));
});
test('accepted or unverified orders are not presented as fills',()=>{
  const html=monitorSummary({monitor_status:'ORDER_PENDING',quote_session:'KRX_AFTER'},fmt);
  assert.ok(html.includes('매도 주문·미체결 확인 중'));
});
test('price monitoring does not hide a sell preflight block',()=>{
  const html=monitorSummary({monitor_status:'ORDER_BLOCKED',order_guard_reason:'ORDER_BOOK_UNAVAILABLE'},fmt);
  assert.ok(html.includes('매도 주문 보류'));
  assert.ok(html.includes('유효 매수호가 확인 불가'));
});
