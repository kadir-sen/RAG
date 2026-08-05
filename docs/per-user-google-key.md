# Per-user Google API keys

COAir stores only a non-secret key alias in `billing_accounts.provider_key_ref`.
The corresponding key is a read-only file under `/run/secrets/google_keys` in
the API container. Keys must never be committed, sent through an API request,
or supplied as a CLI argument.

## Safe production procedure

1. Create or rotate the key in its dedicated Google project.
2. Restrict it to the Gemini API and, where the key type supports it, the
   production server's static egress IP.
3. On the server, create `/opt/mvp-api/secrets/google_keys` with mode `0700`.
4. Install the key as `/opt/mvp-api/secrets/google_keys/demo` with mode `0600`.
   Enter the value interactively on the server; do not place it in shell
   history, GitHub Actions arguments, or chat.
5. Restart the API so the read-only bind mount is present.
6. Validate and bind the alias:

   ```text
   docker exec mvp-api \
     python scripts/bind_provider_key.py --username demo --key-ref demo
   ```

If a dedicated secret is missing, invalid or too broadly permissioned, calls
for that user fail closed. They do not fall back to COAir's shared Google key.
Background ingestion and report workers restore the requesting username before
calling the central LLM client, so OCR/metadata and Chronology use the same
dedicated credential. Local FastEmbed vectorization does not use a Google key.

For the controlled production demo profile, run the interactive configuration
command instead of the alias-only command. It validates the mounted secret
first, then creates or updates the normal demo user with 5,000 credits (USD 50
at direct provider cost with no markup), a 30 GB source-file quota and the
tiered model policy. The percentage decreases from priced input, cached input,
visible output and thinking tokens reported by the provider:

```text
docker exec -it mvp-api python scripts/configure_demo_account.py --username demo
```
