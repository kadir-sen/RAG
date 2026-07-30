"""Serving a .docx over HTTP.

Lifted out of backend/api/chronology.py when the chat-answer export needed the
same three headers. One copy: the `Access-Control-Expose-Headers` line in
particular is the sort of thing that gets forgotten in a second implementation
and then fails only in the browser, where the filename silently becomes
"download".
"""

from fastapi import Response

DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def docx_response(blob: bytes, filename: str) -> Response:
    return Response(
        content=blob,
        media_type=DOCX_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # The browser fetches this with XHR to attach the bearer token, so
            # the header has to be readable from script to name the file.
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )
