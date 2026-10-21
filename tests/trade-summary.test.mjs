import test from 'node:test';
import assert from 'node:assert/strict';
import {tradeSummary} from '../docs/trade-summary.js';
const h={money:v=>String(v),signed:v=>v==null?'—':String(v),pct:v=>v==null?'—':String(v),tone:()=>'',stamp:v=>v,esc:v=>String(v).replaceAll('<','&lt;'),icon:()=>'',reasons:{STOP_LOSS:'손절'}};
const item={side:'SELL',name:'테스트 종목',ts:'10/21',reason:'STOP_LOSS',qty:10,requested_qty:10,price:1020,pnl:200,return_pct:2,basis:'FILL_CONFIRMED',execution_status:'FILLED',corrected:true};
test('confirmed sale uses actual execution label and correction',()=>{const s=tradeSummary(item,h);assert.match(s,/실제 평균 체결가/);assert.match(s,/1020원/);assert.match(s,/매도 완료/);assert.match(s,/정정된 기록/);});
test('pending order shows no invented price or pnl',()=>{const s=tradeSummary({...item,qty:0,price:null,pnl:null,return_pct:null,basis:'ORDER_PENDING',execution_status:'OPEN'},h);assert.match(s,/매도 주문 중/);assert.match(s,/확인 대기/);assert.match(s,/0 \/ 10주/);assert.doesNotMatch(s,/실제 평균 체결가/);});
test('partial execution names only confirmed quantity',()=>{const s=tradeSummary({...item,qty:4,execution_status:'PARTIAL'},h);assert.match(s,/부분체결/);assert.match(s,/4 \/ 10주/);assert.match(s,/확인된 체결 수량 기준/);});
test('stock names remain escaped',()=>assert.match(tradeSummary({...item,name:'<img>'},h),/&lt;img>/));
