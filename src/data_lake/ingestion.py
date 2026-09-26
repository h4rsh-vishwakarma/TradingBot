"""Download Binance archives, verify them, and upload immutable raw objects to S3."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import urllib.request
import zipfile
from dataclasses import asdict
from pathlib import Path

from .manifest import ManifestEntry

BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"


def archive_name(symbol: str, interval: str, month: str) -> str:
    return f"{symbol.upper()}-{interval}-{month}.zip"


def source_url(symbol: str, interval: str, month: str) -> str:
    name = archive_name(symbol, interval, month)
    return f"{BASE_URL}/{symbol.upper()}/{interval}/{name}"


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "trading-data-lake/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as out:
        shutil.copyfileobj(response, out)


def validate_zip(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise ValueError(f"Corrupt member in archive: {bad_member}")
        csv_members = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(csv_members) != 1:
            raise ValueError(f"Expected exactly one CSV, found {len(csv_members)}")
        return csv_members[0]


def upload_raw(s3_client, bucket: str, local_path: Path, key: str, entry: ManifestEntry) -> bool:
    """Upload if the exact checksum is absent; reject conflicting immutable keys."""
    from botocore.exceptions import ClientError

    try:
        current = s3_client.head_object(Bucket=bucket, Key=key)
        remote_checksum = current.get("Metadata", {}).get("sha256")
        if remote_checksum == entry.checksum_sha256:
            return False
        raise RuntimeError(f"Immutable raw key already exists with another checksum: s3://{bucket}/{key}")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
            raise
    s3_client.upload_file(
        str(local_path),
        bucket,
        key,
        ExtraArgs={
            "Metadata": {"sha256": entry.checksum_sha256, "run-id": entry.run_id},
            "ServerSideEncryption": "AES256",
        },
    )
    return True


def record_manifest(s3_client, bucket: str, entry: ManifestEntry, source: str) -> None:
    from botocore.exceptions import ClientError

    key = f"manifests/ingestion/{entry.run_id}.json"
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
            raise
    body = json.dumps({**asdict(entry), "source_url": source}, sort_keys=True).encode()
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
        ServerSideEncryption="AES256",
    )


def run(symbol: str, interval: str, month: str, bucket: str, region: str) -> dict:
    import boto3

    url = source_url(symbol, interval, month)
    csv_name = archive_name(symbol, interval, month).removesuffix(".zip") + ".csv"
    raw_key = f"raw/binance/spot/klines/symbol={symbol.upper()}/interval={interval}/month={month}/{csv_name}"
    with tempfile.TemporaryDirectory(prefix="market-data-") as temp_dir:
        local_path = Path(temp_dir) / archive_name(symbol, interval, month)
        download(url, local_path)
        member = validate_zip(local_path)
        csv_path = Path(temp_dir) / csv_name
        with zipfile.ZipFile(local_path) as archive, archive.open(member) as source, csv_path.open("wb") as target:
            shutil.copyfileobj(source, target)
        entry = ManifestEntry.create(raw_key, csv_path)
        s3 = boto3.client("s3", region_name=region)
        uploaded = upload_raw(s3, bucket, csv_path, raw_key, entry)
        record_manifest(s3, bucket, entry, url)
    result = {**entry.__dict__, "source_url": url, "csv_member": member, "uploaded": uploaded}
    print(json.dumps(result, sort_keys=True))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--region", default="ap-south-1")
    args = parser.parse_args()
    run(args.symbol, args.interval, args.month, args.bucket, args.region)


if __name__ == "__main__":
    main()
