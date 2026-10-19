import {fixture as baseFixture} from './demo.js';
export function fixture() {
  const data=baseFixture();
  const initial=Math.round(data.account.equity/0.8/100)*100;
  const pnl=data.account.equity-initial;
  data.capital={configured:true,initial_capital:initial,net_external_flows:0,net_contributions:initial,pnl,return_pct:pnl/initial*100,basis:'SIMPLE_NET_CONTRIBUTIONS'};
  data.account.purchase_amount=data.positions.reduce((sum,p)=>sum+p.entry*p.qty,0);
  data.account.valuation_amount=data.positions.reduce((sum,p)=>sum+p.price*p.qty,0);
  data.positions.forEach((p,index)=>{
    p.monitor_status=index===0?'NOT_ELIGIBLE':index===2?'UNAVAILABLE':'ACTIVE';
    p.monitor_reason=index===0?'NOT_ELIGIBLE':index===2?'API_ERROR':'OK';
    p.nxt_eligible=index!==0;
    p.last_valid_quote_at=index===0?null:p.observed_at;
    p.last_valid_trade_at=index===0?null:p.observed_at;
  });
  return data;
}
