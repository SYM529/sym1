"""分块策略测试。

重点是两条：表格必须完整保留、每个块都要能知道自己属于哪个标题。
前者决定召回是否有效，后者决定引用能否显示"出自哪一节"。
"""

import pytest

from agent.rag.chunker import _is_table, chunk_document
from agent.rag.loader import Document


def make_document(text: str, source: str = "test.md") -> Document:
    return Document(doc_id="testdoc", source=source, text=text, metadata={})


TABLE_MARKDOWN = """## 关键运行参数

| 参数 | 取值 | 说明 |
| --- | --- | --- |
| 后端端口 | 8000 | uvicorn 默认监听端口 |
| 会话 TTL | 1800 秒 | Redis 中会话历史的过期时间 |
| JWT 有效期 | 7 天 | 由配置控制 |
"""


class TestTableHandling:
    def test_recognizes_table(self):
        assert _is_table("| a | b |\n| --- | --- |\n| 1 | 2 |")
        assert not _is_table("普通段落文本")

    def test_table_kept_intact(self):
        """表格不能被按行切散，否则表头与取值分离，召回必然产生幻觉。"""
        chunks = chunk_document(make_document(TABLE_MARKDOWN), chunk_size=100, overlap=10)
        table_chunks = [c for c in chunks if _is_table(c.text)]
        assert table_chunks, "表格内容丢失"

        # 表头与"会话 TTL"这一行必须还在同一个块里
        joined = "\n".join(c.text for c in table_chunks)
        assert "参数" in joined
        assert "会话 TTL" in joined
        assert "1800" in joined

    def test_table_flagged_in_metadata(self):
        chunks = chunk_document(make_document(TABLE_MARKDOWN), chunk_size=100, overlap=10)
        assert any(c.metadata.get("is_table") for c in chunks)


class TestHeadingAware:
    def test_heading_attached_to_chunk(self):
        text = "## 部署方式\n\n使用 docker compose 启动。\n\n## 常见问题\n\n重启容器即可。"
        chunks = chunk_document(make_document(text), chunk_size=200, overlap=20)
        deployed = [c for c in chunks if "docker compose" in c.text]
        assert deployed
        assert deployed[0].metadata.get("heading") == "部署方式"

    def test_chunks_do_not_span_two_sections(self):
        """相邻标题下的内容不应被混进同一个块。"""
        text = "## 第一节\n\n" + "甲" * 200 + "\n\n## 第二节\n\n" + "乙" * 200
        chunks = chunk_document(make_document(text), chunk_size=100, overlap=10)
        for chunk in chunks:
            assert not ("甲" in chunk.text and "乙" in chunk.text), \
                "块跨越了两个不同主题的小节"


class TestOverlap:
    def test_overlap_preserves_boundary_context(self):
        text = "## 说明\n\n" + "".join(f"第{i}句话。" for i in range(30))
        chunks = chunk_document(make_document(text), chunk_size=80, overlap=30)
        assert len(chunks) > 1
        # 相邻块之间应有重叠：前一块的尾部出现在后一块的开头
        assert chunks[0].text[-20:] in chunks[1].text

    def test_rejects_invalid_overlap(self):
        with pytest.raises(ValueError):
            chunk_document(make_document("内容"), chunk_size=50, overlap=50)


class TestChunkMetadata:
    def test_chunk_ids_are_unique(self):
        text = "## A\n\n" + "内容" * 300
        chunks = chunk_document(make_document(text), chunk_size=100, overlap=10)
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))

    def test_source_preserved(self):
        chunks = chunk_document(make_document("内容", source="docs/x.md"),
                                chunk_size=100, overlap=10)
        assert all(c.source == "docs/x.md" for c in chunks)
