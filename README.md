# 자동매매 현황

HTML/CSS/JavaScript + AWS Python 표준 라이브러리 API. ChatGPT 계정이나 Sites에 종속되지 않습니다.
GitHub Pages에는 `docs/`의 화면 코드만 공개하며 금융 데이터·계좌번호·API 키·비밀번호는 포함하지 않습니다.

## 운영

- 프런트엔드: `https://mathtjungsw.github.io/kiwoom-bot-dashboard/`
- API: 기존 AWS HTTPS 호스트의 `/bot-api/` 경로 → 별도 loopback `127.0.0.1:8880`.
- 기존 수기 기록장의 `/api/`와 파일은 수정하지 않습니다. Caddy에 별도 경로만 추가합니다.
- 서비스 `kiwoom-dashboard`, 코드 `/opt/kiwoom-dashboard`.
- 인증 DB `/var/lib/kiwoom-dashboard/auth.db`. 비밀번호 scrypt 해시, 세션 SHA-256 해시만 저장.
- 세션은 로그인 시점부터 정확히 7일. 재시작으로 만료가 연장되지 않으며 로그아웃/비밀번호 변경 시 즉시 무효화.
- 기기 로그인 유지를 위해 불투명 토큰을 localStorage에 저장. 공용 기기 사용 후 로그아웃.
- 외부 스크립트·분석 추적·CDN 의존성 없음. CSP 적용. 허용된 Origin과 인증 토큰을 모두 확인.
- 비밀번호 설정: 서버에서 `sudo -u ubuntu /opt/bots/kiwoom-stock/.venv/bin/python3 -m backend.server password` (작업 디렉터리 `/opt/kiwoom-dashboard`). 화면에 표시되지 않는 입력을 본인이 수행합니다. 재설정 시 기존 세션 모두 폐기.

## 데이터와 제어

봇 JSON 및 `mode=ro` SQLite만 읽으며 키움 API를 호출하지 않습니다. 계좌 샘플의 보유 종목을 모두 표시하고 상태가 불일치하면 트레일 값을 보류합니다.
시세의 출처, 봇 관측 시각, 지연, 추정/미확인 손익을 구분합니다. 체결 확인 없는 주문 로그를 확정 수익으로 표시하지 않습니다.
계좌 총자산/예수금은 계좌 샘플 시점 값, 평가손익은 표시된 관측 가격 기준의 비용 차감 전 값입니다.
화면은 5초, 서버 캐시는 2초, 무거운 거래/전략 집계는 60초 캐시. 기존 DB를 웹용으로 복제하거나 별도 시세 요청을 늘리지 않습니다.
분석은 네 전략이 모두 종료한 동일 진입만 비교하고 신규 진입/기존 보유를 분리합니다. 직접 매도 60%는 종합 보고 귀속 기준이며 원본 손익을 변조하지 않습니다.

중지 버튼은 `/var/lib/kiwoom-dashboard-control/command.json`에 원자적으로 요청만 기록합니다. 봇이 읽어 저장한 확인 ID와 일치해야 중지 확인을 표시합니다.
중지 시 매수와 매도 감시 모두 멈추며 기존 주문은 취소되지 않습니다. 재개 버튼/매매 주문 API는 없습니다.
재개는 서버 관리자가 로컬 제어 JSON을 `{"id":"local-admin-resume","paused":false}`로 원자적 교체해야 합니다.
제어 파일이 없거나 손상되면 봇은 안전상 중지합니다. 웹 API 중단만으로 기존 제어 상태를 변경하지 않습니다.
구글시트는 조회·기록·제어 호출을 모두 해제하되 서버 분석 로그와 거래 outbox 기록은 계속 유지합니다.

## 수정과 테스트

`docs/` 변경을 main에 push하면 GitHub Pages에서 반영됩니다. 다른 GitHub 계정은 저장소 협업 권한 또는 fork/PR로 수정할 수 있습니다.
서버 코드 변경은 검증 후 별도 반영이 필요합니다. GitHub에 서버 설정/인증 DB/원본 거래 DB를 올리지 마세요.

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile backend/server.py backend/reader.py
node --check docs/app.js
python3 -m http.server 8766 --bind 127.0.0.1 --directory docs
```

로컬 `http://127.0.0.1:8766/?demo`에서 합성 예시를 확인할 수 있습니다. 운영 도메인에서는 demo 모드가 동작하지 않습니다.
정적 아이콘은 Lucide 라이브러리에서 생성하고 라이선스를 포함합니다.
서버/봇 변경 전 백업, 문법검사, 제한된 단위테스트, 서비스 및 HTTPS 확인을 수행합니다. 실패하면 이전 코드/프록시 설정으로 복구합니다.
