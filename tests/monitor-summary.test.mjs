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
