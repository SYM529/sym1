"""Rerank：用 cross-encoder 对候选结果精排。

向量检索和 BM25 都是"分别编码 query 与文档"，精度有限。
Cross-encoder 让模型同时看到两者，判断相关性更准，是 RAG 效果差距最大的一环。

这里调用 SiliconFlow 的 bge-reranker-v2-m3；调用失败时降级为保持原有
融合顺序，保证检索链路不会因为外部服务抖动而整体不可用。
"""

from __future__ import annotations

import logging

import httpx

from agent.rag.chunker import Chunk
from agent.rag.config import (
    MAX_RETRIES,
    RERANK_API_KEY,
    RERANK_BASE_URL,
    RERANK_MODEL,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)


class Reranker:
    """调用 OpenAI 兼容的 /rerank 接口。"""

    def __init__(
        self,
        base_url: str = RERANK_BASE_URL,
        api_key: str = RERANK_API_KEY,
        model: str = RERANK_MODEL,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.model = model

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.base_url)

    def _url(self) -> str:
        if self.base_url.endswith("/rerank"):
            return self.base_url
        return f"{self.base_url}/rerank"

    def rerank(self, query: str, chunks: list[Chunk], top_n: int) -> list[tuple[Chunk, float]]:
        """返回按相关性降序的 (chunk, score)，失败时返回原始顺序与融合分占位。"""
        if not chunks:
            return []

        if not self.enabled:
            logger.warning("Rerank 未配置，跳过精排")
            return [(c, 0.0) for c in chunks[:top_n]]

        payload = {
            "model": self.model,
            "query": query,
            "documents": [c.text for c in chunks],
            "top_n": min(top_n, len(chunks)),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                    response = client.post(self._url(), json=payload, headers=headers)
                    response.raise_for_status()
                    data = response.json()

                results = data.get("results") or []
                ranked = []
                for item in results:
                    index = item.get("index")
                    if index is None or not 0 <= index < len(chunks):
                        continue
                    score = float(item.get("relevance_score", 0.0))
                    ranked.append((chunks[index], score))
                if ranked:
                    ranked.sort(key=lambda x: x[1], reverse=True)
                    return ranked[:top_n]
                raise RuntimeError(f"rerank 返回空结果：{str(data)[:200]}")
            except Exception as e:
                last_error = e
                logger.warning("rerank 第 %s 次调用失败：%s", attempt, e)

        logger.warning("rerank 全部重试失败，降级为融合顺序：%s", last_error)
        return [(c, 0.0) for c in chunks[:top_n]]
