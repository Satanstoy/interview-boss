"""Embedding prefilter service backed by ONNX Runtime.

Production uses a local ONNX export of ``Xenova/bge-small-zh-v1.5`` so the
Docker image does not need sentence-transformers, torch, triton, or CUDA/NVIDIA
wheels. FAISS remains CPU-only and is used only for nearest-neighbor search.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

logger = logging.getLogger("interview-boss")

_SESSION = None
_TOKENIZER = None
_MODEL_REPO = os.environ.get("EMBEDDING_MODEL_REPO", "Xenova/bge-small-zh-v1.5")
_ONNX_FILE = os.environ.get("EMBEDDING_ONNX_FILE", "onnx/model_quantized.onnx")
_MODEL_DIR = Path(os.environ.get("EMBEDDING_MODEL_DIR", "/app/models/bge-small-zh-v1.5"))
_BACKEND = os.environ.get("EMBEDDING_BACKEND", "auto").lower()
_DIMENSION = int(os.environ.get("EMBEDDING_DIMENSION", "512"))
_MAX_LENGTH = int(os.environ.get("EMBEDDING_MAX_LENGTH", "512"))


def _fix_proxy_for_httpx():
    """httpx does not support socks5h://; normalize it for HF clients."""
    for key in ("ALL_PROXY", "all_proxy"):
        val = os.environ.get(key, "")
        if val.startswith("socks5h://"):
            os.environ[key] = val.replace("socks5h://", "socks5://", 1)


def _download_model_if_needed() -> None:
    onnx_path = _MODEL_DIR / _ONNX_FILE
    tokenizer_path = _MODEL_DIR / "tokenizer.json"
    if onnx_path.exists() and tokenizer_path.exists():
        return

    if os.environ.get("EMBEDDING_OFFLINE", "0") == "1":
        raise FileNotFoundError(f"Embedding model is missing in offline mode: {_MODEL_DIR}")

    _fix_proxy_for_httpx()
    endpoint = os.environ.get("HF_ENDPOINT") or "https://hf-mirror.com"
    os.environ.setdefault("HF_ENDPOINT", endpoint)

    from huggingface_hub import snapshot_download

    logger.info("Downloading embedding ONNX model %s from %s", _MODEL_REPO, endpoint)
    snapshot_download(
        repo_id=_MODEL_REPO,
        local_dir=str(_MODEL_DIR),
        allow_patterns=[_ONNX_FILE, "tokenizer.json", "vocab.txt", "config.json", "tokenizer_config.json", "special_tokens_map.json"],
        local_dir_use_symlinks=False,
    )


def _get_onnx_runtime():
    global _SESSION, _TOKENIZER
    if _SESSION is not None and _TOKENIZER is not None:
        return _SESSION, _TOKENIZER

    _download_model_if_needed()

    import onnxruntime as ort
    from tokenizers import Tokenizer

    onnx_path = _MODEL_DIR / _ONNX_FILE
    tokenizer_path = _MODEL_DIR / "tokenizer.json"
    if not onnx_path.exists() or not tokenizer_path.exists():
        raise FileNotFoundError(f"Missing ONNX embedding model files under {_MODEL_DIR}")

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = int(os.environ.get("EMBEDDING_ORT_THREADS", "1"))
    opts.inter_op_num_threads = 1
    _SESSION = ort.InferenceSession(str(onnx_path), sess_options=opts, providers=["CPUExecutionProvider"])
    _TOKENIZER = Tokenizer.from_file(str(tokenizer_path))
    logger.info("Loaded ONNX embedding model: %s", onnx_path)
    return _SESSION, _TOKENIZER


def _normalize(vectors: np.ndarray) -> np.ndarray:
    vectors = vectors.astype(np.float32, copy=False)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def _encode_texts_onnx(texts: List[str]) -> np.ndarray:
    session, tokenizer = _get_onnx_runtime()
    encodings = tokenizer.encode_batch(texts)

    batch = len(encodings)
    max_len = min(max((len(e.ids) for e in encodings), default=0), _MAX_LENGTH)
    if max_len == 0:
        return np.zeros((batch, _DIMENSION), dtype=np.float32)

    input_ids = np.zeros((batch, max_len), dtype=np.int64)
    attention_mask = np.zeros((batch, max_len), dtype=np.int64)
    token_type_ids = np.zeros((batch, max_len), dtype=np.int64)

    for i, enc in enumerate(encodings):
        ids = enc.ids[:max_len]
        mask = enc.attention_mask[:max_len] if enc.attention_mask else [1] * len(ids)
        types = enc.type_ids[:max_len] if enc.type_ids else [0] * len(ids)
        input_ids[i, :len(ids)] = ids
        attention_mask[i, :len(mask)] = mask
        token_type_ids[i, :len(types)] = types

    available_inputs = {inp.name for inp in session.get_inputs()}
    feeds = {"input_ids": input_ids, "attention_mask": attention_mask}
    if "token_type_ids" in available_inputs:
        feeds["token_type_ids"] = token_type_ids
    feeds = {k: v for k, v in feeds.items() if k in available_inputs}

    output = session.run(None, feeds)[0]
    output = np.asarray(output)
    if output.ndim == 3:
        # BGE/BERT-style sentence embedding uses the CLS token representation.
        vectors = output[:, 0, :]
    elif output.ndim == 2:
        vectors = output
    else:
        raise ValueError(f"Unexpected ONNX embedding output shape: {output.shape}")

    return _normalize(vectors.astype(np.float32))


def _encode_texts_hash(texts: List[str]) -> np.ndarray:
    """Tiny deterministic fallback for tests or emergency degraded operation."""
    vectors = np.zeros((len(texts), _DIMENSION), dtype=np.float32)
    for row, text in enumerate(texts):
        tokens = [t for t in text.replace("，", " ").replace("。", " ").split() if t]
        if not tokens:
            tokens = list(text)
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "little") % _DIMENSION
            sign = 1.0 if digest[4] & 1 else -1.0
            vectors[row, idx] += sign
    return _normalize(vectors)


def encode_texts(texts: List[str]) -> np.ndarray:
    """Encode texts as normalized float32 embeddings with shape ``(N, 512)``."""
    if not texts:
        return np.array([], dtype=np.float32).reshape(0, _DIMENSION)

    backend = _BACKEND
    if backend in {"onnx", "auto"}:
        try:
            return _encode_texts_onnx(texts)
        except Exception as exc:
            if backend == "onnx":
                raise
            logger.warning("ONNX embedding unavailable, falling back to hash embeddings: %s", exc)
    if backend in {"hash", "auto"}:
        return _encode_texts_hash(texts)
    raise ValueError(f"Unsupported EMBEDDING_BACKEND={_BACKEND!r}")


def build_index(vectors: np.ndarray):
    """Build a FAISS inner-product index from normalized vectors."""
    import faiss

    if vectors.shape[0] == 0:
        return faiss.IndexFlatIP(_DIMENSION)

    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors.astype(np.float32, copy=False))
    return index


def search_index(index, query: np.ndarray, top_k: int = 10) -> Tuple[List[int], List[float]]:
    if index.ntotal == 0:
        return [], []

    k = min(top_k, index.ntotal)
    scores, indices = index.search(query.astype(np.float32, copy=False), k)
    return indices[0].tolist(), scores[0].tolist()


def compute_confidence_from_embeddings(emb1, emb2) -> float:
    if emb1 is None or emb2 is None:
        return 0.0
    sim = float(np.dot(emb1, emb2))
    if sim >= 0.95:
        return 0.95
    if sim >= 0.85:
        return 0.85
    if sim >= 0.70:
        return 0.75
    return 0.60


def prefilter_centroids(query_text: str, centroids: List[Dict], top_k: int = 10) -> List[Dict]:
    with_emb = [c for c in centroids if c.get("embedding") is not None]
    if not with_emb:
        return centroids

    vectors = np.array([c["embedding"] for c in with_emb], dtype=np.float32)
    index = build_index(vectors)
    query_emb = encode_texts([query_text])
    indices, scores = search_index(index, query_emb, top_k=top_k)

    return [{**with_emb[idx], "_similarity_score": score} for idx, score in zip(indices, scores)]


def prefilter_centroids_batch(query_texts: List[str], centroids: List[Dict], top_k: int = 10) -> Dict[int, List[Dict]]:
    with_emb = [c for c in centroids if c.get("embedding") is not None]
    if not with_emb:
        return {i: centroids for i in range(len(query_texts))}

    vectors = np.array([c["embedding"] for c in with_emb], dtype=np.float32)
    index = build_index(vectors)
    query_embs = encode_texts(query_texts)
    if query_embs.shape[0] == 0:
        return {i: centroids for i in range(len(query_texts))}

    k = min(top_k, len(with_emb))
    all_scores, all_indices = index.search(query_embs.astype(np.float32, copy=False), k)

    results = {}
    for qi in range(len(query_texts)):
        results[qi] = [
            {**with_emb[int(idx)], "_similarity_score": float(score)}
            for idx, score in zip(all_indices[qi], all_scores[qi])
        ]
    return results
