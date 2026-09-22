# Run on FIREBAT (Windows). Deploys USAGE_v1 + CODEX_PROC_v1 + CODEX_MODELS_v1.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$srcDir = 'C:\Users\user\tmp-usage-codex-v1'
if (-not (Test-Path "$srcDir\APPLY_USAGE_CODEX_V1.py")) {
  Write-Error "Missing $srcDir\APPLY_USAGE_CODEX_V1.py — copy usage-codex-v1.tgz extract there first"
}

ssh -o BatchMode=yes diskstation 'mkdir -p /volume1/homes/me/tmp/usage-codex-v1/payload'

Get-Content -Raw -Encoding UTF8 "$srcDir\APPLY_USAGE_CODEX_V1.py" |
  ssh -o BatchMode=yes diskstation 'cat > /volume1/homes/me/tmp/usage-codex-v1/APPLY_USAGE_CODEX_V1.py'

$files = @(
  'server.py','accounts.py','adapters.py','session.py','chatbot-ctl.sh',
  'app.js','index.html','account_login.py'
)
foreach ($f in $files) {
  $p = Join-Path $srcDir "payload\$f"
  if (-not (Test-Path $p)) { Write-Host "skip missing $f"; continue }
  Write-Host "upload $f …"
  Get-Content -Raw -Encoding UTF8 $p |
    ssh -o BatchMode=yes diskstation "cat > /volume1/homes/me/tmp/usage-codex-v1/payload/$f"
}

ssh -o BatchMode=yes diskstation 'python3 /volume1/homes/me/tmp/usage-codex-v1/APPLY_USAGE_CODEX_V1.py'
