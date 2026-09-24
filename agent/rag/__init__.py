"""RAG：文档入库 + 混合检索 + 引用溯源。

模块级刻意不创建客户端——否则一旦没配 Embedding API Key，
整个后端会在导入阶段就崩掉。客户端按需懒加载，由调用方处理不可用情况。
"""

from __future__ import annotations

import logging
from pathlib import Path

from agent.rag.chunker import Chunk, chunk_documents
from agent.rag.config import DOCS_DIR, PERSIST_DIR
from agent.rag.loader import Document, load_directory
from agent.rag.retriever import Citation, RetrievalResult, Retriever
from agent.rag.store import HybridStore

logger = logging.getLogger(__name__)

_store: HybridStore | None = None
_retriever: Retriever | None = None


def get_store() -> HybridStore:
    """获取向量库实例（单例）。"""
    global _store
    if _store is None:
        _store = HybridStore()
    return _store


def get_retriever() -> Retriever:
    """获取检索器（单例）。"""
    global _retriever
    if _retriever is None:
        _retriever = Retriever(get_store())
    return _retriever


def reset() -> None:
    """重置单例，主要用于测试与切换配置后重建。"""
    global _store, _retriever
    _store = None
    _retriever = None


def summarize_documents(chunks) -> list[dict]:
    """把 chunk 按文档聚合，供"知识库里有哪些文档"的展示使用。

    刻意做成**纯函数**（只吃 chunk 列表、不碰 store）：
    真实的 store 依赖向量库与 Embedding 服务，
    没法在无 API Key 的环境里构造出来，也就没法单测。
    把聚合逻辑抽出来之后，这部分就能用普通测试覆盖。

    owner / file_id / ingested_at 都来自 chunk 的 metadata：
    它们是在上传入库时由服务层写入的，CLI 入库的共享文档没有这些字段。
    """
    grouped: dict[str, dict] = {}
    for chunk in chunks:
        meta = chunk.metadata or {}
        info = grouped.get(chunk.doc_id)
        if info is None:
            info = {
                "doc_id": chunk.doc_id,
                "source": chunk.source,
                "chunks": 0,
                "owner": meta.get("owner") or None,
                "file_id": meta.get("file_id") or None,
                "ingested_at": meta.get("ingested_at") or None,
                "_headings": set(),
            }
            grouped[chunk.doc_id] = info

        info["chunks"] += 1
        # 同一文档重新上传后 source 可能变过，以最后见到的为准
        info["source"] = chunk.source
        # 归属信息只要**任一个** chunk 带着就够：
        # 归属决定了谁能删这份文档，漏读会直接导致"自己的文档删不掉"，
        # 或者更糟——被判成共享文档而谁都删不了。
        for key in ("owner", "file_id", "ingested_at"):
            if info.get(key) is None and meta.get(key):
                info[key] = meta[key]
        heading = meta.get("heading")
        if heading:
            info["_headings"].add(heading)

    documents = []
    for info in grouped.values():
        info["headings"] = sorted(info.pop("_headings"))[:5]
        documents.append(info)

    documents.sort(key=lambda d: (d["source"] or "", d["doc_id"]))
    return documents


def list_documents() -> list[dict]:
    """列出知识库中的文档（聚合视图）。"""
    return summarize_documents(get_store().all_chunks())


def delete_document(doc_id: str) -> int:
    """删除一个文档的全部 chunk，返回删除条数。"""
    return get_store().delete_document(doc_id)


def get_document_chunks(doc_id: str) -> list[dict]:
    """取某个文档的全部 chunk（按序），供前端点开预览原文。"""
    return [
        {
            "chunk_index": c.chunk_index,
            "heading": c.metadata.get("heading") or "",
            "text": c.text,
        }
        for c in get_store().get_document_chunks(doc_id)
    ]


def is_ready() -> bool:
    """知识库是否已就绪（有内容且可检索）。"""
    try:
        return get_store().count() > 0
    except Exception as e:
        logger.warning("知识库不可用：%s", e)
        return False


def ingest_directory(directory: Path = DOCS_DIR, rebuild: bool = False) -> dict:
    """把目录下的文档灌进知识库，返回统计信息。

    rebuild=True 时先清空，避免旧文档的 chunk 与新版混在一起。
    """
    store = get_store()
    if rebuild:
        store.clear()

    documents = load_directory(directory)
    if not documents:
        return {"documents": 0, "chunks": 0, "total": store.count()}

    chunks = chunk_documents(documents)
    written = store.add(chunks)
    return {
        "documents": len(documents),
        "chunks": written,
        "total": store.count(),
        "sources": sorted({c.source for c in chunks}),
    }


__all__ = [
    "Chunk",
    "Citation",
    "Document",
    "HybridStore",
    "RetrievalResult",
    "Retriever",
    "chunk_documents",
    "delete_document",
    "get_retriever",
    "get_store",
    "ingest_directory",
    "is_ready",
    "list_documents",
    "summarize_documents",
    "load_directory",
    "PERSIST_DIR",
    "DOCS_DIR",
]
