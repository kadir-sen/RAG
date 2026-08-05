from pathlib import Path

from backend.main import _resolve_frontend_file


def test_resolves_vite_public_file(tmp_path: Path):
    boot = tmp_path / "boot.js"
    boot.write_text("console.log('boot')", encoding="utf-8")

    assert _resolve_frontend_file("boot.js", tmp_path) == boot.resolve()


def test_rejects_missing_and_traversal_paths(tmp_path: Path):
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("secret", encoding="utf-8")

    assert _resolve_frontend_file("missing.js", tmp_path) is None
    assert _resolve_frontend_file("../secret.txt", tmp_path) is None
