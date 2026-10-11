"""Download the official PaddleOCR detection model to the local weights folder."""
from __future__ import annotations

import hashlib
import argparse
import tarfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MODEL_BASE_URL = "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0"
MODELS = {
    "server": {
        "name": "PP-OCRv5_server_det_infer",
        "archive_sha256": "22a33e0ba6a21425ea4192da03bf4395c9a0c67902bd924b7328fc859073045d",
        "max_bytes": 120 * 1024 * 1024,
        "files": {
            "inference.yml": "28fb721efc3634fc8aa677e474b9602cb815a91cf569ef357a7a553d7b3ce685",
            "inference.json": "af5876933d8806a1b50d895867e0781e135cd92ff37381992828fc8d1b842d28",
            "inference.pdiparams": "183146fe9d9910352f68482f623bcbbb9fa7b9e8fa1463b9ad288cef00524d2d",
        },
    },
    "mobile": {
        "name": "PP-OCRv5_mobile_det_infer",
        "archive_sha256": "50446e5d01ac2a73d5319c89513281f6578414c888c602f9af13f93feefffc58",
        "max_bytes": 20 * 1024 * 1024,
        "files": {
            "inference.yml": "98069072e1b6b37d727fd9d9f11725faa46d6ea0de012f2ed26caea011c37699",
            "inference.json": "05feef1acb00aa4cd7362b15f7f501fc4f99d7b1fa73c1c871e0c7b1504b0f5c",
            "inference.pdiparams": "afa1820cb16c1fd0dad589d0f8b389139061c1ef6d68019685fd07be997dda5b",
        },
    },
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install_model(choice: str) -> None:
    config = MODELS[choice]
    model_name = config["name"]
    expected_files = config["files"]
    parent = ROOT / "weights" / "paddle"
    model_dir = parent / model_name
    if all((model_dir / name).is_file() and file_sha256(model_dir / name) == digest
           for name, digest in expected_files.items()):
        print(f"PaddleOCR detector ready: {model_dir}")
        return
    parent.mkdir(parents=True, exist_ok=True)
    archive = parent / f"{model_name}.tar"
    if not archive.is_file():
        url = f"{MODEL_BASE_URL}/{model_name}.tar"
        print(f"Downloading {url}")
        request = urllib.request.Request(url, headers={"User-Agent": "NLHUYOCR-setup/1.0"})
        with urllib.request.urlopen(request, timeout=90) as source, archive.open("wb") as target:
            digest = hashlib.sha256()
            total = 0
            while chunk := source.read(1024 * 1024):
                total += len(chunk)
                if total > config["max_bytes"]:
                    raise ValueError("PaddleOCR model archive exceeds expected size")
                digest.update(chunk)
                target.write(chunk)
        actual = digest.hexdigest()
    else:
        actual = file_sha256(archive)
    if actual != config["archive_sha256"]:
        archive.unlink(missing_ok=True)
        raise ValueError(f"PaddleOCR model SHA-256 mismatch: {actual}")
    with tarfile.open(archive) as source:
        members = source.getmembers()
        if not members or any(
            not (member.name == model_name or member.name in
                 {f"{model_name}/{name}" for name in expected_files})
            or (not member.isdir() and not member.isfile())
            for member in members
        ):
            raise ValueError("Unexpected files in PaddleOCR model archive")
        source.extractall(parent)
    if not all((model_dir / name).is_file() and file_sha256(model_dir / name) == digest
               for name, digest in expected_files.items()):
        raise ValueError("PaddleOCR model extraction is incomplete")
    print(f"PaddleOCR detector ready: {model_dir}")
    print(f"Archive SHA-256: {actual}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=("server", "mobile", "both"), default="server")
    choice = parser.parse_args().model
    for model in ("server", "mobile") if choice == "both" else (choice,):
        install_model(model)


if __name__ == "__main__":
    main()
