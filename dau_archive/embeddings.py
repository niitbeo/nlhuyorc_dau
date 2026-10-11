"""Local-only SentenceTransformer embeddings; no hosted inference fallback."""
from __future__ import annotations

import os
import importlib.util
from pathlib import Path

import numpy as np


DEFAULT_MODEL_ID = "AITeamVN/Vietnamese_Embedding_v2"
_model = None
_loaded_path = None


def configured_path() -> Path | None:
    value = os.getenv("DAU_EMBED_MODEL_PATH", "")
    return Path(value).expanduser().resolve() if value else None


def model_id() -> str:
    path = configured_path()
    return os.getenv("DAU_EMBED_MODEL_ID") or (path.name if path else DEFAULT_MODEL_ID)


def available() -> bool:
    path = configured_path()
    return bool(path and path.is_dir() and importlib.util.find_spec("sentence_transformers"))


def _get_model():
    global _model, _loaded_path
    path = configured_path()
    if not path or not path.is_dir():
        return None
    if _model is None or _loaded_path != path:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(str(path), local_files_only=True)
        _loaded_path = path
    return _model


def embed_texts(texts: list[str]) -> list[bytes] | None:
    model = _get_model()
    if model is None:
        return None
    vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True,
                           show_progress_bar=False)
    return [np.asarray(vector, dtype="<f4").tobytes() for vector in vectors]


def embed_query(query: str) -> np.ndarray | None:
    data = embed_texts([query])
    return np.frombuffer(data[0], dtype="<f4") if data else None


def cosine(query: np.ndarray, data: bytes | None) -> float:
    if not data:
        return 0.0
    vector = np.frombuffer(data, dtype="<f4")
    if vector.shape != query.shape:
        return 0.0
    return float(query @ vector)
