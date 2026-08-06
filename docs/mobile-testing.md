# Mobile UI verification

The local responsive suite is isolated from production data and uses stateful
Playwright API fixtures:

```bash
cd frontend
npm ci
npx playwright install chromium webkit
npm run e2e:mobile
```

It covers 360, 390 and 430 px phones, a 768 px tablet and a 1440 px desktop in
Chromium. The critical 390/768 flows also run in WebKit. Failure traces, video
and screenshots are uploaded by the deploy workflow.

## One-time production smoke setup

The public smoke is intentionally read-only. Provision its account and empty
project on the server with the password supplied through the environment:

```bash
export PROD_E2E_PASSWORD='use-a-secret-manager-value'
python scripts/provision_mobile_smoke_workspace.py
python scripts/provision_mobile_smoke_workspace.py --apply
```

The first command is a dry run. The applied account is a normal user with zero
credits and `viewer` membership; `admin2` remains the project owner. Upload one
harmless PDF and one harmless XLSX/CSV fixture to `Mobile Smoke Workspace` once
as the owner. Do not use customer documents.

Configure the GitHub `production` environment with:

- `PROD_BASE_URL`
- `PROD_E2E_USERNAME` (`mobile_smoke` by default)
- `PROD_E2E_PASSWORD`
- `PROD_E2E_PROJECT_ID` (printed by the provisioning command)

Missing values fail the production preflight. After login, the test rejects
every request that is not `GET`, `HEAD` or `OPTIONS`; it never uploads, edits,
archives, generates reports or deletes records.
