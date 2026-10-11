"""Fetch only the local files needed to run a supported embedding model.

Usage: python3 scripts/fetch_embedding_model.py --model vietnamese-v2
The downloaded weights stay in ignored data/models/ and never enter Git.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dau_archive.db import data_dir
from dau_archive.embeddings import MODEL_REGISTRY


def main() -> None:
    from huggingface_hub import snapshot_download
    parser = argparse.ArgumentParser(description="Tải model embedding chạy nội bộ")
    parser.add_argument("--model", choices=MODEL_REGISTRY, default="vietnamese-v2")
    parser.add_argument("--force", action="store_true", help="Tải lại cả tệp đã có")
    args = parser.parse_args()
    identifier, dirname = MODEL_REGISTRY[args.model]
    destination = data_dir() / "models" / dirname
    destination.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(destination).free
    if free < 3 * 1024**3:
        parser.error("Cần ít nhất 3 GiB trống để tải model")
    snapshot_download(
        repo_id=identifier,
        local_dir=str(destination),
        max_workers=2,
        force_download=args.force,
        allow_patterns=[
            "model.safetensors", "config.json", "tokenizer.json", "tokenizer_config.json",
            "special_tokens_map.json", "sentencepiece.bpe.model", "vocab.json", "merges.txt",
            "modules.json", "config_sentence_transformers.json", "sentence_bert_config.json",
            "1_Pooling/*", "2_Normalize/*",
        ],
    )
    (destination / "2_Normalize").mkdir(exist_ok=True)
    metadata = destination / ".cache" / "huggingface" / "download" / "model.safetensors.metadata"
    expected = metadata.read_text().splitlines()[1] if metadata.is_file() else ""
    digest = hashlib.sha256()
    with (destination / "model.safetensors").open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    if len(expected) != 64 or digest.hexdigest() != expected:
        parser.error("Checksum model.safetensors không khớp. Chạy lại với --force")
    (destination / ".verified.sha256").write_text(digest.hexdigest() + "\n")
    print(f"Đã tải {identifier} vào {destination}")


if __name__ == "__main__":
    main()
