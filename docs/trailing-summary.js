export function returnFromEntry(price, entry) {
  return Number.isFinite(price) && price > 0 && Number.isFinite(entry) && entry > 0
    ? (price / entry - 1) * 100 : null;
}

export function trailingSummary(item, {pct, tone}) {
  if (!['트레일중', '트레일완충'].includes(item.stage)) return '';
  const peak = returnFromEntry(item.peak_price, item.entry);
  const stop = returnFromEntry(item.stop_price, item.entry);
  return `<div class="trailing-rates" aria-label="트레일링 수익률 기준">
    <div title="봇이 확인해 저장한 최고가 기준입니다. 거래소 당일 최고가나 대체가격과 다를 수 있습니다."><span>봇 확인 최고</span><strong class="${tone(peak)}">${pct(peak)}</strong></div>
    <div title="저장된 스톱가의 평단 대비 수익률입니다. 실제 매도 체결 수익률은 달라질 수 있습니다."><span>매도 감시 기준</span><strong class="${tone(stop)}">${pct(stop)}</strong></div>
  </div>`;
}
