param(
    [string]$WorkbookPath = "D:\Study\codexTest\CodexLOFarb\data\analysis_outputs_20260329\LOF Fund basic data.xlsx",
    [string]$EtfDataPath = "D:\Study\codexTest\CodexLOFarb\data\GLD_USO_basic_data.csv",
    [string]$FuturesPath = "D:\Study\codexTest\CodexLOFarb\data\analysis_outputs_20260329\futures_history.csv",
    [string]$HistoryDir = "D:\Study\codexTest\CodexLOFarb\data",
    [string]$OutputDir = "D:\Study\codexTest\CodexLOFarb\data\analysis_outputs_20260329"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-ZipXml {
    param($ZipArchive, [string]$EntryName)
    $entry = $ZipArchive.GetEntry($EntryName)
    if (-not $entry) { throw "Zip entry not found: $EntryName" }
    $reader = [System.IO.StreamReader]::new($entry.Open())
    try { return [xml]$reader.ReadToEnd() } finally { $reader.Close() }
}

function Get-ExcelColumnIndex {
    param([string]$CellRef)
    $letters = ($CellRef -replace '\d', '').ToUpperInvariant()
    $index = 0
    foreach ($char in $letters.ToCharArray()) {
        $index = ($index * 26) + ([int][char]$char - [int][char]'A' + 1)
    }
    return $index
}

function Get-CellValue {
    param($Cell, [string[]]$SharedStrings)
    $typeProp = $Cell.PSObject.Properties["t"]
    $type = if ($typeProp) { [string]$typeProp.Value } else { "" }
    $valueProp = $Cell.PSObject.Properties["v"]
    $valueNode = if ($valueProp) { $valueProp.Value } else { $null }
    if ($null -eq $valueNode) { return $null }
    $rawValue = [string]$valueNode
    if ([string]::IsNullOrWhiteSpace($rawValue)) { return $null }
    if ($type -eq "s") { return $SharedStrings[[int]$rawValue] }
    return $rawValue
}

function Convert-ExcelDate {
    param($Value)
    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) { return $null }
    $text = [string]$Value
    $number = 0.0
    if ([double]::TryParse($text, [ref]$number)) {
        return [datetime]::FromOADate($number).ToString("yyyy-MM-dd")
    }
    return ([datetime]$text).ToString("yyyy-MM-dd")
}

function Convert-ToDoubleOrNull {
    param($Value)
    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) { return $null }
    $number = 0.0
    if ([double]::TryParse([string]$Value, [ref]$number)) { return $number }
    return $null
}

function Format-PercentOrNull {
    param($Value)
    if ($null -eq $Value) { return $null }
    return ("{0:P2}" -f [double]$Value)
}

function Get-Median {
    param([double[]]$Values)
    if (-not $Values -or $Values.Count -eq 0) { return $null }
    $sorted = @($Values | Sort-Object)
    $count = $sorted.Count
    if ($count % 2 -eq 1) { return $sorted[[int]($count / 2)] }
    return ($sorted[($count / 2) - 1] + $sorted[$count / 2]) / 2.0
}

function Get-XlsxTables {
    param([string]$Path)
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
                        $textProp = $_.PSObject.Properties["t"]
                        if ($textProp) { [string]$textProp.Value } else { "" }
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
                $result[[string]$sheet.name] = [pscustomobject]@{ Headers = @(); Rows = @() }
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
                    if ($cellMap.ContainsKey($colIndex)) { $values += $cellMap[$colIndex] } else { $values += $null }
                }
                $dataRows += ,$values
            }

            $result[[string]$sheet.name] = [pscustomobject]@{ Headers = $headers; Rows = $dataRows }
        }
        return $result
    }
    finally {
        $zip.Dispose()
    }
}

function Get-PositionMap {
    param(
        [object]$Table,
        [string[]]$TargetDates
    )

    $known = @{}
    foreach ($rowValues in $Table.Rows) {
        $date = Convert-ExcelDate $rowValues[0]
        $position = Convert-ToDoubleOrNull $rowValues[5]
        if ($date -and $null -ne $position) {
            $known[$date] = $position
        }
    }

    $firstKnownPosition = $null
    if ($known.Count -gt 0) {
        $firstKnownDate = @($known.Keys | Sort-Object)[0]
        $firstKnownPosition = $known[$firstKnownDate]
    }

    $map = @{}
    $currentPosition = $null
    foreach ($date in ($TargetDates | Sort-Object)) {
        if ($known.ContainsKey($date)) {
            $currentPosition = $known[$date]
        }
        elseif ($null -eq $currentPosition) {
            $currentPosition = $firstKnownPosition
        }
        $map[$date] = $currentPosition
    }

    return $map
}

function Find-BaseDateForMethod {
    param(
        [object[]]$Rows,
        [int]$CurrentIndex,
        [scriptblock]$CanUseDate
    )

    for ($k = $CurrentIndex + 1; $k -lt $Rows.Count; $k++) {
        $candidate = $Rows[$k]
        if (& $CanUseDate $candidate.date $candidate.nav) {
            return [string]$candidate.date
        }
    }
    return $null
}

if (-not (Test-Path $WorkbookPath)) { throw "Workbook not found: $WorkbookPath" }
if (-not (Test-Path $EtfDataPath)) { throw "ETF data not found: $EtfDataPath" }
if (-not (Test-Path $FuturesPath)) { throw "Futures data not found: $FuturesPath" }

$tables = Get-XlsxTables -Path $WorkbookPath
$fundCodes = @("160719","160723","161116","161129","164701","165513","501018")
$portfolioConfig = @{
    "160719" = [pscustomobject]@{
        beta = 1.0
        assets = @(
            [pscustomobject]@{ symbol = "GLD"; weight = 0.5672 },
            [pscustomobject]@{ symbol = "^GLD-EU"; weight = 0.4328 }
        )
    }
    "160723" = [pscustomobject]@{
        beta = 0.85
        assets = @(
            [pscustomobject]@{ symbol = "^USO-EU"; weight = 0.3435 },
            [pscustomobject]@{ symbol = "USO"; weight = 0.3424 },
            [pscustomobject]@{ symbol = "^USO-JP"; weight = 0.3141 }
        )
    }
    "161116" = [pscustomobject]@{
        beta = 1.0
        assets = @(
            [pscustomobject]@{ symbol = "GLD"; weight = 0.8725 },
            [pscustomobject]@{ symbol = "^GLD-EU"; weight = 0.1275 }
        )
    }
    "161129" = [pscustomobject]@{
        beta = 0.85
        assets = @(
            [pscustomobject]@{ symbol = "^USO-EU"; weight = 0.3974 },
            [pscustomobject]@{ symbol = "^USO-JP"; weight = 0.3516 },
            [pscustomobject]@{ symbol = "USO"; weight = 0.1894 },
            [pscustomobject]@{ symbol = "^USO-HK"; weight = 0.0617 }
        )
    }
    "164701" = [pscustomobject]@{
        beta = 1.0
        assets = @(
            [pscustomobject]@{ symbol = "GLD"; weight = 0.9869 },
            [pscustomobject]@{ symbol = "SLV"; weight = 0.0131 }
        )
    }
    "165513" = [pscustomobject]@{
        beta = 1.0
        assets = @(
            [pscustomobject]@{ symbol = "GLD"; weight = 0.8622 },
            [pscustomobject]@{ symbol = "^GLD-EU"; weight = 0.1076 },
            [pscustomobject]@{ symbol = "^GLD-JP"; weight = 0.0302 }
        )
    }
    "501018" = [pscustomobject]@{
        beta = 0.85
        assets = @(
            [pscustomobject]@{ symbol = "^USO-EU"; weight = 0.4725 },
            [pscustomobject]@{ symbol = "USO"; weight = 0.2899 },
            [pscustomobject]@{ symbol = "^USO-JP"; weight = 0.2376 }
        )
    }
}

$etfRows = @(Import-Csv -Path $EtfDataPath)
$etfHeaders = @($etfRows[0].PSObject.Properties.Name)
$etfDateHeader = $etfHeaders[0]
$etfRmbHeader = $etfHeaders[1]
$etfMap = @{}
foreach ($row in $etfRows) {
    $etfMap[[string]$row.$etfDateHeader] = $row
}

$futuresRows = @(Import-Csv -Path $FuturesPath)
$futuresMap = @{}
foreach ($row in $futuresRows) {
    $futuresMap[[string]$row.date] = $row
}

$rmbOverrides = @{
    "2026-03-26" = 6.9056
    "2026-03-27" = 6.9141
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

$sheetNames = @($tables.Keys)
$gldCalibrationSheet = @($sheetNames | Where-Object { $_ -like "*GLD*" })[0]
$usoCalibrationSheet = @($sheetNames | Where-Object { $_ -like "*USO*" })[0]

$calibrationMaps = @{ "GC" = @{}; "CL" = @{} }
foreach ($rowValues in $tables[$gldCalibrationSheet].Rows) {
    $date = Convert-ExcelDate $rowValues[0]
    if ($date) {
        $calibrationMaps["GC"][$date] = [pscustomobject]@{
            value = Convert-ToDoubleOrNull $rowValues[1]
            count = Convert-ToDoubleOrNull $rowValues[3]
        }
    }
}
foreach ($rowValues in $tables[$usoCalibrationSheet].Rows) {
    $date = Convert-ExcelDate $rowValues[0]
    if ($date) {
        $calibrationMaps["CL"][$date] = [pscustomobject]@{
            value = Convert-ToDoubleOrNull $rowValues[1]
            count = Convert-ToDoubleOrNull $rowValues[3]
        }
    }
}
foreach ($futureCode in $calibrationOverrides.Keys) {
    foreach ($date in $calibrationOverrides[$futureCode].Keys) {
        $calibrationMaps[$futureCode][$date] = $calibrationOverrides[$futureCode][$date]
    }
}

$detailRowsAll = @()
$summaryRows = @()

foreach ($fundCode in $fundCodes) {
    $fundTable = $tables[$fundCode]
    $positionSheet = @($sheetNames | Where-Object { $_ -like "*$fundCode*" -and $_ -ne $fundCode })[0]
    $futureCode = if ($fundCode -in @("160719","161116","164701","165513")) { "GC" } else { "CL" }
    $replacementSymbol = if ($futureCode -eq "GC") { "GLD" } else { "USO" }
    $futureColumn = "${futureCode}_close"

    $portfolio = $portfolioConfig[$fundCode].assets
    $beta = $portfolioConfig[$fundCode].beta

    $fundRows = @()
    foreach ($rowValues in $fundTable.Rows) {
        $date = Convert-ExcelDate $rowValues[0]
        if (-not $date) { continue }
        $fundRows += [pscustomobject]@{
            date          = $date
            price         = Convert-ToDoubleOrNull $rowValues[1]
            nav           = Convert-ToDoubleOrNull $rowValues[2]
            premium       = Convert-ToDoubleOrNull $rowValues[3]
            official_est  = Convert-ToDoubleOrNull $rowValues[4]
            official_err  = Convert-ToDoubleOrNull $rowValues[6]
        }
    }
    $fundRows = @($fundRows | Sort-Object date -Descending)
    $targetDates = @($fundRows | Select-Object -ExpandProperty date)
    $positionMap = Get-PositionMap -Table $tables[$positionSheet] -TargetDates $targetDates

    $detailRows = @()
    for ($i = 0; $i -lt $fundRows.Count; $i++) {
        $row = $fundRows[$i]
        $date = [string]$row.date
        $navAsOfDate = if ($i + 1 -lt $fundRows.Count) { [string]$fundRows[$i + 1].date } else { $null }
        $etfData = if ($etfMap.ContainsKey($date)) { $etfMap[$date] } else { $null }
        $futureData = if ($futuresMap.ContainsKey($date)) { $futuresMap[$date] } else { $null }
        $futureClose = if ($futureData) { Convert-ToDoubleOrNull $futureData.$futureColumn } else { $null }
        $rmbMid = $null
        if ($rmbOverrides.ContainsKey($date)) { $rmbMid = $rmbOverrides[$date] }
        elseif ($etfData) { $rmbMid = Convert-ToDoubleOrNull $etfData.$etfRmbHeader }
        $position = if ($positionMap.ContainsKey($date)) { $positionMap[$date] } else { $null }
        $calibration = if ($calibrationMaps[$futureCode].ContainsKey($date)) { $calibrationMaps[$futureCode][$date] } else { $null }
        $calibrationValue = if ($calibration) { $calibration.value } else { $null }
        $calibrationCount = if ($calibration) { $calibration.count } else { $null }
        $calibratedEtf = $null
        if ($null -ne $futureClose -and $futureClose -gt 0 -and $null -ne $calibrationValue -and $calibrationValue -gt 0) {
            $calibratedEtf = $futureClose / $calibrationValue
        }

        $actualPremium = $null
        if ($null -ne $row.price -and $row.price -gt 0 -and $null -ne $row.nav -and $row.nav -gt 0) {
            $actualPremium = ($row.price - $row.nav) / $row.nav
        }

        $calibratedBaseDate = Find-BaseDateForMethod -Rows $fundRows -CurrentIndex $i -CanUseDate {
            param($candidateDate, $candidateNav)
            if ($null -eq $candidateNav -or $candidateNav -le 0) { return $false }
            if (-not $positionMap.ContainsKey($date) -or $null -eq $positionMap[$date]) { return $false }
            $candidateEtf = if ($etfMap.ContainsKey($candidateDate)) { $etfMap[$candidateDate] } else { $null }
            $candidateRmb = if ($rmbOverrides.ContainsKey($candidateDate)) { $rmbOverrides[$candidateDate] } elseif ($candidateEtf) { Convert-ToDoubleOrNull $candidateEtf.$etfRmbHeader } else { $null }
            if ($null -eq $candidateEtf -or $null -eq $candidateRmb -or $candidateRmb -le 0) { return $false }
            foreach ($asset in $portfolio) {
                $basePrice = Convert-ToDoubleOrNull $candidateEtf.($asset.symbol)
                if ($null -eq $basePrice -or $basePrice -le 0) { return $false }
            }
            return $true
        }

        $calibratedEst = $null
        $calibratedError = $null
        $calibratedPremium = $null
        if ($calibratedBaseDate -and $null -ne $position -and $null -ne $rmbMid -and $rmbMid -gt 0 -and $null -ne $etfData) {
            $baseEtfData = $etfMap[$calibratedBaseDate]
            $baseNav = ($fundRows | Where-Object { $_.date -eq $calibratedBaseDate } | Select-Object -First 1).nav
            $baseRmb = if ($rmbOverrides.ContainsKey($calibratedBaseDate)) { $rmbOverrides[$calibratedBaseDate] } else { Convert-ToDoubleOrNull $baseEtfData.$etfRmbHeader }

            if ($null -ne $baseNav -and $baseNav -gt 0 -and $null -ne $baseRmb -and $baseRmb -gt 0) {
                $priceFactor = 0.0
                $canCalc = $true
                foreach ($asset in $portfolio) {
                    $basePrice = Convert-ToDoubleOrNull $baseEtfData.($asset.symbol)
                    $currentPrice = $null
                    if ($asset.symbol -eq $replacementSymbol) {
                        $currentPrice = $calibratedEtf
                    }
                    else {
                        $currentPrice = Convert-ToDoubleOrNull $etfData.($asset.symbol)
                    }
                    if ($null -eq $basePrice -or $basePrice -le 0 -or $null -eq $currentPrice -or $currentPrice -le 0) {
                        $canCalc = $false
                        break
                    }
                    $priceFactor += ($currentPrice / $basePrice) * $asset.weight
                }

                if ($canCalc) {
                    $changeRatio = $position * ($priceFactor * ($rmbMid / $baseRmb) - 1)
                    $calibratedEst = $baseNav * (1 + $changeRatio)
                    if ($null -ne $row.nav -and $row.nav -gt 0) { $calibratedError = ($calibratedEst - $row.nav) / $row.nav }
                    if ($null -ne $row.price -and $row.price -gt 0) { $calibratedPremium = ($row.price - $calibratedEst) / $calibratedEst }
                }
            }
        }

        $directBaseDate = Find-BaseDateForMethod -Rows $fundRows -CurrentIndex $i -CanUseDate {
            param($candidateDate, $candidateNav)
            if ($null -eq $candidateNav -or $candidateNav -le 0) { return $false }
            if (-not $positionMap.ContainsKey($date) -or $null -eq $positionMap[$date]) { return $false }
            $candidateFuture = if ($futuresMap.ContainsKey($candidateDate)) { Convert-ToDoubleOrNull $futuresMap[$candidateDate].$futureColumn } else { $null }
            $candidateRmb = if ($rmbOverrides.ContainsKey($candidateDate)) { $rmbOverrides[$candidateDate] } elseif ($etfMap.ContainsKey($candidateDate)) { Convert-ToDoubleOrNull $etfMap[$candidateDate].$etfRmbHeader } else { $null }
            return ($null -ne $candidateFuture -and $candidateFuture -gt 0 -and $null -ne $candidateRmb -and $candidateRmb -gt 0)
        }

        $directEst = $null
        $directError = $null
        $directPremium = $null
        if ($directBaseDate -and $null -ne $position -and $null -ne $rmbMid -and $rmbMid -gt 0 -and $null -ne $futureClose -and $futureClose -gt 0) {
            $baseRow = $fundRows | Where-Object { $_.date -eq $directBaseDate } | Select-Object -First 1
            $baseFuture = Convert-ToDoubleOrNull $futuresMap[$directBaseDate].$futureColumn
            $baseRmb = if ($rmbOverrides.ContainsKey($directBaseDate)) { $rmbOverrides[$directBaseDate] } else { Convert-ToDoubleOrNull $etfMap[$directBaseDate].$etfRmbHeader }
            if ($baseRow -and $null -ne $baseRow.nav -and $baseRow.nav -gt 0 -and $null -ne $baseFuture -and $baseFuture -gt 0 -and $null -ne $baseRmb -and $baseRmb -gt 0) {
                $changeRatio = $position * $beta * (($futureClose / $baseFuture) * ($rmbMid / $baseRmb) - 1)
                $directEst = $baseRow.nav * (1 + $changeRatio)
                if ($null -ne $row.nav -and $row.nav -gt 0) { $directError = ($directEst - $row.nav) / $row.nav }
                if ($null -ne $row.price -and $row.price -gt 0) { $directPremium = ($row.price - $directEst) / $directEst }
            }
        }

        $officialPremium = $null
        if ($null -ne $row.price -and $row.price -gt 0 -and $null -ne $row.official_est -and $row.official_est -gt 0) {
            $officialPremium = ($row.price - $row.official_est) / $row.official_est
        }

        $detailRow = [pscustomobject]@{
            fund_code                    = $fundCode
            date                         = $date
            nav_asof_date                = $navAsOfDate
            price                        = if ($null -ne $row.price) { [math]::Round($row.price, 4) } else { $null }
            nav                          = if ($null -ne $row.nav) { [math]::Round($row.nav, 4) } else { $null }
            actual_premium_pct           = Format-PercentOrNull $actualPremium
            position_used                = $position
            future_code                  = $futureCode
            future_close                 = $futureClose
            rmb_mid                      = $rmbMid
            calibration_value            = $calibrationValue
            calibration_count            = $calibrationCount
            calibrated_etf               = if ($null -ne $calibratedEtf) { [math]::Round($calibratedEtf, 4) } else { $null }
            official_est                 = if ($null -ne $row.official_est) { [math]::Round($row.official_est, 4) } else { $null }
            official_error_pct           = Format-PercentOrNull $row.official_err
            official_premium_pct         = Format-PercentOrNull $officialPremium
            calibrated_base_date         = $calibratedBaseDate
            calibrated_est               = if ($null -ne $calibratedEst) { [math]::Round($calibratedEst, 4) } else { $null }
            calibrated_error_pct         = Format-PercentOrNull $calibratedError
            calibrated_premium_pct       = Format-PercentOrNull $calibratedPremium
            direct_base_date             = $directBaseDate
            direct_est                   = if ($null -ne $directEst) { [math]::Round($directEst, 4) } else { $null }
            direct_error_pct             = Format-PercentOrNull $directError
            direct_premium_pct           = Format-PercentOrNull $directPremium
        }
        $detailRows += $detailRow
        $detailRowsAll += $detailRow
    }

    $detailPath = Join-Path $OutputDir ("method_compare_{0}.csv" -f $fundCode)
    $detailRows | Export-Csv -Path $detailPath -NoTypeInformation -Encoding UTF8
}

$methods = @(
    @{ name = "official"; estCol = "official_est"; premiumCol = "official_premium_pct"; errorCol = "official_error_pct" },
    @{ name = "calibrated"; estCol = "calibrated_est"; premiumCol = "calibrated_premium_pct"; errorCol = "calibrated_error_pct" },
    @{ name = "direct"; estCol = "direct_est"; premiumCol = "direct_premium_pct"; errorCol = "direct_error_pct" }
)

foreach ($scope in @("ALL") + $fundCodes) {
    $scopeRows = if ($scope -eq "ALL") { $detailRowsAll } else { @($detailRowsAll | Where-Object { $_.fund_code -eq $scope }) }
    foreach ($method in $methods) {
        $errorValues = @()
        $signalCount = 0
        $actualDiscountCount = 0
        $truePositive = 0

        foreach ($row in $scopeRows) {
            $nav = Convert-ToDoubleOrNull $row.nav
            $price = Convert-ToDoubleOrNull $row.price
            $est = Convert-ToDoubleOrNull $row.($method.estCol)
            if ($null -ne $nav -and $nav -gt 0 -and $null -ne $est -and $est -gt 0) {
                $errorValues += [math]::Abs(($est - $nav) / $nav)
            }
            if ($null -ne $nav -and $nav -gt 0 -and $null -ne $price -and $price -gt 0) {
                $actualPrem = ($price - $nav) / $nav
                if ($actualPrem -le -0.008) { $actualDiscountCount++ }
                if ($null -ne $est -and $est -gt 0) {
                    $estPrem = ($price - $est) / $est
                    if ($estPrem -le -0.008) {
                        $signalCount++
                        if ($actualPrem -le -0.008) { $truePositive++ }
                    }
                }
            }
        }

        $mae = $null
        $medianAe = $null
        $rmse = $null
        if ($errorValues.Count -gt 0) {
            $mae = ($errorValues | Measure-Object -Average).Average
            $medianAe = Get-Median -Values $errorValues
            $rmse = [math]::Sqrt((($errorValues | ForEach-Object { $_ * $_ }) | Measure-Object -Average).Average)
        }

        $precision = if ($signalCount -gt 0) { $truePositive / $signalCount } else { $null }
        $recall = if ($actualDiscountCount -gt 0) { $truePositive / $actualDiscountCount } else { $null }

        $summaryRows += [pscustomobject]@{
            fund_code              = $scope
            method                 = $method.name
            sample_count           = $errorValues.Count
            mae_abs_error_pct      = Format-PercentOrNull $mae
            median_abs_error_pct   = Format-PercentOrNull $medianAe
            rmse_error_pct         = Format-PercentOrNull $rmse
            est_discount_signals   = $signalCount
            actual_discount_days   = $actualDiscountCount
            true_positive_signals  = $truePositive
            precision              = Format-PercentOrNull $precision
            recall                 = Format-PercentOrNull $recall
        }
    }
}

$summaryPath = Join-Path $OutputDir "valuation_method_comparison_summary.csv"
$summaryRows | Export-Csv -Path $summaryPath -NoTypeInformation -Encoding UTF8

Write-Output "Generated comparison summary: $summaryPath"
Write-Output "Generated per-fund detail files: method_compare_*.csv"
