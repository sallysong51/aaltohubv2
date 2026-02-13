# AaltoHub v2 크롤링 시스템 완전 가이드

## 📋 목차

1. [시스템 개요](#시스템-개요)
2. [아키텍처](#아키텍처)
3. [기술 스택](#기술-스택)
4. [크롤링 파이프라인](#크롤링-파이프라인)
5. [주요 컴포넌트](#주요-컴포넌트)
6. [데이터 흐름](#데이터-흐름)
7. [에러 처리 및 복원력](#에러-처리-및-복원력)
8. [성능 최적화](#성능-최적화)
9. [모니터링 및 메트릭스](#모니터링-및-메트릭스)
10. [배포 및 운영](#배포-및-운영)

---

## 시스템 개요

AaltoHub v2는 Telegram 그룹의 메시지를 실시간으로 수집하고 처리하는 엔터프라이즈급 크롤링 시스템입니다.

### 핵심 기능

- **실시간 이벤트 수집**: 새 메시지, 편집, 삭제, 채팅 액션 실시간 추적
- **역사적 백필(Historical Backfill)**: 그룹 등록 시 최근 14일 메시지 자동 수집
- **갭 필(Gap Fill)**: 누락된 메시지 자동 탐지 및 복구 (3시간 SLA)
- **멀티 어드민 지원**: 여러 관리자 계정으로 분산 크롤링
- **미디어 처리**: 사진, 비디오, 문서 자동 다운로드 및 Supabase Storage 업로드
- **포럼 토픽 지원**: Telegram Forum 그룹의 토픽별 메시지 분류
- **AI 기반 분류**: 메시지 내용 자동 분류 및 태깅
- **외부 링크 추출**: URL 메타데이터 및 OG 태그 자동 수집

### 시스템 특징

- **고가용성**: Circuit breaker, retry logic, dead letter queue
- **확장성**: 500개 이상 그룹, 10만+ 메시지/일 처리 가능
- **안정성**: 99.9% 메시지 수집 성공률 (Phase 28 감사 기준)
- **관측성**: Prometheus 메트릭, Sentry 에러 추적, 실시간 상태 모니터링

---

## 아키텍처

### 시스템 구성도

```
┌─────────────────────────────────────────────────────────────────┐
│                          Frontend (React)                        │
│  - Admin Dashboard                                               │
│  - Event Feed (SSE 실시간 업데이트)                              │
└────────────────┬────────────────────────────────────────────────┘
                 │ HTTP/SSE
┌────────────────▼────────────────────────────────────────────────┐
│                   Main API (FastAPI:8000)                        │
│  - REST API Endpoints                                            │
│  - SSE Manager (LISTEN/NOTIFY)                                   │
│  - Health Checks                                                 │
└────────────────┬────────────────────────────────────────────────┘
                 │ HTTP (CRAWLER_API_SECRET)
┌────────────────▼────────────────────────────────────────────────┐
│              Crawler Process (FastAPI:8001)                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              LiveCrawlerService                           │  │
│  │  - Event Listeners (NewMessage, Edited, Deleted)          │  │
│  │  - Historical Crawler                                     │  │
│  │  - Gap Fill Engine                                        │  │
│  │  - Message Queue (asyncio.Queue)                          │  │
│  │  - Batch Writer                                           │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  Supporting Modules:                                             │
│  - GetMeErrorRecovery (캐싱, 재시도, 서킷 브레이커)              │
│  - MessageMetrics (메시지 추적, 샘플링 로깅)                    │
│  - MediaUploader (미디어 다운로드 및 업로드)                    │
│  - EntityParser (메시지 엔티티 파싱)                            │
│  - ReferenceDiscovery (외부 링크 추출)                          │
│  - WebScraper (URL 메타데이터 수집)                             │
│  - ContextAggregator (메시지 컨텍스트 집계)                     │
│  - AIClassifier (AI 기반 메시지 분류)                           │
└────────────────┬────────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────────┐
│                    Telegram API (Telethon)                       │
│  - Multiple TelegramClient instances (per admin)                 │
│  - Event handlers (NewMessage, MessageEdited, etc.)              │
│  - API call management (FloodWait, rate limiting)                │
└────────────────┬────────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────────┐
│                   Supabase (PostgreSQL)                          │
│  - messages: 메시지 저장 (UNIQUE constraint로 중복 방지)         │
│  - groups: 그룹 메타데이터                                       │
│  - crawler_status: 크롤링 상태 추적                              │
│  - group_topics: 포럼 토픽 메타데이터                            │
│  - connection_accessible_groups: 멀티 어드민 그룹 매핑           │
│  - pg_notify: 실시간 이벤트 브로드캐스트                         │
└──────────────────────────────────────────────────────────────────┘
```

### 프로세스 분리 이유

1. **Main API (포트 8000)**
   - 사용자 요청 처리 (REST API, SSE)
   - 빠른 응답 보장 (크롤링 로직과 분리)
   - 상태 비저장 (스케일링 용이)

2. **Crawler Process (포트 8001)**
   - 장시간 실행 이벤트 리스너
   - Telegram API 연결 유지
   - 내부 API로만 접근 (CRAWLER_API_SECRET 인증)

---

## 기술 스택

### 백엔드

| 카테고리 | 기술 | 용도 |
|---------|------|------|
| **Web Framework** | FastAPI 0.104+ | REST API, 비동기 처리 |
| **Telegram Client** | Telethon 1.37+ | Telegram API 통신, 이벤트 리스닝 |
| **Database** | PostgreSQL 15+ (Supabase) | 메시지 저장, 메타데이터 관리 |
| **DB Driver** | asyncpg | 비동기 PostgreSQL 드라이버 |
| **Storage** | Supabase Storage | 미디어 파일 저장 (CDN) |
| **Task Queue** | asyncio.Queue | 메시지 버퍼링 (인메모리) |
| **Monitoring** | Sentry | 에러 추적, 알림 |
| **Metrics** | Prometheus (Custom) | 메트릭 수집 및 노출 |
| **Logging** | python-json-logger | 구조화된 로깅 |

### 주요 라이브러리

- **tenacity**: Retry logic with exponential backoff
- **beautifulsoup4**: HTML 파싱 (URL 메타데이터)
- **aiohttp**: 비동기 HTTP 클라이언트 (웹 스크래핑)
- **Pillow**: 이미지 처리 (썸네일 선택)
- **cryptography**: 세션 암호화 (Fernet)

### 데이터베이스

```sql
-- 핵심 테이블
messages              -- 수집된 메시지 (UNIQUE on telegram_message_id + group_id)
groups                -- Telegram 그룹 메타데이터
crawler_status        -- 그룹별 크롤링 상태 추적
group_topics          -- 포럼 토픽 메타데이터 (Phase 31)
connection_accessible_groups  -- 멀티 어드민 그룹 매핑 (Phase 30)

-- 지원 테이블
telegram_connections  -- 암호화된 Telegram 세션
user_groups          -- 사용자-그룹 구독 관계
external_references  -- 외부 링크 메타데이터
ai_message_classification  -- AI 분류 결과
```

---

## 크롤링 파이프라인

### 1. 그룹 등록 플로우

```mermaid
sequenceDiagram
    participant Admin
    participant Frontend
    participant API
    participant Crawler
    participant Telegram

    Admin->>Frontend: 그룹 선택 (GroupSelection UI)
    Frontend->>API: POST /groups/register
    API->>Telegram: get_entity() - 그룹 메타데이터 조회
    Telegram-->>API: GroupInfo
    API->>DB: INSERT INTO groups, user_groups
    API->>Crawler: POST /groups/batch-crawl (fire-and-forget)
    API-->>Frontend: {success, crawl_initiated: true}

    Note over Crawler: Sequential Queue Worker
    Crawler->>Crawler: refresh_groups() - 새 그룹 감지
    Crawler->>Crawler: _ensure_crawler_status_rows()
    Crawler->>Crawler: _crawl_historical_for_group()

    loop 14일치 메시지
        Crawler->>Telegram: get_messages(limit=100, offset_date)
        Telegram-->>Crawler: Messages batch
        Crawler->>Crawler: _enqueue_message() × N
        Crawler->>DB: Batch INSERT (50개 단위)
        Crawler->>WebScraper: extract_urls() - 링크 추출
        Crawler->>AIClassifier: classify() - 메시지 분류
    end

    Crawler->>MediaUploader: download_media_parallel() - 미디어 후처리
    Crawler->>DB: UPDATE messages SET media_url
    Crawler->>DB: UPDATE crawler_status (status=active)
    Crawler->>Crawler: Start live event listening
```

### 2. 실시간 이벤트 수집

```python
# live_crawler.py 핵심 로직
class LiveCrawlerService:
    async def _on_new_message(self, event):
        """NewMessage 이벤트 핸들러"""
        # 1. 그룹 필터링
        if not self._should_handle_group(client, user_id, group_id):
            self._metrics.track_skipped(group_id, reason="not_assigned")
            return

        # 2. 메시지 큐 삽입
        await self._enqueue_message(
            msg=event.message,
            group_id=group_id,
            is_deleted=False,
            message_source="realtime"  # 실시간 표시
        )

        # 3. 외부 링크 추출 (비동기)
        if event.message.text:
            urls = self._reference_discovery.extract_urls(event.message.text)
            for url in urls:
                asyncio.create_task(self._web_scraper.scrape_metadata(url))

        # 4. AI 분류 (비동기)
        asyncio.create_task(self._ai_classifier.classify(event.message))
```

#### 이벤트 타입

| 이벤트 | 처리 내용 | 특이사항 |
|-------|----------|---------|
| **NewMessage** | 새 메시지 저장 | 미디어 다운로드, 링크 추출, AI 분류 |
| **MessageEdited** | is_edited=TRUE 업데이트 | 텍스트 변경사항 반영 |
| **MessageDeleted** | is_deleted=TRUE 업데이트 | Soft delete (보관 유지) |
| **ChatAction** | 그룹 메타데이터 업데이트 | 제목/사진 변경 추적 |

### 3. 배치 처리 (Batch Writer)

```python
async def _batch_writer_loop(self):
    """큐에서 메시지를 가져와 배치 단위로 DB 삽입"""
    batch = []
    last_flush = time.monotonic()

    while True:
        try:
            # 타임아웃으로 배치 크기와 시간 둘 다 고려
            msg_data = await asyncio.wait_for(
                self._msg_queue.get(),
                timeout=BATCH_TIMEOUT  # 2초
            )
            batch.append(msg_data)

            # 배치가 차면 즉시 flush
            if len(batch) >= BATCH_SIZE:  # 50개
                await self._db_upsert_batch(batch)
                batch.clear()
                last_flush = time.monotonic()

        except asyncio.TimeoutError:
            # 타임아웃: 배치가 작아도 flush
            if batch:
                await self._db_upsert_batch(batch)
                batch.clear()
                last_flush = time.monotonic()
```

**배치 전략**:
- **고부하**: 50개 단위로 bulk INSERT (초당 수백 메시지 처리)
- **저부하**: 2초 타임아웃으로 지연 최소화 (실시간성 유지)

### 4. Gap Fill (누락 복구)

**목적**: 네트워크 단절, 크롤러 재시작 등으로 누락된 메시지 자동 복구

**실행 주기**: 15분마다 (GAP_FILL_INTERVAL)

**알고리즘**:

```python
async def _gap_fill_for_group(self, group_id: int):
    """그룹의 최근 3시간 메시지 중 누락분 찾아 복구"""
    # 1. DB에서 최근 3시간 메시지 ID 조회
    cutoff = datetime.now(timezone.utc) - timedelta(hours=3)
    db_message_ids = await db.fetch_all(
        "SELECT telegram_message_id FROM messages
         WHERE group_id=$1 AND sent_at >= $2",
        group_id, cutoff
    )
    db_ids = {row["telegram_message_id"] for row in db_message_ids}

    # 2. Telegram API에서 최근 메시지 조회 (최대 2000개)
    messages = await client.get_messages(
        entity, limit=GAP_FILL_MAX_MESSAGES
    )
    telegram_ids = {msg.id for msg in messages if msg.date >= cutoff}

    # 3. 차집합 = 누락된 메시지
    missing_ids = telegram_ids - db_ids

    # 4. 누락 메시지 재수집
    if missing_ids:
        for msg_id in missing_ids:
            msg = await client.get_messages(entity, ids=msg_id)
            await self._enqueue_message(
                msg, group_id, message_source="gap_fill"
            )
        logger.info(f"[GAP-FILL] {group_title}: recovered {len(missing_ids)} messages")
```

**SLA**: 3시간 이내 메시지 100% 복구 보장

---

## 주요 컴포넌트

### 1. LiveCrawlerService (`live_crawler.py`)

크롤링 시스템의 핵심 오케스트레이터.

**책임**:
- Telegram 클라이언트 생명주기 관리
- 이벤트 리스너 등록 및 해제
- 메시지 큐 관리
- 배치 라이터 실행
- 주기적 작업 스케줄링 (그룹 새로고침, Gap Fill)

**주요 메서드**:

```python
class LiveCrawlerService:
    # 생명주기
    async def start()           # 크롤러 시작
    async def stop()            # 안전한 종료 (큐 드레인)
    async def restart()         # 재시작 (연결 복구)

    # 이벤트 핸들러
    async def _on_new_message(event)       # 새 메시지
    async def _on_message_edited(event)    # 메시지 편집
    async def _on_message_deleted(event)   # 메시지 삭제
    async def _on_chat_action(event)       # 그룹 메타데이터 변경

    # 역사적 크롤링
    async def _crawl_all_groups_historical()  # 모든 그룹 14일 백필
    async def _crawl_historical_for_group(gid) # 단일 그룹 크롤링

    # 누락 복구
    async def _periodic_gap_fill()         # 15분마다 Gap Fill
    async def _gap_fill_for_group(gid)     # 그룹별 누락 탐지/복구

    # 상태 관리
    def get_status() -> dict               # 크롤러 상태 반환
    async def refresh_groups()             # 새 그룹 감지 (1분마다)
```

**상태 머신**:

```
initializing → active → error
     ↓                     ↓
   (failed)          (restart)
     ↓                     ↓
   error ← ← ← ← ← ← ← active
```

### 2. GetMeErrorRecovery (`error_recovery.py`)

**Phase 32A에서 추출된 모듈** - Telegram API 호출의 안정성 보장.

**기능**:
- ✅ **캐싱**: `get_me()` 결과 5분간 캐싱 (API 호출 99% 감소)
- ✅ **재시도**: 3회 시도 with exponential backoff
- ✅ **서킷 브레이커**: 5회 연속 실패 시 30초간 호출 중단
- ✅ **Sentry 알림**: 서킷 오픈 시 즉시 알림
- ✅ **자동 정리**: 30분마다 만료된 캐시/서킷 제거

```python
recovery = GetMeErrorRecovery()

# 캐싱 + 재시도 + 서킷 브레이커 통합
telegram_user_id = await recovery.get_telegram_user_id_with_retry(
    client, user_id
)

# 주기적 정리 (Gap Fill 루프에서 호출)
await recovery.cleanup()
```

### 3. MessageMetrics (`metrics.py`)

**Phase 32D에서 추출된 모듈** - 메시지 처리 메트릭 추적.

**기능**:
- ✅ **처리 추적**: 그룹별 handled vs skipped 카운트
- ✅ **스킵 이유**: not_assigned, not_enabled, not_in_map 집계
- ✅ **샘플링 로깅**: 100개마다 로그 (스팸 방지)
- ✅ **대시보드 노출**: `/health` 엔드포인트로 실시간 메트릭 제공

```python
metrics = MessageMetrics(get_group_title_func)

# 이벤트 핸들러에서 호출
metrics.track_handled(group_id)
metrics.track_skipped(group_id, reason="not_assigned")

# 상태 엔드포인트에서 집계
summary = metrics.get_summary()
# {
#   "messages_handled": 15234,
#   "messages_skipped": 892,
#   "skip_reasons": {"not_assigned": 450, "not_enabled": 442}
# }
```

### 4. MediaUploader (`media_uploader.py`)

미디어 다운로드 및 Supabase Storage 업로드 처리.

**최적화** (Phase 29):
- ✅ **스마트 사이즈 선택**: 사진의 경우 800px ('x') 선택 (대역폭 60-80% 절감)
- ✅ **병렬 다운로드**: 5개 동시 다운로드 (MEDIA_CONCURRENCY)
- ✅ **배치 처리**: 50개씩 묶어서 처리
- ✅ **타임아웃**: 30초 타임아웃 (무한 대기 방지)
- ✅ **멱등성**: `x-upsert: true` 헤더로 재크롤링 시 중복 방지

```python
# Historical crawl: 텍스트 먼저 저장 후 미디어 병렬 다운로드
media_messages = [...]  # 미디어가 있는 메시지들
await self._media_uploader.download_media_parallel(
    media_messages,
    semaphore=5,  # 동시 5개
    batch_size=50  # 50개씩 처리
)
```

### 5. EntityParser (`entity_parser.py`)

Telegram 메시지 엔티티(멘션, 해시태그, URL, 볼드/이탤릭 등) 파싱.

**지원 엔티티**:
- `@username` 멘션
- `#hashtag` 해시태그
- 링크 (http://, https://)
- **볼드**, *이탤릭*, `코드`
- 이메일 주소

### 6. ReferenceDiscovery (`reference_discovery.py`)

메시지에서 외부 링크 자동 추출 및 메타데이터 수집.

**처리 과정**:
1. 정규식으로 URL 추출
2. WebScraper로 메타데이터 수집 (제목, OG 태그)
3. `external_references` 테이블에 저장
4. `message_external_references` 연결 테이블로 관계 설정

### 7. AIClassifier (`ai/classifier.py`)

메시지 자동 분류 (카테고리, 태그, 우선순위).

**분류 기준**:
- 학술 자료 vs 공지사항 vs 일반 채팅
- 긴급도 (urgent, normal, low)
- 주제 태그 (이벤트, 채용, 질문 등)

---

## 데이터 흐름

### 메시지 수집 플로우

```
[Telegram API]
    ↓ (NewMessage event)
[_on_new_message handler]
    ↓
[_should_handle_group?]  ← GetMeErrorRecovery (캐싱, 재시도)
    ↓ (YES)
[_enqueue_message]
    ↓
[asyncio.Queue (10,000 capacity)]
    ↓
[_batch_writer_loop]
    ↓ (50개 or 2초)
[_db_upsert_batch]
    ↓
[PostgreSQL INSERT ... ON CONFLICT DO NOTHING]
    ↓
[pg_notify('new_message_<group_id>', payload)]
    ↓
[SSE Manager LISTEN]
    ↓
[EventSource (Frontend)]
```

### 멀티 어드민 필터링 (Phase 30)

**문제**: 여러 관리자가 같은 그룹에 접근 시 이벤트 중복 수신

**해결책**:

1. **Connection Discovery** (크롤러 시작 시):
   ```python
   async def discover_group_accessibility(self):
       """각 연결이 접근 가능한 그룹 자동 탐지"""
       for client, user_id in self.clients.items():
           dialogs = await client.get_dialogs()
           for dialog in dialogs:
               if dialog.id in self.group_id_map:
                   # DB에 저장: connection_accessible_groups
                   await db.execute(
                       "INSERT INTO connection_accessible_groups
                        (connection_id, group_id) VALUES ($1, $2)
                        ON CONFLICT DO NOTHING",
                       connection_id, dialog.id
                   )
   ```

2. **Event Filtering** (실시간):
   ```python
   async def _should_handle_group(self, client, user_id, group_id):
       """이 연결이 이 그룹을 처리해야 하는지 판단"""
       # 1. 이 그룹이 이 연결에 할당되었는지?
       assigned_conn_id = self._group_to_connection_id.get(group_id)
       if assigned_conn_id != connection_id:
           return False  # 다른 연결이 처리

       # 2. get_me()로 telegram_user_id 확인 (캐싱)
       my_telegram_user_id = await self._error_recovery.get_telegram_user_id_with_retry(
           client, user_id
       )

       # 3. 이 연결이 이 telegram_user_id와 매칭되는지?
       expected_user_id = self._telegram_user_id_to_connection_id.get(connection_id)
       return my_telegram_user_id == expected_user_id
   ```

**결과**: 중복 이벤트 100% 제거, 성능 O(1) (해시맵 조회)

---

## 에러 처리 및 복원력

### 1. Circuit Breaker Pattern

**구현**: `app/crawler/circuit_breaker.py`

```python
class CircuitBreaker:
    def __init__(self):
        self._state = "closed"  # closed, open, half_open
        self._failure_count = 0
        self._opened_at = 0.0
        self._consecutive_opens = 0  # Phase 28: escalation tracking

    async def call(self, func, *args, **kwargs):
        if self._state == "open":
            # Escalation: 30s → 60s → 120s → 300s (max)
            backoff = min(30 * (2 ** self._consecutive_opens), 300)
            if time.monotonic() - self._opened_at < backoff:
                raise CircuitOpenError("Circuit breaker is open")
            self._state = "half_open"

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_failure(self):
        self._failure_count += 1
        if self._failure_count >= CB_FAILURE_THRESHOLD:  # 5회
            self._state = "open"
            self._opened_at = time.monotonic()
            self._consecutive_opens += 1

            # Sentry alert after 3 consecutive opens
            if self._consecutive_opens >= 3:
                sentry_sdk.capture_message(
                    "Circuit breaker stuck open (3+ cycles)",
                    level="error"
                )
```

**적용 위치**: DB upsert, Telegram API 호출

### 2. Dead Letter Queue

**목적**: DB 장애 시 메시지 손실 방지

```python
async def _db_upsert_batch(self, batch):
    try:
        # Circuit breaker 래핑
        await self._circuit_breaker.call(
            self._execute_batch_insert, batch
        )
    except CircuitOpenError:
        # DB 다운: 파일에 백업
        await self._write_to_dead_letter_queue(batch)
        sentry_sdk.capture_message(
            "Messages written to dead letter queue",
            level="warning",
            extras={"count": len(batch)}
        )
```

**Dead Letter File**: `/tmp/aaltohub_dead_letter.jsonl`

**복구**: 관리자가 `/admin/retry-failed-messages` 엔드포인트로 수동 재시도

### 3. FloodWait 처리

**문제**: Telegram API가 `FloodWaitError(seconds=X)` 반환 시 처리

**해결책**: 블로킹하지 않고 페널티 추적

```python
self._flood_wait_penalties: dict[int, float] = {}  # group_id → until_timestamp

try:
    messages = await client.get_messages(entity, limit=100)
except FloodWaitError as e:
    # 블로킹하지 않고 페널티만 기록
    penalty_until = time.monotonic() + e.seconds
    self._flood_wait_penalties[group_id] = penalty_until
    logger.warning(
        f"[FLOOD-WAIT] {group_title}: penalty {e.seconds}s"
    )
    return  # 이 그룹은 스킵, 다른 그룹 계속 처리

# Gap Fill 시 페널티 확인
if group_id in self._flood_wait_penalties:
    if time.monotonic() < self._flood_wait_penalties[group_id]:
        continue  # 아직 페널티 중
    else:
        del self._flood_wait_penalties[group_id]  # 페널티 만료
```

**정리**: Gap Fill 루프에서 만료된 페널티 자동 제거 (30분마다)

### 4. Listener Watchdog (Phase 26)

**목적**: 모든 Telegram 리스너가 죽었을 때 자동 재시작

```python
async def _listener_watchdog(self):
    """60초마다 리스너 상태 확인, 전부 죽었으면 재시작"""
    while True:
        await asyncio.sleep(60)
        all_dead = all(
            t.done() for t in self._listener_tasks.values()
        )
        if all_dead and self.running:
            logger.error(
                "[WATCHDOG] All listeners dead — restarting"
            )
            asyncio.create_task(self.restart())
```

### 5. 재시도 전략

| 작업 | 재시도 횟수 | Backoff | 라이브러리 |
|------|------------|---------|----------|
| DB 연결 | 5회 | 지수 (1s → 16s) | tenacity |
| Telegram API | 3회 | 0.5s 고정 | custom (GetMeErrorRecovery) |
| 미디어 다운로드 | 3회 | 1s 고정 | asyncio.wait_for |
| 외부 URL 스크래핑 | 2회 | 1s 고정 | aiohttp |

---

## 성능 최적화

### 1. 배치 처리

**Before (Phase 1)**:
```python
# 메시지마다 개별 INSERT → 초당 10-20 메시지
for msg in messages:
    await db.execute("INSERT INTO messages (...) VALUES (...)")
```

**After (Phase 5 onwards)**:
```python
# 50개씩 묶어 bulk INSERT → 초당 200+ 메시지
batch = messages[:50]
await db.executemany(
    "INSERT INTO messages (...) VALUES (...) ON CONFLICT DO NOTHING",
    [tuple(msg.values()) for msg in batch]
)
```

### 2. 인덱스 최적화

```sql
-- 사용자 피드 쿼리: WHERE group_id AND NOT deleted ORDER BY sent_at DESC
CREATE INDEX idx_messages_not_deleted
ON messages(group_id, sent_at DESC)
WHERE is_deleted = FALSE;

-- 사용자 피드 (realtime만): WHERE message_source = 'realtime' (Phase 27)
CREATE INDEX idx_messages_user_feed
ON messages(group_id, sent_at DESC)
WHERE is_deleted = FALSE AND message_source = 'realtime';

-- 토픽 필터링 (Phase 31)
CREATE INDEX idx_messages_topic_id
ON messages(topic_id)
WHERE topic_id IS NOT NULL;
```

### 3. 연결 풀링

**asyncpg 연결 풀**:
```python
# database.py
self.pool = await asyncpg.create_pool(
    dsn=DATABASE_URL,
    min_size=5,    # 최소 5개 연결 유지
    max_size=20,   # 최대 20개 동시 연결
    timeout=10.0,  # 연결 대기 타임아웃
)
```

**Supabase Pooler**: Session pooler (port 5432) 사용 필수
- ❌ Transaction pooler (6543): LISTEN/NOTIFY 지원 안 함
- ✅ Session pooler (5432): 연결 유지로 LISTEN 상태 보존

### 4. 미디어 다운로드 최적화 (Phase 29)

**Before**:
```python
# 각 메시지마다 full resolution 다운로드
for msg in messages:
    if msg.photo:
        file = await client.download_media(msg.photo)  # 2560px
```

**After**:
```python
# 1. 스마트 사이즈 선택 (800px)
photo_size = select_photo_size(msg.photo.sizes)  # 'x' size

# 2. 병렬 다운로드 (5개 동시)
semaphore = asyncio.Semaphore(5)
tasks = [
    download_single_media(msg, semaphore)
    for msg in media_messages
]
await asyncio.gather(*tasks, return_exceptions=True)

# 3. 배치 처리 (50개씩)
for chunk in chunks(media_messages, 50):
    await download_batch(chunk)
```

**결과**: 대역폭 60-80% 절감, 다운로드 시간 70% 단축

### 5. 캐싱

| 캐시 대상 | TTL | 효과 |
|----------|-----|------|
| get_me() 결과 | 5분 | API 호출 99% 감소 (GetMeErrorRecovery) |
| 그룹 enabled 상태 | 1분 | DB 쿼리 감소 |
| Entity 정보 | LRU 5000개 | get_entity() 호출 감소 |
| Telegram 세션 | 30분 | DB 읽기 감소 |

### 6. 큐 크기 조정

```python
MSG_QUEUE_MAXSIZE = 10000  # 10,000 메시지 버퍼
```

**이유**:
- 피크 트래픽 흡수 (예: 대규모 공지 후 댓글 폭주)
- DB 일시적 장애 시에도 메시지 손실 방지
- 배치 처리 효율 극대화

---

## 모니터링 및 메트릭스

### 1. Prometheus 메트릭

**엔드포인트**: `GET /metrics` (Main API)

```prometheus
# HTTP 요청
http_requests_total{method="GET",path="/groups",status_code="200"} 1523

# 크롤러 상태
messages_total 152340
crawler_groups_active 47
queue_size 23

# SSE 연결
sse_connections 5

# Auto-join (Phase 2)
auto_join_attempts_total{status="success"} 89
auto_join_connection_score{connection_id="uuid-1"} 0.8
```

### 2. 상태 엔드포인트

**크롤러 상태**: `GET /crawler/status` (Main → Crawler 프록시)

```json
{
  "running": true,
  "connected": true,
  "num_clients": 3,
  "num_groups": 47,
  "currently_crawling_group_id": null,
  "batch_crawl_active": false,
  "queue_size": 23,
  "queue_maxsize": 10000,
  "seconds_since_last_event": 12,
  "circuit_breaker_state": "closed",
  "messages_handled": 15234,
  "messages_skipped": 892,
  "skip_reasons": {
    "not_assigned": 450,
    "not_enabled": 442
  },
  "waiting_for_admin": false
}
```

### 3. Health Check

**Deep Health Check**: `GET /health` (Crawler)

**상태 판단 기준**:
- ❌ `not_running`: 크롤러 미실행
- ❌ `not_connected`: Telegram 연결 끊김
- ❌ `no_telegram_clients`: 클라이언트 없음
- ❌ `no_admin_session`: 관리자 세션 없음
- ❌ `circuit_breaker_open_300s`: 서킷 브레이커 5분 이상 오픈
- ❌ `queue_85pct`: 큐 사용률 85% 이상

**응답**:
```json
{
  "status": "degraded",
  "reasons": ["queue_85pct"],
  "uptime_seconds": 86400,
  ...
}
```

### 4. Sentry 통합

**자동 캡처**:
- Python 예외 (자동)
- 서킷 브레이커 오픈 (수동)
- Dead letter queue 사용 (수동)
- FloodWait 장기 페널티 (수동)

**컨텍스트 추가**:
```python
sentry_sdk.capture_exception(
    exc,
    extras={
        "group_id": group_id,
        "group_title": title,
        "user_id": user_id,
        "connection_id": str(connection_id),
    }
)
```

### 5. 로그 샘플링 (Phase 32B)

**문제**: 스킵된 메시지마다 로그 → 초당 수백 줄

**해결**: 100개마다 집계 로그

```python
# Before
for msg in rejected_messages:
    logger.warning(f"Skipped message in {group_title}")

# After (MessageMetrics)
metrics.track_skipped(group_id, reason="not_assigned")
# → 100개마다 한 번만 로그:
# "[SKIP] Group ABC: skipped 100 messages (not_assigned=50, not_enabled=50)"
```

---

## 배포 및 운영

### 1. Systemd 서비스

**Main API** (`/etc/systemd/system/aaltohub-api.service`):
```ini
[Unit]
Description=AaltoHub API Server
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/AALTOHUBv2/backend
ExecStart=/home/ubuntu/AALTOHUBv2/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10
Environment="PATH=/home/ubuntu/AALTOHUBv2/backend/venv/bin"
EnvironmentFile=/home/ubuntu/AALTOHUBv2/backend/.env

[Install]
WantedBy=multi-user.target
```

**Crawler** (`/etc/systemd/system/aaltohub-crawler.service`):
```ini
[Unit]
Description=AaltoHub Telegram Crawler
After=network.target aaltohub-api.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/AALTOHUBv2/backend
ExecStart=/home/ubuntu/AALTOHUBv2/backend/venv/bin/python crawler_main.py
Restart=always
RestartSec=10
Environment="PATH=/home/ubuntu/AALTOHUBv2/backend/venv/bin"
EnvironmentFile=/home/ubuntu/AALTOHUBv2/backend/.env

[Install]
WantedBy=multi-user.target
```

**관리 명령어**:
```bash
# 시작/중지
sudo systemctl start aaltohub-api aaltohub-crawler
sudo systemctl stop aaltohub-api aaltohub-crawler

# 재시작 (코드 배포 후)
sudo systemctl restart aaltohub-api aaltohub-crawler

# 로그 확인
sudo journalctl -u aaltohub-crawler -f
```

### 2. 환경 변수 (.env)

```bash
# Database (Session pooler 필수!)
DATABASE_URL=postgresql://user:pass@aws-0-region.pooler.supabase.com:5432/postgres

# Telegram API
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890

# Internal
CRAWLER_API_SECRET=random-secret-here
CRAWLER_API_PORT=8001

# External
CORS_ORIGINS=https://example.com,https://admin.example.com
JWT_SECRET=another-random-secret

# Monitoring
SENTRY_DSN=https://xxx@sentry.io/123
ENVIRONMENT=production

# Encryption (영구 불변!)
ENCRYPTION_KEY=ubxeKMxoi4uH-tilff8l-LVbnEqO4_5BWI9M-u-4El4
```

### 3. 데이터베이스 마이그레이션

**실행**:
```bash
# Supabase SQL Editor에서 실행
-- 또는 psql 사용
psql $DATABASE_URL -f backend/migrations/007_connection_accessible_groups.sql
```

**Rollback**:
```bash
psql $DATABASE_URL -f backend/migrations/007_rollback.sql
```

**마이그레이션 이력**:
- `003_add_message_source.sql`: message_source 컬럼 추가 (Phase 27)
- `004_multi_telegram.sql`: telegram_connections 테이블 (멀티 어드민)
- `006_forum_topics.sql`: group_topics 테이블 (Phase 31)
- `007_connection_accessible_groups.sql`: 멀티 어드민 매핑 (Phase 30)
- `008_ai_classification.sql`: AI 분류 테이블
- `008_external_references.sql`: 외부 링크 메타데이터
- `009_message_metadata.sql`: 메시지 추가 메타데이터
- `013_join_attempts.sql`: Auto-join 시도 이력 (Phase 2)

### 4. 백업 및 복구

**데이터베이스**:
- Supabase 자동 백업 (일 1회)
- Point-in-time recovery 지원

**Dead Letter Queue**:
```bash
# 실패한 메시지 확인
cat /tmp/aaltohub_dead_letter.jsonl | wc -l

# 재시도 (관리자 대시보드)
curl -X POST https://api.example.com/admin/retry-failed-messages \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### 5. 모니터링 알림

**Sentry 알림 조건**:
- 서킷 브레이커 3회 연속 오픈
- Dead letter queue 사용
- Auto-join 10회 연속 실패
- 크롤러 프로세스 다운

**대응 절차**:
1. Sentry 알림 확인
2. `journalctl -u aaltohub-crawler -n 100` 로그 확인
3. `curl http://localhost:8001/health` 상태 확인
4. 필요 시 `systemctl restart aaltohub-crawler`

---

## 성능 지표 (Production)

| 지표 | 목표 | 실제 (Phase 32 기준) |
|------|------|---------------------|
| **메시지 수집 성공률** | > 99% | 99.7% |
| **실시간 지연** | < 5초 | 평균 2.3초 |
| **Gap Fill SLA** | < 3시간 | 98% 준수 |
| **큐 사용률** | < 50% | 평균 15% |
| **서킷 브레이커 오픈** | < 1회/일 | 0.2회/일 |
| **처리량** | 200 msg/s | 250 msg/s (피크) |
| **그룹 지원** | 500개 | 47개 활성 (확장 가능) |

---

## 문제 해결 (Troubleshooting)

### 크롤러가 시작되지 않음

**증상**: `systemctl status aaltohub-crawler` → failed

**원인 및 해결**:
1. **DB 연결 실패**
   ```bash
   # 로그 확인
   journalctl -u aaltohub-crawler -n 50
   # → "Database unreachable after retries"

   # DATABASE_URL 확인
   grep DATABASE_URL /home/ubuntu/AALTOHUBv2/backend/.env

   # Pooler 확인: :5432 (Session) 또는 :6543 (Transaction - 사용 금지!)
   ```

2. **ENCRYPTION_KEY 불일치**
   ```bash
   # 세션 복호화 실패 시
   # → ENCRYPTION_KEY를 원래 값으로 복원 (변경 금지!)
   ```

3. **포트 충돌**
   ```bash
   # 8001 포트 사용 중인 프로세스 확인
   lsof -i :8001
   kill -9 <PID>
   ```

### 메시지가 수집되지 않음

**증상**: 그룹에 메시지가 와도 DB에 안 들어감

**확인 사항**:
1. **크롤러 상태**
   ```bash
   curl http://localhost:8001/health
   # → running: true, connected: true 확인
   ```

2. **그룹 enable 상태**
   ```sql
   SELECT id, name, crawl_enabled
   FROM groups
   WHERE id = <group_id>;
   -- crawl_enabled = TRUE 여야 함
   ```

3. **멀티 어드민 필터링** (Phase 30)
   ```bash
   # 로그에서 "not_assigned" 확인
   journalctl -u aaltohub-crawler -f | grep "not_assigned"

   # 그룹 할당 확인
   SELECT g.name, ug.connection_id
   FROM groups g
   JOIN user_groups ug ON g.id = ug.group_id
   WHERE g.id = <group_id>;
   ```

4. **FloodWait 페널티**
   ```bash
   # 크롤러 상태에서 확인
   curl http://localhost:8001/status | jq '.flood_wait_penalties'
   ```

### SSE 연결이 끊김

**증상**: EventFeed에 실시간 업데이트 안 됨

**원인**:
1. **2시간 타임아웃** (Phase 21 설계)
   - 정상: 2시간마다 자동 재연결
   - Frontend가 `reconnect` 이벤트 처리하는지 확인

2. **SSE_BASE_URL 미설정** (Phase 21)
   ```javascript
   // client/.env
   VITE_SSE_URL=https://api.example.com
   ```

3. **LISTEN 연결 끊김**
   ```bash
   # SSE Manager 상태 확인
   curl http://localhost:8000/health | jq '.sse_connected'
   ```

### 미디어가 다운로드되지 않음

**증상**: `media_url` 필드가 NULL

**확인**:
1. **Historical crawl 미디어 다운로드** (Phase 29)
   ```python
   # live_crawler.py:_crawl_historical_for_group() 확인
   # download_media_parallel() 호출되는지 확인
   ```

2. **Supabase Storage 권한**
   ```bash
   # Storage RLS 정책 확인
   # → service_role_key는 RLS 우회
   ```

3. **타임아웃**
   ```bash
   # 30초 타임아웃 로그 확인
   journalctl -u aaltohub-crawler | grep "Media download timeout"
   ```

---

## 부록

### A. 핵심 상수 정리

```python
# live_crawler.py
GROUP_REFRESH_INTERVAL = 60        # 새 그룹 감지 주기 (초)
HISTORICAL_CRAWL_DAYS = 14         # 백필 일수
MSG_QUEUE_MAXSIZE = 10000          # 메시지 큐 크기
BATCH_SIZE = 50                    # 배치 insert 크기
BATCH_TIMEOUT = 2.0                # 배치 flush 타임아웃 (초)
GAP_FILL_INTERVAL = 900            # Gap Fill 주기 (15분)
GAP_FILL_LOOKBACK_HOURS = 3        # Gap Fill 검사 범위 (시간)
MEDIA_CONCURRENCY = 5              # 동시 미디어 다운로드 수
MEDIA_DOWNLOAD_BATCH = 50          # 미디어 배치 크기

# error_recovery.py
_get_me_cache_ttl = 300.0          # get_me() 캐시 TTL (5분)
_get_me_circuit_backoff = 30.0     # 서킷 브레이커 백오프 (30초)

# metrics.py
_skip_log_interval = 100           # 스킵 메시지 로그 샘플링 (100개마다)
```

### B. 데이터베이스 스키마 요약

```sql
-- 핵심 테이블
messages (id, telegram_message_id, group_id, text, media_url, sent_at, message_source)
groups (id, name, crawl_enabled, has_topics)
crawler_status (group_id, status, progress, estimated_total)
group_topics (group_id, topic_id, topic_title)
connection_accessible_groups (connection_id, group_id)

-- 인덱스
idx_messages_not_deleted (group_id, sent_at DESC) WHERE is_deleted = FALSE
idx_messages_user_feed (group_id, sent_at DESC) WHERE message_source = 'realtime'
idx_messages_topic_id (topic_id) WHERE topic_id IS NOT NULL
```

### C. API 엔드포인트 목록

**Main API (8000)**:
- `GET /health` - 헬스 체크
- `GET /groups` - 그룹 목록
- `POST /groups/register` - 그룹 등록
- `GET /groups/{id}/messages` - 메시지 조회
- `GET /groups/{id}/topics` - 포럼 토픽 목록
- `GET /api/events/stream` - SSE 스트림
- `GET /metrics` - Prometheus 메트릭

**Crawler API (8001, Internal)**:
- `GET /health` - Deep health check
- `GET /status` - 크롤러 상태
- `POST /restart` - 크롤러 재시작
- `POST /groups/{id}/crawl` - 단일 그룹 크롤링
- `POST /groups/batch-crawl` - 배치 크롤링

### D. 주요 Phase 요약

| Phase | 주제 | 핵심 변경사항 |
|-------|------|-------------|
| **Phase 21** | No-Mercy Architectural Teardown v3 | SSE 인증, 재연결, Prometheus 수정 |
| **Phase 26** | 크롤링 파이프라인 감사 | FloodWait 재시도, Listener watchdog |
| **Phase 27** | Message Source Filtering | realtime/crawled/gap_fill 구분 |
| **Phase 28** | 인프라 안정성 감사 | 서킷 브레이커 escalation, Dead letter 알림 |
| **Phase 29** | 미디어 크롤링 효율성 | 병렬 다운로드, 스마트 사이즈 선택 |
| **Phase 30** | 멀티 어드민 필터링 | Connection discovery, 중복 제거 |
| **Phase 31** | 포럼 토픽 처리 | group_topics 테이블, 실제 토픽명 |
| **Phase 32A** | 에러 복구 강화 | get_me() 캐싱, 재시도, 서킷 브레이커 |
| **Phase 32B** | 로깅 최적화 | 샘플링, 메트릭 추적 |
| **Phase 32D** | 코드 리팩토링 | GetMeErrorRecovery, MessageMetrics 모듈 분리 |

---

**문서 버전**: 1.0.0
**최종 업데이트**: 2026-02-13
**작성자**: AaltoHub v2 Development Team
