const statuses = {
  ACTIVE: '매도 감시 중', EARLY_NXT: '기존 트레일 · 손절 감시',
  TRACK_ONLY: '가격 추적만 · 주문 없음', AUCTION_TRACK: '종가 단일가 · 주문 없음',
  NOT_ELIGIBLE: 'NXT 거래 대상 아님', UNAVAILABLE: '감시 불가 · 시세 확인 필요',
  OFF: '감시 시간 외', CLOSED: '휴장 · 감시 없음', PAUSED: '자동매매 중지',
  SERVICE_UNAVAILABLE: '봇 실행 상태 확인 필요',
};
const reasons = {
  API_ERROR: '시세 API 조회 실패', NO_EXECUTIONS: '해당 시장 체결 응답 없음',
  STALE_EXECUTION: '최근 120초 내 유효 체결 없음', VENUE_MISMATCH: '거래소 응답 불일치',
  INVALID_EXECUTION: '체결가격·시각 검증 실패', SESSION_CHANGED: '시장 전환 중 · 재조회 대기',
  NOT_VERIFIED: '체결 감시 자료 확인 전',
};

export function monitorSummary(item, {stamp}) {
  const status = item.monitor_status;
  const label = statuses[status] || '감시 상태 확인 전';
  const warning = !['ACTIVE', 'EARLY_NXT', 'TRACK_ONLY', 'AUCTION_TRACK'].includes(status);
  const reason = status === 'UNAVAILABLE' ? reasons[item.monitor_reason] || '유효한 체결 시세 없음' : '';
  const eligibility = item.nxt_eligible === false && status !== 'NOT_ELIGIBLE' ? 'NXT 거래 대상 아님' : '';
  const details = [reason, eligibility].filter(Boolean).join(' · ');
  return `<div class="monitor-summary ${warning ? 'monitor-warning' : ''}" role="status"><strong>${label}</strong>${details ? `<span>${details}</span>` : ''}<small>마지막 유효 시세 ${stamp(item.last_valid_quote_at, true)}${item.last_valid_trade_at ? ` · 체결 ${stamp(item.last_valid_trade_at)}` : ''}</small></div>`;
}
