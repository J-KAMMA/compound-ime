<#
.SYNOPSIS
  Copies the learning data and settings of a Mozc-branded MyIME build to CompoundIME.

.DESCRIPTION
  Run as the user (not elevated) after installing CompoundIME. Without -Apply it
  only lists what would be copied. With -Apply it stops both IME servers (they
  restart on the next key press), keeps every CompoundIME file it replaces in
  LocalLow\CompoundIME\before-migration-<time>\, then copies:
    - LocalLow\Mozc\{config1.db, segment.db, boundary.db, history.db,
      context_segment.db, cform.db, keymap.tsv, user_dictionary.db,
      encrypt_key.db, jaen_choices.txt, correction_log.tsv}
    - %APPDATA%\Mozc\azookey_memory\
    - the user settings under HKCU\Software\Mozc (not the status values)
  Nothing is deleted from the Mozc side. The model is not copied: the
  CompoundIME installer downloads it.
#>
param([switch]$Apply)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$oldProfile = Join-Path $env:USERPROFILE 'AppData\LocalLow\Mozc'
$newProfile = Join-Path $env:USERPROFILE 'AppData\LocalLow\CompoundIME'
$oldMemory = Join-Path $env:APPDATA 'Mozc\azookey_memory'
$newMemory = Join-Path $env:APPDATA 'CompoundIME\azookey_memory'
$files = 'config1.db', 'segment.db', 'boundary.db', 'history.db', 'context_segment.db', 'cform.db',
         'keymap.tsv', 'user_dictionary.db', 'encrypt_key.db', 'jaen_choices.txt', 'correction_log.tsv'
$settings = 'ZenzaiEnabled', 'TypoCorrectionEnabled', 'IdleResuggest', 'TypoCorrectionUseAi',
            'ZenzaiUseGpu', 'PassthroughImeOffKeys'

if (-not (Test-Path -LiteralPath $oldProfile)) { throw "No Mozc profile at $oldProfile" }
if (-not (Test-Path -LiteralPath $newProfile)) {
  throw 'Start CompoundIME once (type a few keys with it) so it creates its profile folder, then run again.'
}

$plan = foreach ($name in $files) {
  $from = Join-Path $oldProfile $name
  if (Test-Path -LiteralPath $from) {
    [pscustomobject]@{ Item = $name; From = $from; To = (Join-Path $newProfile $name)
                       Replaces = Test-Path -LiteralPath (Join-Path $newProfile $name) }
  }
}
$oldKey = Get-ItemProperty -LiteralPath 'HKCU:\Software\Mozc' -ErrorAction SilentlyContinue
$values = foreach ($name in $settings) {
  if ($oldKey -and $oldKey.PSObject.Properties[$name]) { [pscustomobject]@{ Name = $name; Value = $oldKey.$name } }
}

'Files:'
$plan | Format-Table Item, Replaces -AutoSize | Out-String -Width 200
'AI learning folder: ' + $(if (Test-Path -LiteralPath $oldMemory) { $oldMemory } else { '(none)' })
'Settings:'
$values | Format-Table -AutoSize | Out-String -Width 200
if (-not $Apply) { 'Dry run. Run again with -Apply to copy.'; return }

# Both servers write these files; they start again on the next key press.
foreach ($dir in 'Mozc', 'CompoundIME') {
  $exe = Join-Path ${env:ProgramFiles(x86)} "$dir\mozc_server.exe"
  Get-Process -Name mozc_server -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and ($_.Path -ieq $exe) } | Stop-Process
}
Start-Sleep -Milliseconds 500

$backup = Join-Path $newProfile ('before-migration-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backup | Out-Null
foreach ($item in $plan) {
  if ($item.Replaces) { Move-Item -LiteralPath $item.To -Destination (Join-Path $backup $item.Item) }
  # A new file inherits the CompoundIME folder's permissions (readable by sandboxed apps).
  [IO.File]::WriteAllBytes($item.To, [IO.File]::ReadAllBytes($item.From))
}
if (Test-Path -LiteralPath $oldMemory) {
  if (Test-Path -LiteralPath $newMemory) {
    Move-Item -LiteralPath $newMemory -Destination (Join-Path $backup 'azookey_memory')
  }
  New-Item -ItemType Directory -Path (Split-Path $newMemory) -Force | Out-Null
  Copy-Item -LiteralPath $oldMemory -Destination $newMemory -Recurse
}
if ($values) {
  $key = New-Item -Path 'HKCU:\Software\CompoundIME' -Force
  foreach ($v in $values) {
    $kind = if ($v.Value -is [string]) { 'String' } else { 'DWord' }
    New-ItemProperty -LiteralPath $key.PSPath -Name $v.Name -Value $v.Value -PropertyType $kind -Force | Out-Null
  }
}
"Copied. Replaced CompoundIME files are in $backup"
