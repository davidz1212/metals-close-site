#!/usr/bin/env bash
# 贵金属日报网站 · NAS 部署自检（在与 docker-compose.yml 同目录运行，或传目录作为参数）
# 用法: bash check_deploy.sh [部署目录]
set -u
D="${1:-$(cd "$(dirname "$0")" && pwd)}"
cd "$D" || exit 1
fail=0
ok(){ echo "OK   $1"; }
bad(){ echo "FAIL $1"; fail=$((fail+1)); }

[ -f docker-compose.yml ] && ok "docker-compose.yml 存在" || bad "docker-compose.yml 缺失"
[ -f Dockerfile ] && ok "Dockerfile 存在" || bad "Dockerfile 缺失"
[ -f .env ] && ok ".env 存在（已把 .env.example 改名）" || bad ".env 缺失：请复制 .env.example 为 .env"
[ -f tools/entrypoint.sh ] && ok "entrypoint.sh 存在" || bad "entrypoint.sh 缺失"
[ -d backend ] && [ -f backend/app.py ] && ok "后端源码齐全" || bad "backend/app.py 缺失"
[ -d web ] && [ -f web/index.html ] && ok "前端源码齐全" || bad "web/index.html 缺失"
[ -f data/seed/2026-11-13.json ] && ok "种子数据存在（首次自动入库）" || bad "种子数据缺失"

# 关键 env 项
SECRET=$(grep -E '^SECRET_KEY=' .env 2>/dev/null | cut -d= -f2-)
[ -n "$SECRET" ] && [ "$SECRET" != "请改成一串随机长字符串" ] && ok "SECRET_KEY 已设置（长度 ${#SECRET}）" || bad "SECRET_KEY 为空或仍是占位符"
SUB=$(grep -E '^INITIAL_SUBSCRIBER=' .env 2>/dev/null | cut -d= -f2-)
case "$SUB" in
  ""|*"@example.com"|*"yourdomain"*) bad "INITIAL_SUBSCRIBER 仍是占位符：请填你自己的邮箱" ;;
  *@*) ok "INITIAL_SUBSCRIBER = $SUB" ;;
  *) bad "INITIAL_SUBSCRIBER 格式异常" ;;
esac
DEV=$(grep -E '^MC_DEV_MODE=' .env 2>/dev/null | cut -d= -f2-)
[ "$DEV" = "0" ] && ok "MC_DEV_MODE=0（生产模式）" || bad "MC_DEV_MODE 不是 0：生产必须为 0"
RESEND=$(grep -E '^RESEND_API_KEY=' .env 2>/dev/null | cut -d= -f2-)
[ -n "$RESEND" ] && ok "RESEND_API_KEY 已填（验证码可发送）" || bad "RESEND_API_KEY 为空：登录验证码发不出去，谁都无法登录"
BASE=$(grep -E '^SITE_BASE_URL=' .env 2>/dev/null | cut -d= -f2-)
case "$BASE" in
  *"192.168.1.99:8790"*) ok "SITE_BASE_URL = $BASE（与 8790 端口一致）" ;;
  *) echo "WARN SITE_BASE_URL = $BASE：若你改了宿主机端口，请同步改这里" ;;
esac

echo "----"
if [ "$fail" -eq 0 ]; then echo "RESULT: ALL CHECKS PASSED"; else echo "RESULT: $fail CHECK(S) FAILED — 先修上面 FAIL 项再建项目"; fi
exit "$fail"
