import test from 'node:test';
import assert from 'node:assert/strict';
import {accountSummary} from '../docs/account-summary.js';
const fmt={money:v=>Number.isFinite(v)?String(v):'—',signed:v=>Number.isFinite(v)?`${v>0?'+':''}${v}원`:'—',pct:v=>Number.isFinite(v)?`${v}%`:'—',tone:v=>v<0?'loss':v>0?'profit':''};
const data={account:{equity:20000,deposit:8000,pnl:600,return_pct:5,purchase_amount:12000,valuation_amount:12600},capital:{configured:true,initial_capital:25000,net_external_flows:0,net_contributions:25000,pnl:-5000,return_pct:-20},positions:[{qty:2,entry:1000,price:1050}],source:{max_stocks:5}};
test('shows cumulative and open-position metrics separately',()=>{const html=accountSummary(data,fmt);for(const label of ['총 투입금','누적손익','누적수익률','추정자산','총매입','총평가','보유 평가손익','보유 수익률','주문가능현금','보유종목'])assert.ok(html.includes(label));assert.ok(html.includes('-20%'));assert.ok(html.includes('5%'));});
test('missing configuration is explicit, not fabricated',()=>{const html=accountSummary({...data,capital:undefined},fmt);assert.ok(html.includes('설정 대기'));assert.ok(!html.includes('-20%'));});
test('missing prices keep unknown valuation unknown',()=>{const html=accountSummary({...data,account:{...data.account,valuation_amount:null}},fmt);assert.ok(html.includes('—<small>원</small>'));});
test('extra flows are disclosed when present',()=>{const html=accountSummary({...data,capital:{...data.capital,net_external_flows:1000}},fmt);assert.ok(html.includes('최초 투입금'));assert.ok(html.includes('추가 순입출금 +1000원'));});
