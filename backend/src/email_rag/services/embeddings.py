"""Text embeddings via Amazon Bedrock (Titan Text Embeddings V2 by default)."""

import json
from concurrent.futures import ThreadPoolExecutor

import boto3

from email_rag.config import settings

_runtime = None


def _client():
    global _runtime
    if _runtime is None:
        _runtime = boto3.client("bedrock-runtime", region_name=settings().aws_region)
    return _runtime


def embed(text: str) -> list[float]:
    s = settings()
    resp = _client().invoke_model(
        modelId=s.embedding_model_id,
        body=json.dumps({
            "inputText": text[:30000],
            "dimensions": s.embedding_dimensions,
            "normalize": True,
        }),
    )
    return json.loads(resp["body"].read())["embedding"]


def embed_many(texts: list[str], max_workers: int = 8) -> list[list[float]]:
    """Titan V2 takes one input per call, so fan out with a small thread pool."""
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(embed, texts))
