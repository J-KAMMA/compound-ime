# 複合IME 新版のお知らせ（ウィンドウズ用）
# PowerShell 5.1 で動く。失敗したときは黙って終わる。
# 外部に送るのは GitHub の releases API への GET だけ。

$ErrorActionPreference = 'Stop'

$UserAgent = 'CompoundIME-update-check'
$ApiUrl    = 'https://api.github.com/repos/J-KAMMA/compound-ime/releases?per_page=5'
$ExePath   = 'C:\Program Files (x86)\CompoundIME\mozc_server.exe'
$StateDir  = Join-Path $env:USERPROFILE 'AppData\LocalLow\CompoundIME'
$StateFile = Join-Path $StateDir 'update_check.txt'
# 通知の押下で起動する PowerShell のアプリID（一般的な方法）
$ToastAppId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'

# 4つの数字の版を [version] にする。読めなければ $null。
function ConvertTo-Ver([string]$text) {
    if ([string]::IsNullOrEmpty($text)) { return $null }
    $t = ($text -replace ',', '.') -replace '\s', ''
    $m = [regex]::Match($t, '^v?(\d+)\.(\d+)\.(\d+)\.(\d+)')
    if (-not $m.Success) { return $null }
    try {
        return New-Object System.Version ([int]$m.Groups[1].Value), ([int]$m.Groups[2].Value), ([int]$m.Groups[3].Value), ([int]$m.Groups[4].Value)
    } catch { return $null }
}

function Read-State {
    $s = @{ checked = 0L; notified = '' }
    if (Test-Path -LiteralPath $StateFile) {
        foreach ($line in (Get-Content -LiteralPath $StateFile -ErrorAction Stop)) {
            if ($line -match '^checked=(\d+)\s*$') { $s.checked = [int64]$Matches[1] }
            elseif ($line -match '^notified=(\S*)\s*$') { $s.notified = $Matches[1] }
        }
    }
    return $s
}

function Write-State($checked, $notified) {
    if (-not (Test-Path -LiteralPath $StateDir)) {
        New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
    }
    $lines = @("checked=$checked", "notified=$notified")
    Set-Content -LiteralPath $StateFile -Value $lines -Encoding ASCII
}

# トーストを出す。出せたら $true。
function Show-Toast([string]$text, [string]$url) {
    try {
        [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
        [void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
        $esc = [System.Security.SecurityElement]::Escape($text)
        $escUrl = [System.Security.SecurityElement]::Escape($url)
        $xmlText = '<toast activationType="protocol" launch="' + $escUrl + '"><visual><binding template="ToastGeneric"><text>' + $esc + '</text></binding></visual></toast>'
        $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
        $xml.LoadXml($xmlText)
        $toast = New-Object Windows.UI.Notifications.ToastNotification $xml
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($ToastAppId).Show($toast)
        return $true
    } catch {
        return $false
    }
}

function Main {
    # 止める設定
    try {
        $flag = (Get-ItemProperty -Path 'HKCU:\Software\CompoundIME' -Name 'UpdateCheck' -ErrorAction Stop).UpdateCheck
        if ($null -ne $flag -and [int]$flag -eq 0) { return }
    } catch { }

    # 今入っている版
    if (-not (Test-Path -LiteralPath $ExePath)) { return }
    $installed = ConvertTo-Ver ((Get-Item -LiteralPath $ExePath).VersionInfo.FileVersion)
    if ($null -eq $installed) { return }

    # 1日1回まで
    $state = Read-State
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    if ($state.checked -gt 0 -and ($now - $state.checked) -ge 0 -and ($now - $state.checked) -lt 86400) { return }
    # 問い合わせる前に時刻を記録する（失敗しても1日は再試行しない）
    Write-State $now $state.notified

    # API（GET のみ、10秒）
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $releases = Invoke-RestMethod -Uri $ApiUrl -Method Get -UserAgent $UserAgent -TimeoutSec 10 -UseBasicParsing -Headers @{ Accept = 'application/vnd.github+json' }

    # 下書きでない中で一番新しい版（試用版も含む）
    $bestVer = $null
    $bestTag = $null
    foreach ($r in @($releases)) {
        if ($r.draft) { continue }
        $tag = [string]$r.tag_name
        $v = ConvertTo-Ver $tag
        if ($null -eq $v) { continue }
        if ($tag -notmatch '^v?[0-9]+(\.[0-9]+){3}$') { continue }  # 余計な文字のある tag は使わない
        if ($null -eq $bestVer -or $v -gt $bestVer) { $bestVer = $v; $bestTag = $tag }
    }
    if ($null -eq $bestVer) { return }

    if ($bestVer -le $installed) { return }
    # 同じ版は1回だけ
    if ($state.notified -eq $bestTag) { return }

    $url = 'https://github.com/J-KAMMA/compound-ime/releases/tag/' + $bestTag
    $msg = '複合IMEの新しい版（' + $bestVer.ToString() + '）があります。押すと配布ページを開きます。'
    if (Show-Toast $msg $url) {
        Write-State $now $bestTag
    }
}

try { Main } catch { }
exit 0
