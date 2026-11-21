"""Small BM25 retriever over the Markdown knowledge base.

No heavy ML dependencies, so it runs on any laptop or small server. Each `## `
section of a knowledge file becomes one chunk. Files can carry Hindi and Hinglish
keywords so questions in either language find the right section.

To upgrade later: swap this for multilingual embeddings + a vector DB (pgvector,
Qdrant) behind the same `search()` function.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
TOKEN_RE = re.compile(r"[a-z0-9]+|[ऀ-ॿ]+")
STOPWORDS = {
    "the", "a", "an", "is", "are", "to", "of", "and", "or", "in", "on", "for", "i", "my", "me", "what",
    "how", "do", "does", "can", "it", "this", "that", "be", "with", "at", "by", "from", "if", "you", "your",
    "kya", "hai", "hain", "ka", "ki", "ke", "ko", "me", "mein", "se", "aur", "ya", "main", "mera", "meri",
    "क्या", "है", "हैं", "का", "की", "के", "को", "में", "से", "और", "या", "मैं", "मेरा", "मेरी", "कैसे",
}


def tokenize(text: str) -> list[str]:
    tokens = []
    for t in TOKEN_RE.findall(text.lower()):
        if t in STOPWORDS:
            continue
        if t.isascii() and len(t) > 3 and t.endswith("s"):
            t = t[:-1]  # crude plural folding: wages -> wage
        tokens.append(t)
    return tokens


@dataclass
class Chunk:
    id: str
    doc_title: str
    section: str
    text: str
    source_url: str
    audience: str  # all | worker | employer


def _load_chunks() -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta = dict(re.findall(r"^(\w+):\s*(.+)$", raw.split("\n\n", 1)[0], flags=re.M))
        title = meta.get("title", path.stem)
        source = meta.get("source", "")
        audience = meta.get("audience", "all")
        for i, block in enumerate(re.split(r"^## ", raw, flags=re.M)[1:]):
            section, _, body = block.partition("\n")
            chunks.append(Chunk(f"{path.stem}#{i}", title, section.strip(), body.strip(), source, audience))
    return chunks


class BM25Index:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.docs = [Counter(tokenize(f"{c.doc_title} {c.section} {c.section} {c.text}")) for c in chunks]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg_len = sum(self.lengths) / max(len(self.lengths), 1)
        df: Counter = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 4, audience: str | None = None) -> list[tuple[Chunk, float]]:
        q = tokenize(query)
        scored = []
        for i, d in enumerate(self.docs):
            c = self.chunks[i]
            if audience and c.audience not in ("all", audience):
                continue
            score = 0.0
            for t in q:
                if t not in d:
                    continue
                tf = d[t]
                denom = tf + self.k1 * (1 - self.b + self.b * self.lengths[i] / self.avg_len)
                score += self.idf[t] * tf * (self.k1 + 1) / denom
            if score > 0:
                scored.append((c, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]


_index: BM25Index | None = None


def get_index() -> BM25Index:
    global _index
    if _index is None:
        _index = BM25Index(_load_chunks())
    return _index


def search(query: str, k: int = 4, audience: str | None = None) -> list[tuple[Chunk, float]]:
    return get_index().search(query, k, audience)
