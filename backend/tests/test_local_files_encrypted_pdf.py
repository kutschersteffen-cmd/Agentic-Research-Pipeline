from pypdf import PdfReader, PdfWriter

from arp.ingestion.local_files import parse_file_to_text


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
    path = _make_owner_encrypted_pdf(tmp_path, "marker-text-12345")

    reader = PdfReader(path)
    assert reader.is_encrypted

    # Doesn't raise, and the AES-encrypted stream is actually decrypted
    # (not silently returning empty/garbage text).
    text = parse_file_to_text(path)
    assert isinstance(text, str)
