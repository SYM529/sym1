# Agent 智能助手

基于 **LangChain v1 + FastAPI + Vue 3** 的对话式 Agent 应用。后端驱动 ReAct Agent 自主调用工具（数学计算、当前时间、联网搜索），通过 SSE 流式返回结果；前端提供登录注册与多轮会话界面。

## 目录结构

```
agent/      Agent 与工具定义（create_agent + 3 个工具）
server/     FastAPI：JWT 认证、SSE 流式对话、Redis 会话、SQLite 用户表
frontend/   Vue 3 + Element Plus 界面
main.py     命令行快速体验入口
```

## 快速开始

### 1. 安装依赖

需要 Python ≥ 3.11（用到 `asyncio.timeout`）。

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

至少填写 `DEEPSEEK_API_KEY`、`TAVILY_API_KEY`、`JWT_SECRET`。生成 JWT 密钥：

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

> 未配置 `JWT_SECRET` 时服务会拒绝启动。`.env` 已在 `.gitignore` 中，请勿提交。

### 3. 启动 Redis

会话历史依赖 Redis；未启动时服务仍可运行，只是不保存上下文。

```bash
docker run -d -p 6379:6379 redis:7-alpine
```

### 4. 启动后端

```bash
uvicorn server.main:app --reload --port 8000
```

访问 `http://127.0.0.1:8000/` 可查看健康状态，`redis` 字段反映 Redis 连通性。

### 5. 启动前端

```bash
cd frontend
npm install
npm run dev
```

打开 `http://localhost:5173`，注册账号后即可对话。开发环境由 Vite 把 `/api` 代理到后端。

### 命令行体验（可选）

```bash
python main.py
```

## 接口

| 方法 | 路径 | 说明 | 鉴权 |
| --- | --- | --- | --- |
| POST | `/api/register` | 注册 | 否 |
| POST | `/api/login` | 登录，返回 JWT | 否 |
| GET | `/api/me` | 当前用户 | 是 |
| POST | `/api/agent/stream` | SSE 流式对话 | 是 |
| DELETE | `/api/session/{session_id}` | 清空会话 | 是 |

## 设计要点

- **会话隔离**：Redis key 为 `session:{user_id}:{session_id}`，TTL 30 分钟，按用户隔离。
- **历史完整性**：保存完整的 human / ai / tool 消息序列并保留 `tool_calls`，多轮对话中模型能延续工具上下文；裁剪时保证 tool 消息不会脱离其 AI 消息。
- **安全求值**：`calculate` 基于 AST 白名单解析，不使用 `eval`，拦截函数调用、属性访问、推导式等危险语法，并限制幂运算与阶乘规模。
- **流式去重**：后端按内容去重后再推送，前端跳过重复的 human 事件。
- **优雅降级**：Redis 异常时记录日志并继续服务，而不是让请求 500。

## 已知限制

- 会话历史只在 Redis 中，未做持久化归档。
- 未做速率限制，公网部署前需补充。
- `agent.db` 使用 SQLite，适合本地开发，生产建议换 PostgreSQL。
