const statuses = {
  ACTIVE: '매도 감시 중', EARLY_NXT: '기존 트레일 · 손절 감시',
  TRACK_ONLY: '가격 추적만 · 주문 없음', AUCTION_TRACK: '종가 단일가 · 주문 없음',
  NOT_ELIGIBLE: 'NXT 거래 대상 아님', UNAVAILABLE: '감시 불가 · 시세 확인 필요',
  EXIT_ONLY_BID: '호가로 청산 감시 · 최고가 갱신 보류', ORDER_PENDING: '매도 주문·미체결 확인 중',
  ORDER_BLOCKED: '시세 감시 · 매도 주문 보류',
  OFF: '감시 시간 외', CLOSED: '휴장 · 감시 없음', PAUSED: '자동매매 중지',
  SERVICE_UNAVAILABLE: '봇 실행 상태 확인 필요',
};
const reasons = {
  API_ERROR: '시세 API 조회 실패', NO_EXECUTIONS: '해당 시장 체결 응답 없음',
  STALE_EXECUTION: '최근 120초 내 유효 체결 없음', VENUE_MISMATCH: '거래소 응답 불일치',
  INVALID_EXECUTION: '체결가격·시각 검증 실패', SESSION_CHANGED: '시장 전환 중 · 재조회 대기',
  NOT_VERIFIED: '체결 감시 자료 확인 전',
  KRX_AFTER_NOT_VERIFIED: 'KRX 애프터 시세 확인 전',
  ELIGIBILITY_UNKNOWN: 'KRX 애프터 거래 제한 확인 필요', AFTER_RESTRICTED: 'KRX 애프터 거래 제한 종목',
  FRESH_BID_ONLY: '최근 체결 대기 · 유효 매수호가 사용', ORDER_BOOK_UNAVAILABLE: '유효 매수호가 확인 불가',
  BID_CHANGED_RECHECK: '호가 변경 · 조건 재확인 대기',
  ORDER_RETRY_WAIT: '최근 주문 거절 · 재시도 대기',
};

export function monitorSummary(item, {stamp}) {
  const status = item.monitor_status;
  const venue = {KRX_AFTER:'KRX 애프터',KRX_REGULAR:'KRX',NXT_PRE:'NXT 프리',NXT_AFTER:'NXT 애프터'}[item.quote_session];
  const label = `${venue && ['ACTIVE','EXIT_ONLY_BID','ORDER_PENDING'].includes(status) ? venue+' · ' : ''}${statuses[status] || '감시 상태 확인 전'}`;
  const warning = !['ACTIVE', 'EARLY_NXT', 'TRACK_ONLY', 'AUCTION_TRACK'].includes(status);
  const reason = status === 'UNAVAILABLE' ? reasons[item.monitor_reason] || '유효한 체결 시세 없음' : status==='ORDER_BLOCKED' ? reasons[item.order_guard_reason] || '주문 조건 재확인 필요' : '';
  const eligibility = item.nxt_eligible === false && status !== 'NOT_ELIGIBLE' ? (item.price_source==='KRX'&&['ACTIVE','EXIT_ONLY_BID','ORDER_PENDING'].includes(status)?'NXT 미대상 · KRX 시세 확인':'NXT 미대상 · KRX 거래는 별도 확인') : '';
  const details = [reason, eligibility].filter(Boolean).join(' · ');
  return `<div class="monitor-summary ${warning ? 'monitor-warning' : ''}" role="status"><strong>${label}</strong>${details ? `<span>${details}</span>` : ''}<small>마지막 유효 시세 ${stamp(item.last_valid_quote_at, true)}${item.quote_basis === 'BID_ONLY' ? ` · 매수호가 ${stamp(item.last_valid_bid_at)}` : item.last_valid_trade_at ? ` · 체결 ${stamp(item.last_valid_trade_at)}` : ''}</small></div>`;
}
