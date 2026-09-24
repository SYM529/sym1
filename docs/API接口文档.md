# API 接口文档

## 认证方式

所有接口通过 `Authorization: Bearer <token>` 请求头认证。
Token 通过 `POST /api/login` 获取，有效期 24 小时。

## 核心接口

### 登录

```
POST /api/login
Content-Type: application/x-www-form-urlencoded

username=demo&password=xxxx
```

成功返回 `access_token` 与用户名。

### 流式对话

```
POST /api/agent/stream
Content-Type: application/json
```

请求体：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| message | string | 用户消息，必填 |
| session_id | string | 会话 ID，1-64 位字母数字 |
| file_id | string | 可选，附件文件的引用 |

响应为 `text/event-stream`，事件类型包括 `human`、`ai`、`tool`、`usage`、`error`，
以 `data: [DONE]` 结尾。

### 上传文件

```
POST /api/upload
Content-Type: multipart/form-data
```

文档入库后返回 `file_id` 与入库片段数。图片走视觉理解，不进入知识库。

## 错误码

| 状态码 | 含义 | 处理建议 |
| --- | --- | --- |
| 400 | 参数非法 | 检查请求体格式与 file_id |
| 401 | 未登录或 token 过期 | 重新调用 /api/login |
| 403 | 权限不足 | 该接口需要管理员身份 |
| 404 | 资源不存在 | 确认 doc_id / session_id |
| 429 | 触发限流 | 按 Retry-After 头等待后重试 |
| 503 | 服务繁忙 | 稍后重试，或联系管理员调整并发上限 |

## 限流规则

单用户默认每分钟 20 次 Agent 请求（`RATE_LIMIT_PER_MIN`），
超出返回 429 并携带 `Retry-After` 响应头。
同时运行的请求上限为 8 个（`AGENT_MAX_CONCURRENCY`），超出发 503。
