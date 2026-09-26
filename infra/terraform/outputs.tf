output "bucket_name" { value = aws_s3_bucket.lake.id }
output "glue_job_name" { value = aws_glue_job.etl.name }
output "glue_database" { value = aws_glue_catalog_database.analytics.name }
output "athena_workgroup" { value = aws_athena_workgroup.analytics.name }
output "failure_topic_arn" { value = aws_sns_topic.failures.arn }
