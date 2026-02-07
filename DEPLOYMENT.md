# AaltoHub v2 Deployment Guide

이 문서는 AaltoHub v2를 AWS EC2와 Vercel에 배포하는 전체 과정을 설명합니다.

## 목차
- [사전 요구사항](#사전-요구사항)
- [1. Supabase 데이터베이스 설정](#1-supabase-데이터베이스-설정)
- [2. AWS EC2 서버 설정](#2-aws-ec2-서버-설정)
- [3. 백엔드 배포](#3-백엔드-배포)
- [4. 크롤러 설정](#4-크롤러-설정)
- [5. 프론트엔드 배포 (Vercel)](#5-프론트엔드-배포-vercel)
- [6. 모니터링 및 로그](#6-모니터링-및-로그)

---

## 사전 요구사항

- AWS 계정
- Supabase 계정
- Vercel 계정
- Telegram API credentials (API ID, API Hash)
- Git 설치
- SSH 키 설정

---

## 1. Supabase 데이터베이스 설정

### 1.1. Supabase 프로젝트 생성

1. [Supabase](https://supabase.com) 접속 후 로그인
2. "New Project" 클릭
3. 프로젝트 이름 입력 (예: `aaltohub-v2`)
4. 데이터베이스 비밀번호 설정
5. Region 선택 (가장 가까운 지역)

### 1.2. 데이터베이스 스키마 적용

1. Supabase Dashboard → SQL Editor
2. `supabase/schema_actual.sql` 파일 내용 복사
3. SQL Editor에 붙여넣기
4. "Run" 클릭하여 스키마 생성

### 1.3. API 키 확인

1. Settings → API
2. 다음 값들을 복사:
   - `Project URL`
   - `anon public` key
   - `service_role` key (비밀로 관리!)

---

## 2. AWS EC2 서버 설정

### 2.1. EC2 인스턴스 생성

1. AWS Console → EC2 → Launch Instance
2. **Name**: `aaltohub-backend`
3. **AMI**: Ubuntu Server 22.04 LTS
4. **Instance Type**: `t2.small` 이상 권장
5. **Key Pair**: 새로 생성하거나 기존 키 사용
6. **Security Group**:
   - SSH (22) - Your IP
   - HTTP (80) - 0.0.0.0/0
   - HTTPS (443) - 0.0.0.0/0
   - Custom TCP (8000) - 0.0.0.0/0 (API)
7. **Storage**: 20GB 이상

### 2.2. 서버 초기 설정

```bash
# SSH 접속
ssh -i your-key.pem ubuntu@your-ec2-ip

# 시스템 업데이트
sudo apt update && sudo apt upgrade -y

# Python 3.11 설치
sudo apt install python3.11 python3.11-venv python3-pip -y

# Git 설치
sudo apt install git -y

# Nginx 설치 (선택사항, 리버스 프록시용)
sudo apt install nginx -y
```

### 2.3. 프로젝트 클론

```bash
cd ~
git clone https://github.com/your-username/AALTOHUBv2.git
cd AALTOHUBv2/backend
```

### 2.4. Python 가상환경 설정

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 2.5. 환경 변수 설정

```bash
# backend/.env 파일 생성
nano backend/.env
```

`backend/.env.example` 내용을 참고하여 실제 값 입력:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_service_role_key
SUPABASE_JWT_SECRET=your_jwt_secret
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
SESSION_ENCRYPTION_KEY=your_32_byte_key
JWT_SECRET_KEY=your_jwt_secret
# ... 나머지 설정
```

**암호화 키 생성:**
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## 3. 백엔드 배포

### 3.1. systemd 서비스 설정 (FastAPI)

```bash
# 서비스 파일 복사
sudo cp systemd/aaltohub-api.service /etc/systemd/system/

# 로그 디렉토리 생성
sudo mkdir -p /var/log/aaltohub
sudo chown ubuntu:ubuntu /var/log/aaltohub

# 서비스 활성화 및 시작
sudo systemctl daemon-reload
sudo systemctl enable aaltohub-api.service
sudo systemctl start aaltohub-api.service

# 상태 확인
sudo systemctl status aaltohub-api.service
```

### 3.2. API 테스트

```bash
curl http://localhost:8000/health
# Expected: {"status":"healthy","environment":"production"}
```

---

## 4. 크롤러 설정

### 4.1. 관리자 계정으로 최초 로그인

크롤러를 시작하기 전에 **반드시** 관리자 계정으로 텔레그램 인증을 완료해야 합니다:

1. 프론트엔드에서 관리자 전화번호로 로그인
2. Telegram 인증 코드 입력
3. 2FA가 있다면 비밀번호 입력
4. 로그인 완료 후 세션이 DB에 저장됨

### 4.2. 크롤러 서비스 설정

```bash
# 스크립트 실행 권한 부여
chmod +x scripts/setup-crawler-service.sh

# 서비스 설치
sudo ./scripts/setup-crawler-service.sh
```

### 4.3. 크롤러 상태 확인

```bash
# 서비스 상태
sudo systemctl status aaltohub-crawler.service

# 실시간 로그
sudo journalctl -u aaltohub-crawler -f

# 로그 파일
tail -f /var/log/aaltohub/crawler.log
tail -f /var/log/aaltohub/crawler.error.log
```

---

## 5. 프론트엔드 배포 (Vercel)

### 5.1. GitHub 연결

1. GitHub에 프로젝트 푸시
```bash
git add .
git commit -m "Ready for deployment"
git push origin main
```

### 5.2. Vercel 프로젝트 생성

1. [Vercel](https://vercel.com) 접속
2. "Import Project" 클릭
3. GitHub 저장소 선택
4. **Framework Preset**: Vite
5. **Root Directory**: `./` (루트)
6. **Build Command**: `cd client && npm run build`
7. **Output Directory**: `client/dist`

### 5.3. 환경 변수 설정

Vercel Dashboard → Settings → Environment Variables:

```env
VITE_API_URL=https://your-ec2-domain.com
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your_anon_key
```

### 5.4. 배포

1. "Deploy" 클릭
2. 배포 완료 후 URL 확인 (예: `https://aaltohub.vercel.app`)

---

## 6. 모니터링 및 로그

### 6.1. 서비스 로그 확인

**API 로그:**
```bash
sudo journalctl -u aaltohub-api -f
tail -f /var/log/aaltohub/api.log
```

**크롤러 로그:**
```bash
sudo journalctl -u aaltohub-crawler -f
tail -f /var/log/aaltohub/crawler.log
```

### 6.2. Supabase 대시보드

1. Supabase Dashboard → Database → Tables
2. 메시지 수집 확인: `messages` 테이블
3. 크롤러 상태 확인: `crawler_status` 테이블
4. 에러 로그 확인: `crawler_error_logs` 테이블

### 6.3. 서비스 재시작

```bash
# API 재시작
sudo systemctl restart aaltohub-api

# 크롤러 재시작
sudo systemctl restart aaltohub-crawler

# 모든 서비스 재시작
sudo systemctl restart aaltohub-api aaltohub-crawler
```

---

## 트러블슈팅

### 크롤러가 시작되지 않을 때

1. 관리자 세션 확인:
```bash
cd backend
source venv/bin/activate
python scripts/check_admin_session.py
```

2. 환경 변수 확인:
```bash
cat backend/.env | grep TELEGRAM
```

3. 로그 확인:
```bash
tail -100 /var/log/aaltohub/crawler.error.log
```

### API 응답 없음

1. 방화벽 확인:
```bash
sudo ufw status
sudo ufw allow 8000/tcp
```

2. Nginx 리버스 프록시 사용 시:
```bash
sudo systemctl status nginx
sudo tail -f /var/log/nginx/error.log
```

### 데이터베이스 연결 실패

1. Supabase 프로젝트 상태 확인
2. `SUPABASE_URL` 및 `SUPABASE_KEY` 재확인
3. 네트워크 연결 테스트:
```bash
curl https://your-project.supabase.co/rest/v1/
```

---

## 자동 배포 스크립트

백엔드 배포 자동화:
```bash
chmod +x scripts/deploy-backend.sh
./scripts/deploy-backend.sh
```

---

## 보안 체크리스트

- [ ] `.env` 파일이 `.gitignore`에 포함되어 있는지 확인
- [ ] Supabase `service_role` 키는 서버에서만 사용
- [ ] EC2 Security Group에서 불필요한 포트 차단
- [ ] SSH는 특정 IP만 허용
- [ ] 정기적으로 시스템 업데이트 (`sudo apt update && sudo apt upgrade`)
- [ ] Sentry 등 에러 모니터링 설정

---

## 참고 자료

- [Supabase Documentation](https://supabase.com/docs)
- [FastAPI Deployment](https://fastapi.tiangolo.com/deployment/)
- [Telethon Documentation](https://docs.telethon.dev/)
- [Vercel Documentation](https://vercel.com/docs)
