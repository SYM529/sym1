# syntax=docker/dockerfile:1

FROM python:3.12-slim

# 系统依赖：gcc 用于编译部分 wheel；curl 用于健康检查；
# tzdata 提供 /usr/share/zoneinfo，配合 TZ 让容器内时间与北京时间一致
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        curl \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

# 容器默认 UTC：不设这个，"现在几点"这类工具会慢 8 小时
ENV TZ=Asia/Shanghai

WORKDIR /app

# 先只复制依赖清单，利用 Docker 构建缓存：requirements 不变时不重装依赖
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY agent/ ./agent/
COPY server/ ./server/
COPY evals/ ./evals/
# 示例文档一并进镜像：否则在容器内执行
# `python -m agent.rag.ingest ./docs` 会因目录不存在而失败
COPY docs/ ./docs/
# 数据库迁移：生产环境用 `alembic upgrade head` 管理 schema
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY main.py ./

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

CMD ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
