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

LLM 사용 시 `OPENAI_API_KEY` 등 필요한 값 입력.

### 3.3 Docker Compose로 실행

```bash
# 빌드 및 실행 (백그라운드)
docker compose up -d --build

# 로그 확인
docker compose logs -f
```

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

### 5.1 Nginx 설치

```bash
sudo apt install -y nginx
```

### 5.2 사이트 설정

```bash
sudo nano /etc/nginx/sites-available/trip-agent
```

내용 (도메인 예: `trip.yourdomain.com`):

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

### 5.3 활성화 및 재시작

```bash
sudo ln -s /etc/nginx/sites-available/trip-agent /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 5.4 HTTPS (Let's Encrypt)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d trip.yourdomain.com
```

이후 `https://trip.yourdomain.com` 으로 접속 가능합니다.

---

## 6. 배포 요약

| 단계 | 작업 |
|------|------|
| 1 | 로컬 `git init`, `.gitignore` 설정, `git add`/`commit` |
| 2 | GitHub 저장소 생성 후 `git remote add`, `git push` |
| 3 | Ubuntu 서버에 `apt update`, Docker 설치 |
| 4 | `git clone` 후 `docker compose up -d --build` |
| 5 | (선택) systemd 유닛 등록으로 부팅 시 자동 기동 |
| 6 | (선택) Nginx 역방향 프록시, HTTPS 적용 |

---

## 7. 트러블슈팅

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

### 로그 확인

```bash
docker compose logs -f session    # Session Agent 로그
docker compose logs -f            # 전체 로그
```
