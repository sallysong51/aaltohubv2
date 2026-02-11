---
template: plan
version: 1.2
feature: event-management-system
date: 2026-02-11
author: Claude Sonnet 4.5
project: AALTOHUBv2
status: Draft
---

# Event Management System Planning Document

> **Summary**: AI 기반 텔레그램 이벤트 자동 분류 및 관리 시스템
>
> **Project**: AALTOHUBv2
> **Version**: 2.0
> **Author**: Claude Sonnet 4.5
> **Date**: 2026-02-11
> **Status**: Draft

---

## 1. Overview

### 1.1 Purpose

**텔레그램 메시지를 실시간으로 수집하여 AI 기반으로 자동 분류하고, 이벤트 정보만 추출하여 사용자에게 제공하는 지능형 관리 시스템**

현재 시스템은 모든 텔레그램 메시지를 동일하게 저장하지만, 실제로 사용자가 필요한 것은:
- **이벤트성 메시지** (모임, 세미나, 공지사항 등)
- **정보성 메시지** (공유 자료, 링크, 뉴스 등)

일반 잡담과 이벤트를 자동으로 구분하여, 사용자는 중요한 정보만 빠르게 확인할 수 있습니다.

### 1.2 Background

**현재 시스템의 한계:**
1. ❌ 모든 메시지가 동일하게 저장됨 (이벤트 vs 잡담 구분 없음)
2. ❌ 사용자가 수동으로 필터링해야 함
3. ❌ 그룹별 맥락(context) 정보가 없음
4. ❌ AI 분류 시스템 부재
5. ❌ 프롬프트 관리 기능 없음

**비즈니스 요구사항:**
- 사용자는 "오늘 새로운 이벤트"만 보고 싶어함
- 관리자는 AI 분류 품질을 개선하고 싶어함 (프롬프트 튜닝)
- 시스템 전체 플로우를 한눈에 모니터링하고 싶어함

### 1.3 Related Documents

- 기존 시스템 분석: `docs/01-plan/aaltohub-v2-system-plan.md`
- MEMORY.md: Phase 32D까지 완료 (Code Refactoring - Modular Design)
- 참고: `backend/app/live_crawler.py` (2500 lines, 메시지 수집 로직)

---

## 2. Scope

### 2.1 In Scope

**Phase 1: AI 분류 엔진 (핵심)**
- [x] LLM API 연동 (OpenAI GPT-4 또는 Anthropic Claude)
- [x] 메시지 분류 로직 (이벤트 vs 정보 vs 잡담)
- [x] 분류 결과 DB 저장 (`message_category`, `ai_confidence`)
- [x] 그룹별 맥락(context) 수집 및 활용

**Phase 2: 프롬프트 관리 시스템**
- [x] 프롬프트 CRUD API (Create, Read, Update, Delete)
- [x] 프롬프트 버전 관리 (v1, v2, ...)
- [x] A/B 테스트 기능 (프롬프트 비교)
- [x] 관리자 UI (`/admin/prompts`)

**Phase 3: 프로세스 시각화**
- [x] 실시간 플로우 차트 (크롤링 → AI 분류 → 저장)
- [x] 상태 모니터링 대시보드
- [x] 병목 지점 표시 (처리 속도, 에러율)

**Phase 4: 이벤트 상세 페이지 개선**
- [x] 원본 메시지 미리보기
- [x] AI 분류 결과 표시 (카테고리, 신뢰도)
- [x] 그룹 맥락 정보 표시
- [x] 관련 이벤트 추천

**Phase 5: 이벤트 수집 대시보드**
- [x] 시간대별/그룹별 통계
- [x] AI 분류 정확도 모니터링
- [x] 에러 로그 및 알림
- [x] 성능 메트릭 (처리 속도, API 비용)

### 2.2 Out of Scope

- ❌ 이벤트 자동 등록 (캘린더 연동) → v3.0 이후
- ❌ 사용자별 개인화 추천 → v3.0 이후
- ❌ 다국어 지원 (영어, 일본어) → v2.5 이후
- ❌ 모바일 앱 → 별도 프로젝트

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| **FR-01** | 실시간 메시지 AI 분류 (이벤트/정보/잡담) | High | Pending |
| **FR-02** | 분류 신뢰도(confidence) 저장 (0-100%) | High | Pending |
| **FR-03** | 프롬프트 CRUD API 구현 | High | Pending |
| **FR-04** | 프롬프트 버전 관리 (git-like) | Medium | Pending |
| **FR-05** | A/B 테스트 기능 (프롬프트 비교) | Medium | Pending |
| **FR-06** | 실시간 플로우 차트 UI | Medium | Pending |
| **FR-07** | 프로세스 상태 모니터링 API | High | Pending |
| **FR-08** | 이벤트 상세 페이지 (미리보기) | High | Pending |
| **FR-09** | 통계 대시보드 (시간대별/그룹별) | Medium | Pending |
| **FR-10** | 그룹별 맥락(context) 자동 수집 | High | Pending |
| **FR-11** | AI 비용 추적 (토큰 사용량) | Medium | Pending |
| **FR-12** | 에러 알림 시스템 (Sentry 연동) | Low | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| **Performance** | AI 분류 처리 < 2초/메시지 | Prometheus 메트릭 |
| **Scalability** | 동시 100개 그룹 처리 가능 | 부하 테스트 |
| **Reliability** | AI API 실패 시 재시도 (3회) | 에러 로그 분석 |
| **Security** | LLM API 키 암호화 저장 | 코드 리뷰 |
| **Cost** | AI 비용 < $100/월 | 토큰 사용량 모니터링 |
| **Accuracy** | 분류 정확도 > 85% | 수동 레이블링 샘플 비교 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [x] FR-01~FR-12 모든 기능 구현
- [x] AI 분류 정확도 85% 이상 달성
- [x] 프롬프트 관리 UI 완성
- [x] 대시보드 실시간 업데이트 작동
- [x] Unit tests 작성 및 통과 (coverage > 70%)
- [x] Code review 완료
- [x] Documentation 완료 (API 문서 + 사용자 가이드)

### 4.2 Quality Criteria

- [x] Test coverage above 70%
- [x] Zero critical security vulnerabilities
- [x] API response time < 500ms (AI 제외)
- [x] Build succeeds without warnings
- [x] ESLint/Prettier 통과

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **LLM API 비용 초과** | High | Medium | 1) 캐싱 전략 (동일 메시지 재분류 방지), 2) 일일 한도 설정, 3) 규칙 기반 pre-filter |
| **LLM API 장애** | High | Low | 1) 재시도 로직 (3회), 2) 대기열 시스템, 3) 대체 API 준비 (OpenAI ↔ Claude) |
| **분류 정확도 낮음** | High | Medium | 1) 프롬프트 엔지니어링, 2) Few-shot 예제 추가, 3) 사용자 피드백 수집 |
| **성능 병목 (AI 처리 느림)** | Medium | High | 1) 비동기 처리, 2) 배치 처리 (10개씩), 3) 우선순위 큐 |
| **프롬프트 버전 충돌** | Low | Low | Git-like 버전 관리 시스템 구현 |
| **데이터 마이그레이션 복잡도** | Medium | Medium | 1) 기존 메시지 재분류 스크립트, 2) 단계별 배포 |

---

## 6. Architecture Considerations

### 6.1 Project Level Selection

| Level | Characteristics | Recommended For | Selected |
|-------|-----------------|-----------------|:--------:|
| **Starter** | Simple structure (`components/`, `lib/`, `types/`) | Static sites, portfolios, landing pages | ☐ |
| **Dynamic** | Feature-based modules, BaaS integration (bkend.ai) | Web apps with backend, SaaS MVPs, fullstack apps | ☑ |
| **Enterprise** | Strict layer separation, DI, microservices | High-traffic systems, complex architectures | ☐ |

**선택 근거:** AALTOHUBv2는 이미 Dynamic 레벨로 구현되어 있음 (FastAPI + React, Feature-based modules)

### 6.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| **LLM API** | OpenAI GPT-4 / Anthropic Claude / Both | **Claude 3.5 Sonnet** | 1) 한국어 성능 우수, 2) 비용 효율적 ($3/M tokens), 3) 긴 컨텍스트 (200K) |
| **프롬프트 저장** | JSON file / Database / Git | **Database** | 버전 관리 + API 연동 용이 |
| **분류 전략** | Realtime / Batch / Hybrid | **Hybrid** | 중요 이벤트는 즉시, 일반 메시지는 배치 |
| **캐싱** | Redis / In-memory / None | **In-memory (LRU)** | 간단하고 빠름, 재시작 시 초기화 OK |
| **상태 관리** | Context / Zustand / Redux | **Zustand** | 이미 사용 중, 간결함 |
| **차트 라이브러리** | Chart.js / Recharts / D3.js | **Recharts** | React 친화적, 타입스크립트 지원 |
| **실시간 업데이트** | SSE / WebSocket / Polling | **SSE (기존)** | 이미 구현됨, 단방향 통신 충분 |

### 6.3 Clean Architecture Approach

```
Selected Level: Dynamic

신규 폴더 구조:
┌─────────────────────────────────────────────────────┐
│ backend/app/                                        │
│   ├── ai/                      # 새로 추가          │
│   │   ├── classifier.py        # AI 분류 엔진       │
│   │   ├── prompt_manager.py    # 프롬프트 관리      │
│   │   ├── context_collector.py # 맥락 수집          │
│   │   └── models.py            # AI 관련 데이터 모델│
│   ├── routes/                                       │
│   │   ├── admin/                                    │
│   │   │   └── prompts.py       # 프롬프트 CRUD API  │
│   │   └── events.py            # 이벤트 상세 API    │
│   └── services/                                     │
│       └── classification_service.py # 분류 서비스   │
│                                                      │
│ client/src/                                         │
│   ├── features/                                     │
│   │   └── event-intelligence/  # 새로 추가          │
│   │       ├── components/                           │
│   │       │   ├── ProcessFlow.tsx                   │
│   │       │   ├── PromptManager.tsx                 │
│   │       │   └── EventDetailCard.tsx               │
│   │       ├── pages/                                │
│   │       │   ├── CollectionDashboard.tsx           │
│   │       │   └── PromptManagement.tsx              │
│   │       └── hooks/                                │
│   │           ├── useClassification.ts              │
│   │           └── usePromptVersions.ts              │
│   └── lib/                                          │
│       └── ai-client.ts         # LLM API 클라이언트 │
└─────────────────────────────────────────────────────┘
```

### 6.4 데이터베이스 스키마 변경

```sql
-- 1. messages 테이블에 AI 분류 컬럼 추가
ALTER TABLE messages ADD COLUMN message_category TEXT;  -- 'event', 'info', 'chat'
ALTER TABLE messages ADD COLUMN ai_confidence REAL;     -- 0.0 ~ 1.0
ALTER TABLE messages ADD COLUMN classified_at TIMESTAMPTZ;
ALTER TABLE messages ADD COLUMN prompt_version_id INT REFERENCES prompts(id);

-- 2. 프롬프트 관리 테이블
CREATE TABLE prompts (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  version TEXT NOT NULL,  -- 'v1.0.0'
  content TEXT NOT NULL,  -- 실제 프롬프트 텍스트
  is_active BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  created_by INT REFERENCES users(id),
  UNIQUE(name, version)
);

-- 3. 그룹 맥락(context) 테이블
CREATE TABLE group_contexts (
  id SERIAL PRIMARY KEY,
  group_id BIGINT REFERENCES groups(id),
  context_type TEXT,  -- 'description', 'keywords', 'event_patterns'
  content JSONB,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. AI 분류 통계 테이블
CREATE TABLE classification_stats (
  id SERIAL PRIMARY KEY,
  date DATE NOT NULL,
  group_id BIGINT REFERENCES groups(id),
  category TEXT,  -- 'event', 'info', 'chat'
  count INT DEFAULT 0,
  avg_confidence REAL,
  UNIQUE(date, group_id, category)
);
```

---

## 7. Convention Prerequisites

### 7.1 Existing Project Conventions

Check which conventions already exist in the project:

- [x] `CLAUDE.md` 없음 (MEMORY.md만 존재)
- [x] `docs/01-plan/conventions.md` 없음
- [ ] `CONVENTIONS.md` 없음
- [x] ESLint configuration (`.eslintrc.*`) - 프론트엔드에만 존재
- [x] Prettier configuration (`.prettierrc`) - 있음
- [x] TypeScript configuration (`tsconfig.json`) - 있음

### 7.2 Conventions to Define/Verify

| Category | Current State | To Define | Priority |
|----------|---------------|-----------|:--------:|
| **Naming** | 일부 존재 | AI 모듈 네이밍 규칙 (`ai_*.py`, `*_classifier.py`) | High |
| **Folder structure** | Dynamic 레벨 | `backend/app/ai/` 폴더 구조 명확화 | High |
| **Import order** | ESLint로 부분 관리 | Backend import 순서 (stdlib → 3rd-party → local) | Medium |
| **Environment variables** | `.env.example` 존재 | AI API 키 추가 (`ANTHROPIC_API_KEY`) | High |
| **Error handling** | Sentry 연동됨 | AI API 에러 처리 패턴 정의 | High |
| **Prompt versioning** | 없음 | Git-like 버전 관리 규칙 (semver) | Medium |

### 7.3 Environment Variables Needed

| Variable | Purpose | Scope | To Be Created |
|----------|---------|-------|:-------------:|
| `ANTHROPIC_API_KEY` | Claude API 인증 | Server | ☑ |
| `OPENAI_API_KEY` | GPT-4 fallback (선택) | Server | ☐ |
| `AI_MODEL_NAME` | 사용할 모델명 | Server | ☑ |
| `AI_MAX_TOKENS` | 최대 토큰 수 | Server | ☑ |
| `AI_TEMPERATURE` | 생성 온도 (0.0~1.0) | Server | ☑ |
| `AI_CACHE_TTL` | 캐시 유지 시간 (초) | Server | ☑ |
| `AI_BATCH_SIZE` | 배치 처리 크기 | Server | ☑ |
| `AI_COST_LIMIT_DAILY` | 일일 비용 한도 ($) | Server | ☑ |

**예시 `.env` 추가 내용:**
```bash
# AI Classification
ANTHROPIC_API_KEY=sk-ant-api03-xxx
AI_MODEL_NAME=claude-3-5-sonnet-20241022
AI_MAX_TOKENS=1024
AI_TEMPERATURE=0.3
AI_CACHE_TTL=3600
AI_BATCH_SIZE=10
AI_COST_LIMIT_DAILY=10.0
```

### 7.4 Pipeline Integration

**참고:** 이 프로젝트는 9-phase Development Pipeline을 사용하지 않고, PDCA 사이클을 사용합니다.

| Phase | Status | Document Location | Command |
|-------|:------:|-------------------|---------|
| Plan | 🔄 In Progress | `docs/01-plan/features/event-management-system.plan.md` | `/pdca plan` |
| Design | ☐ Pending | `docs/02-design/features/event-management-system.design.md` | `/pdca design` |
| Do | ☐ Pending | (Implementation) | `/pdca do` |
| Check | ☐ Pending | `docs/03-analysis/event-management-system.analysis.md` | `/pdca analyze` |
| Act | ☐ Pending | (Iteration) | `/pdca iterate` |

---

## 8. Implementation Phases

### Phase 1: AI 분류 엔진 (Week 1-2)

**Goal:** 메시지를 AI로 분류하는 핵심 로직 구현

**Tasks:**
1. `backend/app/ai/classifier.py` 구현
   - Anthropic API 연동
   - 분류 로직 (이벤트/정보/잡담)
   - 재시도 로직 (3회)
   - 에러 핸들링
2. `backend/app/ai/prompt_manager.py` 구현
   - 기본 프롬프트 정의
   - 프롬프트 로딩 로직
3. DB 마이그레이션
   - `messages` 테이블 컬럼 추가
   - `prompts` 테이블 생성
4. Unit tests 작성
5. 수동 테스트 (샘플 메시지 100개)

**Success Criteria:**
- 분류 정확도 > 80%
- 처리 시간 < 2초/메시지
- 에러율 < 1%

### Phase 2: 프롬프트 관리 (Week 3)

**Goal:** 관리자가 프롬프트를 관리할 수 있는 시스템 구현

**Tasks:**
1. `backend/app/routes/admin/prompts.py` 구현
   - CRUD API
   - 버전 관리 API
2. `client/src/features/event-intelligence/pages/PromptManagement.tsx` 구현
   - 프롬프트 목록
   - 프롬프트 편집기
   - 버전 비교 UI
3. A/B 테스트 로직 구현
4. Integration tests

**Success Criteria:**
- 프롬프트 생성/수정/삭제 작동
- 버전 롤백 가능
- A/B 테스트 결과 확인 가능

### Phase 3: 프로세스 시각화 (Week 4)

**Goal:** 시스템 전체 플로우를 시각화

**Tasks:**
1. `client/src/features/event-intelligence/components/ProcessFlow.tsx` 구현
   - Recharts로 플로우 차트
   - 실시간 상태 업데이트
2. `backend/app/routes/admin/stats.py` 구현
   - 프로세스 통계 API
3. SSE 연동 (실시간 업데이트)

**Success Criteria:**
- 플로우 차트 실시간 업데이트
- 병목 지점 식별 가능
- 에러 지점 시각화

### Phase 4: 이벤트 상세 페이지 (Week 5)

**Goal:** 이벤트 미리보기 및 상세 정보 제공

**Tasks:**
1. `client/src/features/event-intelligence/components/EventDetailCard.tsx` 구현
   - 원본 메시지 표시
   - AI 분류 결과 표시
   - 신뢰도 시각화
2. `backend/app/routes/events.py` 개선
   - 관련 이벤트 추천 API
3. 그룹 맥락 표시

**Success Criteria:**
- 미리보기 로딩 < 200ms
- 관련 이벤트 정확도 > 70%

### Phase 5: 대시보드 (Week 6)

**Goal:** 통합 대시보드 구현

**Tasks:**
1. `client/src/features/event-intelligence/pages/CollectionDashboard.tsx` 구현
   - 시간대별 통계
   - 그룹별 통계
   - AI 비용 추적
   - 에러 로그
2. `backend/app/services/classification_service.py` 구현
   - 통계 계산 로직
3. Prometheus 메트릭 추가

**Success Criteria:**
- 대시보드 로딩 < 1초
- 실시간 업데이트 (30초 간격)
- 비용 추적 정확도 100%

---

## 9. Testing Strategy

### 9.1 Unit Tests

**Backend:**
- `tests/ai/test_classifier.py` - AI 분류 로직
- `tests/ai/test_prompt_manager.py` - 프롬프트 관리
- `tests/services/test_classification_service.py` - 분류 서비스

**Frontend:**
- `tests/components/ProcessFlow.test.tsx` - 플로우 차트
- `tests/components/EventDetailCard.test.tsx` - 이벤트 상세
- `tests/hooks/useClassification.test.ts` - 분류 훅

### 9.2 Integration Tests

- AI API 연동 테스트
- 프롬프트 버전 관리 테스트
- SSE 실시간 업데이트 테스트

### 9.3 E2E Tests (선택)

- 관리자가 프롬프트를 수정하고 분류 결과가 바뀌는지 확인
- 대시보드에서 통계가 정확한지 확인

### 9.4 Performance Tests

- 100개 메시지 동시 분류 테스트
- AI API 부하 테스트
- 대시보드 렌더링 성능 테스트

---

## 10. Cost Estimation

### 10.1 AI API 비용 (월간)

**가정:**
- 일일 메시지 수: 1,000개
- 평균 메시지 길이: 200 tokens
- Claude 3.5 Sonnet 비용: $3/M input tokens, $15/M output tokens
- 평균 출력: 50 tokens

**계산:**
```
Input:  1,000 msgs/day × 30 days × 200 tokens × $3/M = $18/month
Output: 1,000 msgs/day × 30 days × 50 tokens × $15/M = $22.5/month
Total: ~$40/month
```

**최적화 전략:**
1. 캐싱 (동일 메시지 재분류 방지) → 30% 절감
2. 규칙 기반 pre-filter (명확한 잡담 제거) → 20% 절감
3. 배치 처리 (API 호출 횟수 감소) → 10% 절감

**예상 실제 비용: $20-30/month**

### 10.2 개발 시간 (추정)

| Phase | Estimated Time | Developer |
|-------|----------------|-----------|
| Phase 1 (AI 엔진) | 40 hours | Backend Dev |
| Phase 2 (프롬프트 관리) | 24 hours | Fullstack Dev |
| Phase 3 (시각화) | 16 hours | Frontend Dev |
| Phase 4 (상세 페이지) | 16 hours | Frontend Dev |
| Phase 5 (대시보드) | 24 hours | Fullstack Dev |
| Testing & QA | 20 hours | QA Engineer |
| **Total** | **140 hours** | **~3.5 weeks (1 dev)** |

---

## 11. Next Steps

1. [x] **Plan 문서 검토 및 승인**
   - 사용자 확인
   - 팀 리뷰 (있다면)

2. [ ] **Design 문서 작성** (`/pdca design event-management-system`)
   - API 명세서
   - DB 스키마 상세
   - UI/UX 와이어프레임
   - 시퀀스 다이어그램

3. [ ] **환경 설정**
   - Anthropic API 키 발급
   - `.env` 파일 업데이트
   - DB 마이그레이션 실행

4. [ ] **Phase 1 구현 시작** (`/pdca do event-management-system`)
   - AI 분류 엔진 구현
   - Unit tests 작성

---

## 12. Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-02-11 | Initial draft | Claude Sonnet 4.5 |

---

## 13. Appendix

### A. 참고 자료

- **Claude API Documentation**: https://docs.anthropic.com/claude/reference/getting-started-with-the-api
- **Prompt Engineering Guide**: https://docs.anthropic.com/claude/docs/intro-to-prompting
- **Recharts Documentation**: https://recharts.org/en-US/

### B. 예시 프롬프트 (v1.0.0)

```
당신은 텔레그램 메시지를 분류하는 AI 전문가입니다.

주어진 메시지를 다음 3가지 카테고리 중 하나로 분류하세요:
1. event - 오프라인/온라인 모임, 세미나, 공지사항 등
2. info - 뉴스, 자료 공유, 링크, 정보성 메시지
3. chat - 일반 대화, 인사, 잡담

응답 형식 (JSON):
{
  "category": "event" | "info" | "chat",
  "confidence": 0.95,  // 0.0 ~ 1.0
  "reasoning": "이벤트 날짜(3월 15일)와 장소(강남역)가 명시되어 있음"
}

메시지:
"""
{message_text}
"""

그룹 맥락:
"""
{group_context}
"""
```

### C. 기술 스택 요약

**Backend:**
- FastAPI 0.104+
- asyncpg (PostgreSQL)
- anthropic 0.8+ (Claude SDK)
- pydantic 2.0+ (데이터 검증)

**Frontend:**
- React 18
- TypeScript 5+
- Zustand (상태 관리)
- Recharts (차트)
- shadcn/ui (UI 컴포넌트)

**Infrastructure:**
- Supabase PostgreSQL
- Sentry (에러 추적)
- Prometheus (메트릭)
