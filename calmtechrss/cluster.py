from __future__ import annotations

import math
import os
from collections import Counter

import numpy as np

from .models import Article, Event
from .text import sha256_text


def cluster_articles(
    articles: list[Article],
    embedding_model: str | None = None,
    embedding_device: str = "cpu",
    embedding_batch_size: int = 32,
    embedding_cpu_threads: int = 4,
) -> list[Event]:
    if not articles:
        return []
    embedder = Embedder(
        model_name=embedding_model,
        device=embedding_device,
        batch_size=embedding_batch_size,
        cpu_threads=embedding_cpu_threads,
    )
    vectors = embedder.encode([cluster_text(article) for article in articles])
    groups: list[tuple[list[Article], np.ndarray]] = []
    for article, vector in zip(articles, vectors, strict=True):
        best_index = -1
        best_similarity = -1.0
        for index, (_, centroid) in enumerate(groups):
            similarity = cosine(vector, centroid)
            if similarity > best_similarity:
                best_similarity = similarity
                best_index = index
        if best_similarity >= 0.90 or (
            best_similarity >= 0.86 and best_index >= 0 and compatible(article, groups[best_index][0])
        ):
            group, centroid = groups[best_index]
            group.append(article)
            groups[best_index] = (group, (centroid * (len(group) - 1) + vector) / len(group))
        else:
            groups.append(([article], vector))
    events = [make_event(group) for group, _ in groups]
    return sorted(events, key=lambda event: event.score, reverse=True)


def cluster_text(article: Article) -> str:
    title = article.translated_title or article.title
    summary = article.translated_summary or article.summary
    content = article.translated_content or article.content
    return f"{title}\n{summary[:400]}\n{content[:600]}"


def make_event(articles: list[Article]) -> Event:
    hashes = sorted(article.url_hash for article in articles)
    event_hash = sha256_text("\n".join(hashes))
    source_count = len({article.source_name for article in articles})
    official_bonus = sum(1 for a in articles if a.source_category == "official") * 0.5
    weight = sum(article.source_weight for article in articles)
    score = math.log1p(len(articles)) + source_count * 0.8 + official_bonus + weight * 0.2
    return Event(event_hash=event_hash, articles=articles, score=score)


def compatible(article: Article, group: list[Article]) -> bool:
    title_tokens = tokens(article.translated_title or article.title)
    for other in group:
        overlap = title_tokens & tokens(other.translated_title or other.title)
        if len(overlap) >= 2:
            return True
    return False


def tokens(value: str) -> set[str]:
    return {token.lower() for token in value.replace("-", " ").split() if len(token) >= 3}


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denominator = np.linalg.norm(a) * np.linalg.norm(b)
    if denominator == 0:
        return 0.0
    return float(np.dot(a, b) / denominator)


class Embedder:
    def __init__(
        self,
        model_name: str | None = None,
        device: str = "cpu",
        batch_size: int = 32,
        cpu_threads: int = 4,
    ) -> None:
        self.model_name = model_name or os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
        self.device = device
        self.batch_size = batch_size
        self.model = None
        try:
            import torch

            if self.device == "cpu":
                torch.set_num_threads(max(1, cpu_threads))
        except Exception:
            pass
        try:
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(self.model_name, device=self.device)
        except Exception:
            self.model = None

    def encode(self, texts: list[str]) -> list[np.ndarray]:
        if self.model is not None:
            vectors = self.model.encode(
                [f"passage: {text}" for text in texts],
                normalize_embeddings=True,
                batch_size=self.batch_size,
            )
            return [np.array(vector, dtype=float) for vector in vectors]
        return [hashing_vector(text) for text in texts]


def hashing_vector(text: str, dimensions: int = 256) -> np.ndarray:
    counts: Counter[int] = Counter()
    for token in tokens(text):
        counts[int(sha256_text(token)[:8], 16) % dimensions] += 1
    vector = np.zeros(dimensions, dtype=float)
    for index, count in counts.items():
        vector[index] = count
    norm = np.linalg.norm(vector)
    if norm:
        vector = vector / norm
    return vector
