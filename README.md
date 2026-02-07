# AaltoHub v2 🚀

**Telegram Group Message Crawler & Dashboard**

AaltoHub v2는 텔레그램 그룹의 메시지를 실시간으로 수집하고, 깔끔한 대시보드에서 확인할 수 있는 통합 플랫폼입니다.

---

## 📋 주요 기능

- ✅ **텔레그램 MTProto 인증** (Telethon userbot)
- ✅ **24/7 무중단 메시지 크롤링** (초기 30일 + 실시간)
- ✅ **실시간 대시보드** (Supabase Realtime)
- ✅ **텔레그램 스타일 UI** (Message Bubbles, Split View)
- ✅ **Public/Private 그룹 관리**
- ✅ **토픽 필터링** (Forum/Supergroup topics)
- ✅ **에러 로깅 & 모니터링**
- ✅ **Admin 대시보드**

---

## 🛠 기술 스택

### Backend
- **Python 3.11+** - FastAPI
- **Telethon** - Telegram MTProto API
- **Supabase** - PostgreSQL Database
- **JWT** - Authentication
- **Cryptography** - Session Encryption

### Frontend
- **React 19** - UI Framework
- **TypeScript** - Type Safety
- **Vite** - Build Tool
- **Radix UI** - Component Library
- **Supabase Realtime** - Live Updates
- **Wouter** - Client-side Routing

### Infrastructure
- **AWS EC2** - Backend & Crawler Hosting
- **Vercel** - Frontend Hosting
- **Supabase** - Database & Realtime
- **systemd** - Service Management

---

## 🚀 Quick Start

### 사전 요구사항
- Python 3.11+
- Node.js 18+
- pnpm (권장) 또는 npm
- Supabase 계정
- Telegram API credentials

### 1. 프로젝트 클론

```bash
git clone https://github.com/your-username/AALTOHUBv2.git
cd AALTOHUBv2
```

### 2. 환경 변수 설정

**Backend:**
```bash
cp backend/.env.example backend/.env
# backend/.env 파일을 열어 실제 값 입력
```

**Frontend:**
```bash
cp client/.env.example client/.env.local
# client/.env.local 파일을 열어 실제 값 입력
```

자세한 설정은 [CREDENTIALS_SETUP.md](CREDENTIALS_SETUP.md) 참고

### 3. 데이터베이스 스키마 적용

Supabase Dashboard → SQL Editor에서 `supabase/schema_actual.sql` 실행

### 4. 백엔드 실행

```bash
cd backend
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. 프론트엔드 실행

```bash
cd client
pnpm install  # 또는 npm install
pnpm dev      # 또는 npm run dev
```

### 6. 관리자 로그인

1. 브라우저에서 `http://localhost:3000` 접속
2. 관리자 전화번호로 로그인 (`+358...`)
3. Telegram 인증 코드 입력
4. 2FA 비밀번호 입력 (있는 경우)

### 7. 크롤러 실행 (선택사항)

```bash
cd backend
source venv/bin/activate
python scripts/crawler_enhanced.py
```

---

## 📁 프로젝트 구조

```
AALTOHUBv2/
├── backend/                 # Python FastAPI Backend
│   ├── app/
│   │   ├── main.py         # FastAPI 앱
│   │   ├── routes/         # API 라우트
│   │   ├── models.py       # Pydantic 모델
│   │   ├── telegram_client.py  # Telethon 관리
│   │   ├── database.py     # Supabase 연결
│   │   ├── encryption.py   # 세션 암호화
│   │   └── config.py       # 설정
│   ├── scripts/
│   │   ├── crawler.py      # 기본 크롤러
│   │   └── crawler_enhanced.py  # 고급 크롤러
│   └── requirements.txt
├── client/                  # React Frontend
│   ├── src/
│   │   ├── pages/          # 페이지 컴포넌트
│   │   ├── components/     # 재사용 컴포넌트
│   │   ├── contexts/       # React Context
│   │   ├── lib/            # API, Supabase
│   │   └── main.tsx
│   ├── index.html
│   └── package.json
├── supabase/
│   └── schema_actual.sql          # 데이터베이스 스키마
├── systemd/                # systemd 서비스 파일
│   ├── aaltohub-api.service
│   └── aaltohub-crawler.service
├── scripts/                # 배포 스크립트
│   ├── deploy-backend.sh
│   └── setup-crawler-service.sh
├── DEPLOYMENT.md           # 배포 가이드
├── CREDENTIALS_SETUP.md    # 크레덴셜 설정 가이드
└── README.md
```

---

## 📚 문서

- [DEPLOYMENT.md](DEPLOYMENT.md) - 전체 배포 가이드 (EC2, Vercel)
- [CREDENTIALS_SETUP.md](CREDENTIALS_SETUP.md) - API 키 및 환경 변수 설정
- [QUICK_START.md](QUICK_START.md) - 빠른 시작 가이드
- [TECH_STACK_CHECKLIST.md](TECH_STACK_CHECKLIST.md) - 기술 스택 점검 결과
- [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) - 구현 상태

---

## 🔧 개발 명령어

### Backend

```bash
# 개발 서버 실행
cd backend && source venv/bin/activate
python -m uvicorn app.main:app --reload

# 크롤러 실행
python scripts/crawler_enhanced.py

# 의존성 설치
pip install -r requirements.txt
```

### Frontend

```bash
# 개발 서버
pnpm dev

# 빌드
pnpm build

# 프리뷰
pnpm preview

# 타입 체크
pnpm check
```

---

## 🚢 배포

### Backend (AWS EC2)

```bash
# 자동 배포 스크립트 사용
./scripts/deploy-backend.sh
```

또는 수동 배포는 [DEPLOYMENT.md](DEPLOYMENT.md) 참고

### Frontend (Vercel)

1. GitHub에 푸시
2. Vercel에서 Import
3. 환경 변수 설정
4. Deploy

---

## 🐛 트러블슈팅

### 크롤러가 시작되지 않음
- 관리자 계정으로 먼저 로그인했는지 확인
- `backend/.env`에서 `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` 확인
- 로그 확인: `tail -f /var/log/aaltohub/crawler.error.log`

### API 연결 실패
- `client/.env.local`에서 `VITE_API_URL` 확인
- CORS 설정 확인 (`backend/.env` → `CORS_ORIGINS`)

### Supabase Realtime 작동 안함
- `VITE_SUPABASE_ANON_KEY` 설정 확인
- Supabase Dashboard → Database → Replication에서 `messages` 테이블 활성화 확인

---

## 📊 주요 기능 상세

### 1. 텔레그램 인증
- MTProto userbot 방식 (Telethon)
- 2FA 지원
- 세션 암호화 저장

### 2. 메시지 크롤링
- **Phase 1**: 초기 30일 메시지 수집 (진행률 트래킹)
- **Phase 2**: 실시간 모니터링 (NewMessage, MessageEdited, MessageDeleted)
- Rate limit 자동 처리 (FloodWaitError)

### 3. 실시간 대시보드
- Supabase Realtime (postgres_changes)
- 새 메시지 자동 업데이트
- 텔레그램 스타일 메시지 버블
- Split-view 레이아웃 (그룹 목록 + 메시지 뷰어)

### 4. 그룹 관리
- Public/Private 그룹 지원
- Private 그룹 초대 시스템
- 토픽 필터링 (Forum/Supergroup)

---

## 🔐 보안

- 세션 데이터 AES 암호화
- JWT 토큰 인증
- Supabase RLS (Row Level Security)
- HTTPS 전용 (프로덕션)

---

## 📈 모니터링

- Sentry 에러 트래킹
- Supabase 대시보드 (메시지 통계)
- systemd 로그 (`journalctl`)
- 크롤러 상태 (`crawler_status` 테이블)
- 에러 로그 (`crawler_error_logs` 테이블)

---

## 🤝 기여

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 라이선스

MIT License

---

## 📞 문의

프로젝트 관련 문의: [GitHub Issues](https://github.com/your-username/AALTOHUBv2/issues)

---

## 🙏 Acknowledgments

- [Telethon](https://github.com/LonamiWebs/Telethon) - Telegram MTProto API
- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python Web Framework
- [Supabase](https://supabase.com/) - Open Source Firebase Alternative
- [Radix UI](https://www.radix-ui.com/) - Accessible Component Library
