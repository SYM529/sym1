# 前端（Vue 3 + Vite）

```bash
npm install
npm run dev      # http://localhost:5173
npm run build
npm run lint
```

## 结构

- `src/api.js` — 统一封装鉴权与 SSE 读取，token 存于 localStorage，401 时自动清理并退回登录页
- `src/App.vue` — 聊天界面（消息流、工具调用折叠、会话管理）
- `src/components/LoginView.vue` — 登录 / 注册

## 后端地址

请求统一走相对路径 `/api`，开发环境由 `vite.config.js` 的 proxy 转发到 `http://127.0.0.1:8000`。

需要指向其他后端时，在 `frontend/.env` 中设置：

```
VITE_API_BASE_URL=http://your-host:8000/api
```
