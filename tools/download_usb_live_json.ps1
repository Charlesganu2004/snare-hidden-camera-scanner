param(
    [string]$Port,
    [string]$OutputPath = "snare_live_scan_data.json",
    [int]$BaudRate = 115200,
    [int]$TimeoutSeconds = 30
)

$scriptPath = Join-Path $PSScriptRoot "download_usb_json.ps1"
$argsList = @(
    "-OutputPath", $OutputPath,
    "-Command", "live download",
    "-BeginMarker", "BEGIN-LIVE-DOWNLOAD",
    "-EndMarker", "END-LIVE-DOWNLOAD",
    "-BaudRate", $BaudRate,
    "-TimeoutSeconds", $TimeoutSeconds
)

if ($Port) {
    $argsList = @("-Port", $Port) + $argsList
}

& $scriptPath @argsList
