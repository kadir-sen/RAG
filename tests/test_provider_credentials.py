import pytest

from src import provider_credentials
from src.logger import redact_secrets


def _secret(tmp_path, name="demo", value="replacement-secret-value-123456"):
    path = tmp_path / name
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_dedicated_key_is_read_from_protected_file(monkeypatch, tmp_path):
    _secret(tmp_path)
    monkeypatch.setattr(provider_credentials, "GOOGLE_USER_KEY_DIR", tmp_path)
    monkeypatch.setattr(provider_credentials, "current_provider_key_ref", lambda: "demo")
    assert provider_credentials.get_google_api_key() == "replacement-secret-value-123456"


def test_dedicated_key_never_falls_back_when_file_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(provider_credentials, "GOOGLE_USER_KEY_DIR", tmp_path)
    monkeypatch.setattr(provider_credentials, "GOOGLE_API_KEY", "shared-global-value-123456")
    monkeypatch.setattr(provider_credentials, "current_provider_key_ref", lambda: "demo")
    with pytest.raises(provider_credentials.ProviderCredentialError,
                       match="provider_key_secret_unavailable"):
        provider_credentials.get_google_api_key()


def test_dedicated_key_rejects_open_permissions(monkeypatch, tmp_path):
    path = _secret(tmp_path)
    path.chmod(0o644)
    monkeypatch.setattr(provider_credentials, "GOOGLE_USER_KEY_DIR", tmp_path)
    with pytest.raises(provider_credentials.ProviderCredentialError,
                       match="permissions_too_open"):
        provider_credentials.get_google_api_key_for_ref("demo")


def test_global_key_is_used_only_without_binding(monkeypatch):
    monkeypatch.setattr(provider_credentials, "GOOGLE_API_KEY", "shared-global-value-123456")
    monkeypatch.setattr(provider_credentials, "current_provider_key_ref", lambda: "")
    assert provider_credentials.get_google_api_key() == "shared-global-value-123456"


@pytest.mark.parametrize("value", ["../demo", "/tmp/demo", "demo/key", "demo key"])
def test_key_reference_cannot_escape_secret_directory(value):
    with pytest.raises(ValueError):
        provider_credentials.validate_provider_key_ref(value)


def test_google_authorization_keys_are_fully_redacted_from_logs():
    sample = "AQ." + "A" * 48
    redacted = redact_secrets(f"provider rejected {sample}")
    assert sample not in redacted
    assert "[GOOGLE_API_KEY_REDACTED]" in redacted
