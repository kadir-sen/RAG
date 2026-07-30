"""Serving a .docx over HTTP.

Lifted out of backend/api/chronology.py when the chat-answer export needed the
same three headers. One copy: the `Access-Control-Expose-Headers` line in
particular is the sort of thing that gets forgotten in a second implementation
and then fails only in the browser, where the filename silently becomes
"download".
"""

import re
from urllib.parse import quote

from fastapi import Response

DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def content_disposition(filename: str) -> str:
    """An attachment header that survives a name with quotes or accents.

    Authored documents download under their author's own name, and those names
    contain characters the quoted-string form cannot carry — a `"` would close
    the string early and truncate the name. So we send both forms RFC 6266
    allows: a flattened ASCII `filename=` that any parser can read, and the
    RFC 5987 `filename*` that carries the real one. Clients prefer `filename*`.
    """
    ascii_name = re.sub(r'[\\"]', "'", filename)
    ascii_name = ascii_name.encode("ascii", "replace").decode("ascii")
    return (f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(filename, safe='')}")


def docx_response(blob: bytes, filename: str) -> Response:
    return Response(
        content=blob,
        media_type=DOCX_MIME,
        headers={
            "Content-Disposition": content_disposition(filename),
            # The browser fetches this with XHR to attach the bearer token, so
            # the header has to be readable from script to name the file.
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )
