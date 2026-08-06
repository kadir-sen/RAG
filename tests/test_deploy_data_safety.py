import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_production_state_uses_host_bind_mounts():
    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    for mount in (
        "./storage:/app/storage",
        "./data:/app/data",
        "./qdrant_storage:/qdrant/storage",
        "./qdrant_snapshots:/qdrant/snapshots",
    ):
        assert mount in compose


def test_deploy_requires_verified_backup_and_never_prunes_volumes():
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    assert "scripts/create_deploy_backup.sh" in workflow
    assert "SHA256SUMS" in (ROOT / "scripts/create_deploy_backup.sh").read_text(encoding="utf-8")
    forbidden = ("docker volume prune", "down -v", "rm -rf storage", "rm -rf data")
    combined = workflow + (ROOT / "scripts/create_deploy_backup.sh").read_text(encoding="utf-8")
    for command in forbidden:
        assert command not in combined
    assert 'sudo -n true' in workflow
    assert '$BACKUP_RUNNER env' in workflow


def test_unused_image_cleanup_precedes_candidate_pull_and_never_touches_data():
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    cleanup = "$SUDO docker image prune -a -f"
    pull = "docker compose -f docker-compose.prod.yml pull api"
    backup = 'bash "$HOME/coair-deploy/scripts/create_deploy_backup.sh"'
    assert cleanup in workflow
    cleanup_index = workflow.index(cleanup)
    pull_index = workflow.index(pull, cleanup_index)
    backup_index = workflow.index(backup, pull_index)
    assert cleanup_index < pull_index < backup_index


def test_backup_covers_application_data_and_qdrant_snapshot():
    script = (ROOT / "scripts/create_deploy_backup.sh").read_text(encoding="utf-8")
    assert 'tar -C "$APP_DIR" -cf "$backup_dir/application-data.tar" storage data' in script
    assert 'backup_mode="incremental"' in script
    assert 'find "$APP_DIR/data" -type f -newer "$base_backup/manifest.txt"' in script
    assert "printf 'storage\\0'" in script
    assert 'base_backup=$base_backup' in script
    assert 'if ! ln "$snapshot_path" "$backup_dir/$snapshot_name"' in script
    assert "/collections/$QDRANT_COLLECTION/snapshots?wait=true" in script
    assert 'sha256sum -c SHA256SUMS' in script
    assert 'docker stop --time 45 "$API_CONTAINER"' in script
    assert 'docker start "$API_CONTAINER"' in script
    assert 'BACKUP_ROOT="${BACKUP_ROOT:-$APP_DIR/.deploy-backups}"' in script


@pytest.mark.skipif(sys.platform != "linux", reason="production backup script targets GNU/Linux")
def test_incremental_backup_keeps_mutable_state_and_only_new_source_files(tmp_path):
    app_dir = tmp_path / "app"
    backup_root = app_dir / ".deploy-backups"
    for name in ("storage", "data", "qdrant_storage", "qdrant_snapshots"):
        (app_dir / name).mkdir(parents=True)

    (app_dir / "storage" / "users.db").write_text("current-user-state", encoding="utf-8")
    (app_dir / "qdrant_storage" / "collection.db").write_bytes(b"qdrant-state")
    old_source = app_dir / "data" / "existing.pdf"
    old_source.write_bytes(b"already protected by full backup")

    base = backup_root / "20260805T000000Z"
    base.mkdir(parents=True)
    (base / "application-data.tar").write_bytes(b"verified-full-backup")
    (base / "SHA256SUMS").write_text("verified previously\n", encoding="utf-8")
    base_manifest = base / "manifest.txt"
    base_manifest.write_text("application_archive=application-data.tar\n", encoding="utf-8")
    cutoff = time.time() - 120
    os.utime(old_source, (cutoff - 60, cutoff - 60))
    os.utime(base_manifest, (cutoff, cutoff))
    (app_dir / "data" / "new.pdf").write_bytes(b"uploaded after full backup")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = inspect ]; then echo true; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    curl = fake_bin / "curl"
    curl.write_text(
        "#!/bin/sh\n"
        "printf 'snapshot' > \"$TEST_SNAPSHOT_PATH\"\n"
        "printf '%s' '{\"result\":{\"name\":\"test.snapshot\"}}'\n",
        encoding="utf-8",
    )
    curl.chmod(0o755)

    env = os.environ.copy()
    env.update({
        "APP_DIR": str(app_dir),
        "BACKUP_ROOT": str(backup_root),
        "QDRANT_API_KEY": "test-only-key",
        "TEST_SNAPSHOT_PATH": str(app_dir / "qdrant_snapshots" / "test.snapshot"),
        "PATH": f"{fake_bin}:{env['PATH']}",
    })
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/create_deploy_backup.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    created = max(path for path in backup_root.iterdir() if path != base)
    manifest = (created / "manifest.txt").read_text(encoding="utf-8")
    assert "backup_mode=incremental" in manifest
    assert f"base_backup={base}" in manifest
    assert "data_delta_files=1" in manifest
    with tarfile.open(created / "application-data.tar") as archive:
        names = archive.getnames()
    assert "storage/users.db" in names
    assert "data/new.pdf" in names
    assert "data/existing.pdf" not in names
    assert (created / "test.snapshot").stat().st_ino == (
        app_dir / "qdrant_snapshots" / "test.snapshot"
    ).stat().st_ino
