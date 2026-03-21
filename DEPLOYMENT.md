# 배포 가이드: GitHub 업로드 및 Ubuntu 서버 서비스

이 문서는 Trip Agent를 GitHub에 올리고, Ubuntu 서버에 배포해 서비스로 운영하는 과정을 설명합니다.

---

## 1. GitHub에 코드 업로드

### 1.1 Git 저장소 초기화 (최초 1회)

로컬 프로젝트 디렉터리에서:

```bash
cd trip-agent

# Git 초기화 (이미 되어 있다면 생략)
git init

# .gitignore 생성
cat > .gitignore << 'EOF'
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environment
.venv/
venv/
ENV/

# IDE & OS
.idea/
.vscode/
.DS_Store
Thumbs.db

# Environment
.env
.env.local

# Logs
*.log
EOF
```

> **Windows PowerShell 사용 시**: `cat > .gitignore << 'EOF'` 문법은 Bash 전용입니다. 프로젝트에 이미 `.gitignore`가 있으면 생략하고, 없으면 Git Bash를 사용하거나 `.gitignore` 내용을 직접 생성하세요.

```bash
# 변경 사항 스테이징
git add .
git status

# 첫 커밋
git commit -m "Initial commit: Trip Agent with A2A agents and MCP servers"
```

### 1.2 GitHub 원격 저장소 연결

1. [GitHub](https://github.com)에서 새 저장소 생성 (예: `trip-agent`)
2. `README`, `.gitignore` 추가하지 않고 **빈 저장소**로 생성

```bash
# 원격 저장소 추가 (본인 계정/저장소명으로 수정)
git remote add origin https://github.com/YOUR_USERNAME/trip-agent.git

# 또는 SSH 사용 시
# git remote add origin git@github.com:YOUR_USERNAME/trip-agent.git

# main 브랜치로 푸시
git branch -M main
git push -u origin main
```

### 1.3 이후 변경 사항 푸시

```bash
git add .
git status
git commit -m "변경 내용 설명"
git push origin main
```

---

## 2. Ubuntu 서버 준비

### 2.1 서버 접속

```bash
ssh your_user@your_server_ip
# 예: ssh ubuntu@192.168.1.100
```

### 2.2 기본 패키지 업데이트

```bash
sudo apt update && sudo apt upgrade -y
```

### 2.3 Docker 설치

```bash
# Docker 공식 설치 스크립트
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# 현재 사용자를 docker 그룹에 추가 (sudo 없이 docker 실행)
sudo usermod -aG docker $USER

# 로그아웃 후 다시 접속하거나, 다음으로 적용
newgrp docker

# Docker Compose (Docker 23+ 에선 docker compose 명령 포함)
docker compose version
```

### 2.4 Git 설치 (없는 경우)

```bash
sudo apt install -y git
```

### 2.5 방화벽 포트 설정

외부에서 웹 UI에 접속하려면 포트를 열어야 합니다. **9000**만 열면 됩니다 (9001~9006은 Session Agent가 localhost로 호출하므로 외부 개방 불필요).

**Ubuntu UFW:**

```bash
sudo ufw allow 9000/tcp
sudo ufw reload
sudo ufw status
```

**전체 포트(9000~9006)를 열어야 하는 경우:**

```bash
sudo ufw allow 9000:9006/tcp
sudo ufw reload
```

**AWS / GCP / Azure 등 클라우드**: 보안 그룹(Inbound)에서 TCP 9000 허용. 9001~9006은 같은 서버 내부 통신이면 불필요.

**Nginx 역방향 프록시 사용 시**: 80/443만 열고, 내부에서 9000으로 프록시하면 더 안전합니다. 상세 설명과 설정 방법은 [5. Nginx 역방향 프록시](#5-nginx-역방향-프록시-선택-프로덕션) 참고.

---

## 3. 프로젝트 클론 및 배포

### 3.1 저장소 클론

```bash
# 작업 디렉터리 (예: /home/ubuntu)
cd ~

# 클론
git clone https://github.com/YOUR_USERNAME/trip-agent.git
cd trip-agent
```

### 3.2 환경 변수 설정 (선택)

```bash
cp .env.example .env
nano .env   # 또는 vim .env
```

**LLM 사용 시** 필요한 값 입력. Itinerary Agent는 OpenAI 호환 API를 사용합니다.

- **OpenAI**: `OPENAI_API_KEY`만 설정, `LLM_MODEL`은 `gpt-4o-mini` 등
- **Gemini 3.1 Pro (OpenRouter)**: [OpenRouter](https://openrouter.ai)에서 API 키 발급 후 아래처럼 설정

```env
OPENAI_API_KEY=sk-or-v1-xxxxxxxx
OPENAI_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=google/gemini-3.1-pro-preview
```

다른 모델(`google/gemini-2.5-pro`, `google/gemini-2.0-flash` 등)은 [OpenRouter 모델 목록](https://openrouter.ai/docs/features/models) 참고.

### Travelpayouts (항공 캐시 참고·렌트카 제휴 링크)

항공편은 **SerpApi 우선**, Amadeus(429 시)·이후 **SerpApi·Amadeus 모두 결과가 없을 때만** `TRAVELPAYOUTS_API_TOKEN`이 있으면 [Travelpayouts Data API](https://api.travelpayouts.com/documentation)로 **캐시 기준 최저가·Aviasales 링크를 참고**합니다.

```env
# 선택(항공: SerpApi·Amadeus 실패 시 캐시 참고). https://www.travelpayouts.com/programs/100/tools/api
TRAVELPAYOUTS_API_TOKEN=발급받은_토큰
# Aviasales 예약 딥링크·제휴 마커 (권장)
TRAVELPAYOUTS_MARKER=제휴_마커
```

렌트카는 공개 Data API가 없습니다. 대시보드 **Tools → Link Generator** 등에서 렌트카 프로그램용 URL을 만든 뒤 아래에 넣으면 검색 결과 **맨 위**에 제휴 카드가 붙습니다.

```env
TRAVELPAYOUTS_RENTAL_BOOKING_URL=https://...
```

상세는 [docs/TRAVELPAYOUTS_API_GUIDE.md](docs/TRAVELPAYOUTS_API_GUIDE.md), 항공 흐름은 [FLIGHT_API_SETUP.md](FLIGHT_API_SETUP.md) 참고.

### SerpApi (항공 1순위, 실시간 Google Flights)

항공 검색의 **기본 소스**입니다.

```env
SERPAPI_API_KEY=발급받은_api_key
```

SerpApi·Travelpayouts·Amadeus를 모두 쓰지 않으면 항공은 Mock(예시) 데이터로 동작합니다.

### 3.3 Docker Compose로 실행

```bash
# 빌드 및 실행 (백그라운드)
docker compose up -d --build

# 로그 확인
docker compose logs -f
```

- 프로젝트 루트에 `.env`가 있으면 각 서비스가 `env_file: .env`로 변수를 읽습니다. `cp .env.example .env` 후 토큰·키를 채우세요.
- 웹 UI: `http://서버IP:9000`
- 내부 포트: 9000(Session+UI), 9001~9006(각 Agent)

---

## 4. systemd로 서비스 등록 (재부팅 시 자동 실행)

### 4.1 systemd 유닛 파일 생성

```bash
sudo nano /etc/systemd/system/trip-agent.service
```

내용:

```ini
[Unit]
Description=Trip Agent Docker Compose
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/ubuntu/trip-agent
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

- `WorkingDirectory`: 실제 클론한 경로로 수정 (예: `/home/ubuntu/trip-agent`)
- 사용자에 따라 경로가 다를 수 있음

### 4.2 서비스 활성화 및 시작

```bash
sudo systemctl daemon-reload
sudo systemctl enable trip-agent
sudo systemctl start trip-agent
sudo systemctl status trip-agent
```

### 4.3 이후 수동 제어

```bash
# 시작
sudo systemctl start trip-agent

# 중지
sudo systemctl stop trip-agent

# 재시작 (코드 반영 후)
cd ~/trip-agent
git pull
docker compose up -d --build
```

---

## 5. Nginx 역방향 프록시 (선택, 프로덕션)

도메인을 쓰거나 80/443 포트로 서비스할 때 사용합니다.

### Nginx 사용이 더 안전한 이유

| 구분 | 9000 직접 노출 | Nginx 역방향 프록시 |
|------|----------------|---------------------|
| 외부 노출 포트 | 9000 (비표준) | 80, 443 (표준 웹 포트) |
| HTTPS | 앱에서 별도 구성 | Nginx + Let's Encrypt로 간편 적용 |
| Trip Agent 노출 | 외부에 직접 연결 | localhost만 사용, 외부 비노출 |
| 보안 기능 | 앱별 구현 필요 | Rate limiting, 헤더 정리 등 Nginx에서 처리 |

흐름: `[인터넷] → 80/443 → [Nginx] → localhost:9000 → [Trip Agent]`. 외부에서는 Nginx만 보이며, Trip Agent는 내부 통신만 합니다.

---

### 5.1 Nginx 설치

```bash
sudo apt install -y nginx
```

### 5.2 사이트 설정

#### A. 기본 설정 (필수)

`sites-available`에 Trip Agent용 설정을 추가합니다.

```bash
sudo nano /etc/nginx/sites-available/trip-agent
```

아래 내용을 그대로 넣고 `trip.yourdomain.com`을 본인 도메인으로 바꿉니다.

```nginx
server {
    listen 80;
    server_name trip.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:9000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
}
```

#### B. 보안 강화 (선택)

Rate limiting(초당 요청 제한)과 요청 크기 제한을 쓰려면 두 파일을 만듭니다.

**1단계: Rate limit 영역 정의**

새 파일을 만들고 한 줄만 넣습니다. `nginx.conf`를 수정할 필요는 없습니다.

```bash
sudo nano /etc/nginx/conf.d/trip-rate-limit.conf
```

```nginx
# Trip Agent용 rate limit: IP당 초당 10요청, 버스트 20까지 허용
limit_req_zone $binary_remote_addr zone=trip_limit:10m rate=10r/s;
```

**2단계: 사이트 설정에 적용**

`/etc/nginx/sites-available/trip-agent`을 아래처럼 수정합니다. (A 기본 설정에서 `client_max_body_size`와 `limit_req` 한 줄만 추가)

```nginx
server {
    listen 80;
    server_name trip.yourdomain.com;

    client_max_body_size 1M;   # 요청 본문 최대 1MB

    location / {
        limit_req zone=trip_limit burst=20 nodelay;   # rate limit 적용
        proxy_pass http://127.0.0.1:9000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
}
```

**용어 설명**:

| 항목 | 의미 |
|------|------|
| `rate=10r/s` | IP당 초당 10개 요청으로 제한 |
| `burst=20` | 갑작스러운 트래픽 시 최대 20개까지 버퍼로 허용 |
| `nodelay` | 버퍼 대기 없이 곧바로 처리 (burst 구간에서도 즉시 응답) |

> **참고**: Ubuntu 기본 `nginx.conf`는 `include /etc/nginx/conf.d/*.conf`로 `conf.d`를 불러옵니다. `nginx -t`에서 `trip_limit`을 찾을 수 없다는 오류가 나면 `nginx.conf`를 확인해야 합니다.

**nginx.conf를 직접 수정해야 하는 경우**

`conf.d` include가 없거나 `trip-rate-limit.conf`가 적용되지 않으면, `sudo nano /etc/nginx/nginx.conf`를 열고 `http {` 바로 아래에 다음 한 줄을 추가합니다:

```nginx
http {
    limit_req_zone $binary_remote_addr zone=trip_limit:10m rate=10r/s;
    # ... 아래 기존 내용 유지 ...
}
```

### 5.3 활성화 및 재시작

```bash
sudo ln -s /etc/nginx/sites-available/trip-agent /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 5.4 방화벽 (Nginx 사용 시)

Nginx를 쓰면 **9000을 열지 않고** 80/443만 허용합니다.

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
# sudo ufw deny 9000/tcp   # 9000 닫기 (선택)
sudo ufw reload
```

클라우드 보안 그룹에서도 80, 443만 열고 9000은 제거합니다.

### 5.5 HTTPS (Let's Encrypt)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d trip.yourdomain.com
```

이후 `https://trip.yourdomain.com` 으로 접속 가능합니다. 인증서는 90일마다 자동 갱신됩니다.

---

## 6. 가정/사무실 배포 (DuckDNS + KT 공유기)

집이나 사무실에서 서버를 운영하고 **KT 공유기**와 **DuckDNS**를 사용할 때의 설정입니다. 클라우드 보안 그룹 대신 **공유기 포트포워딩**을 사용합니다.

### 흐름

```
[인터넷] → DuckDNS(xxx.duckdns.org) → KT 공유기(공인 IP)
    → 포트포워딩(80, 443) → 서버(192.168.x.x) → Nginx → Trip Agent(9000)
```

### 6.1 DuckDNS 설정

1. [duckdns.org](https://www.duckdns.org) 로그인
2. 도메인 생성 (예: `mytrip.duckdns.org`)
3. 공유기 재시작 등으로 공인 IP가 바뀌면 DuckDNS에 자동 반영되도록 [DuckDNS 클라이언트](https://www.duckdns.org/spec.jsp) 설치 권장

### 6.2 KT 공유기 포트포워딩

1. PC에서 `192.168.0.1` 또는 `192.168.1.1` 접속 (KT 공유기 관리 화면)
2. **포트포워딩** 메뉴로 이동
3. 아래 규칙 추가 (내부 서버 IP는 `ip addr`로 확인):

| 외부 포트 | 내부 IP | 내부 포트 | 프로토콜 |
|-----------|---------|-----------|----------|
| 80 | 192.168.x.x (서버) | 80 | TCP |
| 443 | 192.168.x.x (서버) | 443 | TCP |

9000은 포트포워딩하지 않습니다 (Nginx가 내부에서만 사용).

### 6.3 서버 방화벽 (UFW)

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw reload
```

### 6.4 Nginx 사이트 설정

`server_name`을 DuckDNS 도메인으로 설정합니다.

```bash
sudo nano /etc/nginx/sites-available/trip-agent
```

```nginx
server {
    listen 80;
    server_name mytrip.duckdns.org;   # 본인 DuckDNS 도메인

    location / {
        proxy_pass http://127.0.0.1:9000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
}
```

활성화 및 재시작:

```bash
sudo ln -s /etc/nginx/sites-available/trip-agent /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 6.5 HTTPS (Let's Encrypt)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d mytrip.duckdns.org
```

이후 `https://mytrip.duckdns.org` 로 접속 가능합니다.

### 6.6 CGNAT 여부 확인

KT에서 **CGNAT**를 쓰면 공유기에 공인 IP가 없어 포트포워딩이 동작하지 않습니다. 이 경우:

- KT에 **공인 IP 전환** 요청 (유료), 또는
- [ngrok](https://ngrok.com), [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps) 같은 터널 서비스 사용

---

## 7. 배포 요약

### 클라우드 서버

| 단계 | 작업 |
|------|------|
| 1 | 로컬 `git init`, `.gitignore` 설정, `git add`/`commit` |
| 2 | GitHub 저장소 생성 후 `git remote add`, `git push` |
| 3 | Ubuntu 서버에 `apt update`, Docker 설치 |
| 4 | 방화벽에서 포트 9000 허용 (UFW 또는 클라우드 보안 그룹) |
| 5 | `git clone` 후 `docker compose up -d --build` |
| 6 | (선택) systemd 유닛 등록으로 부팅 시 자동 기동 |
| 7 | (선택) Nginx 역방향 프록시, 80/443만 개방, HTTPS 적용 |

### 가정/사무실 (DuckDNS + KT 공유기)

| 단계 | 작업 |
|------|------|
| 1 | DuckDNS 도메인 생성, 서버 내부 IP 확인 |
| 2 | KT 공유기 포트포워딩: 80, 443 → 서버 IP |
| 3 | UFW에서 80, 443 허용 |
| 4 | Nginx `server_name`을 DuckDNS 도메인으로 설정 |
| 5 | (선택) Let's Encrypt로 HTTPS 적용 |

---

## 8. 트러블슈팅

### 외부에서 접속이 안 될 때

방화벽(UFW) 또는 클라우드 보안 그룹에서 **TCP 9000** 포트가 허용되었는지 확인하세요. [2.5 방화벽 포트 설정](#25-방화벽-포트-설정) 참고.

### 포트가 이미 사용 중일 때

```bash
# 9000 포트 사용 프로세스 확인
sudo lsof -i :9000
# 또는
sudo ss -tlnp | grep 9000

# docker-compose.yml 에서 ports 변경 (예: "8080:9000")
```

### Docker 빌드 실패

```bash
# 캐시 없이 다시 빌드
docker compose build --no-cache
docker compose up -d
```

### 502 Bad Gateway (Nginx 사용 시)

Nginx는 동작하지만 Trip Agent(9000 포트)에 연결할 수 없을 때 나옵니다.

1. **Trip Agent 실행 여부 확인**:

```bash
sudo ss -tlnp | grep 9000
```

아무것도 안 나오면 Trip Agent가 떠 있지 않습니다.

2. **Docker로 실행했다면**:

```bash
docker compose ps
docker compose up -d --build
```

3. **호스트에서 직접 접속 테스트**:

```bash
curl http://127.0.0.1:9000
```

응답이 있으면 Trip Agent는 동작하는 것이고, Nginx 설정을 확인하세요.

4. **Nginx 에러 로그**:

```bash
sudo tail -50 /var/log/nginx/error.log
```

`Connection refused` → Trip Agent 미실행. `docker compose up -d` 또는 `python main.py`로 기동하세요.

### 컨테이너가 바로 종료될 때 (Exited 1)

`docker compose ps -a` 에서 `Exited (1)` 이 보이면 **로그를 먼저 확인**하세요.

```bash
# session 로그 (502 원인 - 웹 UI 서비스)
docker compose logs session

# 다른 실패 서비스 로그
docker compose logs flight
docker compose logs accommodation
docker compose logs itinerary
```

로그 맨 아래의 **Traceback/Error** 메시지가 해결 단서입니다.

| 에러 | 원인 | 해결 |
|------|------|------|
| `extra_forbidden: amadeus_client_id` | .env에 제거된 변수 남음 | .env에서 AMADEUS_*, DUFFEL_*, KIWI_* 등 과거 변수 삭제. 항공은 `TRAVELPAYOUTS_*`, `SERPAPI_*` 사용 |
| `ModuleNotFoundError: a2a.server.events.event_factory` | a2a-sdk 0.3.x에서 모듈 제거 | `git pull` 후 `docker compose up -d --build` |
| `ImportError: MessagePart from a2a.types` | API 변경 (MessagePart→Part/TextPart) | 위와 동일 |
| `ValidationError: AgentSkill... description Field required` | AgentSkill에 `description` 필수 | 위와 동일 |
| `ModuleNotFoundError` (기타) | 의존성 미설치 | `docker compose build --no-cache` 후 재시작 |

**진단용 임시 실행** (로그에서 원인을 찾기 어려울 때):

```bash
docker compose run --rm session python -c "
from main import create_app
create_app()
print('OK')
"
```

**정상화 절차**: 최신 코드 pull → `docker compose down` → `docker compose up -d --build` → `docker compose ps -a`에서 모든 서비스 `Up` 확인.

### Docker "permission denied" 오류

`permission denied while trying to connect to the docker API` 가 나오면:

```bash
sudo usermod -aG docker $USER
newgrp docker
# 또는 로그아웃 후 재로그인
```

이후 `docker compose up -d --build` 다시 시도.

### 배포 정상화 체크리스트

| 확인 항목 | 명령 |
|----------|------|
| 최신 코드 | `git log -1 --oneline` |
| 모든 컨테이너 Up | `docker compose ps -a` (session, flight 등 7개 `Up`) |
| 9000 포트 리스닝 | `ss -tlnp | grep 9000` |
| 웹 UI 응답 | `curl http://127.0.0.1:9000` |

### 로그 확인

```bash
docker compose logs -f session    # Session Agent 로그
docker compose logs -f            # 전체 로그
```
