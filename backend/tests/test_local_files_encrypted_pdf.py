from pypdf import PdfReader, PdfWriter


def _make_owner_encrypted_pdf(tmp_path, text: str):
    """An empty-user-password, owner-password-restricted PDF -- the common
    "no printing/copying in the viewer" disclosure PDF pattern, which
    should read like any other PDF here (only a real user-password lock
    should stay unreadable)."""
    src = tmp_path / "plain.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with open(src, "wb") as f:
        writer.write(f)

    reader = PdfReader(src)
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    writer.add_metadata({"/Producer": text})  # cheap way to embed checkable content
    writer.encrypt(user_password="", owner_password="owner-secret", algorithm="AES-256")

    out = tmp_path / "encrypted.pdf"
    with open(out, "wb") as f:
        writer.write(f)
    return out


def test_owner_encrypted_pdf_is_readable_without_a_password(tmp_path):
    """The full parse path (_extract_pdf_text -> DocumentConverter) always
    loads Docling's layout-detection model, downloaded from Hugging Face
    Hub on first use -- not available in every environment this suite runs
    in. Decryption itself happens one layer down, in Docling's PDF
    backend, before the layout model is ever invoked, so this exercises
    that layer directly: real Docling code against real AES-encrypted
    bytes, with no network dependency."""
    from docling.backend.docling_parse_backend import DoclingParseDocumentBackend
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.document import InputDocument

    path = _make_owner_encrypted_pdf(tmp_path, "marker-text-12345")

    reader = PdfReader(path)
    assert reader.is_encrypted

    in_doc = InputDocument(path_or_stream=path, format=InputFormat.PDF, backend=DoclingParseDocumentBackend)

    # Opens and validates -- the AES-encrypted stream is actually decrypted
    # (an owner-only, empty-user-password PDF), not rejected the way a
    # genuinely user-password-locked PDF would be (InputDocument.valid is
    # False and no backend is attached).
    assert in_doc.valid is True
    assert in_doc._backend.page_count() == 1
