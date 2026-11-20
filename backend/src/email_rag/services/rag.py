"""Inbox Q&A: embed question -> top-k chunks (tenant-filtered) -> grounded answer with citations."""

import re
from typing import Any

from email_rag import repo
from email_rag.config import settings
from email_rag.services import embeddings, llm


def cited_indices(answer: str) -> set[int]:
    return {int(n) for n in re.findall(r"\[(\d+)\]", answer)}


def ask(user_id: str, question: str, account_id: str | None = None) -> dict[str, Any]:
    query_vec = embeddings.embed(question)
    chunks = repo.search_chunks(user_id, query_vec, settings().rag_top_k, account_id)
    if not chunks:
        return {"answer": "I couldn't find any emails related to that question.", "sources": []}

    answer = llm.answer_question(question, chunks)
    used = cited_indices(answer)
    sources = [
        {
            "index": i,
            "email_id": str(c["email_id"]),
            "account_id": str(c["account_id"]),
            "thread_id": c["thread_id"],
            "subject": c["subject"],
            "sender": c["sender"],
            "sent_at": c["sent_at"].isoformat() if c["sent_at"] else None,
            "score": float(c["score"]),
            "cited": i in used,
        }
        for i, c in enumerate(chunks, 1)
    ]
    return {"answer": answer, "sources": sources}
