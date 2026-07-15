<#
.SYNOPSIS
    Initializes a project directory with a specific Gemini API key from the central vault.

.DESCRIPTION
    Reads /Users/shanfu/cc/MEMORY/gemini_keys.json, finds the key matching the provided label, 
    and writes it to a local .env file in the target project directory.

.EXAMPLE
    ./Init-ProjectEnv.ps1 -Path "/Users/shanfu/cc/Projects/MyProject" -Label "research"
#>

param (
    [Parameter(Mandatory=$true)]
    [string]$Path,

    [Parameter(Mandatory=$true)]
    [string]$Label
)

# Configuration Paths
$VaultPath = "/Users/shanfu/cc/MEMORY/gemini_keys.json"

# Check if vault exists
if (-not (Test-Path $VaultPath)) {
    Write-Error "Gemini Key Vault not found at $VaultPath"
    exit 1
}

# Load Vault
try {
    $Vault = Get-Content $VaultPath -Raw | ConvertFrom-Json
} catch {
    Write-Error "Failed to parse Gemini Key Vault JSON."
    exit 1
}

# Find Key
$Key = $Vault.$Label
if (-not $Key) {
    Write-Host "❌ Error: Label '$Label' not found in vault." -ForegroundColor Red
    Write-Host "Available labels: $(($Vault | Get-Member -MemberType NoteProperty).Name -join ', ')"
    exit 1
}

# Resolve Full Path
$FullPath = [System.IO.Path]::GetFullPath($Path)
$EnvFilePath = Join-Path $FullPath ".env"

# Create Directory if it doesn't exist
if (-not (Test-Path $FullPath)) {
    Write-Host "Creating directory: $FullPath"
    New-Item -ItemType Directory -Path $FullPath -Force | Out-Null
}

# Prepare .env content
# We preserve existing keys if the file exists, or create a fresh one if not.
$NewLines = @()
$VariableSet = $false

if (Test-Path $EnvFilePath) {
    $CurrentLines = Get-Content $EnvFilePath
    foreach ($line in $CurrentLines) {
        if ($line -match "^GEMINI_API_KEY=") {
            $NewLines += "GEMINI_API_KEY=$Key"
            $VariableSet = $true
        } else {
            $NewLines += $line
        }
    }
}

if (-not $VariableSet) {
    $NewLines += "GEMINI_API_KEY=$Key"
}

# Write back to .env (UTF8 without BOM for compatibility)
$Utf8NoBomEncoding = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($EnvFilePath, $NewLines, $Utf8NoBomEncoding)

Write-Host "✅ Successfully initialized .env for kind [$Label] at:" -ForegroundColor Green
Write-Host "$EnvFilePath" -ForegroundColor Cyan