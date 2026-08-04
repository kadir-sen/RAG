import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "vendor" / "delay-analysis-toolkit"


def test_upstream_lock_and_required_report_contract_are_present():
    lock = json.loads((ROOT / "vendor" / "delay-analysis-toolkit.upstream.json").read_text())
    assert lock["repository"] == "https://github.com/altunozan/delay-analysis-toolkit.git"
    assert len(lock["commit"]) == 40
    assert (UPSTREAM / "app.py").is_file()
    report = (UPSTREAM / "views" / "report.py").read_text(encoding="utf-8")
    shared = (UPSTREAM / "views" / "_shared.py").read_text(encoding="utf-8")
    assert "def report_tab(" in report
    assert "def ai_provider_block(" in shared
    assert "stream_narrative" in report


def test_integration_keeps_auth_and_ai_overrides_outside_vendor():
    wrapper = (ROOT / "integrations" / "delay_toolkit" / "app.py").read_text(encoding="utf-8")
    assert "TOOLKIT_SERVICE_SECRET" in wrapper
    assert '"gemini-3.6-flash"' in wrapper
    assert "upstream_app.intake_tab = _project_intake" in wrapper
    assert "narrative.stream_narrative = _managed_stream" in wrapper


def test_toolkit_container_uses_the_vendored_source_and_base_path():
    dockerfile = (ROOT / "Dockerfile.toolkit").read_text(encoding="utf-8")
    config = (ROOT / "integrations" / "delay_toolkit" / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert "COPY vendor/delay-analysis-toolkit/" in dockerfile
    assert "integrations/delay_toolkit/app.py" in dockerfile
    assert 'baseUrlPath = "toolkit"' in config


def test_upstream_sync_is_event_driven_with_polling_and_deploy_fallback():
    receiver = (ROOT / ".github" / "workflows" / "sync-delay-toolkit.yml").read_text(encoding="utf-8")
    sender = (ROOT / "deploy" / "upstream-trigger" / "sync-coair.yml").read_text(encoding="utf-8")
    assert "repository_dispatch:" in receiver
    assert 'cron: "*/10 * * * *"' in receiver
    assert "git push origin HEAD:main" in receiver
    assert "gh workflow run deploy.yml --ref main" in receiver
    assert "COAIR_REPOSITORY_DISPATCH_TOKEN" in sender
    assert "repos/kadir-sen/RAG/dispatches" in sender
