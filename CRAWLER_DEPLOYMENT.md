# AaltoHub v2 - Crawler 배포 가이드

## 📋 사전 요구사항

1. **AWS EC2 인스턴스**: 백엔드가 실행 중이어야 함
2. **관리자 계정**: 최소 1명의 관리자가 텔레그램 로그인 완료
3. **Public 그룹 등록**: 크롤링할 그룹이 등록되어 있어야 함
4. **환경변수**: `backend/.env` 파일 설정 완료

---

## 🚀 Step 1: EC2에 파일 업로드

```bash
# 로컬에서 실행 (프로젝트 루트)
cd /Users/songchaeyeon/AALTOHUBv2

# 백엔드 파일을 EC2로 복사
scp -i telegram-crawler-key.pem -r backend ubuntu@63.180.156.219:/home/ubuntu/aaltohubv2/
```

---

## 🔧 Step 2: EC2에서 systemd 서비스 설정

```bash
# SSH 접속
ssh -i telegram-crawler-key.pem ubuntu@63.180.156.219

# 프로젝트 디렉토리로 이동
cd /home/ubuntu/aaltohubv2/backend

# Python 가상환경 활성화
source venv/bin/activate

# 필요한 패키지 설치 (이미 설치되어 있으면 스킵)
pip install -r requirements.txt

# systemd 서비스 설정 (root 권한 필요)
sudo bash scripts/setup_crawler_service.sh
```

---

## ▶️ Step 3: 크롤러 시작

```bash
# 크롤러 시작
sudo systemctl start aaltohub-crawler

# 상태 확인
sudo systemctl status aaltohub-crawler

# 실시간 로그 확인
sudo journalctl -u aaltohub-crawler -f

# 또는 로그 파일 직접 확인
tail -f /var/log/aaltohub-crawler.log
```

---

## 📊 Step 4: 크롤러 작동 확인

### 4.1 로그에서 확인
```bash
tail -f /var/log/aaltohub-crawler.log
```

예상 출력:
```
============================================================
AaltoHub v2 - Enhanced Message Crawler
============================================================

Initializing enhanced crawler...
Admin user: John Doe (@johndoe)
Connected as: John Doe (@johndoe)
Loading registered groups...
Loaded 3 groups:
  - Aalto CS Events (ID: -1001234567890)
  - Design Factory (ID: -1009876543210)
  - Student Housing (ID: -1005555555555)

============================================================
PHASE 1: Historical Message Collection (30 days)
============================================================

=== Crawling historical messages for: Aalto CS Events ===
Counting messages...
Found 1250 messages to crawl
Progress: 10/1250 (0%)
Progress: 20/1250 (1%)
...
```

### 4.2 관리자 대시보드에서 확인
1. 브라우저에서 관리자 대시보드 접속: `http://localhost:3000/admin`
2. 그룹 선택 → 메시지가 표시되는지 확인
3. 크롤러 관리 페이지: `http://localhost:3000/admin/crawler`
   - 크롤러 상태 확인
   - 에러 로그 확인

### 4.3 Supabase에서 확인
```sql
-- 메시지 수 확인
SELECT COUNT(*) FROM messages;

-- 최근 메시지 확인
SELECT * FROM messages ORDER BY sent_at DESC LIMIT 10;

-- 크롤러 상태 확인
SELECT * FROM crawler_status;
```

---

## 🛑 크롤러 중지/재시작

```bash
# 중지
sudo systemctl stop aaltohub-crawler

# 재시작
sudo systemctl restart aaltohub-crawler

# 자동 시작 비활성화
sudo systemctl disable aaltohub-crawler

# 자동 시작 활성화
sudo systemctl enable aaltohub-crawler
```

---

## 🔍 문제 해결 (Troubleshooting)

### 크롤러가 시작되지 않을 때

1. **로그 확인**
   ```bash
   sudo journalctl -u aaltohub-crawler -n 50
   ```

2. **환경변수 확인**
   ```bash
   cat /home/ubuntu/aaltohubv2/backend/.env
   ```
   필수 변수:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY` (또는 `SUPABASE_KEY`)
   - `TELEGRAM_API_ID`
   - `TELEGRAM_API_HASH`

3. **Python 경로 확인**
   ```bash
   which python
   # 출력: /home/ubuntu/aaltohubv2/backend/venv/bin/python
   ```

4. **수동 실행 테스트**
   ```bash
   cd /home/ubuntu/aaltohubv2/backend
   source venv/bin/activate
   python scripts/crawler_enhanced.py
   ```

### "Admin user not found" 에러

**원인**: 관리자가 텔레그램 로그인을 하지 않음

**해결책**:
1. 프론트엔드에서 관리자 계정으로 로그인
2. `backend/.env`의 `ADMIN_USERNAMES` 또는 `ADMIN_PHONE_NUMBERS` 확인

### "Admin session not found" 에러

**원인**: 관리자 세션이 DB에 저장되지 않음

**해결책**:
1. 관리자 계정으로 다시 로그인
2. Supabase `telethon_sessions` 테이블 확인:
   ```sql
   SELECT user_id, created_at FROM telethon_sessions WHERE user_id = (
     SELECT id FROM users WHERE role = 'admin' LIMIT 1
   );
   ```

### "No public groups found" 경고

**원인**: 크롤링 가능한 public 그룹이 없음

**해결책**:
1. 프론트엔드에서 그룹 등록 (`/groups/select`)
2. 그룹 visibility를 "public"으로 설정
3. 관리자가 해당 그룹에 초대되었는지 확인

### FloodWaitError

**원인**: Telegram API rate limit

**크롤러가 자동으로 처리**:
- 에러 메시지에 표시된 시간만큼 대기 후 재시도
- `crawler_status` 테이블에 에러 로그 기록

---

## 📈 성능 모니터링

### CPU/메모리 사용량
```bash
# 크롤러 프로세스 확인
ps aux | grep crawler_enhanced

# htop으로 모니터링
htop
```

### 크롤링 진행률
관리자 대시보드 → Crawler Management → Progress 컬럼 확인

### 데이터베이스 크기
```sql
-- messages 테이블 크기 확인
SELECT
  pg_size_pretty(pg_total_relation_size('messages')) as total_size,
  COUNT(*) as message_count
FROM messages;
```

---

## 🔄 업데이트 및 재배포

코드 변경 후:
```bash
# 로컬 → EC2 파일 복사
scp -i telegram-crawler-key.pem -r backend/scripts ubuntu@63.180.156.219:/home/ubuntu/aaltohubv2/backend/

# EC2에서 크롤러 재시작
ssh -i telegram-crawler-key.pem ubuntu@63.180.156.219
sudo systemctl restart aaltohub-crawler
sudo journalctl -u aaltohub-crawler -f
```

---

## ✅ 체크리스트

배포 전 확인사항:
- [ ] 관리자 계정 로그인 완료
- [ ] Public 그룹 최소 1개 이상 등록
- [ ] 백엔드 `.env` 파일 설정 완료
- [ ] EC2에 백엔드 코드 업로드
- [ ] systemd 서비스 설정 완료
- [ ] 크롤러 시작 및 로그 확인
- [ ] 관리자 대시보드에서 메시지 확인
- [ ] Supabase에서 데이터 확인

---

## 📞 지원

문제 발생 시:
1. 로그 확인: `sudo journalctl -u aaltohub-crawler -n 100`
2. 에러 로그 확인: `/var/log/aaltohub-crawler-error.log`
3. Supabase `crawler_error_logs` 테이블 확인
