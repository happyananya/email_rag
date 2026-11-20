"""Split an email into overlapping chunks, each prefixed with header context for retrieval."""

from email_rag.services.mime import ParsedEmail

CHUNK_CHARS = 1500  # ~375 tokens
OVERLAP_CHARS = 200


def header_context(email: ParsedEmail) -> str:
    date = email.sent_at.isoformat() if email.sent_at else "unknown"
    return f"Subject: {email.subject or '(no subject)'}\nFrom: {email.sender or ''}\nDate: {date}\n\n"


def split_text(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # Prefer breaking at a paragraph, then a sentence, then a space.
            for sep in ("\n\n", ". ", " "):
                cut = text.rfind(sep, start + size // 2, end)
                if cut != -1:
                    end = cut + len(sep)
                    break
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def chunk_email(email: ParsedEmail) -> list[str]:
    header = header_context(email)
    body_chunks = split_text(email.body) or [""]
    return [header + c for c in body_chunks]
