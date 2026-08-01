# ConstructionIQ — AWS Lightsail Deployment Runbook

Single-server deployment of the FastAPI + React app to AWS Lightsail using
Docker Compose. Image is built locally on the developer Mac and shipped via
`docker save | ssh | docker load` (no registry needed).

## Server

| Field | Value |
|---|---|
| Instance | `mvp-api` |
| Region | eu-central-1 (Frankfurt) |
| OS | Ubuntu (Lightsail base) |
| Plan | 2 GB RAM / 2 vCPU / 60 GB SSD |
| Public IPv4 | `63.184.32.196` |
| SSH user | `ubuntu` |
| Remote app dir | `/opt/mvp-api` |

## Architecture

```
Browser ── HTTP 80 ──► Lightsail (63.184.32.196)
                       └── docker compose -f docker-compose.prod.yml
                           └── mvp-api (FastAPI :8000, port-mapped 80)
                               ├── /          → React SPA
                               ├── /assets/   → Vite build assets
                               ├── /api/*     → FastAPI routes
                               ├── /api/health → liveness probe
                               └── /docs      → OpenAPI UI

Volumes (host bind):
  /opt/mvp-api/storage  → /app/storage   (parquets, registry, etc.)
  /opt/mvp-api/data     → /app/data      (uploaded documents)
  /opt/mvp-api/.env.production           (env_file, chmod 600)
```

External: Pinecone (managed). Vector store backend selected via
`VECTOR_STORE_BACKEND=pinecone`.

## Prerequisites (local Mac)

- Docker Desktop with `buildx` (Apple Silicon: cross-build to `linux/amd64`).
- SSH private key at `~/Downloads/LightsailDefaultKey-eu-central-1.pem`
  (override with `SSH_KEY_PATH` env var).
- A real `.env.production` at the project root (see `.env.production.example`).
  Never commit it.

```bash
cp .env.production.example .env.production
# fill GOOGLE_API_KEY, PINECONE_API_KEY, PINECONE_INDEX_NAME, etc.
chmod 600 .env.production
```

## One-time server bootstrap

Run on a fresh Lightsail instance. Idempotent.

```bash
SSH_KEY=~/Downloads/LightsailDefaultKey-eu-central-1.pem
chmod 400 "$SSH_KEY"

scp -i "$SSH_KEY" \
    scripts/server_bootstrap_lightsail.sh \
    ubuntu@63.184.32.196:/tmp/

ssh -i "$SSH_KEY" ubuntu@63.184.32.196 \
    'bash /tmp/server_bootstrap_lightsail.sh'
```

What it does:
- `apt` base packages (curl, rsync, jq, htop)
- 2 GB swap file at `/swapfile` (persisted via `/etc/fstab`)
- Docker Engine + Compose plugin (official repo)
- Adds `ubuntu` to `docker` group
- Docker daemon log rotation (`max-size: 20m`, `max-file: 3`)
- Creates `/opt/mvp-api/{storage,data}` owned by `ubuntu`
- Smoke test: `docker run hello-world`

After bootstrap, the SSH session may need to be re-established for
sudo-less `docker` (group change). The deploy script uses `sudo docker`
defensively.

## Deploy (every release)

From the project root on local Mac:

```bash
./scripts/deploy_lightsail.sh             # default: build + ship
./scripts/deploy_lightsail.sh --with-data  # also rsync local data/ + storage/
./scripts/deploy_lightsail.sh --skip-build # re-use existing local image tag
```

Flow:
1. Pre-flight: SSH key perms, `.env.production` presence, Docker buildx.
2. SSH connectivity test.
3. `buildx build --platform linux/amd64 --load -t mvp-api:latest .`
4. `docker save | gzip | ssh | docker load` to remote.
5. `rsync` `docker-compose.prod.yml` + `scripts/`.
6. `scp` `.env.production` + remote `chmod 600`.
7. Optional: `rsync` `data/` and `storage/`.
8. Remote: `docker compose down` + `up -d` (NEVER `down -v`).
9. Health loop: poll `http://63.184.32.196/api/health` for up to 60 s.

## Verification

```bash
curl -i http://63.184.32.196/api/health      # → 200 {"status":"ok"}
curl -i http://63.184.32.196/                 # → 200 SPA HTML
curl -i http://63.184.32.196/docs             # → 200 OpenAPI UI
```

Server-side checks (over SSH):

```bash
sudo docker ps                                # mvp-api Up (healthy)
sudo docker logs --tail 50 mvp-api            # uvicorn started, no fatal errors
free -h                                       # swap visible, available > 200 MB
df -h /                                       # disk usage < 50%
sudo ss -tulpn | grep :80                     # docker-proxy listening
sudo ss -tulpn | grep -E ':6333|:6334|:8000'  # MUST be empty (Qdrant + raw API not exposed)
```

## Operations

| Action | Command |
|---|---|
| Tail logs | `ssh -i $SSH_KEY ubuntu@63.184.32.196 "sudo docker logs -f mvp-api"` |
| Restart | `ssh -i $SSH_KEY ubuntu@63.184.32.196 "cd /opt/mvp-api && sudo docker compose -f docker-compose.prod.yml restart"` |
| Stop | `ssh -i $SSH_KEY ubuntu@63.184.32.196 "cd /opt/mvp-api && sudo docker compose -f docker-compose.prod.yml stop"` |
| Status | `ssh -i $SSH_KEY ubuntu@63.184.32.196 "sudo docker ps && free -h && df -h /"` |
| Backup `storage/` | `ssh -i $SSH_KEY ubuntu@63.184.32.196 "sudo tar -czf /tmp/storage-$(date +%F).tgz -C /opt/mvp-api storage data"` then `scp` it down |
| Reboot test | `ssh -i $SSH_KEY ubuntu@63.184.32.196 "sudo reboot"` (wait 2 min, hit `/api/health`) |

> **Never** run `docker compose down -v` — it deletes named volumes and
> would wipe state. The deploy script uses `down` (no `-v`) only.

## Open ports

Lightsail console → Networking → Firewall:

| Port | Protocol | Use | Open? |
|---|---|---|---|
| 22 | TCP | SSH | yes |
| 80 | TCP | HTTP (FastAPI via Docker) | yes |
| 443 | TCP | HTTPS (future, when TLS added) | yes |
| 6333 / 6334 | TCP | Qdrant | **NO** (not used in this deploy) |
| 8000 | TCP | Raw API | **NO** (only via host port 80) |

## Static IP

By default Lightsail issues a dynamic public IPv4. The current
`63.184.32.196` will change if the instance is stopped/started.

Action: in Lightsail console → Networking → "Create static IP" → attach
to instance `mvp-api`. Free while attached. Update the deploy script's
`SSH_HOST` if the IP changes.

## Troubleshooting

**`Healthcheck failed` after deploy.**
- `sudo docker logs --tail 200 mvp-api` for tracebacks.
- 99% of the time: missing env var (e.g. `GOOGLE_API_KEY`, `PINECONE_API_KEY`).
- Validate `.env.production` exists on remote: `ssh ... "ls -l /opt/mvp-api/.env.production"`.

**`[Startup] GCS sync error (non-fatal): ...`**
- Expected. The codebase has GCS sync wrapped in `try/except`; no AWS
  credential is present, so it logs and moves on.

**Build OOM or container OOMKilled.**
- We build locally to avoid the 2 GB instance OOM during `npm ci` / Vite
  build. If it ever happens at runtime, the swap (2 GB) absorbs spikes.
  If sustained, upgrade Lightsail plan to 4 GB (~$24/mo).

**Cross-arch errors (`exec format error`).**
- The image must be `linux/amd64`. Verify locally:
  `docker image inspect mvp-api:latest --format '{{.Architecture}}'` →
  must be `amd64`. The deploy script handles this with `buildx --platform`.

**`docker save` transfer slow or interrupted.**
- The image is ~1–1.2 GB uncompressed, ~400–500 MB gzipped. Over a slow
  line, expect minutes. If it fails, the previous container is still
  running (we don't `down` until after a successful `load`).

## Security notes

- `.env.production` lives only on the developer Mac and at
  `/opt/mvp-api/.env.production` (chmod 600). Never committed; `.gitignore`
  covers `.env.production` and `*.pem`/`*.key`.
- SSH key never copied to the server.
- Qdrant (6333/6334) and raw API (8000) are **not** exposed to the
  public — the only public listener is host port 80 → container :8000.
- HTTP only for now. TLS is the next phase: add Caddy or nginx + Let's
  Encrypt once a domain is attached.

## Out of scope (future phases)

- Domain + TLS (Caddy / nginx + Let's Encrypt).
- Pinecone → self-hosted Qdrant migration (separate plan).
- S3 nightly backup of `storage/` and `data/`.
- `requirements.txt` version pinning.
- GCS → S3 storage abstraction.
- Streamlit legacy (`app.py`, `debug_app.py`) — kept in dev compose
  only; production runs FastAPI.
