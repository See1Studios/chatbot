$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$src = 'C:\Users\user\tmp-apply_codex_claude_login_fix.py'
if (-not (Test-Path $src)) { Write-Host "Missing $src"; exit 1 }
Get-Content -Raw -Encoding UTF8 $src | ssh -o BatchMode=yes diskstation "cat > /volume1/homes/me/tmp/apply_codex_claude_login_fix.py"
ssh -o BatchMode=yes diskstation "python3 /volume1/homes/me/tmp/apply_codex_claude_login_fix.py"
