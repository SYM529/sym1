import json
import asyncio
import logging
import os
import re
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, field_validator
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from sqlalchemy.orm import Session
from agent.service import agent
from server.database import get_db, User
from server.auth import (
    hash_password, verify_password, create_access_token, get_current_user
)
import redis
from dotenv import load_dotenv

# 必须在导入任何读取环境变量的模块（agent.service / server.auth）之前加载
load_dotenv()

logger = logging.getLogger(__name__)

app = FastAPI(title="Agent Service")

# 生产环境不要再用 "*"：带凭证时必须显式列出来源，否则浏览器会直接拒绝
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

r = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)

SESSION_TTL = 1800
MAX_HISTORY = 20
AGENT_TIMEOUT = 60
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


# ================== 数据模型 ==================

class RegisterRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def check_username(cls, v: str) -> str:
        v = v.strip()
        if not (3 <= len(v) <= 32) or not USERNAME_PATTERN.match(v):
            raise ValueError("用户名需为 3-32 位字母、数字、下划线、点或短横线")
        return v


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"

    @field_validator("session_id")
    @classmethod
    def check_session_id(cls, v: str) -> str:
        if not SESSION_ID_PATTERN.match(v):
            raise ValueError("session_id 只能由字母、数字、下划线、短横线组成（1-64 位）")
        return v

    @field_validator("message")
    @classmethod
    def check_message(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("消息不能为空")
        if len(v) > 2000:
            raise ValueError("消息过长（上限 2000 字）")
        return v


# ================== 会话存储（按 user_id 隔离） ==================

def session_key(user_id: int, session_id: str) -> str:
    return f"session:{user_id}:{session_id}"


def _msg_to_dict(msg) -> dict:
    """序列化消息。保留 tool_calls，否则多轮对话中模型会丢失工具调用上下文。"""
    data = {"role": msg.type, "content": msg.content or ""}
    tool_calls = getattr(msg, "tool_calls", None)
    if tool_calls:
        data["tool_calls"] = tool_calls
    if msg.type == "tool":
        data["tool_call_id"] = getattr(msg, "tool_call_id", "") or ""
        data["name"] = getattr(msg, "name", "") or ""
    return data


def _dict_to_msg(data: dict):
    role = data.get("role")
    content = data.get("content", "")
    if role in ("user", "human"):
        return HumanMessage(content=content)
    if role == "tool":
        return ToolMessage(
            content=content,
            tool_call_id=data.get("tool_call_id", "") or "",
            name=data.get("name", "") or "",
        )
    return AIMessage(content=content, tool_calls=data.get("tool_calls") or [])


def _trim_history(messages: list) -> list:
    """裁剪历史，并保证首尾完整：tool 消息不能脱离它对应的 AI 消息。"""
    trimmed = list(messages[-MAX_HISTORY:])
    while trimmed and trimmed[0].type == "tool":
        trimmed.pop(0)
    # 丢弃尾部缺少工具结果的 tool_calls，避免模型收到不完整的调用序列
    while trimmed and getattr(trimmed[-1], "tool_calls", None):
        trimmed.pop()
    return trimmed


def get_history(user_id: int, session_id: str) -> list:
    try:
        data = r.get(session_key(user_id, session_id))
    except redis.RedisError as e:
        logger.warning("Redis 不可用，本次请求不读取历史: %s", e)
        return []
    if not data:
        return []
    try:
        raw = json.loads(data)
    except json.JSONDecodeError:
        logger.warning("会话历史解析失败，已忽略")
        return []
    return [_dict_to_msg(m) for m in raw if isinstance(m, dict)]


def save_history(user_id: int, session_id: str, messages: list):
    trimmed = _trim_history(messages)
    try:
        r.setex(
            session_key(user_id, session_id),
            SESSION_TTL,
            json.dumps([_msg_to_dict(m) for m in trimmed], ensure_ascii=False),
        )
    except redis.RedisError as e:
        logger.warning("Redis 不可用，会话历史未持久化: %s", e)


# ================== 认证接口 ==================

@app.post("/api/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")

    user = User(username=req.username, hashed_password=hash_password(req.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "username": user.username}


@app.post("/api/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_access_token(user.id)
    return {"access_token": token, "token_type": "bearer", "username": user.username}


@app.get("/api/me")
def me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "username": current_user.username}


# ================== Agent 接口（需登录） ==================

@app.get("/")
def root():
    try:
        r.ping()
        redis_ok = True
    except redis.RedisError:
        redis_ok = False
    return {"status": "ok", "redis": redis_ok}


@app.post("/api/agent/stream")
async def agent_stream(
    req: ChatRequest,
    current_user: User = Depends(get_current_user)
):
    user_id = current_user.id

    history = get_history(user_id, req.session_id)
    history.append(HumanMessage(content=req.message))

    async def event_generator():
        collected = []      # 本轮产生的全部消息，用于写回会话历史
        last_ai = None      # 最后一条 AI 消息，用于提取最终答案
        try:
            async with asyncio.timeout(AGENT_TIMEOUT):
                async for event in agent.astream(
                    {"messages": history},
                    stream_mode="values"
                ):
                    last_msg = event["messages"][-1]

                    # values 模式会把同一条消息重复推送，按内容去重避免前端重复渲染
                    if collected:
                        prev = collected[-1]
                        if (prev.type == last_msg.type
                                and (prev.content or "") == (last_msg.content or "")
                                and getattr(prev, "name", "") == getattr(last_msg, "name", "")):
                            continue

                    collected.append(last_msg)
                    if last_msg.type == "ai":
                        last_ai = last_msg

                    tool_name = ""
                    if last_msg.type == "tool":
                        tool_name = getattr(last_msg, "name", "") or ""
                    data = {
                        "type": last_msg.type,
                        "content": last_msg.content or "",
                        "name": tool_name,
                    }
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

            # 只有不带 tool_calls 的 AI 消息才是最终答案（带 tool_calls 说明还要继续调用工具）
            final_answer = ""
            if last_ai is not None and not getattr(last_ai, "tool_calls", None):
                final_answer = last_ai.content or ""

            if final_answer:
                # 保存完整序列（含工具调用），多轮对话才能延续上下文
                old = get_history(user_id, req.session_id)
                save_history(user_id, req.session_id, old + collected)

            yield "data: [DONE]\n\n"

        except asyncio.TimeoutError:
            err = {"type": "error", "content": f"请求超时（>{AGENT_TIMEOUT}秒），请重试"}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"
        except Exception as e:
            err = {"type": "error", "content": f"服务异常: {str(e)}"}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.delete("/api/session/{session_id}")
def clear_session(
    session_id: str,
    current_user: User = Depends(get_current_user)
):
    if not SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(status_code=400, detail="session_id 格式非法")
    try:
        r.delete(session_key(current_user.id, session_id))
    except redis.RedisError as e:
        logger.warning("Redis 不可用，会话未清除: %s", e)
        raise HTTPException(status_code=503, detail="会话服务暂不可用")
    return {"status": "cleared", "session_id": session_id}