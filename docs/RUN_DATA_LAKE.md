# Data-lake runbook

## Before a run

1. Confirm the source month exists in the public Binance archive.
2. Record the Git commit and ensure no secrets or private data are staged.
3. Run fast unit tests and the Glue Docker test.
4. Review `terraform plan`, especially IAM and estimated worker/runtime choices.

## Execute

1. Ingest each bounded symbol/month and save the JSON output containing checksum, run ID, byte size, and S3 key.
2. Start Glue with explicit input, curated, quarantine, and run-ID arguments.
3. Wait for `SUCCEEDED`; capture the job-run ID and CloudWatch reconciliation event.
4. Confirm Catalog partitions. If they are not registered by the write path, run `MSCK REPAIR TABLE trading_analytics.klines` in Athena.
5. Execute correctness and performance SQL from `sql/athena/`.

## Failure handling

- `schema_or_type_error`: inspect the quarantined source row and archive schema before changing the contract.
- Reconciliation failure: stop publication; compare raw, invalid, and duplicate logic for the same run ID.
- Immutable-key conflict: do not overwrite. Validate upstream revision and choose a versioned source key only when justified.
- Glue timeout/worker exhaustion: use Spark UI/explain evidence before increasing workers or timeout.
- Alert not received: confirm the SNS email subscription, EventBridge rule match, and SNS topic policy.

## Teardown

Export required evidence first. Delete project-bucket object versions deliberately, then use Terraform destroy. Never use broad bucket/account cleanup commands.
