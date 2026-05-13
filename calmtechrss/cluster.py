from __future__ import annotations

import math
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .models import Article, Event
from .text import sha256_text, truncate

EventJudge = Callable[[Article, list[Article]], bool]


@dataclass
class ExistingCluster:
    event_hash: str
    articles: list[Article]
    centroid: list[float]


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
    groups: list[dict] = []
    for article, vector in zip(articles, vectors, strict=True):
        selected = judge_candidates(article, top_candidates(vector, groups), event_judge=None)
        if selected is not None:
            selected["cluster"]["articles"].append(article)
        else:
            groups.append({"articles": [article], "centroid": vector})
    events = [make_event(group["articles"], centroid=group["centroid"]) for group in groups]
    return sorted(events, key=lambda event: event.score, reverse=True)


def incremental_cluster_articles(
    articles: list[Article],
    existing_clusters: list[ExistingCluster],
    embedding_model: str | None = None,
    embedding_device: str = "cpu",
    embedding_batch_size: int = 32,
    embedding_cpu_threads: int = 4,
    event_judge: EventJudge | None = None,
    max_judge_workers: int = 4,
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
    changed_events: dict[str, Event] = {}
    existing = [
        {
            "event_hash": cluster.event_hash,
            "articles": list(cluster.articles),
            "centroid": np.array(cluster.centroid, dtype=float),
        }
        for cluster in existing_clusters
        if cluster.centroid
    ]

    for article, vector in zip(articles, vectors, strict=True):
        existing_candidates = top_candidates(vector, existing)
        selected = judge_candidates(article, existing_candidates, event_judge, max_judge_workers)
        if selected is not None:
            cluster = selected["cluster"]
            cluster["articles"].append(article)
            event = make_event(
                cluster["articles"],
                event_hash=str(cluster["event_hash"]),
                centroid=cluster["centroid"],
                is_new=False,
            )
            changed_events[event.event_hash] = event
        else:
            new_cluster = {
                "event_hash": make_event([article]).event_hash,
                "articles": [article],
                "centroid": vector,
            }
            existing.append(new_cluster)
            event = make_event([article], event_hash=str(new_cluster["event_hash"]), centroid=vector, is_new=True)
            changed_events[event.event_hash] = event
    return sorted(changed_events.values(), key=lambda event: event.score, reverse=True)


def top_candidates(
    vector: np.ndarray,
    clusters: list[dict],
    limit: int = 5,
    threshold: float = 0.75,
) -> list[dict]:
    scored = []
    for cluster in clusters:
        similarity = cosine(vector, cluster["centroid"])
        if similarity > threshold:
            scored.append({"cluster": cluster, "similarity": similarity})
    return sorted(scored, key=lambda item: item["similarity"], reverse=True)[:limit]


def judge_candidates(
    article: Article,
    candidates: list[dict],
    event_judge: EventJudge | None,
    max_workers: int = 4,
) -> dict | None:
    if not candidates:
        return None
    if event_judge is None:
        return candidates[0]
    approved: list[dict] = []
    workers = max(1, min(max_workers, len(candidates)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_candidate = {
            executor.submit(event_judge, article, candidate["cluster"]["articles"]): candidate
            for candidate in candidates
        }
        for future in as_completed(future_to_candidate):
            candidate = future_to_candidate[future]
            try:
                if future.result():
                    approved.append(candidate)
            except Exception:
                continue
    if not approved:
        return None
    return sorted(approved, key=lambda item: item["similarity"], reverse=True)[0]


def cluster_text(article: Article) -> str:
    return truncate(
        "\n".join(
            [
                article.title,
                article.summary,
                article.content,
            ]
        ),
        2000,
    )


def make_event(
    articles: list[Article],
    event_hash: str | None = None,
    centroid: np.ndarray | None = None,
    is_new: bool = False,
) -> Event:
    hashes = sorted(article.url_hash for article in articles)
    event_hash = event_hash or sha256_text("\n".join(hashes))
    source_count = len({article.source_name for article in articles})
    official_bonus = sum(1 for a in articles if a.source_category == "official") * 0.5
    weight = sum(article.source_weight for article in articles)
    score = math.log1p(len(articles)) + source_count * 0.8 + official_bonus + weight * 0.2
    centroid_list = centroid.tolist() if centroid is not None else None
    return Event(
        event_hash=event_hash,
        articles=articles,
        score=score,
        centroid=centroid_list,
        is_new=is_new,
    )


def compatible(article: Article, group: list[Article]) -> bool:
    title_tokens = tokens(article.title)
    for other in group:
        overlap = title_tokens & tokens(other.title)
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
        if self.model_name == "hashing":
            return
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
