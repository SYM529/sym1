"""图片理解：把视觉模型包装成 Agent 工具。

为什么主模型不能直接看图
----------------------
主模型用的是 deepseek-chat，它是**纯文本模型**，不接受 `image_url` 内容块，
把图片塞给它会直接报错。所以图片理解单独走一个支持视觉的模型
（默认 Qwen/Qwen3-VL，经 SiliconFlow 的 OpenAI 兼容接口）。

为什么不Bypass Agent、直接问模型
-----------------------------
直接把图片丢给视觉模型当然更简单，但那样这条能力就脱离了工具链：
"图里有几个苹果？一个 3 块，一共多少钱？"就没法再串上 calculate。
做成工具之后，是否看图、是否需要配合其它工具，仍然由 Agent 自己决定。

为什么用 base64 内联而不是图片 URL
-------------------------------
实测过公开 URL：模型服务商不会替我们去下载外链，只接受
`data:<mime>;base64,<内容>` 这种内联形式（已验证一轮，外链会直接被拒）。
因此服务端读出文件字节编码后再随请求发出。这也意味着
**图片大小直接换算成 token 成本**，所以尺寸上限比普通附件严格得多。
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os

logger = logging.getLogger(__name__)

from langchain_core.messages import HumanMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402

VISION_BASE_URL = os.getenv(
    "VISION_BASE_URL",
    os.getenv("EMBEDDING_BASE_URL", os.getenv("SILICON_BASE_URL",
                                              "https://api.siliconflow.cn/v1")),
)
# 与 Embedding 共用同一套凭据：DeepSeek 不提供多模态能力，
# 这里用 SiliconFlow，所以优先取 VISION_*，再逐级回退。
VISION_API_KEY = (
    os.getenv("VISION_API_KEY")
    or os.getenv("EMBEDDING_API_KEY")
    or os.getenv("SILICON_API_KEY")
)
VISION_MODEL = os.getenv("VISION_MODEL", "Qwen/Qwen3-VL-32B-Instruct")
VISION_TIMEOUT = float(os.getenv("VISION_TIMEOUT", "60"))
# 视觉请求更贵也更慢，单图再设一道上限（单位是字节）
VISION_MAX_IMAGE_BYTES = int(os.getenv("VISION_MAX_IMAGE_MB", "5")) * 1024 * 1024

_vision_model = None

# 由服务层注入：把 file_id 解析成磁盘路径。
# 放在这里注入而不是让 agent 直接 import server，是为了保持分层——
# agent 不需要知道文件具体存在哪、按什么规则隔离。
_file_resolver = None


def set_file_resolver(resolver) -> None:
    """注册 file_id -> Path 的解析器（由 server.uploads 提供）。"""
    global _file_resolver
    _file_resolver = resolver


def vision_available() -> bool:
    """是否配置了视觉模型。缺 key 时不挂载工具，其余能力不受影响。"""
    flag = os.getenv("VISION_ENABLED", "auto").lower()
    if flag in ("0", "off", "false", "no"):
        return False
    return bool(VISION_API_KEY)


def get_vision_model():
    """懒加载视觉模型：缺 key 时只在真正看图时报错，不影响服务启动。"""
    global _vision_model
    if _vision_model is None:
        if not VISION_API_KEY:
            raise RuntimeError("缺少 VISION_API_KEY，请在 .env 配置后再使用图片理解")
        from langchain_openai import ChatOpenAI

        _vision_model = ChatOpenAI(
            model=VISION_MODEL,
            base_url=VISION_BASE_URL,
            api_key=VISION_API_KEY,
            temperature=0,
        )
    return _vision_model


def _mime_of(path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "image/png"


def _build_multimodal_message(path, question: str) -> HumanMessage:
    """把图片编码成 data URI，与文本问题一起组成多模态消息。"""
    from server.uploads import IMAGE_SUFFIXES

    if path.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError(f"{path.suffix} 不是受支持的图片格式")

    raw = path.read_bytes()
    if len(raw) > VISION_MAX_IMAGE_BYTES:
        raise ValueError(
            f"图片过大（{len(raw) / 1024 / 1024:.1f}MB），"
            f"上限 {VISION_MAX_IMAGE_BYTES / 1024 / 1024:.0f}MB"
        )

    encoded = base64.b64encode(raw).decode("ascii")
    return HumanMessage(content=[
        {"type": "text", "text": question},
        {
            "type": "image_url",
            "image_url": {"url": f"data:{_mime_of(path)};base64,{encoded}"},
        },
    ])


@tool
async def analyze_image(file_id: str, question: str) -> str:
    """看懂一张用户上传的图片，并用中文回答关于它的问题。

    适用于：识别图中物体、读取图中文字（OCR）、描述场景、回答"图里有几个xx"。
    注意：本工具只负责"看懂图片"。算总数钱数这类数值问题请另行调用 calculate。

    参数：
        file_id: 上传返回的图片标识，形如 u1/xxxx.png
        question: 针对这张图片要问的问题
    """
    if _file_resolver is None:
        return "图片理解服务未就绪：缺少文件解析器。"

    try:
        path = _file_resolver(file_id)
        message = _build_multimodal_message(path, question)
        response = await get_vision_model().ainvoke([message])
    except Exception as e:
        # 与其它工具保持一致：把失败原因返回给模型，让它自己降级处理，
        # 而不是让整条 Agent 链路崩掉。
        logger.warning("图片理解失败：%s", e)
        return f"图片理解失败：{e}"

    content = (response.content or "").strip()
    return content or "模型没有返回有效内容。"
