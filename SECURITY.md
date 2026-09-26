# Security policy

## Never commit credentials

Keep API keys, webhook secrets, service-account JSON, SSH keys, `.env` files,
and runtime databases outside Git. Commit only placeholder templates such as
`.env.example`. Before every push, run:

```bash
python scripts/scan_secrets.py
```

CI runs the same scanner over every tracked file and blocks private-key material,
common provider tokens, and non-placeholder secrets in configuration files.
`.gitignore` is not sufficient after a file has already been tracked; remove it
with `git rm --cached <path>` and rotate the credential.

## If a secret is exposed

1. Revoke or rotate it immediately. Deleting a file or commit does not revoke a credential.
2. Remove it from the current branch and identify every affected tag and branch.
3. Coordinate any history rewrite with all repository users before force-pushing.
4. Clear cached clones, CI artifacts, releases, and server copies where applicable.
5. Verify the new credential is stored only in the deployment secret store.

Report security incidents privately to the repository owner; do not open a public
issue containing credential material.
