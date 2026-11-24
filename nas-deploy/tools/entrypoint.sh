#!/bin/sh
set -e
cd /app
echo "[entrypoint] init db ..."
python tools/ingest.py || true

# INITIAL_SUBSCRIBER：首次部署时写入一个可用订阅邮箱；留空则跳过。
# 标记文件保证只在第一次执行，后续重启不会覆盖你在数据库里改过的订阅状态。
if [ -n "$INITIAL_SUBSCRIBER" ] && [ ! -f /app/data/.subscriber_seeded ]; then
  echo "[entrypoint] seeding subscriber: $INITIAL_SUBSCRIBER"
  python tools/seed_subscriber.py add "$INITIAL_SUBSCRIBER" --days 365 --note "initial deploy"
  touch /app/data/.subscriber_seeded
fi

echo "[entrypoint] starting server on port ${PORT:-8765} ..."
exec python server.py
