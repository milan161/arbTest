param(
    [string]$WorkbookPath = "D:\Study\codexTest\CodexLOFarb\data\analysis_outputs_20260329\LOF Fund basic data.xlsx",
    [string]$FuturesPath = "D:\Study\codexTest\CodexLOFarb\data\analysis_outputs_20260329\futures_history.csv",
    [string]$HistoryDir = "D:\Study\codexTest\CodexLOFarb\data",
    [string]$OutputDir = "D:\Study\codexTest\CodexLOFarb\data\analysis_outputs_20260329"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-ZipXml {
    param(
        [Parameter(Mandatory = $true)]$ZipArchive,
        [Parameter(Mandatory = $true)][string]$EntryName
    )

    $entry = $ZipArchive.GetEntry($EntryName)
    if (-not $entry) {
        throw "Zip entry not found: $EntryName"
    }

    $reader = [System.IO.StreamReader]::new($entry.Open())
    try {
        return [xml]$reader.ReadToEnd()
    }
    finally {
        $reader.Close()
    }
}

function Get-ExcelColumnIndex {
    param([Parameter(Mandatory = $true)][string]$CellRef)

    $letters = ($CellRef -replace '\d', '').ToUpperInvariant()
    $index = 0
    foreach ($char in $letters.ToCharArray()) {
        $index = ($index * 26) + ([int][char]$char - [int][char]'A' + 1)
    }
    return $index
}

function Get-CellValue {
    param(
        [Parameter(Mandatory = $true)]$Cell,
        [Parameter(Mandatory = $true)][string[]]$SharedStrings
    )

    if ($null -eq $Cell) {
        return $null
    }

    $typeProp = $Cell.PSObject.Properties["t"]
    $type = if ($typeProp) { [string]$typeProp.Value } else { "" }
    $valueProp = $Cell.PSObject.Properties["v"]
    $valueNode = if ($valueProp) { $valueProp.Value } else { $null }
    if ($null -eq $valueNode) {
        return $null
    }

    $rawValue = [string]$valueNode
    if ([string]::IsNullOrWhiteSpace($rawValue)) {
        return $null
    }

    if ($type -eq "s") {
        return $SharedStrings[[int]$rawValue]
    }

    return $rawValue
}

function Convert-ExcelDate {
    param($Value)

    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) {
        return $null
    }

    $text = [string]$Value
    $number = 0.0
    if ([double]::TryParse($text, [ref]$number)) {
        return [datetime]::FromOADate($number).ToString("yyyy-MM-dd")
    }

    return ([datetime]$text).ToString("yyyy-MM-dd")
}

function Convert-ToDoubleOrNull {
    param($Value)

    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) {
        return $null
    }

    $number = 0.0
    if ([double]::TryParse([string]$Value, [ref]$number)) {
        return $number
    }

    return $null
}

function Format-PercentOrNull {
    param($Value)

    if ($null -eq $Value) {
        return $null
    }

    return ("{0:P2}" -f [double]$Value)
}

function Get-XlsxTables {
    param([Parameter(Mandatory = $true)][string]$Path)

    $zip = [System.IO.Compression.ZipFile]::OpenRead($Path)
    try {
        $sharedStrings = @()
        $sharedEntry = $zip.GetEntry("xl/sharedStrings.xml")
        if ($sharedEntry) {
            $sharedXml = Get-ZipXml -ZipArchive $zip -EntryName "xl/sharedStrings.xml"
            foreach ($si in $sharedXml.sst.si) {
                $plainTextProp = $si.PSObject.Properties["t"]
                $richTextProp = $si.PSObject.Properties["r"]
                if ($plainTextProp) {
                    $sharedStrings += [string]$plainTextProp.Value
                }
                elseif ($richTextProp) {
                    $sharedStrings += (($richTextProp.Value | ForEach-Object {
                        $rtTextProp = $_.PSObject.Properties["t"]
                        if ($rtTextProp) { [string]$rtTextProp.Value } else { "" }
                    }) -join '')
                }
                else {
                    $sharedStrings += ""
                }
            }
        }

        $workbookXml = Get-ZipXml -ZipArchive $zip -EntryName "xl/workbook.xml"
        $relsXml = Get-ZipXml -ZipArchive $zip -EntryName "xl/_rels/workbook.xml.rels"
        $namespaceManager = [System.Xml.XmlNamespaceManager]::new($workbookXml.NameTable)
        $namespaceManager.AddNamespace("d", "http://schemas.openxmlformats.org/spreadsheetml/2006/main")

        $relMap = @{}
        foreach ($rel in $relsXml.Relationships.Relationship) {
            $relMap[[string]$rel.Id] = [string]$rel.Target
        }

        $result = @{}
        foreach ($sheet in $workbookXml.SelectNodes("//d:sheets/d:sheet", $namespaceManager)) {
            $rid = $sheet.GetAttribute("id", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")
            $target = "xl/" + $relMap[$rid]
            $sheetXml = Get-ZipXml -ZipArchive $zip -EntryName $target
            $rows = @($sheetXml.worksheet.sheetData.row)

            if ($rows.Count -eq 0) {
                $result[[string]$sheet.name] = [pscustomobject]@{
                    Headers = @()
                    Rows    = @()
                }
                continue
            }

            $headerMap = @{}
            foreach ($cell in $rows[0].c) {
                $colIndex = Get-ExcelColumnIndex -CellRef ([string]$cell.r)
                $headerMap[$colIndex] = [string](Get-CellValue -Cell $cell -SharedStrings $sharedStrings)
            }

            $headerIndexes = @($headerMap.Keys | Sort-Object)
            $headers = @($headerIndexes | ForEach-Object { $headerMap[$_] })
            $dataRows = @()

            foreach ($row in $rows | Select-Object -Skip 1) {
                $cellMap = @{}
                foreach ($cell in $row.c) {
                    $colIndex = Get-ExcelColumnIndex -CellRef ([string]$cell.r)
                    $cellMap[$colIndex] = Get-CellValue -Cell $cell -SharedStrings $sharedStrings
                }

                $values = @()
                foreach ($colIndex in $headerIndexes) {
                    if ($cellMap.ContainsKey($colIndex)) {
                        $values += $cellMap[$colIndex]
                    }
                    else {
                        $values += $null
                    }
                }

                $dataRows += ,$values
            }

            $result[[string]$sheet.name] = [pscustomobject]@{
                Headers = $headers
                Rows    = $dataRows
            }
        }

        return $result
    }
    finally {
        $zip.Dispose()
    }
}

function Find-BaseRow {
    param(
        [Parameter(Mandatory = $true)][object[]]$Rows,
        [Parameter(Mandatory = $true)][int]$CurrentIndex,
        [Parameter(Mandatory = $true)][hashtable]$RmbMap,
        [Parameter(Mandatory = $true)][hashtable]$FuturesMap,
        [Parameter(Mandatory = $true)][string]$FutureColumn
    )

    for ($k = $CurrentIndex + 1; $k -lt $Rows.Count; $k++) {
        $candidate = $Rows[$k]
        $date = [string]$candidate.date
        $nav = Convert-ToDoubleOrNull $candidate.nav
        if ($null -eq $nav) {
            continue
        }

        if (-not $RmbMap.ContainsKey($date) -or -not $FuturesMap.ContainsKey($date)) {
            continue
        }

        $futurePrice = Convert-ToDoubleOrNull $FuturesMap[$date].$FutureColumn
        $rmbRate = Convert-ToDoubleOrNull $RmbMap[$date]
        if ($null -eq $futurePrice -or $futurePrice -le 0 -or $null -eq $rmbRate -or $rmbRate -le 0) {
            continue
        }

        return $candidate
    }

    return $null
}

if (-not (Test-Path $WorkbookPath)) {
    throw "Workbook not found: $WorkbookPath"
}

if (-not (Test-Path $FuturesPath)) {
    throw "Futures file not found: $FuturesPath"
}

$tables = Get-XlsxTables -Path $WorkbookPath
$sheetNames = @($tables.Keys)
$gldCalibrationSheet = @($sheetNames | Where-Object { $_ -like "*GLD*" })[0]
$usoCalibrationSheet = @($sheetNames | Where-Object { $_ -like "*USO*" })[0]

$futuresRows = @(Import-Csv -Path $FuturesPath)
$futuresMap = @{}
foreach ($row in $futuresRows) {
    $futuresMap[[string]$row.date] = $row
}

$rmbMap = @{}
foreach ($rowValues in $tables["RMB"].Rows) {
    $date = Convert-ExcelDate $rowValues[0]
    $usdTimes100 = Convert-ToDoubleOrNull $rowValues[1]
    if ($date -and $null -ne $usdTimes100) {
        $rmbMap[$date] = [math]::Round($usdTimes100 / 100.0, 4)
    }
}

$rmbOverrides = @{
    "2026-03-26" = 6.9056
    "2026-03-27" = 6.9141
}
foreach ($key in $rmbOverrides.Keys) {
    $rmbMap[$key] = $rmbOverrides[$key]
}

$calibrationMaps = @{
    "GC" = @{}
    "CL" = @{}
}

foreach ($rowValues in $tables[$gldCalibrationSheet].Rows) {
    $date = Convert-ExcelDate $rowValues[0]
    if (-not $date) { continue }
    $calibrationMaps["GC"][$date] = [pscustomobject]@{
        value = Convert-ToDoubleOrNull $rowValues[1]
        count = Convert-ToDoubleOrNull $rowValues[3]
    }
}

foreach ($rowValues in $tables[$usoCalibrationSheet].Rows) {
    $date = Convert-ExcelDate $rowValues[0]
    if (-not $date) { continue }
    $calibrationMaps["CL"][$date] = [pscustomobject]@{
        value = Convert-ToDoubleOrNull $rowValues[1]
        count = Convert-ToDoubleOrNull $rowValues[3]
    }
}

$calibrationOverrides = @{
    "GC" = @{
        "2025-06-10" = [pscustomobject]@{ value = 10.9206; count = 140 }
        "2025-06-09" = [pscustomobject]@{ value = 10.9224; count = 150 }
        "2025-06-06" = [pscustomobject]@{ value = 10.9227; count = 176 }
        "2025-06-05" = [pscustomobject]@{ value = 10.9276; count = 244 }
        "2025-06-04" = [pscustomobject]@{ value = 10.9328; count = 191 }
        "2025-06-03" = [pscustomobject]@{ value = 10.9254; count = 408 }
    }
    "CL" = @{
        "2025-06-10" = [pscustomobject]@{ value = 0.8912; count = 156 }
        "2025-06-09" = [pscustomobject]@{ value = 0.9059; count = 205 }
        "2025-06-06" = [pscustomobject]@{ value = 0.9063; count = 223 }
        "2025-06-05" = [pscustomobject]@{ value = 0.9063; count = 270 }
        "2025-06-04" = [pscustomobject]@{ value = 0.9057; count = 341 }
        "2025-06-03" = [pscustomobject]@{ value = 0.9064; count = 580 }
    }
}
foreach ($futureCode in $calibrationOverrides.Keys) {
    foreach ($key in $calibrationOverrides[$futureCode].Keys) {
        $calibrationMaps[$futureCode][$key] = $calibrationOverrides[$futureCode][$key]
    }
}

$fundFutureMap = @{
    "160719" = "GC"
    "161116" = "GC"
    "164701" = "GC"
    "165513" = "GC"
    "160723" = "CL"
    "161129" = "CL"
    "501018" = "CL"
}

$manualNeedRows = @()
$backtestSummaryRows = @()

foreach ($fundCode in ($fundFutureMap.Keys | Sort-Object)) {
    if (-not $tables.ContainsKey($fundCode)) {
        continue
    }

    $futureCode = $fundFutureMap[$fundCode]
    $futureColumn = "${futureCode}_close"
    $historyPath = Join-Path $HistoryDir ("LOF_{0}_history.csv" -f $fundCode)
    $historyMap = @{}
    if (Test-Path $historyPath) {
        foreach ($historyRow in (Import-Csv -Path $historyPath)) {
            $props = @($historyRow.PSObject.Properties.Name)
            $dateValue = [string]$historyRow.($props[0])
            $positionValue = if ($props.Count -gt 2) { $historyRow.($props[2]) } else { $null }
            $betaKey = @($props | Where-Object { $_ -like "*Beta*" })[0]
            $betaValue = if ($betaKey) { $historyRow.$betaKey } else { $null }

            $historyMap[$dateValue] = [pscustomobject]@{
                position = Convert-ToDoubleOrNull $positionValue
                beta     = Convert-ToDoubleOrNull $betaValue
            }
        }
    }

    $fundRows = @()
    foreach ($rowValues in $tables[$fundCode].Rows) {
        $date = Convert-ExcelDate $rowValues[0]
        if (-not $date) {
            continue
        }

        $fundRows += [pscustomobject]@{
            date          = $date
            price         = Convert-ToDoubleOrNull $rowValues[1]
            nav           = Convert-ToDoubleOrNull $rowValues[2]
            premium       = Convert-ToDoubleOrNull $rowValues[3]
            official      = Convert-ToDoubleOrNull $rowValues[4]
            officialError = Convert-ToDoubleOrNull $rowValues[6]
        }
    }

    $fundRows = @($fundRows | Sort-Object date -Descending)
    $alignedRows = @()

    for ($i = 0; $i -lt $fundRows.Count; $i++) {
        $row = $fundRows[$i]
        $date = [string]$row.date
        $rmbRate = if ($rmbMap.ContainsKey($date)) { $rmbMap[$date] } else { $null }
        $futurePrice = if ($futuresMap.ContainsKey($date)) { Convert-ToDoubleOrNull $futuresMap[$date].$futureColumn } else { $null }
        $calibration = if ($calibrationMaps[$futureCode].ContainsKey($date)) { $calibrationMaps[$futureCode][$date] } else { $null }
        $history = if ($historyMap.ContainsKey($date)) { $historyMap[$date] } else { $null }
        $position = if ($null -ne $history) { $history.position } else { $null }
        $beta = if ($null -ne $history -and $null -ne $history.beta) { $history.beta } else { 1.0 }

        $calibrationValue = if ($null -ne $calibration) { $calibration.value } else { $null }
        $calibrationCount = if ($null -ne $calibration) { $calibration.count } else { $null }
        $calibratedEtf = $null
        if ($null -ne $futurePrice -and $futurePrice -gt 0 -and $null -ne $calibrationValue -and $calibrationValue -gt 0) {
            $calibratedEtf = [math]::Round($futurePrice / $calibrationValue, 4)
        }

        $baseDate = $null
        $directValue = $null
        $directError = $null
        $directPremium = $null

        $baseRow = Find-BaseRow -Rows $fundRows -CurrentIndex $i -RmbMap $rmbMap -FuturesMap $futuresMap -FutureColumn $futureColumn
        if ($null -ne $baseRow -and $null -ne $futurePrice -and $futurePrice -gt 0 -and $null -ne $rmbRate -and $rmbRate -gt 0 -and $null -ne $position) {
            $baseDate = [string]$baseRow.date
            $baseNav = Convert-ToDoubleOrNull $baseRow.nav
            $baseFuturePrice = Convert-ToDoubleOrNull $futuresMap[$baseDate].$futureColumn
            $baseRmbRate = Convert-ToDoubleOrNull $rmbMap[$baseDate]

            if ($null -ne $baseNav -and $baseNav -gt 0 -and $null -ne $baseFuturePrice -and $baseFuturePrice -gt 0 -and $null -ne $baseRmbRate -and $baseRmbRate -gt 0) {
                $positionFloat = if ($position -gt 10) { $position / 100.0 } else { $position }
                $futureChange = $futurePrice / $baseFuturePrice
                $exchangeChange = $rmbRate / $baseRmbRate
                $changeRatio = $positionFloat * $beta * ($futureChange * $exchangeChange - 1)
                $directValue = [math]::Round($baseNav * (1 + $changeRatio), 4)

                if ($null -ne $row.nav -and $row.nav -gt 0) {
                    $directError = ($directValue - $row.nav) / $row.nav
                }
                if ($null -ne $row.price -and $row.price -gt 0 -and $directValue -gt 0) {
                    $directPremium = ($row.price - $directValue) / $directValue
                }
            }
        }

        $alignedRows += [pscustomobject]@{
            date                     = $date
            price                    = if ($null -ne $row.price) { [math]::Round($row.price, 4) } else { $null }
            nav                      = if ($null -ne $row.nav) { [math]::Round($row.nav, 4) } else { $null }
            premium_pct              = Format-PercentOrNull $row.premium
            official_est             = if ($null -ne $row.official) { [math]::Round($row.official, 4) } else { $null }
            official_est_error_pct   = Format-PercentOrNull $row.officialError
            rmb_mid                  = if ($null -ne $rmbRate) { [math]::Round($rmbRate, 4) } else { $null }
            future_code              = $futureCode
            future_close             = $futurePrice
            calibration_value        = $calibrationValue
            calibration_count        = $calibrationCount
            calibrated_etf           = $calibratedEtf
            position_pct             = $position
            future_beta              = $beta
            direct_base_date         = $baseDate
            direct_future_est        = $directValue
            direct_future_error_pct  = Format-PercentOrNull $directError
            direct_future_premium_pct = Format-PercentOrNull $directPremium
        }
    }

    $alignedPath = Join-Path $OutputDir ("aligned_backtest_{0}.csv" -f $fundCode)
    $alignedRows | Export-Csv -Path $alignedPath -NoTypeInformation -Encoding UTF8

    $analysisCorePath = Join-Path $OutputDir ("analysis_core_{0}.csv" -f $fundCode)
    if (Test-Path $analysisCorePath) {
        $existingRows = @(Import-Csv -Path $analysisCorePath)
        $existingHeaders = if ($existingRows.Count -gt 0) { @($existingRows[0].PSObject.Properties.Name) } else { @() }
        if ($existingHeaders.Count -eq 6) {
            $alignedMap = @{}
            foreach ($alignedRow in $alignedRows) {
                $alignedMap[[string]$alignedRow.date] = $alignedRow
            }

            $updatedRows = foreach ($existingRow in $existingRows) {
                $date = [string]$existingRow.($existingHeaders[0])
                if ($alignedMap.ContainsKey($date)) {
                    $alignedRow = $alignedMap[$date]
                    $obj = [ordered]@{}
                    $obj[$existingHeaders[0]] = $date
                    $obj[$existingHeaders[1]] = $alignedRow.nav
                    $obj[$existingHeaders[2]] = $alignedRow.direct_future_est
                    $obj[$existingHeaders[3]] = $alignedRow.direct_future_error_pct
                    $obj[$existingHeaders[4]] = $alignedRow.official_est
                    $obj[$existingHeaders[5]] = $alignedRow.official_est_error_pct
                    [pscustomobject]$obj
                }
                else {
                    $obj = [ordered]@{}
                    foreach ($header in $existingHeaders) {
                        $obj[$header] = $existingRow.$header
                    }
                    [pscustomobject]$obj
                }
            }

            $updatedRows = @($updatedRows | Sort-Object $existingHeaders[0] -Descending)
            $updatedRows | Export-Csv -Path $analysisCorePath -NoTypeInformation -Encoding UTF8
        }
    }

    $missingNavDates = @($alignedRows | Where-Object { [string]::IsNullOrWhiteSpace([string]$_.nav) } | Select-Object -ExpandProperty date)
    $missingDirectDates = @($alignedRows | Where-Object { [string]::IsNullOrWhiteSpace([string]$_.direct_future_est) } | Select-Object -ExpandProperty date)

    if ($missingNavDates.Count -gt 0) {
        $manualNeedRows += [pscustomobject]@{
            fund_code = $fundCode
            field     = "nav"
            dates     = ($missingNavDates -join ", ")
        }
    }

    $backtestSummaryRows += [pscustomobject]@{
        fund_code                = $fundCode
        start_date               = ($alignedRows | Sort-Object date | Select-Object -First 1 -ExpandProperty date)
        end_date                 = ($alignedRows | Sort-Object date | Select-Object -Last 1 -ExpandProperty date)
        row_count                = $alignedRows.Count
        missing_nav_days         = $missingNavDates.Count
        missing_official_est_days = ($alignedRows | Where-Object { [string]::IsNullOrWhiteSpace([string]$_.official_est) }).Count
        missing_direct_est_days  = $missingDirectDates.Count
    }
}

$manualNeedPath = Join-Path $OutputDir "manual_inputs_needed.csv"
$summaryPath = Join-Path $OutputDir "aligned_backtest_summary.csv"

$manualNeedRows | Export-Csv -Path $manualNeedPath -NoTypeInformation -Encoding UTF8
$backtestSummaryRows | Export-Csv -Path $summaryPath -NoTypeInformation -Encoding UTF8

Write-Output "Generated aligned backtest files in $OutputDir"
Write-Output "Manual input summary: $manualNeedPath"
Write-Output "Backtest summary: $summaryPath"
