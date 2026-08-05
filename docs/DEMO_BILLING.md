# Demo billing rollout

The public demo must use a non-admin account. Never publish the credentials of
the existing `demo` administrator.

## 1. Back up and migrate

```bash
cp storage/users.db storage/users.db.pre-billing
cp storage/query_runs.db storage/query_runs.db.pre-billing
python scripts/migrate_billing.py
python scripts/migrate_billing.py --apply
```

The first command is a dry run. Historical calls are imported for reporting and
do not consume new demo credits. Existing users remain on the legacy plan.

## 2. Provision the public account

Supply the password through the deployment secret workflow rather than shell
history where possible:

```bash
python scripts/create_user.py \
  --username demo_user \
  --password '<deployment-secret>' \
  --display 'Demo User' \
  --role user \
  --plan demo \
  --initial-credits 5000 \
  --markup-percent 0 \
  --storage-limit-bytes 30000000000 \
  --model-policy demo-gemini-3.6-v1
```

Sign in as `demo_user`, create a project, upload a small file, run one query and
verify that credit and storage percentages change.

## 3. Disable the old public-facing admin login

After the smoke test succeeds, deactivate the old `demo` account through
`PATCH /api/admin/users/demo` with `{"is_active": false}`. This is deliberately
not automatic: the cutover must not remove the current recovery login before
the new account has been verified.

Credit top-up remains an audited ledger action:

```bash
python scripts/create_user.py --username demo_user \
  --add-credits 250 --reason 'Approved demo extension'
```

After a top-up, a file job stopped as `credit_balance_exhausted` can be retried
from the Projects page without uploading or consuming storage a second time.
