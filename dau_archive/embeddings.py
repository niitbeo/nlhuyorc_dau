"""Local-only Vietnamese document embeddings; no hosted inference fallback."""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import threading
from pathlib import Path

import numpy as np

from .db import connect, data_dir


MODEL_REGISTRY = {
    "vietnamese-v2": ("AITeamVN/Vietnamese_Embedding_v2", "vietnamese-v2"),
    "bge-m3": ("BAAI/bge-m3", "bge-m3"),
}
DEFAULT_MODEL_KEY = "vietnamese-v2"
_model = None
_loaded_path: Path | None = None
_lock = threading.RLock()


def selected_model_key() -> str:
    if os.getenv("DAU_EMBED_MODEL_PATH"):
        return "custom"
    try:
        with connect() as db:
            row = db.execute("SELECT value FROM embedding_settings WHERE key='model'").fetchone()
            if row and row["value"] in MODEL_REGISTRY:
                return row["value"]
    except sqlite3.OperationalError:
        pass
    return DEFAULT_MODEL_KEY


def configured_path() -> Path:
    custom = os.getenv("DAU_EMBED_MODEL_PATH")
    if custom:
        return Path(custom).expanduser().resolve()
    return data_dir() / "models" / MODEL_REGISTRY[selected_model_key()][1]


def model_id() -> str:
    override = os.getenv("DAU_EMBED_MODEL_ID")
    if override:
        return override
    key = selected_model_key()
    return MODEL_REGISTRY[key][0] if key in MODEL_REGISTRY else configured_path().name


def available() -> bool:
    path = configured_path()
    marker_ready = bool(os.getenv("DAU_EMBED_MODEL_PATH")) or (path / ".verified.sha256").is_file()
    files_ready = marker_ready and (path / "config.json").is_file() and (path / "model.safetensors").is_file()
    tokenizer_ready = (path / "tokenizer.json").is_file() or (path / "sentencepiece.bpe.model").is_file()
    runner_ready = bool(importlib.util.find_spec("sentence_transformers") or
                        importlib.util.find_spec("transformers"))
    return files_ready and tokenizer_ready and runner_ready


def model_catalog() -> list[dict]:
    active = selected_model_key()
    result = []
    for key, (identifier, dirname) in MODEL_REGISTRY.items():
        path = data_dir() / "models" / dirname
        result.append({"key": key, "model_id": identifier, "installed":
                       (path / "model.safetensors").is_file() and
                       (path / "config.json").is_file() and
                       (path / ".verified.sha256").is_file(), "active": key == active})
    return result


def select_model(key: str) -> None:
    if os.getenv("DAU_EMBED_MODEL_PATH"):
        raise ValueError("Model đang được cố định bằng DAU_EMBED_MODEL_PATH")
    if key not in MODEL_REGISTRY:
        raise ValueError("Model không được hỗ trợ")
    with connect() as db:
        db.execute("INSERT INTO embedding_settings(key,value) VALUES ('model',?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key,))


class _TransformerEncoder:
    """Mirror the local SentenceTransformer pooling config without its dependency."""

    def __init__(self, path: Path):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(str(path), local_files_only=True,
                                                       use_fast=False)
        self.model = AutoModel.from_pretrained(str(path), local_files_only=True)
        self.model.eval()
        pooling_path = path / "1_Pooling" / "config.json"
        if not pooling_path.is_file():
            raise ValueError("Thiếu cấu hình pooling của model embedding")
        pooling = json.loads(pooling_path.read_text(encoding="utf-8"))
        self.cls_pooling = bool(pooling.get("pooling_mode_cls_token"))
        self.mean_pooling = bool(pooling.get("pooling_mode_mean_tokens"))
        if self.cls_pooling == self.mean_pooling:
            raise ValueError("Cấu hình pooling chưa được hỗ trợ")

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = []
        for start in range(0, len(texts), 4):
            batch = texts[start:start + 4]
            inputs = self.tokenizer(batch, padding=True, truncation=True,
                                    max_length=1024, return_tensors="pt")
            with self.torch.no_grad():
                hidden = self.model(**inputs).last_hidden_state
                if self.cls_pooling:
                    pooled = hidden[:, 0]
                else:
                    mask = inputs["attention_mask"].unsqueeze(-1)
                    pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
                pooled = self.torch.nn.functional.normalize(pooled, p=2, dim=1)
            vectors.extend(pooled.cpu().numpy())
        return np.asarray(vectors, dtype="<f4")


def _get_model():
    global _model, _loaded_path
    path = configured_path()
    if not available():
        return None
    with _lock:
        if _model is None or _loaded_path != path:
            if importlib.util.find_spec("sentence_transformers"):
                from sentence_transformers import SentenceTransformer
                _model = SentenceTransformer(str(path), local_files_only=True)
            else:
                _model = _TransformerEncoder(path)
            _loaded_path = path
        return _model


def embed_texts(texts: list[str]) -> list[bytes] | None:
    if not texts:
        return []
    model = _get_model()
    if model is None:
        return None
    with _lock:
        if isinstance(model, _TransformerEncoder):
            vectors = model.encode(texts)
        else:
            vectors = model.encode(texts, normalize_embeddings=True,
                                   convert_to_numpy=True, show_progress_bar=False,
                                   batch_size=4)
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
