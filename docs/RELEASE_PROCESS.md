# Release Process

Until GitHub Actions billing and branch-protection automation are restored, EC2 is the canonical CI environment for this deployment.

## Canonical EC2 release evidence

1. Run the full EC2 pytest suite and save the artifact under `storage/reports/ec2_ci/`.
2. Run `python3 scripts/go_live_gate_check.py` and save the artifact under `storage/reports/ec2_ci/`.
3. Only treat a release as launch-ready if:
   - pytest exits with code 0,
   - the gate checker returns `GO`,
   - the paper window is complete,
   - only explicitly classified `candidate_for_tiny_capital` entries are in tiny-capital scope.

## Temporary release rule

- GitHub UI checks are advisory while billing is unresolved.
- EC2 artifacts are the source of truth for the current server deployment.
- Once GitHub Actions billing is restored, branch protection can be switched back to GitHub-hosted CI.
