const finite = Number.isFinite;
function sumHoldings(positions, field) {
  return positions.every(p => finite(p[field]) && finite(p.qty))
    ? positions.reduce((sum, p) => sum + p[field] * p.qty, 0) : null;
}

export function accountSummary(data, {money, signed, pct, tone}) {
  const {account:a, capital:c = {}} = data;
  const purchase = a.purchase_amount === undefined ? sumHoldings(data.positions, 'entry') : a.purchase_amount;
  const valuation = a.valuation_amount === undefined ? sumHoldings(data.positions, 'price') : a.valuation_amount;
  const ready = c.configured === true;
  const amount = value => `${money(value)}<small>원</small>`;
  const metric = (label, value, color='') => `<div><span>${label}</span><strong class="${color}">${value}</strong></div>`;
  const flows = ready && c.net_external_flows !== 0
    ? `<p class="capital-flows">최초 투입금 ${money(c.initial_capital)}원 · 추가 순입출금 ${signed(c.net_external_flows)}</p>` : '';
  return `<section class="capital-section" aria-label="투입금 대비 누적 성과">
    <div class="section-heading"><h2>투자 성과</h2><span>계좌 전체 · 누적</span></div>
    <div class="summary capital-summary">
      ${metric('총 투입금<span class="metric-hint">(순입금)</span>', ready ? amount(c.net_contributions) : '설정 대기')}
      ${metric('누적손익', ready ? signed(c.pnl) : '—', tone(c.pnl))}
      ${metric('누적수익률', ready ? pct(c.return_pct) : '—', tone(c.return_pct))}
      ${metric('추정자산', amount(a.equity))}
    </div>${flows}
    <p class="capital-basis">추정자산 − 총 투입금 = 누적손익${ready ? '' : ' · 서버 투입금 설정 대기'}</p>
  </section>
  <section class="summary holdings-summary" aria-label="현재 보유분 요약">
    ${metric('총매입<span class="metric-hint">(보유분)</span>', amount(purchase))}
    ${metric('총평가<span class="metric-hint">(보유분)</span>', amount(valuation))}
    ${metric('보유 평가손익', signed(a.pnl), tone(a.pnl))}
    ${metric('보유 수익률', pct(a.return_pct), tone(a.return_pct))}
  </section>
  <div class="account-rail"><span>주문가능현금 <b>${money(a.deposit)}원</b></span><span>보유종목 <b>${data.positions.length} / ${data.source.max_stocks}</b></span></div>`;
}
