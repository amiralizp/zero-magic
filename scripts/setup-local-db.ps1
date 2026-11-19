<#
Creates the local PostgreSQL role and database for Gantry (step S9) and writes
DATABASE_URL to .env. Run it yourself in a normal PowerShell window. Do NOT run
it through an agent: it asks for the PostgreSQL admin password.
Nothing secret is printed. The generated application password is stored only in
.env. Re-running it rotates the application password and rewrites DATABASE_URL.
#>
param(
    [string]$PgBin = "C:\Program Files\PostgreSQL\17\bin",
    [string]$DbHost = "127.0.0.1",
    [int]$Port = 5432,
    [string]$AppUser = "gantry_app",
    [string]$Database = "gantry"
)

$ErrorActionPreference = "Stop"
$psql = Join-Path $PgBin "psql.exe"
if (-not (Test-Path $psql)) { throw "psql.exe not found at $psql" }
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$envPath = Join-Path $repoRoot ".env"

# .env must never be committed.
Push-Location $repoRoot
try {
    git check-ignore -q .env
    if ($LASTEXITCODE -ne 0) { throw ".env is not ignored by git. Stopping." }
}
finally { Pop-Location }

function Read-Secret([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function Invoke-Psql([string]$Sql, [string]$User = "postgres", [string]$Db = "postgres") {
    $result = $Sql | & $psql -U $User -h $DbHost -p $Port -d $Db -v ON_ERROR_STOP=1 -t -A -q -f -
    if ($LASTEXITCODE -ne 0) { throw "psql failed (exit code $LASTEXITCODE)" }
    return ($result | Out-String).Trim()
}

$appPassword = $null
try {
    $env:PGPASSWORD = Read-Secret "PostgreSQL password of the 'postgres' user"

    # 32 random letters and digits, no characters that break a URL.
    $alphabet = @((48..57) + (65..90) + (97..122) | ForEach-Object { [char]$_ })
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    $appPassword = -join ($bytes | ForEach-Object { $alphabet[$_ % $alphabet.Length] })

    $roleExists = Invoke-Psql "SELECT 1 FROM pg_roles WHERE rolname = '$AppUser';"
    if ($roleExists -eq "1") {
        Invoke-Psql "ALTER ROLE $AppUser WITH LOGIN PASSWORD '$appPassword';" | Out-Null
        Write-Host "Role $AppUser existed: password rotated."
    }
    else {
        Invoke-Psql "CREATE ROLE $AppUser WITH LOGIN PASSWORD '$appPassword';" | Out-Null
        Write-Host "Role $AppUser created."
    }

    $dbExists = Invoke-Psql "SELECT 1 FROM pg_database WHERE datname = '$Database';"
    if ($dbExists -ne "1") {
        Invoke-Psql "CREATE DATABASE $Database OWNER $AppUser;" | Out-Null
        Write-Host "Database $Database created."
    }
    else { Write-Host "Database $Database already exists." }

    $newLine = "DATABASE_URL=postgresql+psycopg://${AppUser}:${appPassword}@${DbHost}:${Port}/${Database}"
    $lines = @()
    $replaced = $false
    if (Test-Path $envPath) {
        foreach ($l in [System.IO.File]::ReadAllLines($envPath)) {
            if ($l -match '^\s*DATABASE_URL=') {
                if (-not $replaced) { $lines += $newLine; $replaced = $true }
            }
            else { $lines += $l }
        }
    }
    if (-not $replaced) { $lines += $newLine }
    [System.IO.File]::WriteAllLines($envPath, $lines, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host ".env updated (DATABASE_URL). The password was not printed."

    $env:PGPASSWORD = $appPassword
    $check = Invoke-Psql "SELECT current_user || ' @ ' || current_database();" $AppUser $Database
    Write-Host "Connection check: $check"
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    $appPassword = $null
}