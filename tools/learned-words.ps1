<#
.SYNOPSIS
  Compound IME が覚えた「英語にする語／日本語にする語」を見る・消す。

.DESCRIPTION
  覚えた語は jaen_choices.txt に語ごとの点数で入っている（正は英語、負は日本語）。
  点数は半減期60日で薄れる。ここに出す「点数」は今の時点に薄れた後の値。
    英語として覚えた    点数が +2 以上
    日本語として覚えた  点数が -2 以下（ブランド名など強い英語の語は -3 以下）
    様子見              そのあいだ（まだ決まっていない）

  -Remove <語> で、その語の記録を1つ消す（元に戻す）。ほかの語はそのまま。
  既定の保存先は %USERPROFILE%\AppData\LocalLow\CompoundIME\jaen_choices.txt。
  試すときは -Path で別のファイルを指す。

.EXAMPLE
  .\learned-words.ps1
  .\learned-words.ps1 -Remove github
  .\learned-words.ps1 -Path C:\temp\jaen_choices.txt
#>
[CmdletBinding()]
param(
  [string]$Path,
  [string]$Remove,
  [long]$Now = 0   # 試験用: 現在時刻（unix秒）。省略すると今。
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false) } catch { }

if (-not $Path) {
  $Path = Join-Path $env:USERPROFILE 'AppData\LocalLow\CompoundIME\jaen_choices.txt'
}
if ($Now -le 0) { $Now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() }

$HalfLifeDays = 60.0
$MaxScore = 10.0
$ForgetBelow = 0.05
$Inv = [System.Globalization.CultureInfo]::InvariantCulture

function Get-Decayed([double]$score, [long]$time) {
  $age = $Now - $time
  if ($age -le 0) { return $score }
  return $score * [Math]::Pow(2.0, -([double]$age) / ($HalfLifeDays * 86400.0))
}

# 強い英語の語（ブランド名・略語）。リポジトリ内で動かしたときだけ分かる。
$strong = @{}
$strongKnown = $false
foreach ($name in 'brand-casing.tsv', 'brand-casing-fixes.tsv', 'jaen-modern-words.tsv') {
  $file = Join-Path $PSScriptRoot (Join-Path 'data' $name)
  if (Test-Path -LiteralPath $file) {
    $strongKnown = $true
    foreach ($line in [System.IO.File]::ReadAllLines($file, [System.Text.Encoding]::UTF8)) {
      if ($line.Length -eq 0 -or $line[0] -eq '#') { continue }
      $strong[($line -split "`t")[0].ToLowerInvariant()] = $true
    }
  }
}

# 保存形式を読む: v2 は w<TAB>語<TAB>点<TAB>時刻。旧形式の e / j も読む（C++側と同じ）。
function Read-Entries([string]$file) {
  $entries = [ordered]@{}
  if (-not (Test-Path -LiteralPath $file)) { return $entries }
  $fileTime = [DateTimeOffset]::new((Get-Item -LiteralPath $file).LastWriteTimeUtc).ToUnixTimeSeconds()
  foreach ($line in [System.IO.File]::ReadAllLines($file, [System.Text.Encoding]::UTF8)) {
    $line = $line.TrimEnd("`r")
    if ($line.Length -eq 0 -or $line[0] -eq '#') { continue }
    $f = $line -split "`t"
    if ($f.Count -lt 2) { continue }
    $word = $f[1].ToLowerInvariant()
    if ($word.Length -eq 0) { continue }
    $score = 0.0
    $time = $fileTime
    $number = 0.0
    $hasNumber = $f.Count -ge 3 -and [double]::TryParse($f[2], [System.Globalization.NumberStyles]::Float, $Inv, [ref]$number)
    $count = if ($hasNumber) { [Math]::Max($number, 1.0) } else { 1.0 }
    if ($f[0] -eq 'w') {
      if (-not $hasNumber) { continue }
      $score = $number
      $stamp = [long]0
      if ($f.Count -ge 4 -and [long]::TryParse($f[3], [ref]$stamp)) { $time = [Math]::Min($stamp, $Now) }
    } elseif ($f[0] -eq 'e') {
      $score = $count
    } elseif ($f[0] -eq 'j') {
      $score = -[Math]::Min($count, 2.0)
    } else {
      continue
    }
    $score = [Math]::Max(-$MaxScore, [Math]::Min($MaxScore, $score))
    $entries[$word] = [pscustomobject]@{ Score = $score; Time = $time }
  }
  return $entries
}

function Write-Entries([string]$file, $entries) {
  $sb = [System.Text.StringBuilder]::new()
  [void]$sb.Append("# v2`n")
  foreach ($word in $entries.Keys) {
    $e = $entries[$word]
    if ([Math]::Abs((Get-Decayed $e.Score $e.Time)) -lt $ForgetBelow) { continue }
    [void]$sb.Append("w`t$word`t$($e.Score.ToString('0.0000', $Inv))`t$($e.Time)`n")
  }
  $temp = "$file.tmp"
  # BOM なしの UTF-8、改行は LF（IME側の読み書きと同じ）
  [System.IO.File]::WriteAllText($temp, $sb.ToString(), [System.Text.UTF8Encoding]::new($false))
  Move-Item -LiteralPath $temp -Destination $file -Force
}

if (-not (Test-Path -LiteralPath $Path)) {
  Write-Output "覚えた語はまだありません（$Path）。"
  return
}

try {
  $entries = Read-Entries $Path
} catch [System.IO.IOException] {
  [Console]::Error.WriteLine("ファイルを使用中のため読めません。少し待ってからもう一度実行してください: $Path")
  exit 1
}

if ($Remove) {
  $word = $Remove.Trim().ToLowerInvariant()
  if (-not $entries.Contains($word)) {
    Write-Output "「$word」は覚えた語の中にありません。"
    return
  }
  # IME が読み書きしている最中なら、壊さないよう断る。
  try {
    $lock = [System.IO.File]::Open($Path, 'Open', 'ReadWrite', 'None')
    $lock.Dispose()
  } catch {
    [Console]::Error.WriteLine("ファイルを使用中のため消せません。少し待ってからもう一度実行してください: $Path")
    exit 1
  }
  $entries.Remove($word)
  Write-Entries $Path $entries
  Write-Output "「$word」を消しました。IME は数秒のうちに読み直します。"
  return
}

$rows = foreach ($word in $entries.Keys) {
  $e = $entries[$word]
  $score = Get-Decayed $e.Score $e.Time
  if ([Math]::Abs($score) -lt $ForgetBelow) { continue }
  $need = if ($strong.ContainsKey($word)) { 3.0 } else { 2.0 }
  $state = if ($score -ge 2.0 - 0.05) { '英語として覚えた' }
           elseif ($score -le -$need + 0.05) { '日本語として覚えた' }
           else { '様子見' }
  [pscustomobject]@{
    語 = $word
    状態 = $state
    点数 = [Math]::Round($score, 2)
    最終更新 = [DateTimeOffset]::FromUnixTimeSeconds($e.Time).LocalDateTime.ToString('yyyy-MM-dd')
  }
}
if (-not $rows) {
  Write-Output '覚えた語はまだありません。'
  return
}
$rows | Sort-Object 状態, 点数 | Format-Table -AutoSize
if (-not $strongKnown) {
  Write-Output '（ブランド名など強い英語の語の一覧が見つからないため、日本語の判定は一律 -2 以下で表示しています。）'
}
Write-Output "消すには: -Remove <語>    保存先: $Path"
