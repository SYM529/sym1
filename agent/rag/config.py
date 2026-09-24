"""RAG 配置。

全部参数可通过环境变量覆盖，方便做对比实验（例如比较不同 chunk_size
对召回率的影响），而不需要改代码。
"""

import os
from pathlib import Path


# ---------- Embedding ----------
# DeepSeek 只提供对话模型，不提供 embedding，这里用 SiliconFlow 的
# OpenAI 兼容接口（BAAI/bge-m3，支持中文且效果稳定）
EMBEDDING_BASE_URL = os.getenv(
    "EMBEDDING_BASE_URL", os.getenv("SILICON_BASE_URL", "https://api.siliconflow.cn/v1")
)
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY") or os.getenv("SILICON_API_KEY")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

# ---------- Rerank ----------
RERANK_BASE_URL = os.getenv("RERANK_BASE_URL", EMBEDDING_BASE_URL)
RERANK_API_KEY = os.getenv("RERANK_API_KEY") or EMBEDDING_API_KEY
RERANK_MODEL = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")

# ---------- 分块 ----------
CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "80"))

# ---------- 检索 ----------
TOP_K = int(os.getenv("RAG_TOP_K", "4"))
# 候选倍数：先召回 top_k * 3 条交给 rerank 精排，兼顾召回与成本
CANDIDATE_MULTIPLIER = int(os.getenv("RAG_CANDIDATE_MULTIPLIER", "3"))
# RRF 融合常数，越大越弱化排名靠前结果的权重
RRF_K = 60
# rerank 分数低于该阈值视为未命中，宁可让 Agent 说"知识库里没有"，
# 也不要把噪声塞进上下文诱发幻觉。
#
# 该值基于实测分数分布确定，不是拍脑袋定的：
#   相关查询的最高分：0.97 / 0.93 / 0.0055
#   不相关查询（天气、股价等）：0.0000 ~ 0.0004
# 初版取 0.05 时，会把"前端用什么 UI 组件库"这条正确答案（0.0055）误杀，
# 表现为"检索不到明明在文档里的内容"。
MIN_RERANK_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.002"))
# 引用文本在前端展示时的截断长度
MAX_CITATION_CHARS = 400

# ---------- 存储 ----------
PERSIST_DIR = Path(os.getenv("RAG_PERSIST_DIR", "./rag_store"))
DOCS_DIR = Path(os.getenv("RAG_DOCS_DIR", "./docs"))

# ---------- 调用限制 ----------
EMBED_BATCH_SIZE = int(os.getenv("RAG_EMBED_BATCH", "16"))
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
