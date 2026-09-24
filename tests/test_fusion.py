"""混合检索的融合逻辑测试。

RRF 的作用是把量纲不同的两路召回（向量相似度、BM25 分数）合并成可比的排序。
直接把两路分数相加是没有意义的——向量相似度在 0~1，BM25 分数可能到几十，
相加会让 BM25 完全主导结果。
"""

from agent.rag.store import _reciprocal_rank_fusion, _tokenize


class TestReciprocalRankFusion:
    def test_item_in_both_rankings_wins(self):
        vector = ["a", "b", "c"]
        bm25 = ["c", "a"]
        scores = _reciprocal_rank_fusion([vector, bm25], k=60)

        assert scores["a"] > scores["c"], "两路都命中的条目应当排在最前"

    def test_rank_position_matters(self):
        scores = _reciprocal_rank_fusion([["x", "y", "z"]], k=60)
        assert scores["x"] > scores["y"] > scores["z"]

    def test_single_path_item_still_scored(self):
        """只在单路召回中出现的结果不应被丢弃。"""
        scores = _reciprocal_rank_fusion([["only_vector"], ["only_bm25"]], k=60)
        assert scores["only_vector"] > 0
        assert scores["only_bm25"] > 0
        assert scores["only_vector"] == scores["only_bm25"]

    def test_empty_rankings(self):
        assert _reciprocal_rank_fusion([], k=60) == {}
        assert _reciprocal_rank_fusion([[]], k=60) == {}

    def test_k_parameter_changes_spread(self):
        """k 越大，排名靠前的优势被削弱，各条目分数越接近。"""
        tight = _reciprocal_rank_fusion([["a", "b"]], k=1)
        loose = _reciprocal_rank_fusion([["a", "b"]], k=100)
        assert (tight["a"] - tight["b"]) > (loose["a"] - loose["b"])


class TestTokenize:
    def test_english_and_digits(self):
        tokens = _tokenize("Redis TTL 1800 seconds")
        assert "redis" in tokens
        assert "1800" in [t.lower() for t in tokens]

    def test_chinese_is_segmented(self):
        tokens = _tokenize("会话历史在 Redis 中保存多久")
        assert tokens
        assert any("会话" in t or "会" in t for t in tokens)

    def test_empty_input(self):
        assert _tokenize("") == []

    def test_case_insensitive(self):
        assert _tokenize("Redis") == _tokenize("redis")
