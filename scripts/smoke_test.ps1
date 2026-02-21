Write-Host "--- Running Windows Smoke Test ---" -ForegroundColor Cyan

try {
    $health = Invoke-RestMethod -Uri "http://localhost:5000/health"
    if ($health.status -eq "ok") {
        Write-Host "PASS: Health Check OK" -ForegroundColor Green
    } else {
        Write-Host "FAIL: Health Check Status Degraded" -ForegroundColor Red
    }
} catch {
    Write-Host "ERROR: Webhook Server not reachable." -ForegroundColor Red
}

$body = @{
    signal_id = "win_smoke_$(Get-Date -Format 'HHmm')"
    payload = @{ symbol = "BTCUSDT"; side = "BUY" }
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:5000/webhook" -Method Post -Body $body -ContentType "application/json"
Write-Host "PASS: Test Signal Sent!" -ForegroundColor Green