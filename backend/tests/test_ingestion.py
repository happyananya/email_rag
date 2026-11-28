from email.message import EmailMessage

from email_rag.services.chunking import chunk_email, split_text
from email_rag.services.mime import clean_body, html_to_text, parse_raw
from email_rag.services.rag import cited_indices


def _raw(body: str, html: str | None = None) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = "Q3 planning"
    msg["From"] = "Alice <alice@example.com>"
    msg["To"] = "bob@example.com"
    msg["Cc"] = "carol@example.com"
    msg["Date"] = "Mon, 10 Nov 2026 09:30:00 -0500"
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    msg.add_attachment(b"pdfbytes", maintype="application", subtype="pdf", filename="plan.pdf")
    return msg.as_bytes()


def test_parse_raw_extracts_metadata_and_body():
    parsed = parse_raw(_raw("Let's meet Thursday.\n\nOn Sun, Bob wrote:\n> old stuff"))
    assert parsed.subject == "Q3 planning"
    assert "alice@example.com" in parsed.sender
    assert parsed.recipients == ["bob@example.com", "carol@example.com"]
    assert parsed.sent_at.year == 2026
    assert parsed.body == "Let's meet Thursday."
    assert parsed.html_body is None
    assert parsed.attachments == ["plan.pdf"]


def test_parse_raw_preserves_html_for_safe_ui_rendering():
    html = "<html><body><h1>Q3 planning</h1><img src='https://example.com/chart.png'></body></html>"
    parsed = parse_raw(_raw("Plain-text version for search.", html))

    assert parsed.body == "Plain-text version for search."
    assert parsed.html_body.rstrip() == html


def test_html_to_text_skips_scripts():
    assert html_to_text("<p>Hi</p><script>x()</script><p>there</p>").split() == ["Hi", "there"]


def test_clean_body_drops_quoted_lines():
    assert clean_body("new\n> quoted\nmore") == "new\nmore"


def test_split_text_overlaps_and_covers_everything():
    text = " ".join(f"word{i}" for i in range(2000))
    chunks = split_text(text, size=500, overlap=100)
    assert len(chunks) > 1
    assert all(len(c) <= 500 for c in chunks)
    assert chunks[0].split()[0] == "word0"
    assert chunks[-1].split()[-1] == "word1999"


def test_chunk_email_prefixes_header():
    chunks = chunk_email(parse_raw(_raw("Short body.")))
    assert len(chunks) == 1
    assert chunks[0].startswith("Subject: Q3 planning")
    assert chunks[0].endswith("Short body.")


def test_cited_indices():
    assert cited_indices("Yes [1], and also [3][1].") == {1, 3}
