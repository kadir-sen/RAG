"""Authenticated COAir launcher for the unmodified upstream Streamlit app."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Iterator

import requests


UPSTREAM_ROOT = Path(os.getenv(
    "TOOLKIT_UPSTREAM_ROOT", "/app/vendor/delay-analysis-toolkit",
)).resolve()
API_URL = os.getenv("TOOLKIT_INTERNAL_API_URL", "http://api:8000/api/internal/toolkit").rstrip("/")
SERVICE_SECRET = os.getenv("TOOLKIT_SERVICE_SECRET", "")
MAX_ANALYSIS_BYTES = 75 * 1024 * 1024

if str(UPSTREAM_ROOT) not in sys.path:
    sys.path.insert(0, str(UPSTREAM_ROOT))


def _load_upstream() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "coair_upstream_toolkit", UPSTREAM_ROOT / "app.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the vendored toolkit")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# Importing upstream applies Streamlit's page configuration. Authentication and
# data loading still happen before upstream main() renders any content.
upstream_app = _load_upstream()

import streamlit as st  # noqa: E402
import state as sk  # noqa: E402
from dcma import DCMAConfig, parse_xer, structural_defects  # noqa: E402
from dcma.narrative import NarrativeError  # noqa: E402
from programme import build_inventory  # noqa: E402
from views._shared import stash_raw  # noqa: E402


def _api_post(path: str, payload: dict, timeout: int = 30) -> dict:
    if not SERVICE_SECRET:
        raise RuntimeError("TOOLKIT_SERVICE_SECRET is not configured")
    response = requests.post(
        f"{API_URL}/{path.lstrip('/')}", json=payload,
        headers={"X-Toolkit-Service": SERVICE_SECRET}, timeout=timeout,
    )
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        error = RuntimeError(str(detail))
        setattr(error, "status_code", response.status_code)
        raise error
    return response.json()


def _authenticate() -> dict | None:
    current = st.session_state.get("coair_toolkit_session")
    if current:
        return current
    ticket = str(st.query_params.get("ticket", "") or "")
    if not ticket:
        st.error("This toolkit session is missing or expired. Return to COAir and open it again.")
        st.page_link("/", label="Return to COAir")
        st.stop()
    try:
        current = _api_post("session", {"ticket": ticket})
    except Exception as exc:
        st.query_params.clear()
        st.error(f"The secure toolkit link could not be used: {exc}")
        st.info("Links expire after 60 seconds and can only be used once. Return to COAir to create a new link.")
        st.stop()
    st.query_params.clear()
    st.session_state["coair_toolkit_session"] = current
    st.session_state[sk.AUTH_OK] = True
    return current


def _load_project_programmes(session: dict) -> None:
    identity = f"{session['project_id']}:{session['session_token']}"
    if st.session_state.get("coair_programme_identity") == identity:
        return
    programmes = list(session.get("programmes") or [])
    total = sum(int(item.get("size_bytes") or 0) for item in programmes)
    if not programmes:
        st.error("The active project has no programme files. Return to COAir and upload a P6 XER file.")
        st.stop()
    if total > MAX_ANALYSIS_BYTES:
        st.error("The selected programme set exceeds the 75 MB analysis memory budget.")
        st.stop()

    project_root = (Path("/app/data/projects") / session["project_id"] / "programmes").resolve()
    files = []
    hashes: dict[str, str] = {}
    with st.spinner("Loading the active project's programme files…"):
        for item in programmes:
            source = Path(str(item.get("file_path") or "")).resolve()
            if not source.is_relative_to(project_root) or not source.is_file():
                st.error(f"Programme source is unavailable: {item.get('name', 'unknown')}")
                st.stop()
            raw = source.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest != item.get("sha256"):
                st.error(f"Programme chain-of-custody check failed: {item.get('name', source.name)}")
                st.stop()
            try:
                parsed = parse_xer(raw, DCMAConfig())
            except Exception as exc:
                st.error(f"Programme could not be parsed ({item.get('name')}): {exc}")
                st.stop()
            defects = structural_defects(parsed)
            if defects or not parsed.tasks:
                st.error(f"Programme was refused ({item.get('name')}): " + "; ".join(defects or ["no TASK table found"]))
                st.stop()
            name = str(item.get("name") or source.name)
            stash_raw(name, raw)
            hashes[name] = digest
            files.append((name, parsed))

    st.session_state[sk.XER_POOL] = files
    st.session_state[sk.XER_HASHES] = hashes
    st.session_state[sk.XER_POOL_SIG] = tuple(sorted(hashes.items()))
    st.session_state[sk.INVENTORY] = build_inventory(files)
    st.session_state["coair_programme_identity"] = identity


def _managed_provider_block(_state_key: str) -> tuple[str, str, str]:
    st.caption("COAir managed AI · Gemini 3.6 Flash · usage is charged to the active project")
    return "coair", "gemini-3.6-flash", "managed"


def _managed_credentials_panel(_page: str) -> None:
    st.session_state[sk.AI_PROVIDER] = "coair"
    st.session_state[sk.AI_MODEL] = "gemini-3.6-flash"
    st.session_state[sk.AI_KEY] = "managed"
    st.session_state[sk.AI_MANAGED] = True
    st.success("AI enabled — COAir managed Gemini 3.6 Flash.")


def _managed_credentials() -> tuple[str, str, str]:
    return "coair", "gemini-3.6-flash", "managed"


def _managed_stream(
    _provider: str, _api_key: str, prompt: str,
    _model: str | None = None, system: str | None = None,
) -> Iterator[str]:
    session = st.session_state.get("coair_toolkit_session") or {}
    try:
        result = _api_post("narrative", {
            "session_token": session.get("session_token", ""),
            "prompt": prompt,
            "system": system or "",
            "max_tokens": 4096,
        }, timeout=240)
    except Exception as exc:
        if getattr(exc, "status_code", 0) == 402:
            raise NarrativeError(
                "The COAir credit balance is exhausted. Deterministic analysis remains available; "
                "add credits before generating another AI narrative."
            ) from exc
        raise NarrativeError(f"COAir narrative service failed: {exc}") from exc
    text = str(result.get("text") or "")
    for start in range(0, len(text), 400):
        yield text[start:start + 400]


def _project_intake() -> None:
    session = st.session_state["coair_toolkit_session"]
    programmes = session.get("programmes") or []
    st.caption("Programme sources are managed by the active COAir project and cannot be replaced from this page.")
    st.info(f"Active project: {session.get('project_name')}")
    for item in programmes:
        st.write(f"• {item['name']} — {int(item['size_bytes']) / 1048576:.2f} MB — SHA-256 `{item['sha256'][:12]}…`")
    st.success(f"{len(programmes)} programme file(s) loaded. Use the sidebar to run analyses and assemble the report.")


def _install_overrides(session: dict) -> None:
    import buildinfo
    import dcma.narrative as narrative
    import views._shared as shared

    coair_sha = os.getenv("COAIR_COMMIT_SHA", "development")
    upstream_sha = str(session.get("upstream_sha") or "unknown")
    buildinfo._commit = lambda: f"{upstream_sha[:10]} / COAir {coair_sha[:10]}"
    narrative.stream_narrative = _managed_stream
    shared.stream_narrative = _managed_stream
    shared.ai_provider_block = _managed_provider_block
    shared.ai_credentials_panel = _managed_credentials_panel
    shared.resolve_ai_credentials = _managed_credentials
    for name, module in tuple(sys.modules.items()):
        if not name.startswith("views.") or module is None:
            continue
        if hasattr(module, "stream_narrative"):
            setattr(module, "stream_narrative", _managed_stream)
        if hasattr(module, "ai_provider_block"):
            setattr(module, "ai_provider_block", _managed_provider_block)
        if hasattr(module, "ai_credentials_panel"):
            setattr(module, "ai_credentials_panel", _managed_credentials_panel)
        if hasattr(module, "resolve_ai_credentials"):
            setattr(module, "resolve_ai_credentials", _managed_credentials)
    upstream_app.intake_tab = _project_intake
    with st.sidebar:
        st.caption(f"COAir `{coair_sha[:10]}` · Toolkit `{upstream_sha[:10]}`")


session = _authenticate()
assert session is not None
_load_project_programmes(session)
_install_overrides(session)
upstream_app.main()
