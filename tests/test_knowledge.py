"""知识库文档聚合测试。

为什么要为"列个列表"写测试：知识库是**所有人共用**的，
删除接口的安全性完全依赖能否正确读出每个文档归属于谁。
owner 读错或读漏，后果是任何人都能删掉别人的资料。

聚合逻辑做成纯函数（只吃 chunk 列表）正是为了能在这里覆盖——
真实的 store 连着向量库和 Embedding 服务，没法在单测里构造。
"""

from agent.rag import summarize_documents
from agent.rag.chunker import Chunk


def make_chunk(doc_id: str, source: str, index: int = 0, **meta) -> Chunk:
    return Chunk(
        chunk_id=f"{doc_id}-{index}",
        doc_id=doc_id,
        source=source,
        chunk_index=index,
        text=f"{source} 的第 {index} 段",
        metadata=dict(meta),
    )


class TestGrouping:
    def test_chunks_are_grouped_by_document(self):
        chunks = [
            make_chunk("aaaa1111aaaa1111", "手册.md", 0),
            make_chunk("aaaa1111aaaa1111", "手册.md", 1),
            make_chunk("bbbb2222bbbb2222", "FAQ.md", 0),
        ]

        docs = summarize_documents(chunks)

        assert len(docs) == 2
        manual = next(d for d in docs if d["doc_id"] == "aaaa1111aaaa1111")
        assert manual["chunks"] == 2

    def test_empty_knowledge_base(self):
        assert summarize_documents([]) == []

    def test_documents_are_sorted_by_source(self):
        chunks = [
            make_chunk("bbbb2222bbbb2222", "运维FAQ.md"),
            make_chunk("aaaa1111aaaa1111", "API说明.md"),
        ]

        sources = [d["source"] for d in summarize_documents(chunks)]

        assert sources == ["API说明.md", "运维FAQ.md"]


class TestOwnership:
    def test_uploaded_document_carries_owner(self):
        chunks = [make_chunk("aaaa1111aaaa1111", "我的笔记.md", 0, owner="7")]

        doc = summarize_documents(chunks)[0]

        assert doc["owner"] == "7"
        assert doc["file_id"] is None

    def test_shared_document_has_no_owner(self):
        # CLI 入库的示例文档没有归属，接口层据此拒绝通过 HTTP 删除
        chunks = [make_chunk("cccc3333cccc3333", "项目技术说明.md")]

        doc = summarize_documents(chunks)[0]

        assert doc["owner"] is None

    def test_owner_is_taken_from_any_chunk_of_the_document(self):
        # 归属只写进部分 chunk 也不能丢（这里故意放在**后面**的块上）：
        # 聚合必须在文档层补齐，否则自己的文档会被判成共享文档而删不掉
        chunks = [
            make_chunk("aaaa1111aaaa1111", "笔记.md", 0),
            make_chunk("aaaa1111aaaa1111", "笔记.md", 1, owner="9"),
        ]

        doc = summarize_documents(chunks)[0]

        assert doc["owner"] == "9"

    def test_file_id_and_timestamp_survive(self):
        chunks = [
            make_chunk("aaaa1111aaaa1111", "笔记.md", 0,
                       owner="3", file_id="u3/abc.txt", ingested_at="2026-09-22T10:00:00"),
        ]

        doc = summarize_documents(chunks)[0]

        assert doc["file_id"] == "u3/abc.txt"
        assert doc["ingested_at"] == "2026-09-22T10:00:00"


class TestPresentation:
    def test_headings_are_collected_and_sorted(self):
        chunks = [
            make_chunk("aaaa1111aaaa1111", "手册.md", 0, heading="保修政策"),
            make_chunk("aaaa1111aaaa1111", "手册.md", 1, heading="基本参数"),
            make_chunk("aaaa1111aaaa1111", "手册.md", 2, heading="基本参数"),
        ]

        doc = summarize_documents(chunks)[0]

        # 去重并排序（按 Unicode 码点，与 locale 无关），前端展示顺序才稳定
        assert doc["headings"] == sorted(["保修政策", "基本参数"])
        assert len(doc["headings"]) == 2

    def test_headings_are_capped(self):
        chunks = [
            make_chunk("aaaa1111aaaa1111", "手册.md", i, heading=f"第{i}节")
            for i in range(8)
        ]

        assert len(summarize_documents(chunks)[0]["headings"]) == 5

    def test_latest_source_wins_after_reupload(self):
        # 重新上传时改了文件名，展示名应当跟着更新
        chunks = [
            make_chunk("aaaa1111aaaa1111", "旧名字.md", 0),
            make_chunk("aaaa1111aaaa1111", "新名字.md", 1),
        ]

        assert summarize_documents(chunks)[0]["source"] == "新名字.md"
