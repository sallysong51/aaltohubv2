# AaltoHub v2 - 성능 최적화 계획

**날짜:** 2026-02-05  
**현재 성능:**
- Frontend 로드: ~2.5초
- API 응답: ~1.9초
- 총 로드 시간: ~4.4초

**목표:**
- Frontend 로드: <1초
- API 응답: <500ms
- 총 로드 시간: <1.5초

---

## 🎯 최적화 전략

### 1. 프론트엔드 최적화

#### 1.1 코드 분할 (Code Splitting)
**현재 문제:** 모든 JavaScript가 한 번에 로드됨

**해결책:**
```javascript
// React.lazy()를 사용한 동적 import
const LoginPage = React.lazy(() => import('./pages/LoginPage'));
const EventsPage = React.lazy(() => import('./pages/EventsPage'));
```

**예상 개선:** 초기 로드 시간 40% 감소

#### 1.2 이미지 최적화
**현재 문제:** 최적화되지 않은 이미지

**해결책:**
- WebP 포맷 사용
- 이미지 lazy loading
- Responsive images (srcset)

```html
<img 
  src="image.webp" 
  loading="lazy"
  srcset="image-small.webp 480w, image-large.webp 1080w"
  alt="..."
/>
```

**예상 개선:** 페이지 크기 60% 감소

#### 1.3 CSS 최적화
**현재 문제:** 사용하지 않는 CSS 포함

**해결책:**
- PurgeCSS로 미사용 CSS 제거
- Critical CSS inline
- CSS minification

**예상 개선:** CSS 크기 70% 감소

#### 1.4 JavaScript 최적화
**현재 문제:** 번들 크기가 큼

**해결책:**
- Tree shaking
- Minification
- Compression (Brotli)

**예상 개선:** JS 크기 50% 감소

---

### 2. 백엔드 API 최적화

#### 2.1 응답 캐싱
**현재 문제:** 모든 요청이 데이터베이스 조회

**해결책:**
```python
from functools import lru_cache
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend

# 메모리 캐싱
@lru_cache(maxsize=128)
def get_events_cached():
    return get_events_from_db()

# Redis 캐싱 (프로덕션)
@cache(expire=300)  # 5분 캐시
async def get_events():
    return await get_events_from_db()
```

**예상 개선:** API 응답 시간 80% 감소

#### 2.2 데이터베이스 쿼리 최적화
**현재 문제:** N+1 쿼리 문제

**해결책:**
```python
# Before: N+1 queries
events = db.query(Event).all()
for event in events:
    event.registrations  # 각 이벤트마다 쿼리 실행

# After: 1 query with join
events = db.query(Event).options(
    joinedload(Event.registrations)
).all()
```

**예상 개선:** 쿼리 시간 90% 감소

#### 2.3 데이터베이스 인덱스
**현재 문제:** 인덱스 부족

**해결책:**
```sql
-- 자주 조회되는 컬럼에 인덱스 추가
CREATE INDEX idx_events_start_time ON events(start_time);
CREATE INDEX idx_events_category ON events(category_id);
CREATE INDEX idx_messages_group_id ON messages(group_id);
CREATE INDEX idx_messages_created_at ON messages(created_at);
```

**예상 개선:** 검색 속도 95% 향상

#### 2.4 Connection Pooling
**현재 문제:** 매 요청마다 새 DB 연결

**해결책:**
```python
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True
)
```

**예상 개선:** 연결 시간 70% 감소

---

### 3. 네트워크 최적화

#### 3.1 CDN 사용
**현재 문제:** 모든 파일이 Vercel에서 직접 제공

**해결책:**
- Cloudflare CDN 설정
- 정적 파일 캐싱
- Edge caching

**예상 개선:** 전 세계 로드 시간 60% 감소

#### 3.2 HTTP/2 및 HTTP/3
**현재 문제:** HTTP/1.1 사용

**해결책:**
- Vercel은 자동으로 HTTP/2 지원
- Cloudflare를 통한 HTTP/3 활성화

**예상 개선:** 동시 요청 처리 속도 향상

#### 3.3 Compression
**현재 문제:** 압축되지 않은 응답

**해결책:**
```python
from fastapi.middleware.gzip import GZipMiddleware

app.add_middleware(GZipMiddleware, minimum_size=1000)
```

**예상 개선:** 전송 크기 70% 감소

---

### 4. Vercel 최적화

#### 4.1 Edge Functions
**현재 문제:** Serverless Functions가 cold start 발생

**해결책:**
```javascript
// vercel.json
{
  "functions": {
    "api/**/*.js": {
      "memory": 1024,
      "maxDuration": 10
    }
  }
}
```

**예상 개선:** Cold start 시간 50% 감소

#### 4.2 Static Generation
**현재 문제:** 모든 페이지가 동적 렌더링

**해결책:**
- 정적 페이지는 빌드 시 생성
- ISR (Incremental Static Regeneration) 사용

**예상 개선:** 페이지 로드 시간 90% 감소

---

## 📊 구현 우선순위

### 🔴 High Priority (즉시 구현)
1. **데이터베이스 인덱스 추가** - 가장 큰 성능 향상
2. **API 응답 캐싱** - 백엔드 부하 감소
3. **이미지 최적화** - 페이지 크기 감소
4. **Compression 활성화** - 전송 크기 감소

### 🟡 Medium Priority (1주일 내)
5. **코드 분할** - 초기 로드 시간 감소
6. **CDN 설정** - 전 세계 성능 향상
7. **Connection Pooling** - DB 연결 최적화
8. **쿼리 최적화** - N+1 문제 해결

### 🟢 Low Priority (1개월 내)
9. **CSS 최적화** - 추가 크기 감소
10. **Edge Functions** - Cold start 개선
11. **Static Generation** - 정적 페이지 최적화
12. **Redis 캐싱** - 고급 캐싱 전략

---

## 🛠️ 즉시 적용 가능한 최적화

### 1. 데이터베이스 인덱스 추가 (5분)
```sql
-- SQL 프록시를 통해 실행
CREATE INDEX IF NOT EXISTS idx_events_start_time ON events(start_time);
CREATE INDEX IF NOT EXISTS idx_events_category ON events(category_id);
CREATE INDEX IF NOT EXISTS idx_messages_group_id ON messages(group_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_event_registrations_event_id ON event_registrations(event_id);
CREATE INDEX IF NOT EXISTS idx_event_registrations_user_id ON event_registrations(user_id);
```

### 2. FastAPI Compression 활성화 (2분)
```python
# backend/app/main.py
from fastapi.middleware.gzip import GZipMiddleware

app.add_middleware(GZipMiddleware, minimum_size=1000)
```

### 3. Vercel 함수 메모리 증가 (1분)
```json
// vercel.json
{
  "functions": {
    "api/**/*.js": {
      "memory": 1024,
      "maxDuration": 10
    }
  }
}
```

### 4. 프론트엔드 이미지 lazy loading (5분)
```jsx
// client/src/components/EventCard.tsx
<img 
  src={event.image_url} 
  loading="lazy"
  alt={event.title}
/>
```

---

## 📈 예상 성능 개선

| 항목 | 현재 | 목표 | 개선율 |
|-----|------|------|--------|
| Frontend 로드 | 2.5초 | 0.8초 | 68% ↓ |
| API 응답 | 1.9초 | 0.4초 | 79% ↓ |
| 총 로드 시간 | 4.4초 | 1.2초 | 73% ↓ |
| 페이지 크기 | ~2MB | ~600KB | 70% ↓ |
| DB 쿼리 시간 | ~500ms | ~50ms | 90% ↓ |

---

## 🔍 모니터링 지표

### 추적할 메트릭
1. **TTFB (Time to First Byte)** - 서버 응답 시간
2. **FCP (First Contentful Paint)** - 첫 콘텐츠 표시 시간
3. **LCP (Largest Contentful Paint)** - 주요 콘텐츠 로드 시간
4. **TTI (Time to Interactive)** - 인터랙티브 가능 시간
5. **CLS (Cumulative Layout Shift)** - 레이아웃 안정성

### 도구
- Google Lighthouse
- WebPageTest
- Vercel Analytics
- Sentry Performance Monitoring

---

## ✅ 실행 계획

1. **즉시 (오늘):**
   - 데이터베이스 인덱스 추가
   - FastAPI Compression 활성화
   - Vercel 함수 메모리 증가

2. **이번 주:**
   - 이미지 lazy loading 구현
   - API 응답 캐싱 구현
   - 쿼리 최적화

3. **다음 주:**
   - CDN 설정
   - 코드 분할 구현
   - Connection Pooling 설정

4. **1개월 내:**
   - CSS 최적화
   - Static Generation
   - Redis 캐싱

---

**작성자:** Manus AI Agent  
**날짜:** 2026-02-05
