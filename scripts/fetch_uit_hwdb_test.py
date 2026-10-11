"""Fetch a small labeled UIT-HWDB test subset (CC-BY-4.0) for OCR evaluation."""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("data/benchmark/uit_hwdb_test"))
    args = parser.parse_args()
    if not 1 <= args.count <= 100:
        parser.error("--count must be between 1 and 100")
    args.output.mkdir(parents=True, exist_ok=True)
    url = ("https://datasets-server.huggingface.co/rows?dataset=blue7012/UIT_HWDB"
           f"&config=default&split=test&offset=0&length={args.count}")
    with urllib.request.urlopen(url, timeout=30) as response:
        rows = json.load(response)["rows"]
    labels = []
    for item in rows:
        index, row = item["row_idx"], item["row"]
        name = f"{index:03}.jpg"
        urllib.request.urlretrieve(row["image"]["src"], args.output / name)
        labels.append({"file": name, "text": row["text"], "row_index": index})
    (args.output / "labels.json").write_text(
        json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(labels)} labeled lines to {args.output}")


if __name__ == "__main__":
    main()
