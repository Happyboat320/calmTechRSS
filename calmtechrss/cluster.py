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
    centroid: list[float] | dict[str, list[float]]
    vectors: dict[str, list[float]] | None = None


ArticleVectorMap = dict[str, np.ndarray]


def cluster_articles(
    articles: list[Article],
    embedding_model: str | None = None,
    embedding_device: str = "cpu",
    embedding_batch_size: int = 32,
    embedding_cpu_threads: int = 4,
) -> list[Event]:
    if not articles:
        return []
    vectors = encode_articles(
        articles,
        models=[embedding_model] if embedding_model else None,
        device=embedding_device,
        batch_size=embedding_batch_size,
        cpu_threads=embedding_cpu_threads,
    )
    groups: list[dict] = []
    for article, vector_map in zip(articles, vectors, strict=True):
        selected = judge_candidates(article, top_candidates(vector_map, groups), event_judge=None)
        if selected is not None:
            selected["cluster"]["articles"].append(article)
        else:
            groups.append({"articles": [article], "vectors": vector_map})
    events = [make_event(group["articles"], vectors=group["vectors"]) for group in groups]
    return sorted(events, key=lambda event: event.score, reverse=True)


def incremental_cluster_articles(
    articles: list[Article],
    existing_clusters: list[ExistingCluster],
    embedding_model: str | None = None,
    embedding_models: list[str] | tuple[str, ...] | None = None,
    embedding_device: str = "cpu",
    embedding_batch_size: int = 32,
    embedding_cpu_threads: int = 4,
    embedding_max_chars: int = 2000,
    similarity_threshold: float = 0.8,
    event_judge: EventJudge | None = None,
    max_judge_workers: int = 4,
) -> list[Event]:
    if not articles:
        return []
    model_names = list(embedding_models or ([embedding_model] if embedding_model else []))
    vectors = encode_articles(
        articles,
        models=model_names or None,
        device=embedding_device,
        batch_size=embedding_batch_size,
        cpu_threads=embedding_cpu_threads,
        max_chars=embedding_max_chars,
    )
    changed_events: dict[str, Event] = {}
    existing = [
        {
            "event_hash": cluster.event_hash,
            "articles": list(cluster.articles),
            "vectors": cluster_vectors(cluster, model_names),
        }
        for cluster in existing_clusters
        if cluster.centroid or cluster.vectors
    ]

    unassigned: list[tuple[Article, ArticleVectorMap]] = []
    for article, vector_map in zip(articles, vectors, strict=True):
        existing_candidates = top_candidates(vector_map, existing, threshold=similarity_threshold)
        selected = judge_candidates(article, existing_candidates, event_judge, max_judge_workers)
        if selected is not None:
            cluster = selected["cluster"]
            cluster["articles"].append(article)
            event = make_event(
                cluster["articles"],
                event_hash=str(cluster["event_hash"]),
                vectors=cluster["vectors"],
                is_new=False,
            )
            changed_events[event.event_hash] = event
        else:
            unassigned.append((article, vector_map))

    for group in merge_new_articles(unassigned, threshold=similarity_threshold):
        event = make_event(group["articles"], vectors=group["vectors"], is_new=True)
        changed_events[event.event_hash] = event
    return sorted(changed_events.values(), key=lambda event: event.score, reverse=True)


def top_candidates(
    vector: ArticleVectorMap,
    clusters: list[dict],
    limit: int = 5,
    threshold: float = 0.8,
) -> list[dict]:
    scored = []
    for cluster in clusters:
        similarities = vector_similarities(vector, cluster["vectors"])
        if similarities and all(item > threshold for item in similarities.values()):
            scored.append(
                {
                    "cluster": cluster,
                    "similarity": sum(similarities.values()) / len(similarities),
                }
            )
    return sorted(scored, key=lambda item: item["similarity"], reverse=True)[:limit]


def merge_new_articles(
    items: list[tuple[Article, ArticleVectorMap]],
    threshold: float = 0.8,
) -> list[dict]:
    groups = [{"articles": [article], "vectors": vectors} for article, vectors in items]
    changed = True
    while changed:
        changed = False
        for left_index in range(len(groups)):
            if changed:
                break
            for right_index in range(left_index + 1, len(groups)):
                similarities = vector_similarities(
                    groups[left_index]["vectors"],
                    groups[right_index]["vectors"],
                )
                if similarities and all(item > threshold for item in similarities.values()):
                    groups[left_index]["articles"].extend(groups[right_index]["articles"])
                    del groups[right_index]
                    changed = True
                    break
    return groups


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
    return cluster_text_with_limit(article, 2000)


def cluster_text_with_limit(article: Article, max_chars: int) -> str:
    return truncate("\n".join([article.title, article.summary, article.content]), max_chars)


def make_event(
    articles: list[Article],
    event_hash: str | None = None,
    centroid: np.ndarray | None = None,
    vectors: ArticleVectorMap | None = None,
    is_new: bool = False,
) -> Event:
    hashes = sorted(article.url_hash for article in articles)
    event_hash = event_hash or sha256_text("\n".join(hashes))
    source_count = len({article.source_name for article in articles})
    official_bonus = sum(1 for a in articles if a.source_category == "official") * 0.5
    weight = sum(article.source_weight for article in articles)
    score = math.log1p(len(articles)) + source_count * 0.8 + official_bonus + weight * 0.2
    if vectors:
        centroid_list = {name: vector.tolist() for name, vector in vectors.items()}
    elif centroid is not None:
        centroid_list = {"default": centroid.tolist()}
    else:
        centroid_list = None
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
    if a.shape != b.shape:
        return 0.0
    denominator = np.linalg.norm(a) * np.linalg.norm(b)
    if denominator == 0:
        return 0.0
    return float(np.dot(a, b) / denominator)


def encode_articles(
    articles: list[Article],
    models: list[str] | tuple[str, ...] | None = None,
    device: str = "cpu",
    batch_size: int = 32,
    cpu_threads: int = 4,
    max_chars: int = 2000,
) -> list[ArticleVectorMap]:
    model_names = list(models or ["intfloat/multilingual-e5-small", "sentence-transformers/all-MiniLM-L6-v2"])
    texts = [cluster_text_with_limit(article, max_chars) for article in articles]
    vectors_by_model: dict[str, list[np.ndarray]] = {}
    workers = max(1, min(len(model_names), len(model_names)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_model = {
            executor.submit(
                Embedder(
                    model_name=model_name,
                    device=device,
                    batch_size=batch_size,
                    cpu_threads=cpu_threads,
                ).encode,
                texts,
            ): model_name
            for model_name in model_names
        }
        for future in as_completed(future_to_model):
            vectors_by_model[future_to_model[future]] = future.result()
    return [
        {model_name: vectors_by_model[model_name][index] for model_name in model_names}
        for index in range(len(articles))
    ]


def cluster_vectors(cluster: ExistingCluster, model_names: list[str]) -> ArticleVectorMap:
    if cluster.vectors:
        if set(cluster.vectors) == {"default"} and model_names:
            return {model_names[0]: np.array(cluster.vectors["default"], dtype=float)}
        return {name: np.array(vector, dtype=float) for name, vector in cluster.vectors.items()}
    if isinstance(cluster.centroid, dict):
        if set(cluster.centroid) == {"default"} and model_names:
            return {model_names[0]: np.array(cluster.centroid["default"], dtype=float)}
        return {name: np.array(vector, dtype=float) for name, vector in cluster.centroid.items()}
    fallback_name = model_names[0] if model_names else "default"
    return {fallback_name: np.array(cluster.centroid, dtype=float)}


def vector_similarities(left: ArticleVectorMap, right: ArticleVectorMap) -> dict[str, float]:
    names = sorted(set(left) & set(right))
    return {name: cosine(left[name], right[name]) for name in names}


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
