"""Tests for email parser module."""
import email
import email.mime.multipart
import email.mime.text
import email.mime.base
import tempfile
from pathlib import Path

import pytest

from src.email_parser import EmailParser, ParsedEmail, EmailAttachment


@pytest.fixture
def parser():
    return EmailParser()


@pytest.fixture
def simple_eml(tmp_path):
    """Create a simple .eml file for testing."""
    msg = email.mime.multipart.MIMEMultipart()
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@example.com"
    msg["Subject"] = "Test Email Subject"
    msg["Date"] = "Mon, 01 Jan 2026 12:00:00 +0000"
    msg["CC"] = "cc1@example.com, cc2@example.com"

    body = email.mime.text.MIMEText("Hello, this is the email body.\nSecond line here.")
    msg.attach(body)

    eml_path = tmp_path / "test_email.eml"
    eml_path.write_bytes(msg.as_bytes())
    return str(eml_path)


@pytest.fixture
def eml_with_attachment(tmp_path):
    """Create a .eml file with an attachment."""
    msg = email.mime.multipart.MIMEMultipart()
    msg["From"] = "John Doe <john@company.com>"
    msg["To"] = "jane@company.com"
    msg["Subject"] = "Report attached"

    body = email.mime.text.MIMEText("Please find the report attached.")
    msg.attach(body)

    # Add a text attachment
    att = email.mime.base.MIMEBase("application", "octet-stream")
    att.set_payload(b"attachment content here")
    att.add_header("Content-Disposition", "attachment", filename="report.txt")
    msg.attach(att)

    eml_path = tmp_path / "with_attachment.eml"
    eml_path.write_bytes(msg.as_bytes())
    return str(eml_path)


class TestEmailParserEML:
    def test_parse_simple_eml(self, parser, simple_eml):
        result = parser.parse(simple_eml)
        assert isinstance(result, ParsedEmail)
        assert result.subject == "Test Email Subject"
        assert "sender@example.com" in result.sender
        assert len(result.recipients) == 1
        assert "recipient@example.com" in result.recipients[0]
        assert len(result.cc) == 2
        assert "Hello, this is the email body." in result.body_text

    def test_parse_sender_email_extraction(self, parser, eml_with_attachment):
        result = parser.parse(eml_with_attachment)
        assert result.sender_email == "john@company.com"

    def test_parse_attachment(self, parser, eml_with_attachment):
        result = parser.parse(eml_with_attachment)
        assert len(result.attachments) == 1
        assert result.attachments[0].filename == "report.txt"
        assert result.attachments[0].data == b"attachment content here"
        assert result.attachments[0].size == len(b"attachment content here")

    def test_parse_body_text(self, parser, simple_eml):
        result = parser.parse(simple_eml)
        assert "Hello, this is the email body." in result.body_text
        assert "Second line here." in result.body_text


class TestSaveAttachments:
    def test_save_attachments(self, parser, eml_with_attachment, tmp_path):
        result = parser.parse(eml_with_attachment)
        saved = parser.save_attachments(result, tmp_path / "attachments")
        assert len(saved) == 1
        assert Path(saved[0]).exists()
        assert Path(saved[0]).read_bytes() == b"attachment content here"

    def test_save_no_attachments(self, parser, simple_eml, tmp_path):
        result = parser.parse(simple_eml)
        saved = parser.save_attachments(result, tmp_path / "attachments")
        assert len(saved) == 0

    def test_sanitize_filename(self, parser, tmp_path):
        att = EmailAttachment(
            filename="bad/file<name>.txt",
            content_type="text/plain",
            data=b"test",
            size=4,
        )
        parsed = ParsedEmail(attachments=[att])
        saved = parser.save_attachments(parsed, tmp_path / "attachments")
        assert len(saved) == 1
        # No special chars in filename
        saved_name = Path(saved[0]).name
        assert "/" not in saved_name
        assert "<" not in saved_name


class TestToDocumentText:
    def test_basic_conversion(self, parser, simple_eml):
        result = parser.parse(simple_eml)
        pages = parser.to_document_text(result)
        assert 1 in pages
        assert "From:" in pages[1]
        assert "To:" in pages[1]
        assert "Subject: Test Email Subject" in pages[1]
        assert "Hello, this is the email body." in pages[1]

    def test_long_body_splits_pages(self, parser):
        parsed = ParsedEmail(
            subject="Test",
            body_text="A" * 5000,
            sender="test@test.com",
        )
        pages = parser.to_document_text(parsed)
        # Should have multiple pages for long body
        assert len(pages) >= 2

    def test_empty_body(self, parser):
        parsed = ParsedEmail(subject="Empty")
        pages = parser.to_document_text(parsed)
        assert 1 in pages
        assert "Subject: Empty" in pages[1]


class TestStripHtml:
    def test_strip_tags(self):
        html = "<html><body><p>Hello <b>World</b></p></body></html>"
        result = EmailParser._strip_html(html)
        assert "Hello" in result
        assert "World" in result
        assert "<" not in result

    def test_strip_style_and_script(self):
        html = '<style>body{color:red}</style><script>alert(1)</script><p>Content</p>'
        result = EmailParser._strip_html(html)
        assert "Content" in result
        assert "color" not in result
        assert "alert" not in result


class TestUnsupportedFormat:
    def test_unsupported_extension(self, parser, tmp_path):
        path = tmp_path / "test.xyz"
        path.write_text("data")
        with pytest.raises(ValueError, match="Unsupported email format"):
            parser.parse(str(path))
