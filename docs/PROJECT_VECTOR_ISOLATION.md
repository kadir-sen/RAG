# Project vector isolation runbook

Qdrant uses one collection per embedding profile. Projects are isolated by the
mandatory `project_id` payload filter and a keyword index configured with
`is_tenant=true`. Application code must never issue an unscoped vector or BM25
operation.

## Production migration

Run the audit first. It writes a quarantine manifest but changes no Qdrant data:

```bash
python scripts/migrate_project_tenants.py \
  --expected-total 156218 \
  --expected-assigned 156200 \
  --expected-orphans 18
```

If the counts match, stop the API/ingestion workers and apply the migration:

```bash
python scripts/migrate_project_tenants.py --apply --enable-strict \
  --expected-total 156218 \
  --expected-assigned 156200 \
  --expected-orphans 18
```

The apply phase creates a collection snapshot before indexes, verifies exact
counts after the change, and leaves points without `project_id` untouched and
invisible. Manifests are stored under
`storage/migrations/project-tenants/`. Restore using the snapshot recorded in
the manifest and the Qdrant snapshot recovery procedure.

Set `QDRANT_API_KEY` to a generated secret in `.env.production` before the
compose restart. Set `QDRANT_STRICT_MODE=true` only after the migration succeeds.

## Invariants

- A project is `empty` until its first upload is accepted.
- The first ingestion provisions the shared collection contract and transitions
  through `provisioning → indexing → ready`.
- `project_id`, `file_id`, and `embedding_profile` are server-owned metadata.
- Admin users must select one project; there is no global semantic search.
- Project deletion/cleanup uses a project-scoped manifest. Global collection
  deletion is disabled.
