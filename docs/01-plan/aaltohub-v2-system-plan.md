# AaltoHub v2 — System Analysis & Plan Document

> Generated: 2026-02-11
> Status: DRAFT — 사용자 검토 후 수정 예정
> Scope: 전체 시스템 현황 분석 + 코드 품질 + 갭 분석 + 개선 계획

---

## 1. 시스템 개요

### 1.1 아키텍처

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│  Frontend   │────▶│  Vercel      │────▶│  Backend (8000)  │
│  React+Vite │     │  Proxy       │     │  FastAPI+asyncpg │
│  SSE direct │─────────────────────────▶│  SSEManager      │
└─────────────┘     └──────────────┘     └──────┬───────────┘
                                                │ pg_notify
                                         ┌──────▼───────────┐
                                         │  Supabase        │
                                         │  PostgreSQL      │
                                         └──────▲───────────┘
                                                │
                                         ┌──────┴───────────┐
                                         │  Crawler (8001)  │
                                         │  Telethon        │
                                         │  LiveCrawler     │
                                         └──────────────────┘
```

### 1.2 기술 스택

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + Vite + TypeScript + shadcn/ui + Tailwind |
| Backend API | FastAPI + asyncpg (port 8000) |
| Crawler | FastAPI + Telethon (port 8001) |
| Database | Supabase PostgreSQL |
| Realtime | pg_notify → SSEManager LISTEN → SSE → EventSource |
| Auth | Custom JWT (not Supabase Auth) |
| Storage | Supabase Storage (media files) |
| Proxy | Vercel Serverless (API REST only, NOT SSE) |
| Monitoring | Sentry + Custom Prometheus-format metrics |
| Deployment | systemd services (backend), Vercel (frontend) |

### 1.3 코드 규모

| Component | Files | Lines | Key Files |
|-----------|-------|-------|-----------|
| Backend - Core | 12 | ~5,500 | live_crawler.py (2776), main.py (500), telegram_client.py (782) |
| Backend - Routes | 8 | ~4,000 | groups.py (800+), auth.py (600+), admin/* |
| Backend - Modules | 6 | ~1,200 | error_recovery.py, metrics.py, sse.py, database.py |
| Backend - Migrations | 7 | ~500 | 001-007 SQL migrations |
| Frontend - Pages | 15 | ~6,000 | EventFeed (740), AdminDashboard (685), GroupSelection (708) |
| Frontend - Hooks | 7 | ~500 | useSSE.ts (180), useMessageSearch.ts |
| Frontend - Lib | 2 | ~700 | api.ts (700+) |
| Tests | 3 | ~543 | test_auth.py, test_models.py, test_config.py |
| **Total** | **~60** | **~19,000** | |

---

## 2. 현재 구현 상태 (Phase 21~32D)

### 2.1 완료된 주요 기능

| Phase | Feature | Status |
|-------|---------|--------|
| 21 | No-Mercy Architectural Teardown v3 (SSE auth, reconnect, metrics) | ✅ |
| 22 | Dev Startup Resilience (preflight, retry, degraded mode) | ✅ |
| 23 | 20-Point verify-code 500 Error Fix | ✅ |
| 24 | Group Selection Flow + 3-Flow Deep Audit | ✅ |
| 25 | 500 Error Fix + Crawl Progress Display | ✅ |
| 26 | Ultra-Thorough Crawling Pipeline Audit (16 fixes) | ✅ |
| 27 | Message Source Filtering (realtime vs crawled) | ✅ |
| 28 | Full-Stack Infrastructure Stability Audit (13 fixes) | ✅ |
| 29 | Media Crawling Efficiency Overhaul (6 fixes) | ✅ |
| 30 | Multi-Admin Connection Filtering & Deduplication (3 phases) | ✅ |
| 31 | Forum Topic Handling (4 fixes, has_topics, group_topics table) | ✅ |
| 31.1 | Forum Topic Refactoring (batch ops, decomposed methods) | ✅ |
| 32A | Error Recovery & Resilience (get_me cache, retry, circuit breaker) | ✅ |
| 32B | Logging Optimization & Metrics Enhancement | ✅ |
| 32C | Migration 007 Application (connection_accessible_groups) | ✅ |
| 32D | Code Refactoring — Modular Design (error_recovery.py, metrics.py) | ✅ |

### 2.2 핵심 기능 목록

**인증 & 사용자 관리**
- Telegram 로그인 (phone + code + 2FA) with rate limiting
- Custom JWT (access 30min + refresh 7d) with revocation
- Admin role management
- Email linking (optional secondary auth)
- Session encryption (AES-GCM + PBKDF2 600K iterations)

**그룹 관리**
- Telegram 그룹 등록 (auto-discovery from dialogs)
- Multi-connection admin support (10+ connections per admin)
- Connection-group mapping with duplicate prevention
- Group visibility settings (public/private)
- Forum topic support (has_topics, group_topics table)
- Invite link generation and management

**메시지 수집 (Crawler)**
- Real-time event listening (NewMessage, Edited, Deleted, ChatAction)
- Historical crawl (14 days backfill, batch queue)
- Gap-fill (30-min periodic re-check)
- Media download (parallel, 800px photo optimization, 5 concurrent)
- Message source tracking (realtime/crawled/gap_fill)
- Dead letter queue with retry

**실시간 이벤트 (SSE)**
- pg_notify → SSEManager → per-group channels
- Overflow handling (queue full → refresh event)
- Truncation detection (8KB NOTIFY limit)
- 2-hour max connection duration with reconnect
- Auth via query parameter token

**관리자 대시보드**
- Group list with crawler status
- Message viewer with search
- Crawler management (start/stop/progress)
- User management
- Connection diagnostics
- Failed message retry

**모니터링 & 회복**
- Circuit breaker on DB writes (5 failures/60s)
- get_me() caching (5-min TTL) + retry (3 attempts) + circuit breaker
- Listener watchdog (60s auto-restart)
- Heartbeat with dead letter monitoring
- Sentry integration (circuit breaker alerts)
- Prometheus-format metrics endpoint

---

## 3. 코드 품질 분석 결과

### 3.1 Backend Quality Score: 62/100

#### CRITICAL Issues (즉시 수정 필요)

| # | Issue | File | Detail |
|---|-------|------|--------|
| B-C1 | **God Class** | `live_crawler.py` (2776줄) | 30+ member variables, 7+ 책임 혼재. Phase 32D에서 일부 추출했으나 여전히 과대 |
| B-C2 | **Dynamic SQL** | `live_crawler.py:~2200` | `_update_crawler_status`에서 f-string으로 SQL 컬럼명 조합 — SQL injection 위험 (현재 내부값이지만 fragile) |
| B-C3 | **Token revocation bypass** | `auth.py:117-118` | DB 에러 시 `except Exception: pass` → 취소된 토큰이 통과될 수 있음 |
| B-C4 | **JWT in SSE URL** | `events.py:31` | EventSource query param으로 JWT 전달 → 서버 로그, 브라우저 히스토리에 노출 |
| B-C5 | **ILIKE wildcard injection** | `groups.py:331` | 검색어에서 `%`, `_` 미이스케이프 → 와일드카드 확장으로 전체 테이블 스캔 가능 |

#### WARNING Issues

| # | Issue | File | Detail |
|---|-------|------|--------|
| B-W1 | `get_user_groups_by_connection`에 `has_topics` 누락 | `telegram_client.py:735` | `get_user_groups`에는 있으나 connection variant에 없음 — forum 그룹 등록 시 `has_topics=False` |
| B-W2 | Duplicate dialog parsing | `telegram_client.py:561-611,716-745` | 거의 동일한 로직 2번 구현 |
| B-W3 | Duplicate error handling | `routes/auth.py:164-271` | `verify_code`/`verify_2fa`에 동일한 catch 블록 반복 |
| B-W4 | TelegramClient 생성 중복 | `live_crawler.py:296-389` | 동일 파라미터로 2번 생성, factory method 미사용 |
| B-W5 | Health endpoint 무인증 | `crawler_main.py:145-190` | 포트 8001 노출 시 내부 상태 누출 |
| B-W6 | Topics endpoint 5000행 스캔 | `groups.py:442-447` | `GROUP BY + COUNT(*)` 대신 5000행 SELECT → Python 집계 |
| B-W7 | COUNT(*) on every page | `queries/messages.py:104-106` | 페이지네이션마다 전체 카운트 — 대형 테이블에서 성능 저하 |
| B-W8 | Private attribute 접근 | `main.py:85`, `database.py:106` | `_warm_client`, `_pool._closed` 직접 접근 |
| B-W9 | f-string 로깅 | `routes/groups.py:37-92` | `logger.debug(f"...")` → lazy `%s` 미사용 |

### 3.2 Frontend Quality Score: 58/100

#### CRITICAL Issues

| # | Issue | File | Detail |
|---|-------|------|--------|
| F-C1 | **Auth tokens in localStorage** | `api.ts:57-60` | XSS 시 access+refresh 토큰 탈취 가능 |
| F-C2 | **SSE token in URL** | `useSSE.ts:92` | JWT가 URL query string에 노출 |
| F-C3 | **3개 모놀리스 페이지** | EventFeed(740줄), AdminDashboard(685줄), GroupSelection(708줄) | 20+ state 변수, 분리 필요 |

#### WARNING Issues

| # | Issue | File | Detail |
|---|-------|------|--------|
| F-W1 | SSE insert handler 중복 | EventFeed:171-209, AdminDashboard:138-169 | ~85% 유사 로직 반복 |
| F-W2 | Health check 중복 | AdminDashboard:73-83, CrawlerManagement:61-71 | 100% 동일 + raw `fetch` 사용 |
| F-W3 | Missing useMemo | AdminDashboard:342-352 (`groupMessagesByDate`), 357-372 (`filteredGroups`) | 매 render마다 재계산 |
| F-W4 | No code splitting | App.tsx:44-66 | 14개 페이지 전부 eager import |
| F-W5 | No virtualization | EventFeed:624-683 | 500 메시지 전체 DOM 렌더링 |
| F-W6 | Single ErrorBoundary | App.tsx:112 | 루트에만 1개 → 한 페이지 crash = 전체 다운 |
| F-W7 | Missing useEffect deps | AdminDashboard:87-91, EventFeed:99-105 | 종속성 누락 |
| F-W8 | `any` types | useSSE.ts:28-30, AdminDashboard:201, CrawlerManagement:78 | 타입 안전성 부족 |
| F-W9 | Accessibility | EventFeed:451-729 | aria-label 미설정, `<span role="button">` 등 |
| F-W10 | Operator precedence | GroupSelection:267 | `&&` vs `||` 우선순위 모호 |
| F-W11 | Hardcoded constants | EventFeed:34/198, AdminDashboard:155/284/214 | 매직넘버 산재 |

---

## 4. Gap Analysis 결과 (Overall: 77%)

### 4.1 Score Summary

| Category | Score | Status |
|----------|:-----:|:------:|
| Schema vs Code | 82% | ⚠️ |
| API Routes vs Frontend | 88% | ⚠️ |
| Models vs DB | 85% | ⚠️ |
| SSE vs Frontend | 95% | ✅ |
| Migrations vs Schema | 75% | ⚠️ |
| Config vs .env | 85% | ⚠️ |
| Error Handling | 80% | ⚠️ |
| Test Coverage | 25% | 🔴 |
| **Overall** | **77%** | ⚠️ |

### 4.2 P0 — 즉시 수정 필요

| # | Gap | Location | Impact |
|---|-----|----------|--------|
| G-P0-1 | **`RegisterGroupItem` missing `has_topics` field** | `models.py:173` → `groups.py:175`에서 `group_data.has_topics` 접근 | 런타임 `AttributeError` 가능 |
| G-P0-2 | **`user_statistics`/`group_statistics` view 미존재** | `admin/users.py:127,140` | 해당 엔드포인트 항상 500 에러 반환 |
| G-P0-3 | **Admin group deletion FK 누락** | `admin/groups.py:93-96` | `group_topics`, `connection_accessible_groups`, `failed_messages`, `private_group_invites` 테이블 미삭제 → FK violation |

### 4.3 P1 — 문서화/동기화 필요

| # | Gap | Detail |
|---|-----|--------|
| G-P1-1 | `schema_actual.sql`에 `group_topics` 테이블 누락 | Migration 006에서 추가됨 |
| G-P1-2 | `schema_actual.sql`에 `connection_accessible_groups` 테이블 누락 | Migration 007에서 추가됨 |
| G-P1-3 | `schema_actual.sql`에 `idx_messages_user_feed` 인덱스 누락 | Phase 27에서 추가됨 |
| G-P1-4 | `.env.example`에 `CRAWLER_API_PORT/SECRET/URL` 미기재 | `config.py`에는 정의됨 |
| G-P1-5 | Frontend `Message.sender_username` dead field | DB에서 제거됨 (Phase 25), api.ts에 남아있음 |
| G-P1-6 | Frontend `RegisteredGroup.description` dead field | DB에 해당 컬럼 없음 |

### 4.4 P2 — 코드 품질

| # | Gap | Detail |
|---|-----|--------|
| G-P2-1 | Test mock infrastructure 불일치 | `conftest.py`가 Supabase-py mock → 실제는 asyncpg |
| G-P2-2 | `MessageResponse` 모델에 `is_edited`, `message_source`, `media_thumbnail_url` 누락 | DB에는 존재 |
| G-P2-3 | 10개 Admin 엔드포인트 Frontend 미연결 | 구현됐으나 프론트엔드에서 호출 안 함 |
| G-P2-4 | Test coverage 25% | 라우트, SSE, 크롤러, 프론트엔드 테스트 0개 |

---

## 5. 인프라 & 운영 현황

### 5.1 Deployment

| Component | Method | Config |
|-----------|--------|--------|
| Backend API | systemd service | port 8000, --reload-dir app |
| Crawler | systemd service | port 8001 |
| Frontend | Vercel (auto-deploy from main) | vercel.json rewrites |
| Database | Supabase (managed) | Session pooler port 5432 |

### 5.2 Missing Infrastructure

| Item | Current | Needed |
|------|---------|--------|
| CI/CD | None | GitHub Actions (lint, test, type-check, deploy) |
| Dockerfile | None | Containerization for consistent deployment |
| Staging environment | None | Pre-production validation |
| DB backup automation | Supabase managed | Additional pg_dump for safety |
| Load testing | None | k6 or similar for crawler capacity planning |
| Frontend tests | 0 files | Vitest + Testing Library for critical flows |
| E2E tests | None | Playwright for login → group → event flow |

### 5.3 Security Audit Summary

**Good Practices (이미 적용됨):**
- PBKDF2 600K iterations for key derivation
- AAD binding on session encryption
- SecurityHeaders middleware
- Rate limiting on auth endpoints
- IDOR checks on group access
- Parameterized SQL queries throughout
- DegradedMode middleware

**Needs Improvement:**
- Token storage: localStorage → httpOnly cookies (refresh token)
- SSE auth: URL query param → short-lived ticket or cookie
- Token revocation: silent fail → fail-closed
- Health endpoint: unauthenticated on port 8001
- ILIKE wildcard: needs escaping

---

## 6. 개선 계획 (우선순위별)

### Phase 33: Critical Bug Fixes (P0)

> 예상: 1 session

| Task | Detail | Files |
|------|--------|-------|
| 33-1 | `RegisterGroupItem`에 `has_topics` 필드 추가 | models.py |
| 33-2 | `user_statistics`/`group_statistics` 뷰 생성 또는 엔드포인트 제거 | admin/users.py + migration |
| 33-3 | Admin group deletion FK cascade 보완 | admin/groups.py |
| 33-4 | `schema_actual.sql` 동기화 (group_topics, connection_accessible_groups, idx) | schema_actual.sql |
| 33-5 | `.env.example` 누락 변수 추가 | .env.example |

### Phase 34: Security Hardening (P0-P1)

> 예상: 2-3 sessions

| Task | Detail | Files |
|------|--------|-------|
| 34-1 | Token revocation fail-closed 전환 | auth.py |
| 34-2 | ILIKE wildcard escape | routes/groups.py |
| 34-3 | Dynamic SQL → fixed query | live_crawler.py |
| 34-4 | SSE short-lived ticket 도입 (optional) | events.py, useSSE.ts |
| 34-5 | Refresh token → httpOnly cookie (optional) | auth.py, api.ts |

### Phase 35: Backend Refactoring (P1)

> 예상: 3-4 sessions

| Task | Detail | Files |
|------|--------|-------|
| 35-1 | `LiveCrawlerService` 분해 → CrawlerClientManager, HistoricalCrawler, GapFillService, EventHandler, EntityCacheManager, MediaUploader | live_crawler.py → 6 modules |
| 35-2 | Duplicate dialog parsing 통합 | telegram_client.py |
| 35-3 | `has_topics` extraction 추가 (by_connection variant) | telegram_client.py |
| 35-4 | Auth error handling 중복 제거 | routes/auth.py |
| 35-5 | Topics endpoint 쿼리 최적화 (GROUP BY) | routes/groups.py |
| 35-6 | Cursor-based pagination 도입 | queries/messages.py |

### Phase 36: Frontend Refactoring (P1)

> 예상: 3-4 sessions

| Task | Detail | Files |
|------|--------|-------|
| 36-1 | EventFeed 분해 → MessageList, FeedHeader, useFeedMessages | EventFeed.tsx → 4 files |
| 36-2 | AdminDashboard 분해 → AdminSidebar, AdminMessageViewer, useAdminGroups | AdminDashboard.tsx → 4 files |
| 36-3 | GroupSelection 분해 → SelectStep, VisibilityStep, CompleteStep | GroupSelection.tsx → 4 files |
| 36-4 | `useSSEMessageSync` 공통 hook 추출 | new hook |
| 36-5 | useMemo/useCallback 최적화 | 각 페이지 |
| 36-6 | React.lazy code splitting | App.tsx |
| 36-7 | Per-page ErrorBoundary 추가 | App.tsx |
| 36-8 | Dead fields 정리 (sender_username, description) | api.ts |

### Phase 37: Test Infrastructure (P2)

> 예상: 3-4 sessions

| Task | Detail | Files |
|------|--------|-------|
| 37-1 | conftest.py mock 재구성 (asyncpg 호환) | tests/conftest.py |
| 37-2 | error_recovery.py + metrics.py 단위 테스트 | tests/test_error_recovery.py, test_metrics.py |
| 37-3 | Route 통합 테스트 (httpx TestClient) | tests/test_routes_*.py |
| 37-4 | Frontend Vitest 설정 + 핵심 hook 테스트 | client/tests/ |
| 37-5 | GitHub Actions CI 파이프라인 | .github/workflows/ |

### Phase 38: Operational Excellence (P2)

> 예상: 2 sessions

| Task | Detail | Files |
|------|--------|-------|
| 38-1 | Dockerfile 생성 (backend + crawler) | Dockerfile |
| 38-2 | docker-compose.yml (local dev) | docker-compose.yml |
| 38-3 | Accessibility 개선 (aria-labels, keyboard nav) | Frontend pages |
| 38-4 | Hardcoded constants → named constants | 전체 |
| 38-5 | `any` types 제거 | Frontend hooks + pages |

---

## 7. 아키텍처 개선 로드맵 (장기)

### 7.1 LiveCrawlerService 분해 구상

```
LiveCrawlerService (orchestrator, ~500 lines)
├── CrawlerClientManager       — client lifecycle, entity cache
├── EventHandler               — NewMessage, Edited, Deleted, ChatAction
├── HistoricalCrawler          — batch crawl, historical backfill
├── GapFillService             — periodic gap detection + fill
├── MediaUploader              — download, resize, upload to storage
├── ErrorRecovery (done)       — get_me cache, retry, circuit breaker
└── MessageMetrics (done)      — tracking, sampling, per-group stats
```

### 7.2 Frontend State Management

```
Current: 20+ useState per page
Target:  Custom hooks per concern

EventFeed
├── useFeedMessages()          — load, paginate, SSE sync
├── useFeedSearch()            — debounced search
├── useFeedGroups()            — group selection, topic filter
└── useFeedUI()                — lightbox, keyboard shortcuts

AdminDashboard
├── useAdminGroups()           — group list, search, filter
├── useAdminMessages()         — message viewer, pagination
├── useAdminCrawler()          — crawler status, polling
└── useAdminSSE()              — SSE connection, dedup
```

---

## 8. 결정 필요 사항

사용자 결정 후 Plan 수정 예정:

1. **Phase 33 즉시 진행 여부** — P0 버그 3개 (has_topics, views, FK cascade) 먼저 수정?
2. **Security hardening 범위** — SSE ticket + httpOnly cookie까지 할 건지, token revocation + ILIKE만?
3. **Backend refactoring 전략** — LiveCrawlerService 점진적 분해 vs 한번에?
4. **Frontend refactoring 순서** — EventFeed 먼저? AdminDashboard 먼저?
5. **Test 우선순위** — 단위 테스트 먼저? CI 파이프라인 먼저?
6. **`user_statistics`/`group_statistics`** — 뷰 생성할 건지 엔드포인트 제거할 건지?

---

## Appendix A: File Inventory

### Backend

| File | Lines | Responsibility |
|------|-------|---------------|
| `app/live_crawler.py` | 2776 | Core crawler logic (event handlers, historical crawl, gap-fill, media, status) |
| `app/telegram_client.py` | 782 | Telethon wrapper (session mgmt, dialogs, groups, send code/verify) |
| `app/main.py` | 500 | FastAPI app (middleware, health, metrics, startup) |
| `crawler_main.py` | 390 | Crawler process entry (lifespan, batch crawl, health) |
| `app/sse.py` | 275 | SSE manager (LISTEN, fan-out, reconnect, ping, overflow) |
| `app/database.py` | 178 | asyncpg pool management (connect, retry, execute, fetch) |
| `app/config.py` | 136 | Settings (env vars, validation, CORS) |
| `app/models.py` | 240 | Pydantic models (User, Group, Message, Auth requests) |
| `app/error_recovery.py` | 200 | get_me cache, retry, circuit breaker (Phase 32D) |
| `app/metrics.py` | 150 | Message metrics tracking, sampling (Phase 32D) |
| `app/auth.py` | 190 | JWT creation, verification, revocation check |
| `app/encryption.py` | 120 | AES-GCM session encryption |
| `app/crawler_client.py` | 180 | HTTP client for crawler API |
| `app/routes/groups.py` | 800+ | Group CRUD, topics, search, crawl progress, invite links |
| `app/routes/auth.py` | 600+ | Login flow (send_code, verify_code, verify_2fa, refresh) |
| `app/routes/events.py` | 120 | SSE event stream endpoint |
| `app/routes/admin/groups.py` | 250 | Admin group management |
| `app/routes/admin/messages.py` | 200 | Admin message management + dead letter retry |
| `app/routes/admin/crawler.py` | 200 | Crawler control endpoints |
| `app/routes/admin/users.py` | 150 | User management + statistics |
| `app/routes/admin/credentials.py` | 130 | Admin credential management |

### Frontend

| File | Lines | Responsibility |
|------|-------|---------------|
| `pages/EventFeed.tsx` | 740 | User message feed (SSE, search, lightbox, keyboard) |
| `pages/GroupSelection.tsx` | 708 | 3-step group registration wizard |
| `pages/AdminDashboard.tsx` | 685 | Admin panel (groups, messages, crawler, connections) |
| `pages/CrawlerManagement.tsx` | 600 | Crawler control UI |
| `pages/GroupSettings.tsx` | 300 | Group visibility and settings |
| `pages/UserManagement.tsx` | 340 | User admin page |
| `pages/Signup.tsx` | 200 | Registration flow |
| `pages/Login.tsx` | 110 | Login flow |
| `pages/EmailLinking.tsx` | 195 | Email account linking |
| `pages/UnmappedGroups.tsx` | 270 | Groups without connection mapping |
| `lib/api.ts` | 700+ | API client (axios, auth, interceptors, retry) |
| `hooks/useSSE.ts` | 180 | SSE connection management |
| `hooks/useMessageSearch.ts` | 89 | Debounced message search |
| `hooks/useInfiniteScroll.ts` | 53 | IntersectionObserver pagination |
| `hooks/useKeyboardShortcuts.ts` | 45 | Keyboard shortcut handling |

### Database (7 migrations applied)

| Migration | Tables/Changes |
|-----------|---------------|
| 001 | `auth_user_id` on users, `telegram_connections` table |
| 002 | Email linking tables |
| 003 | `message_source` column on messages |
| 004 | `connection_id` on user_groups (multi-telegram) |
| 005 | Timestamp backfill (data migration) |
| 006 | `group_topics` table |
| 007 | `connection_accessible_groups` table |

---

## Appendix B: Duplicate Code Map

| Type | Location 1 | Location 2 | Similarity | Action |
|------|-----------|-----------|:----------:|--------|
| Exact | AdminDashboard:73-83 | CrawlerManagement:61-71 | 100% | → shared util |
| Structural | AdminDashboard:138-169 (SSE insert) | EventFeed:171-209 (SSE insert) | ~85% | → useSSEMessageSync hook |
| Structural | AdminDashboard:171-186 (SSE update/delete) | EventFeed:211-223 | ~90% | → same hook |
| Structural | telegram_client:561-611 (get_user_groups) | telegram_client:716-745 (by_connection) | ~80% | → _parse_dialogs helper |
| Structural | auth.py:164-200 (verify_code catch) | auth.py:240-271 (verify_2fa catch) | ~90% | → shared error handler |
