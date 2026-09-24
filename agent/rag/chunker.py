"""文档分块。

分块质量直接决定召回质量，也是 RAG 最容易出问题的一环。这里做了三件关键的事：

1. **按 Markdown 标题先分段**：让每个块都归属明确的主题，
   而不是跨主题切断后变成语义混杂的碎片。
2. **表格整体保留**：参数表这类内容按行切散后，表头与取值分离，
   检索到后半段时模型根本看不到"这一行说的是哪个参数"，必然产生幻觉。
   所以表格被视为不可分割的原子单元。
3. **相邻块保留重叠**：避免答案正好落在块边界上导致怎么都检索不到。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agent.rag.loader import Document
from agent.rag.config import CHUNK_OVERLAP, CHUNK_SIZE

# 从粗到细的分隔符：优先在段落处断开，其次句子，最后才按字符硬切
SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]

HEADING_LINE = re.compile(r"^#{1,6}\s+(.+?)\s*$")
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")


@dataclass
class Chunk:
    """一个检索单元。"""

    chunk_id: str
    doc_id: str
    source: str          # 来源文件名
    chunk_index: int     # 在文档内的序号
    text: str
    metadata: dict = field(default_factory=dict)


def _is_table(text: str) -> bool:
    """判断是否为完整的 Markdown 表格（含表头分隔行）。"""
    lines = [line for line in text.strip().split("\n") if line.strip()]
    if len(lines) < 2:
        return False
    return all(TABLE_ROW.match(line) for line in lines)


def _split_by_heading(text: str) -> list[tuple[str, str]]:
    """按 Markdown 标题切成若干 (标题, 正文) 段落。"""
    sections: list[tuple[str, str]] = []
    heading = ""
    buffer: list[str] = []

    def flush():
        content = "\n".join(buffer).strip()
        if content:
            sections.append((heading, content))

    for line in text.split("\n"):
        matched = HEADING_LINE.match(line)
        if matched:
            flush()
            heading = matched.group(1).strip()
            buffer = [line]
        else:
            buffer.append(line)
    flush()

    return sections


def _split_recursive(text: str, chunk_size: int, separators: list[str]) -> list[str]:
    """递归按分隔符切分，直到每个片段都不超过 chunk_size。"""
    if len(text) <= chunk_size or not separators:
        return [text] if text.strip() else []

    # 表格是原子单元：切散后表头与取值分离，等于制造幻觉
    if _is_table(text):
        return [text]

    separator, rest = separators[0], separators[1:]
    parts = text.split(separator) if separator else list(text)

    pieces: list[str] = []
    buffer = ""
    for part in parts:
        piece = part + (separator if separator else "")
        if len(buffer) + len(piece) <= chunk_size:
            buffer += piece
        else:
            if buffer:
                pieces.append(buffer)
            if len(piece) > chunk_size:
                if _is_table(piece):
                    pieces.append(piece)      # 表格整体保留，不再细分
                    buffer = ""
                else:
                    pieces.extend(_split_recursive(piece, chunk_size, rest))
                    buffer = ""
            else:
                buffer = piece
    if buffer:
        pieces.append(buffer)

    return [p for p in pieces if p.strip()]


def _apply_overlap(pieces: list[str], overlap: int) -> list[str]:
    """给相邻块补上前一块的尾部，保留跨块的上下文连续性。

    但表格要排除在外：它本身是自洽的原子单元，叠加前文反而会破坏
    "整块就是一张表"这一属性，导致 `is_table` 标记失效、引用展示被污染。
    """
    if overlap <= 0 or len(pieces) <= 1:
        return pieces
    merged = [pieces[0]]
    for previous, current in zip(pieces, pieces[1:]):
        if _is_table(current):
            merged.append(current)
        else:
            merged.append(previous[-overlap:] + current)
    return merged


def chunk_document(
    document: Document,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[Chunk]:
    """把一份文档切成若干检索单元。"""
    if overlap >= chunk_size:
        raise ValueError(f"overlap({overlap}) 必须小于 chunk_size({chunk_size})")

    chunks: list[Chunk] = []
    index = 0
    for heading, content in _split_by_heading(document.text):
        pieces = _split_recursive(content, chunk_size, SEPARATORS)
        pieces = _apply_overlap(pieces, overlap)

        for text in pieces:
            text = text.strip()
            if not text:
                continue
            chunks.append(Chunk(
                chunk_id=f"{document.doc_id}-{index}",
                doc_id=document.doc_id,
                source=document.source,
                chunk_index=index,
                text=text,
                metadata={
                    "heading": heading,
                    "is_table": _is_table(text),
                    "chars": len(text),
                    **document.metadata,
                },
            ))
            index += 1

    return chunks


def chunk_documents(documents: list[Document], **kwargs) -> list[Chunk]:
    chunks: list[Chunk] = []
    for document in documents:
        chunks.extend(chunk_document(document, **kwargs))
    return chunks
