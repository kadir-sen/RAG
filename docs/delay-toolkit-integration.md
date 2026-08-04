# Delay Analysis Toolkit integration

COAir carries the complete public upstream source in `vendor/delay-analysis-toolkit` as a squashed Git subtree. The exact upstream revision is recorded in `vendor/delay-analysis-toolkit.upstream.json`. Do not patch the vendor directory: authentication, project intake and managed AI overrides belong in `integrations/delay_toolkit`.

## Local development

1. Set `TOOLKIT_SERVICE_SECRET` to the same non-empty random value for the API and toolkit services.
2. Start `docker compose up --build api toolkit`.
3. Open a project in COAir, upload one or more `.xer` files from Forensic Reports, then choose **Open toolkit**.

The toolkit is served at `http://localhost:8501/toolkit/`; a direct visit is intentionally rejected because a 60-second launch ticket is required. Stored programme files count against the uploader's account storage quota. A project may hold at most 75 MiB of active XER input because the upstream parser estimates approximately 8× expansion in memory.

## Upstream updates

Run `scripts/sync_delay_toolkit.sh` from a clean branch to pull upstream `main`. The `sync-delay-toolkit.yml` workflow accepts an immediate `repository_dispatch` event and also polls upstream every 10 minutes as a fallback. When a new revision is found it runs upstream QA, COAir contract tests, vendor integrity checks and a toolkit image build. Only a fully passing revision is committed to COAir `main`; the workflow then explicitly starts `deploy.yml`, which replaces the toolkit container on the chatbot server behind the existing health gate and rollback.

For immediate event-driven updates, the upstream owner must copy `deploy/upstream-trigger/sync-coair.yml` to `.github/workflows/sync-coair.yml` in `altunozan/delay-analysis-toolkit` and create the Actions secret `COAIR_REPOSITORY_DISPATCH_TOKEN`. The secret should be a fine-grained token restricted to `kadir-sen/RAG` with **Contents: write** permission, which is required by GitHub's repository-dispatch endpoint. COAir currently has read-only upstream permission and cannot perform this one-time installation itself. Until it is installed, the 10-minute polling fallback provides automatic deployment without upstream changes.

`scripts/check_delay_toolkit_vendor.sh` proves that the checked-in vendor tree is byte-for-byte equivalent to the locked upstream Git tree. A failure means someone changed vendor code directly or the lock metadata is stale.

## Production

Production runs the toolkit as a separate 2 GiB container bound to loopback port 8501. The deploy workflow health-checks the API and toolkit before installing the version-controlled Nginx location under `/toolkit/`. The Nginx installer validates the full configuration and restores its backup if validation fails; the deploy script also restores the previous compose configuration when either service fails its health gate.

The upstream repository contained no software licence when it was integrated. Written redistribution/deployment permission must be retained with the project records; see `THIRD_PARTY_NOTICES.md`.
