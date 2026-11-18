# Back up the Gantry database into backups\Gantry_<timestamp>.bak.
#
# Used by the "Gantry DB Backup" scheduled task and by backup-db-now.bat.
# Every backup is verified with RESTORE VERIFYONLY before the old ones are
# pruned, so a corrupt file is reported instead of silently replacing a good one.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backup-db.ps1
#   powershell ... -File scripts\backup-db.ps1 -KeepDays 30 -Database Gantry

param(
    [string]$Server = "localhost",
    [string]$Database = "Gantry",
    [int]$KeepDays = 14
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $root "backups"
$log = Join-Path $dest "backup.log"

New-Item -ItemType Directory -Force -Path $dest | Out-Null

function Write-Log([string]$line) {
    $stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    Add-Content -Path $log -Value "$stamp  $line" -Encoding UTF8
    Write-Host $line
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$file = Join-Path $dest "$($Database)_$stamp.bak"

$sql = "BACKUP DATABASE [$Database] TO DISK = N'$file' " +
       "WITH INIT, COMPRESSION, CHECKSUM, NAME = N'$Database full backup'"

Write-Log "backup start: $file"

& sqlcmd -S $Server -E -C -b -Q $sql | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Log "FAILED: BACKUP DATABASE returned $LASTEXITCODE"
    exit 1
}

& sqlcmd -S $Server -E -C -b -Q "RESTORE VERIFYONLY FROM DISK = N'$file' WITH CHECKSUM" | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Log "FAILED: the backup did not verify; keeping it for inspection"
    exit 1
}

$size = [math]::Round((Get-Item $file).Length / 1MB, 2)
Write-Log "backup ok: $file ($size MB)"

$cutoff = (Get-Date).AddDays(-$KeepDays)
$old = Get-ChildItem -Path $dest -Filter "$($Database)_*.bak" |
    Where-Object { $_.LastWriteTime -lt $cutoff }
foreach ($item in $old) {
    Remove-Item $item.FullName -Force
    Write-Log "pruned: $($item.Name)"
}

Write-Log "done (keeping $KeepDays days)"
exit 0
