data "aws_caller_identity" "current" {}

resource "random_id" "suffix" {
  byte_length = 4
}

locals {
  bucket_name = "${var.project_name}-${data.aws_caller_identity.current.account_id}-${random_id.suffix.hex}"
  glue_job    = "${var.project_name}-etl"
}

resource "aws_s3_bucket" "lake" {
  bucket        = local.bucket_name
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "lake" {
  bucket                  = aws_s3_bucket.lake.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "lake" {
  bucket = aws_s3_bucket.lake.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "lake" {
  bucket = aws_s3_bucket.lake.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "lake" {
  bucket = aws_s3_bucket.lake.id
  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}

resource "aws_s3_object" "glue_script" {
  bucket = aws_s3_bucket.lake.id
  key    = "code/glue/market_data_etl.py"
  source = "${path.module}/../../glue/jobs/market_data_etl.py"
  etag   = filemd5("${path.module}/../../glue/jobs/market_data_etl.py")
}

resource "aws_glue_catalog_database" "analytics" {
  name = "trading_analytics"
}

resource "aws_glue_catalog_table" "klines" {
  database_name = aws_glue_catalog_database.analytics.name
  name          = "klines"
  table_type    = "EXTERNAL_TABLE"
  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"
  }
  partition_keys {
    name = "symbol"
    type = "string"
  }
  partition_keys {
    name = "year"
    type = "int"
  }
  partition_keys {
    name = "month"
    type = "int"
  }
  storage_descriptor {
    location      = "s3://${aws_s3_bucket.lake.id}/curated/klines/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }
    dynamic "columns" {
      for_each = {
        open_time                   = "bigint", open = "decimal(38,18)", high = "decimal(38,18)", low = "decimal(38,18)", close = "decimal(38,18)",
        volume                      = "decimal(38,18)", close_time = "bigint", quote_asset_volume = "decimal(38,18)", number_of_trades = "bigint",
        taker_buy_base_asset_volume = "decimal(38,18)", taker_buy_quote_asset_volume = "decimal(38,18)", interval = "string",
        source_month                = "string", event_time = "timestamp", event_date = "date", price_change = "decimal(38,18)", quote_volume = "decimal(38,18)",
        run_id                      = "string", ingested_at = "timestamp"
      }
      content {
        name = columns.key
        type = columns.value
      }
    }
  }
}

resource "aws_iam_role" "glue" {
  name = "${var.project_name}-glue-role"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "glue.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "glue" {
  name = "lake-access"
  role = aws_iam_role.glue.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:ListBucket", "s3:GetBucketLocation"], Resource = aws_s3_bucket.lake.arn },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], Resource = "${aws_s3_bucket.lake.arn}/*" },
      { Effect = "Allow", Action = ["glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables", "glue:CreatePartition", "glue:BatchCreatePartition", "glue:UpdatePartition"], Resource = "*" },
      { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:AssociateKmsKey"], Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws-glue/*" }
    ]
  })
}

resource "aws_cloudwatch_log_group" "glue" {
  name              = "/aws-glue/jobs/${var.project_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_glue_job" "etl" {
  name              = local.glue_job
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "5.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = 30
  max_retries       = 1
  execution_class   = "STANDARD"
  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "s3://${aws_s3_bucket.lake.id}/${aws_s3_object.glue_script.key}"
  }
  default_arguments = {
    "--job-language"                     = "python"
    "--enable-glue-datacatalog"          = "true"
    "--enable-metrics"                   = "true"
    "--enable-observability-metrics"     = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--continuous-log-logGroup"          = aws_cloudwatch_log_group.glue.name
    "--enable-spark-ui"                  = "true"
    "--spark-event-logs-path"            = "s3://${aws_s3_bucket.lake.id}/spark-ui/"
    "--conf"                             = "spark.sql.session.timeZone=UTC"
    "--TempDir"                          = "s3://${aws_s3_bucket.lake.id}/tmp/"
  }
}

resource "aws_athena_workgroup" "analytics" {
  name = "${var.project_name}-analytics"
  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = 10737418240
    result_configuration {
      output_location = "s3://${aws_s3_bucket.lake.id}/athena-results/"
      encryption_configuration { encryption_option = "SSE_S3" }
    }
  }
}

resource "aws_sns_topic" "failures" {
  name = "${var.project_name}-failures"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.failures.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_event_rule" "glue_failure" {
  name = "${var.project_name}-glue-failure"
  event_pattern = jsonencode({
    source      = ["aws.glue"]
    detail-type = ["Glue Job State Change"]
    detail      = { jobName = [aws_glue_job.etl.name], state = ["FAILED", "TIMEOUT", "STOPPED"] }
  })
}

resource "aws_cloudwatch_event_target" "sns" {
  rule = aws_cloudwatch_event_rule.glue_failure.name
  arn  = aws_sns_topic.failures.arn
}

resource "aws_sns_topic_policy" "events" {
  arn = aws_sns_topic.failures.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Principal = { Service = "events.amazonaws.com" }, Action = "sns:Publish",
      Resource  = aws_sns_topic.failures.arn,
      Condition = { ArnEquals = { "aws:SourceArn" = aws_cloudwatch_event_rule.glue_failure.arn } }
    }]
  })
}
