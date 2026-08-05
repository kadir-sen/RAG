from pathlib import Path


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
    assert "/collections/$QDRANT_COLLECTION/snapshots?wait=true" in script
    assert 'sha256sum -c SHA256SUMS' in script
    assert 'docker stop --time 45 "$API_CONTAINER"' in script
    assert 'docker start "$API_CONTAINER"' in script
    assert 'BACKUP_ROOT="${BACKUP_ROOT:-$APP_DIR/.deploy-backups}"' in script
