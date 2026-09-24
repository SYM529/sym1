"""混合检索存储：向量检索 + BM25 关键词检索，用 RRF 融合。

为什么必须混合：纯向量检索对型号、缩写、代码标识符这类"字面匹配很关键"
的查询召回很差；纯关键词检索又抓不住语义相近但用词不同的情况。
两者互补，用 RRF（Reciprocal Rank Fusion）融合排名，不需要归一化分数。
"""

from __future__ import annotations

import json
import logging
import pickle
import re
from dataclasses import dataclass
from pathlib import Path

from agent.rag.chunker import Chunk
from agent.rag.config import PERSIST_DIR
from agent.rag.embeddings import EmbeddingClient

logger = logging.getLogger(__name__)

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")

try:  # 中文分词优先用 jieba，没有安装时降级为按字切分
    import jieba  # type: ignore

    def _tokenize(text: str) -> list[str]:
        lowered = text.lower()
        return [t for t in jieba.lcut(lowered) if t.strip()]
except ImportError:
    def _tokenize(text: str) -> list[str]:
        return _TOKEN_PATTERN.findall(text.lower())


@dataclass
class RetrievalHit:
    """一次召回结果，保留两路召回的排名便于分析。"""

    chunk: Chunk
    score: float             # RRF 融合分
    vector_rank: int | None = None
    bm25_rank: int | None = None


def _reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    """RRF：各路召回只贡献 1/(k+rank)，避免不同量纲的分数直接相加。"""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


class HybridStore:
    """Chroma 负责向量检索，BM25 负责字面召回，对外暴露统一的 search。"""

    def __init__(
        self,
        persist_dir: Path = PERSIST_DIR,
        collection_name: str = "knowledge_base",
        embedding_client: EmbeddingClient | None = None,
    ):
        import chromadb
        from chromadb.config import Settings

        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.embedding = embedding_client or EmbeddingClient()

        self._collection_name = collection_name
        self._client = chromadb.PersistentClient(
            path=str(self.persist_dir / "chroma"),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        self._chunks_path = self.persist_dir / "chunks.json"
        self._bm25_path = self.persist_dir / "bm25.pkl"
        self._chunks: dict[str, Chunk] = self._load_chunks()
        self._bm25 = None

    # ---------- 持久化 ----------

    def _load_chunks(self) -> dict[str, Chunk]:
        if not self._chunks_path.exists():
            return {}
        try:
            raw = json.loads(self._chunks_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("chunks.json 损坏，按空库处理")
            return {}
        return {
            item["chunk_id"]: Chunk(
                chunk_id=item["chunk_id"],
                doc_id=item["doc_id"],
                source=item["source"],
                chunk_index=item["chunk_index"],
                text=item["text"],
                metadata=item.get("metadata", {}),
            )
            for item in raw
        }

    def _save_chunks(self) -> None:
        payload = [
            {
                "chunk_id": c.chunk_id,
                "doc_id": c.doc_id,
                "source": c.source,
                "chunk_index": c.chunk_index,
                "text": c.text,
                "metadata": c.metadata,
            }
            for c in self._chunks.values()
        ]
        self._chunks_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ---------- BM25 ----------

    def _build_bm25(self):
        if not self._chunks:
            return None
        from rank_bm25 import BM25Okapi

        ordered = sorted(self._chunks.values(), key=lambda c: c.chunk_id)
        corpus = [_tokenize(c.text) for c in ordered]
        return BM25Okapi(corpus), [c.chunk_id for c in ordered]

    def _get_bm25(self):
        if self._bm25 is None:
            self._bm25 = self._build_bm25()
        return self._bm25

    def _invalidate_bm25(self) -> None:
        self._bm25 = None

    # ---------- 写入 ----------

    def _ensure_collection(self) -> None:
        """重新获取 collection 句柄。

        触发场景：运维在**另一个进程**执行 `ingest --rebuild` 清库后，
        本进程缓存的句柄立即失效，之后写入会报
        "Collection [...] does not exist"，而且会一直失败下去。

        重新拉一次句柄就能恢复。与其要求"重建后必须重启服务"，
        不如让写入自己站起来——热重建是常规操作，不该拖上重启。
        """
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def _upsert(self, ids, documents, vectors, metadatas) -> None:
        """写入向量数据；集合句柄失效时自动恢复并重试一次。"""
        try:
            self._collection.upsert(
                ids=ids, documents=documents, embeddings=vectors, metadatas=metadatas
            )
        except Exception as e:
            # 只针对句柄失效做重试，其它错误原样抛出，避免掩盖真实问题
            if "does not exist" not in str(e):
                raise
            logger.warning("Chroma 集合句柄失效，重新获取后重试：%s", e)
            self._ensure_collection()
            self._collection.upsert(
                ids=ids, documents=documents, embeddings=vectors, metadatas=metadatas
            )

    def add(self, chunks: list[Chunk]) -> int:
        """写入 chunk，已存在的 chunk_id 会被覆盖。返回写入条数。"""
        if not chunks:
            return 0

        vectors = self.embedding.embed([c.text for c in chunks])
        self._upsert(
            ids=[c.chunk_id for c in chunks],
            documents=[c.text for c in chunks],
            vectors=vectors,
            metadatas=[
                {
                    "source": c.source,
                    "doc_id": c.doc_id,
                    "chunk_index": c.chunk_index,
                    **{k: v for k, v in c.metadata.items() if v},
                }
                for c in chunks
            ],
        )
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk

        self._save_chunks()
        self._invalidate_bm25()
        return len(chunks)

    def clear(self) -> None:
        """清空知识库。"""
        try:
            self._client.delete_collection(self._collection.name)
        except Exception as e:
            logger.warning("删除 collection 失败：%s", e)
        self._collection = self._client.get_or_create_collection(
            name=self._collection.name, metadata={"hnsw:space": "cosine"}
        )
        self._chunks = {}
        self._save_chunks()
        self._invalidate_bm25()

    def count(self) -> int:
        return len(self._chunks)

    def all_chunks(self) -> list[Chunk]:
        """返回全部 chunk，供"知识库里有哪些文档"的展示使用。"""
        return list(self._chunks.values())

    def get_document_chunks(self, doc_id: str) -> list[Chunk]:
        """返回某个文档的全部 chunk（按 chunk_index 排序），供前端点开预览。

        内容都在内存缓存里，不需要查向量库——预览是纯读操作，
        不应该有检索那种毫秒级以上的开销。
        """
        chunks = [c for c in self._chunks.values() if c.doc_id == doc_id]
        chunks.sort(key=lambda c: c.chunk_index)
        return chunks

    def delete_document(self, doc_id: str) -> int:
        """删除某个文档的全部 chunk，返回删除条数。

        三处存储必须一起清理，漏掉任何一处都会产生不一致：
        - 向量库：漏了会"展示已删但还能被向量检索召回"
        - chunks.json：漏了会"进程重启后已删的文档又回来了"
        - BM25 缓存：漏了会"字面召回仍命中已删内容"
        """
        ids = [cid for cid, c in self._chunks.items() if c.doc_id == doc_id]
        if not ids:
            return 0

        try:
            self._collection.delete(ids=ids)
        except Exception as e:
            # 与写入同理：别的进程重建过库时句柄失效，重新获取后重试
            if "does not exist" not in str(e):
                raise
            logger.warning("Chroma 集合句柄失效，重新获取后重试删除：%s", e)
            self._ensure_collection()
            self._collection.delete(ids=ids)

        for cid in ids:
            self._chunks.pop(cid, None)

        self._save_chunks()
        self._invalidate_bm25()
        logger.info("已删除文档 %s（%d 个 chunk）", doc_id, len(ids))
        return len(ids)

    # ---------- 检索 ----------

    def search(self, query: str, top_k: int = 20) -> list[RetrievalHit]:
        """混合检索，返回按 RRF 融合分排序的结果。"""
        if not self._chunks:
            return []

        vector_ranking: list[str] = []
        try:
            query_vector = self.embedding.embed_one(query)
            result = self._collection.query(
                query_embeddings=[query_vector],
                n_results=min(top_k, self.count()),
            )
            vector_ranking = list(result.get("ids", [[]])[0])
        except Exception as e:
            logger.warning("向量检索失败，仅使用 BM25：%s", e)

        bm25_ranking: list[str] = []
        bm25 = self._get_bm25()
        if bm25 is not None:
            index, ids = bm25
            scores = index.get_scores(_tokenize(query))
            ranked = sorted(zip(ids, scores), key=lambda x: x[1], reverse=True)
            bm25_ranking = [cid for cid, _ in ranked[:top_k]]

        rankings = [r for r in (vector_ranking, bm25_ranking) if r]
        if not rankings:
            return []

        from agent.rag.config import RRF_K

        fused = _reciprocal_rank_fusion(rankings, k=RRF_K)
        vector_positions = {cid: i + 1 for i, cid in enumerate(vector_ranking)}
        bm25_positions = {cid: i + 1 for i, cid in enumerate(bm25_ranking)}

        ordered = sorted(fused.items(), key=lambda x: x[1], reverse=True)[:top_k]
        hits = []
        for chunk_id, score in ordered:
            chunk = self._chunks.get(chunk_id)
            if chunk is None:
                continue
            hits.append(RetrievalHit(
                chunk=chunk,
                score=score,
                vector_rank=vector_positions.get(chunk_id),
                bm25_rank=bm25_positions.get(chunk_id),
            ))
        return hits
