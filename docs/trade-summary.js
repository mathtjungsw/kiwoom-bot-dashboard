const statuses = {
  SUBMITTING: '주문 응답 확인 중', OPEN: '매도 주문 중', PARTIAL: '부분체결',
  CANCEL_REQUESTED: '잔량 취소 확인 중', CANCELLED: '잔량 취소 완료',
  FILLED: '매도 완료', UNCONFIRMED: '체결 확인 필요', REJECTED: '주문 거절',
};

export function tradeSummary(item, {money, signed, pct, tone, stamp, esc, icon, reasons}) {
  const sell = item.side === 'SELL';
  const tracked = !!item.execution_status;
  const confirmed = item.basis === 'FILL_CONFIRMED';
  const status = statuses[item.execution_status] || (confirmed ? '체결 확인' : '추정 / 미확인');
  const basis = confirmed ? '체결가 확인 · 비용 차감 전' : item.basis === 'REFERENCE_ESTIMATE' ? '주문 판단가 기준 추정' : tracked ? '체결 확인 대기' : '기록 기준 · 체결 미확인';
  return `<details class="trade-item"><summary class="trade-row"><span class="trade-name"><time>${stamp(item.ts,true)}</time><strong>${esc(item.name)}</strong></span><span class="trade-reason"><span class="${sell?'sell-type':'buy-type'}">${sell?'매도':'매수'}</span><small>${esc(reasons[item.reason]||item.reason)}</small></span><span class="trade-pnl ${tone(item.pnl)}"><strong>${sell?signed(item.pnl):'—'}</strong><small>${sell?pct(item.return_pct):''}</small>${sell?`<em>${status}</em>`:''}</span>${icon('chevron-down')}</summary><div class="trade-detail"><span>${tracked?'체결 / 주문':'수량'} <b>${money(item.qty)}${tracked&&item.requested_qty!==undefined?' / '+money(item.requested_qty):''}주</b></span><span>${confirmed?'실제 평균 체결가':'기록 가격'} <b>${item.price==null?'확인 대기':money(item.price)+'원'}</b></span><span>손익 기준 <b>${basis}</b></span>${tracked&&item.execution_status!=='FILLED'?'<p>표시 손익은 확인된 체결 수량 기준입니다.</p>':''}${item.corrected?'<p>증권사 체결내역 확인 후 정정된 기록입니다.</p>':''}${item.manual?'<p>직접 매도 손익은 전액 표시합니다. 자동매매 성과 귀속 60%는 종합 분석에서만 적용합니다.</p>':''}</div></details>`;
}
