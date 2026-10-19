import test from 'node:test';
import assert from 'node:assert/strict';
import {returnFromEntry,trailingSummary} from '../docs/trailing-summary.js';
const fmt={pct:v=>v==null?'—':`${v.toFixed(2)}%`,tone:v=>v>0?'profit':v<0?'loss':''};
test('uses actual stored prices rather than re-creating a 1% stop',()=>{const html=trailingSummary({stage:'트레일중',entry:100,peak_price:105,stop_price:104.5},fmt);assert.ok(html.includes('5.00%'));assert.ok(html.includes('4.50%'));assert.ok(html.includes('매도 감시 기준'));assert.ok(html.includes('실제 매도 체결 수익률은 달라질 수 있습니다'));});
test('waiting positions do not invent trailing results',()=>assert.equal(trailingSummary({stage:'대기',entry:100,peak_price:0,stop_price:90},fmt),''));
test('buffer stage uses its saved actual stop',()=>assert.ok(trailingSummary({stage:'트레일완충',entry:100,peak_price:103,stop_price:101},fmt).includes('1.00%')));
test('missing and invalid values are unknown, not negative 100%',()=>{for(const price of [null,undefined,0,NaN,Infinity])assert.equal(returnFromEntry(price,100),null);assert.equal(returnFromEntry(105,0),null);assert.ok(trailingSummary({stage:'트레일중',entry:100,peak_price:null,stop_price:null},fmt).includes('—'));});
test('negative stop return is represented honestly',()=>assert.ok(trailingSummary({stage:'트레일중',entry:100,peak_price:103,stop_price:99},fmt).includes('-1.00%')));
