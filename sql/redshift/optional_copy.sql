-- Optional extension. Use an IAM role with read-only access to curated/.
COPY analytics.klines
FROM 's3://REPLACE_BUCKET/curated/klines/'
IAM_ROLE 'arn:aws:iam::REPLACE_ACCOUNT:role/REPLACE_REDSHIFT_ROLE'
FORMAT AS PARQUET;

SELECT count(*) AS redshift_rows FROM analytics.klines;
