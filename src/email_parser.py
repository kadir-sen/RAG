"""
Email Parser - Parse EML and MSG files into structured data.
Extracts headers, body text, and attachments for RAG pipeline integration.
"""
import email
import email.policy
from email.parser import BytesParser
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from .logger import logger


@dataclass
class EmailAttachment:
    """A single email attachment."""
    filename: str
    content_type: str
    data: bytes
    size: int


@dataclass
class ParsedEmail:
    """Parsed email with headers, body, and attachments."""
    subject: str = ""
    body_text: str = ""
    sender: str = ""
    sender_email: str = ""
    recipients: List[str] = field(default_factory=list)
    cc: List[str] = field(default_factory=list)
    date: Optional[str] = None
    attachments: List[EmailAttachment] = field(default_factory=list)


class EmailParser:
    """Parse EML and MSG email files."""

    def parse(self, file_path: str) -> ParsedEmail:
        """Parse an email file (EML or MSG) and return structured data."""
        ext = Path(file_path).suffix.lower()
        if ext == ".eml":
            return self._parse_eml(file_path)
        elif ext == ".msg":
            return self._parse_msg(file_path)
        else:
            raise ValueError(f"Unsupported email format: {ext}")

    def _parse_eml(self, file_path: str) -> ParsedEmail:
        """Parse a .eml file using Python's email stdlib."""
        with open(file_path, "rb") as f:
            msg = BytesParser(policy=email.policy.default).parse(f)

        result = ParsedEmail(
            subject=str(msg.get("subject", "")),
            sender=str(msg.get("from", "")),
            date=str(msg.get("date", "")),
        )

        # Extract sender email
        from_header = msg.get("from", "")
        if "<" in str(from_header) and ">" in str(from_header):
            result.sender_email = str(from_header).split("<")[1].split(">")[0]
        else:
            result.sender_email = str(from_header)

        # Recipients
        to_header = msg.get("to", "")
        if to_header:
            result.recipients = [addr.strip() for addr in str(to_header).split(",")]

        cc_header = msg.get("cc", "")
        if cc_header:
            result.cc = [addr.strip() for addr in str(cc_header).split(",")]

        # Body text
        body_parts = []
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get("Content-Disposition", ""))

                if "attachment" in disposition:
                    # Attachment
                    filename = part.get_filename() or "unnamed_attachment"
                    data = part.get_payload(decode=True) or b""
                    result.attachments.append(EmailAttachment(
                        filename=filename,
                        content_type=content_type,
                        data=data,
                        size=len(data),
                    ))
                elif content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        try:
                            body_parts.append(payload.decode(charset, errors="replace"))
                        except Exception:
                            body_parts.append(payload.decode("utf-8", errors="replace"))
                elif content_type == "text/html" and not body_parts:
                    # Fallback to HTML if no plain text
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        try:
                            html_text = payload.decode(charset, errors="replace")
                            body_parts.append(self._strip_html(html_text))
                        except Exception:
                            pass
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                try:
                    body_parts.append(payload.decode(charset, errors="replace"))
                except Exception:
                    body_parts.append(payload.decode("utf-8", errors="replace"))

        result.body_text = "\n".join(body_parts).strip()
        logger.info(f"[EmailParser] Parsed EML: subject='{result.subject[:50]}', "
                     f"attachments={len(result.attachments)}")
        return result

    def _parse_msg(self, file_path: str) -> ParsedEmail:
        """Parse a .msg file using extract-msg library."""
        try:
            import extract_msg
        except ImportError:
            raise ImportError("extract-msg package required for .msg files. "
                              "Install with: pip install extract-msg")

        msg = extract_msg.Message(file_path)
        try:
            result = ParsedEmail(
                subject=msg.subject or "",
                body_text=msg.body or "",
                sender=msg.sender or "",
                sender_email=msg.senderEmail or "",
                date=str(msg.date) if msg.date else None,
            )

            # Recipients
            if msg.to:
                result.recipients = [addr.strip() for addr in msg.to.split(";")]
            if msg.cc:
                result.cc = [addr.strip() for addr in msg.cc.split(";")]

            # Attachments
            for att in msg.attachments:
                if hasattr(att, "data") and att.data:
                    result.attachments.append(EmailAttachment(
                        filename=att.longFilename or att.shortFilename or "unnamed",
                        content_type=att.mimetype or "application/octet-stream",
                        data=att.data,
                        size=len(att.data),
                    ))

            logger.info(f"[EmailParser] Parsed MSG: subject='{result.subject[:50]}', "
                         f"attachments={len(result.attachments)}")
            return result
        finally:
            msg.close()

    def save_attachments(self, parsed_email: ParsedEmail, target_dir: Path) -> List[str]:
        """Save email attachments to disk. Returns list of saved file paths."""
        target_dir.mkdir(parents=True, exist_ok=True)
        saved = []
        for att in parsed_email.attachments:
            if not att.filename or not att.data:
                continue
            # Sanitize filename
            safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in att.filename)
            path = target_dir / safe_name
            # Avoid overwrite
            if path.exists():
                stem = path.stem
                suffix = path.suffix
                path = target_dir / f"{stem}_{len(saved)}{suffix}"
            path.write_bytes(att.data)
            saved.append(str(path))
            logger.info(f"[EmailParser] Saved attachment: {safe_name}")
        return saved

    def to_document_text(self, parsed_email: ParsedEmail) -> Dict[int, str]:
        """
        Convert parsed email to page-text dict for RAG indexing.
        Page 1: Headers (From, To, Date, Subject)
        Page 2+: Body text (split into ~2000 char chunks)
        """
        pages = {}

        # Page 1: Headers
        header_lines = []
        if parsed_email.sender:
            header_lines.append(f"From: {parsed_email.sender}")
        if parsed_email.recipients:
            header_lines.append(f"To: {', '.join(parsed_email.recipients)}")
        if parsed_email.cc:
            header_lines.append(f"CC: {', '.join(parsed_email.cc)}")
        if parsed_email.date:
            header_lines.append(f"Date: {parsed_email.date}")
        if parsed_email.subject:
            header_lines.append(f"Subject: {parsed_email.subject}")

        header_lines.append("")  # separator
        # Include first portion of body in page 1
        body = parsed_email.body_text or ""
        chunk_size = 2000
        first_chunk = body[:chunk_size]
        header_lines.append(first_chunk)

        pages[1] = "\n".join(header_lines)

        # Additional pages for long body text
        remaining = body[chunk_size:]
        page_num = 2
        while remaining:
            pages[page_num] = remaining[:chunk_size]
            remaining = remaining[chunk_size:]
            page_num += 1

        return pages

    @staticmethod
    def _strip_html(html: str) -> str:
        """Basic HTML tag stripping."""
        import re
        text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
