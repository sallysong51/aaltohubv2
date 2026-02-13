# Phase 34: Telethon Session Stability Enhancement

## 목표
장시간 운영 시 텔레그램 크롤링 안정성 개선 — 세션 끊김, 재연결, 메시지 누락 방지

## 개선사항

### 1. `catch_up=True` 추가 (최우선 개선)
**문제점:**
- Telethon 클라이언트가 재연결 시 오프라인 중 발생한 이벤트를 수신하지 못함
- 네트워크 단절 → 재연결 사이에 메시지 누락 발생

**해결:**
```python
client = TelegramClient(
    ...
    catch_up=True,  # ★ 재연결 시 놓친 이벤트 수신
)
```

**영향:**
- 재연결 시 텔레그램 서버가 오프라인 중 발생한 업데이트를 자동 전송
- 단기 네트워크 장애 시에도 메시지 누락 없음
- Gap-fill 의존도 감소 (보조 안전망으로 역할 변경)

### 2. 연결 안정성 파라미터 강화
**변경사항:**
```python
# Before
connection_retries=5
request_retries=3
retry_delay=3
flood_sleep_threshold=300

# After
connection_retries=10      # 재연결 시도 증가
request_retries=5          # API 요청 재시도 증가
retry_delay=2              # 더 빠른 재연결
flood_sleep_threshold=60   # 합리적인 자동 대기 (5분 → 1분)
```

**근거:**
- `connection_retries=10`: 일시적 네트워크 장애 시 충분한 재시도 기회
- `request_retries=5`: 텔레그램 API 일시적 오류 대응
- `retry_delay=2s`: 3초는 불필요하게 김, 2초로 단축
- `flood_sleep_threshold=60s`: 300초(5분)는 너무 김, 60초가 적당
  - 60초 이하 FloodWait는 자동 대기
  - 60초 초과는 FloodWaitError 발생 → 로그 + penalty 시스템 처리

### 3. 클라이언트 식별 정보 추가
```python
device_model="AaltoHub Server",
system_version="Ubuntu 24.04",
app_version="2.0.0",
```

**효과:**
- 텔레그램 서버에서 세션 식별 용이
- 다중 세션 사용 시 어느 서버인지 구분 가능
- 디버깅 시 유용

### 4. 연결 상태 모니터링 강화
**새로운 메서드:** `_connection_health_check()`

**동작:**
1. 30초마다 모든 클라이언트의 실제 연결 상태 확인
2. `client.is_connected()` 체크 (TCP 연결 상태)
3. `client.get_me()` 호출로 Auth 유효성 검증
4. 끊김 감지 시 자동 재연결 시도 (10s timeout)
5. Auth 문제 감지 시 Sentry 알림 (세션 만료, 계정 비활성화 등)

**기존 `_listener_watchdog`와의 차이:**
- `_listener_watchdog`: asyncio Task 레벨 체크 (60초 간격)
- `_connection_health_check`: Telethon TCP 연결 레벨 체크 (30초 간격)
- 두 메커니즘 모두 필요 (레이어가 다름)

**Sentry 알림 케이스:**
- Auth 실패 (세션 만료, unauthorized)
- get_me() 반환 None (드물지만 발생 가능)
- 재연결 타임아웃 (10초 초과)

## 파일 변경

### 1. `backend/app/live_crawler.py`
**TelegramClient 생성 (2곳):**
- Line 319-330: telegram_connections 기반 클라이언트
- Line 383-394: telethon_sessions fallback 클라이언트

**변경:**
```python
# 파라미터 추가/수정
request_retries=5,           # 3 → 5
connection_retries=10,       # 5 → 10
retry_delay=2,               # 3 → 2
flood_sleep_threshold=60,    # 300 → 60
catch_up=True,               # NEW
device_model="AaltoHub Server",
system_version="Ubuntu 24.04",
app_version="2.0.0",
```

**새 메서드 추가:**
- `_connection_health_check()` (Line ~2760)
  - 30초마다 연결 상태 + Auth 검증
  - 자동 재연결 + Sentry 알림

**멤버 변수 추가:**
- `self._connection_health_task: asyncio.Task | None = None` (Line 168)

**Task 시작/취소:**
- `start()`: Line 489 — task 시작
- `stop()`: Line 520 — task 취소

## 테스트 계획

### 수동 테스트 (1-3일 모니터링)

#### 1. 재연결 시 catch_up 동작 확인
**시나리오:**
1. 크롤러 실행 중 네트워크 일시 차단 (방화벽 규칙 or 서버 재시작)
2. 차단 중 텔레그램 그룹에 메시지 전송
3. 네트워크 복구
4. 로그에서 `catch_up=True`로 인한 메시지 재수신 확인

**예상 로그:**
```
[HEALTH] Client user_id=XXX disconnected, reconnecting...
[HEALTH] Client user_id=XXX reconnected
[NewMessage] Received message (catch_up): group=YYY, msg_id=ZZZ
```

**검증:**
- DB에 차단 중 전송된 메시지가 모두 저장되었는지 확인
- Gap-fill 없이도 메시지 수집되었는지 확인

#### 2. FloodWait 자동 대기 확인
**시나리오:**
1. 의도적으로 API 호출 빈도를 높여 FloodWaitError 유도
2. 60초 이하 FloodWait → 자동 대기 확인
3. 60초 초과 FloodWait → FloodWaitError 발생 + penalty 시스템 동작 확인

**예상 동작:**
- 30초 FloodWait → 자동 대기 후 재시도 (로그 없음)
- 120초 FloodWait → FloodWaitError 발생 → `_flood_wait_until` 업데이트

#### 3. 연결 상태 모니터링 동작 확인
**시나리오:**
1. 크롤러 실행 중 로그 모니터링
2. 30초마다 health check 실행 확인
3. 의도적으로 클라이언트 연결 끊기 (kill -STOP PID)
4. Health check가 끊김 감지 및 재연결 시도 확인

**예상 로그:**
```
[HEALTH] Client user_id=XXX disconnected, reconnecting...
[HEALTH] Client user_id=XXX reconnect timeout
[WATCHDOG] 1/1 listeners dead (CRITICAL). Restarting: [XXX]
```

#### 4. Auth 실패 Sentry 알림 확인
**시나리오:**
1. 텔레그램 앱에서 세션 강제 종료 (Settings → Devices → Terminate)
2. Health check가 Auth 실패 감지
3. Sentry에 알림 전송 확인

**예상 Sentry 이벤트:**
```
Message: "Telegram auth lost for user_id=XXX"
Level: error
Extras: {"user_id": XXX}
```

### 자동 모니터링 (Grafana Dashboard)

#### 추가 메트릭 (향후 Phase 35)
1. **연결 상태:**
   - `telethon_clients_connected` (gauge)
   - `telethon_reconnect_attempts_total` (counter)
   - `telethon_auth_failures_total` (counter)

2. **Catch-up 효과:**
   - `messages_received_via_catchup_total` (counter)
   - `gap_fill_runs_total` (counter) — catch_up 도입 후 감소 예상

3. **FloodWait:**
   - `floodwait_auto_sleep_total` (counter, ≤60s)
   - `floodwait_penalty_total` (counter, >60s)

## 예상 효과

### 정량적 개선
1. **메시지 누락률 감소:**
   - Before: 재연결 시 최대 15분 메시지 누락 (gap-fill 간격)
   - After: catch_up로 즉시 재수신 → 누락 거의 0

2. **Gap-fill 빈도 감소:**
   - Before: 메시지 누락 복구용으로 매 15분 실행 필수
   - After: 보조 안전망으로만 사용 (주 역할은 catch_up)

3. **재연결 성공률 증가:**
   - Before: connection_retries=5 → 5번 실패 시 포기
   - After: connection_retries=10 → 일시적 장애 시 복구 확률 2배

### 정성적 개선
1. **운영 안정성:**
   - NAT 타임아웃, 일시적 네트워크 장애 시에도 메시지 수집 지속
   - Health check가 조용한 연결 끊김 사전 감지

2. **디버깅 편의성:**
   - Sentry 알림으로 Auth 문제 즉시 인지
   - 세션 만료 시 사용자 재로그인 유도 가능

3. **FloodWait 대응:**
   - 60초 이하는 자동 대기 (로그 노이즈 감소)
   - 60초 초과는 명시적 처리 (penalty 시스템)

## 알려진 제약사항

1. **catch_up 한계:**
   - 오프라인 시간이 매우 길면 (24시간+) 텔레그램 서버가 일부 이벤트 삭제 가능
   - 이 경우에도 gap-fill이 백업 역할 수행

2. **FloodWait 자동 대기:**
   - 60초 이하만 자동 대기
   - 60초 초과 시 FloodWaitError 발생 → penalty 시스템으로 그룹 스킵
   - 일부 고빈도 그룹은 여전히 수집 지연 가능

3. **Auth 실패:**
   - Health check가 감지하지만 자동 복구 불가
   - 사용자 재로그인 필요 (현재는 Sentry 알림만)

## 향후 개선 (Phase 35 이후)

1. **Prometheus 메트릭 추가:**
   - 연결 상태, catch_up 효과, FloodWait 통계
   - Grafana 대시보드 구축

2. **Auth 실패 시 자동 이메일 알림:**
   - Sentry 알림 → 이메일 전송 자동화
   - 사용자에게 재로그인 안내

3. **FloodWait 동적 조정:**
   - 그룹별 FloodWait 패턴 학습
   - API 호출 빈도 자동 조절

4. **StringSession 완전 전환:**
   - 파일 기반 세션 제거 (이미 StringSession 사용 중이지만 명시적 전환)
   - 다중 프로세스 환경에서 세션 충돌 방지

## Commit Message
```
feat: Enhance Telethon session stability (Phase 34)

- Add catch_up=True to prevent message loss on reconnect
- Increase connection_retries (5→10) and request_retries (3→5)
- Reduce flood_sleep_threshold (300s→60s) for better FloodWait handling
- Add _connection_health_check() for 30s TCP + Auth validation
- Add device_model/system_version/app_version for session identification

Impact:
- Message loss prevention during network interruptions
- Faster reconnection with more retry attempts
- Proactive auth failure detection via Sentry alerts
```

## 참고 문서
- Telethon Docs: https://docs.telethon.dev/en/stable/concepts/updates.html#catching-up
- Phase 32A: Error Recovery & Resilience Enhancement
- Phase 26: Ultra-Thorough Crawling Pipeline Audit
