"""Embedding 客户端。

封装 OpenAI 兼容的 /embeddings 接口，处理批量、重试和超时。
批量调用是有意为之：逐条请求会让入库时间随文档量线性增长，
而 bge-m3 这类模型单次可处理多条文本。
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from agent.rag.config import (
    EMBED_BATCH_SIZE,
    EMBEDDING_API_KEY,
    EMBEDDING_BASE_URL,
    EMBEDDING_MODEL,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """Embedding 调用失败。"""


class EmbeddingClient:
    """OpenAI 兼容的 embedding 客户端。"""

    def __init__(
        self,
        base_url: str = EMBEDDING_BASE_URL,
        api_key: str = EMBEDDING_API_KEY,
        model: str = EMBEDDING_MODEL,
        batch_size: int = EMBED_BATCH_SIZE,
    ):
        if not api_key:
            raise ValueError(
                "缺少 Embedding API Key，请在 .env 配置 EMBEDDING_API_KEY 或 SILICON_API_KEY"
            )
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.batch_size = batch_size
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _url(self) -> str:
        # 兼容用户把 base_url 配成 .../v1 或已含 /embeddings 的情况
        if self.base_url.endswith("/embeddings"):
            return self.base_url
        return f"{self.base_url}/embeddings"

    def embed(self, texts: list[str]) -> list[list[float]]:
        """同步批量编码，保持输入顺序。"""
        if not texts:
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            vectors.extend(self._request(batch))
        return vectors

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        """异步版本，供 FastAPI 接口使用，避免阻塞事件循环。"""
        return await asyncio.to_thread(self.embed, texts)

    def _request(self, batch: list[str]) -> list[list[float]]:
        payload = {"model": self.model, "input": batch, "encoding_format": "float"}
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                    response = client.post(self._url(), json=payload, headers=self._headers)
                    response.raise_for_status()
                    data = response.json()
                # 部分实现不保证顺序，按 index 回填更稳妥
                items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
                vectors = [item["embedding"] for item in items]
                if len(vectors) != len(batch):
                    raise EmbeddingError(
                        f"返回向量数 {len(vectors)} 与请求条数 {len(batch)} 不一致"
                    )
                return vectors
            except Exception as e:
                last_error = e
                logger.warning("embedding 第 %s 次调用失败：%s", attempt, e)

        raise EmbeddingError(f"embedding 调用失败（重试 {MAX_RETRIES} 次）：{last_error}")

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]
