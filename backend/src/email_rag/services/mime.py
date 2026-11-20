"""Parse raw RFC 822 messages into clean text + metadata."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser


@dataclass
class ParsedEmail:
    subject: str | None
    sender: str | None
    recipients: list[str]
    sent_at: datetime | None
    body: str
    attachments: list[str] = field(default_factory=list)


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("br", "p", "div", "li", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _HTMLText()
    p.feed(html)
    return "".join(p.parts)


def parse_raw(raw: bytes) -> ParsedEmail:
    msg = BytesParser(policy=policy.default).parsebytes(raw)

    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if body_part is not None:
        content = body_part.get_content()
        body = html_to_text(content) if body_part.get_content_type() == "text/html" else content

    attachments = [p.get_filename() for p in msg.iter_attachments() if p.get_filename()]
    recipients = [
        addr for _, addr in getaddresses(msg.get_all("to", []) + msg.get_all("cc", [])) if addr
    ]
    sent_at = None
    if msg["date"]:
        try:
            sent_at = parsedate_to_datetime(str(msg["date"]))
        except (TypeError, ValueError):
            pass

    return ParsedEmail(
        subject=str(msg["subject"]) if msg["subject"] else None,
        sender=str(msg["from"]) if msg["from"] else None,
        recipients=recipients,
        sent_at=sent_at,
        body=clean_body(body),
        attachments=attachments,
    )


_QUOTE_HEADER = re.compile(r"^On .{0,200}wrote:\s*$", re.MULTILINE)


def clean_body(text: str) -> str:
    """Drop quoted reply history and collapse whitespace; the thread keeps earlier messages."""
    m = _QUOTE_HEADER.search(text)
    if m:
        text = text[: m.start()]
    lines = [ln.rstrip() for ln in text.splitlines() if not ln.lstrip().startswith(">")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
