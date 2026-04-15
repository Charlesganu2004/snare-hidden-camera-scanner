param(
    [string]$Port,
    [string]$OutputPath = "snare_scan_data.json",
    [string]$Command = "import",
    [string]$BeginMarker = "BEGIN-DOWNLOAD",
    [string]$EndMarker = "END-DOWNLOAD",
    [int]$BaudRate = 115200,
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"

if (-not $Port) {
    $ports = [System.IO.Ports.SerialPort]::GetPortNames()
    if ($ports.Count -eq 1) {
        $Port = $ports[0]
    } else {
        Write-Host "Available serial ports:"
        $ports | ForEach-Object { Write-Host "  $_" }
        throw "Pass the Pico serial port with -Port, for example: .\tools\download_usb_json.ps1 -Port COM5"
    }
}

$serial = [System.IO.Ports.SerialPort]::new($Port, $BaudRate)
$serial.NewLine = "`n"
$serial.ReadTimeout = 1000
$serial.WriteTimeout = 1000

$jsonLines = New-Object System.Collections.Generic.List[string]
$capturing = $false
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)

try {
    $serial.Open()
    Start-Sleep -Milliseconds 800
    $serial.DiscardInBuffer()
    $serial.WriteLine($Command)

    while ((Get-Date) -lt $deadline) {
        try {
            $line = $serial.ReadLine().TrimEnd("`r", "`n")
        } catch [TimeoutException] {
            continue
        }

        if ($line -like "*$BeginMarker*") {
            $capturing = $true
            continue
        }

        if ($line -like "*$EndMarker*") {
            break
        }

        if ($capturing) {
            $jsonLines.Add($line)
        }
    }
} finally {
    if ($serial.IsOpen) {
        $serial.Close()
    }
}

if ($jsonLines.Count -eq 0) {
    throw "No JSON data was received from the Pico. Confirm the SNARE code is running and the correct COM port is selected."
}

$jsonText = ($jsonLines -join "`n").Trim()
$null = $jsonText | ConvertFrom-Json

$resolvedOutput = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)
$outputDirectory = Split-Path -Parent $resolvedOutput
if ($outputDirectory -and -not (Test-Path -LiteralPath $outputDirectory)) {
    New-Item -ItemType Directory -Path $outputDirectory | Out-Null
}

Set-Content -LiteralPath $resolvedOutput -Value $jsonText -Encoding UTF8
Write-Host "Saved SNARE scan data JSON to $resolvedOutput"
