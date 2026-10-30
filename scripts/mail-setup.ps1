<#
 One-time, local setup for REAL Gmail notification mail in the demo (Windows PowerShell 5.1+ / PowerShell 7).
 Run from anywhere:  .\scripts\mail-setup.ps1

 Writes two files, both ignored by git AND by docker builds (.gitignore: ".env.*" and "secrets/"; .dockerignore likewise):
   .env.mail                    the Gmail addresses (not secret, but private)
   secrets\smtp_password.txt    the Gmail APP PASSWORD, read by the backend through ACCESS_NOTIFY_SMTP_PASSWORD_FILE
 The app password is typed at a hidden prompt: it is never a command-line argument, never echoed, never put in an environment
 variable, never written to .env.demo and never printed. Use a Gmail APP PASSWORD (Google Account > Security > 2-Step Verification
 > App passwords), not your normal Google password. Re-run with -Force to replace existing files.
#>
param([switch]$Force)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

$envMail = '.env.mail'
$secretDir = 'secrets'
$secretFile = Join-Path $secretDir 'smtp_password.txt'
if (((Test-Path $envMail) -or (Test-Path $secretFile)) -and -not $Force) {
  throw "$envMail or $secretFile already exists. Re-run with -Force to replace them."
}

$addr = '^[^\s@<>",;]+@[^\s@<>",;]+\.[^\s@<>",;]+$'
$user = (Read-Host 'Gmail address that sends the mail (the account the app password belongs to)').Trim()
if ($user -notmatch $addr) { throw 'That does not look like an email address.' }
$owner = (Read-Host "Address that receives the new-request notification [$user]").Trim()
if (-not $owner) { $owner = $user }
if ($owner -notmatch $addr) { throw 'That does not look like an email address.' }

$secure = Read-Host 'Gmail app password (16 characters, input is hidden)' -AsSecureString
$bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
  $plain = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
  $plain = $plain -replace '\s', ''   # Google shows it as four groups of four; the spaces are not part of it
  if ($plain -notmatch '^[A-Za-z0-9]{16}$') {
    throw 'That is not a 16-character app password. Nothing was written. Create one under Google Account > Security > App passwords.'
  }
  if (-not (Test-Path $secretDir)) { New-Item -ItemType Directory -Path $secretDir | Out-Null }
  $utf8 = New-Object System.Text.UTF8Encoding($false)
  $root = (Get-Location).Path
  [System.IO.File]::WriteAllText((Join-Path $root $secretFile), $plain, $utf8)
  [System.IO.File]::WriteAllLines((Join-Path $root $envMail), @(
      "ACCESS_NOTIFY_SMTP_USER=$user",
      "ACCESS_NOTIFY_OWNER_EMAIL=$owner",
      "ACCESS_NOTIFY_FROM=$user"
    ), $utf8)
} finally {
  [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
  $plain = $null
  $secure.Dispose()
}

# Best effort: leave only the current Windows user with access to the password file.
try {
  & icacls $secretFile /inheritance:r /grant:r "${env:USERNAME}:(R,W)" | Out-Null
} catch {
  Write-Warning "Could not tighten permissions on $secretFile (continuing)."
}

Write-Host "Wrote $envMail and $secretFile (git-ignored and docker-ignored). The password was not printed."
Write-Host 'Next:  .\scripts\demo.ps1 -WithMail'
