# 贵金属日报对外展示站点 · 单端口镜像
# 基础镜像走国内加速源，避免国内直连 Docker Hub 卡在拉镜像阶段。
# 2026-11-17 实测：docker.1ms.run 返回完整 Bearer 挑战并可成功拉取 manifest。
# 备用源：docker.m.daocloud.io（1ms 失效时替换下一行前缀即可）。
# 注意：飞牛内置 docker.fnnas.com 只能作为 daemon 级 registry-mirror，
#       不能当 FROM 前缀用（401 无鉴权挑战头，buildx 会失败）。
FROM docker.1ms.run/library/python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PORT=8765

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY server.py ./
COPY backend/ ./backend/
COPY web/ ./web/
COPY tools/ ./tools/
COPY data/ ./data/

RUN chmod +x /app/tools/entrypoint.sh

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8765/api/health',timeout=3)" || exit 1

ENTRYPOINT ["/app/tools/entrypoint.sh"]
