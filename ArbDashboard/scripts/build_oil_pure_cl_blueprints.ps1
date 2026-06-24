param(
    [string]$RootDir = "D:\Study\codexTest\CodexLOFarb",
    [double]$CalibrationJumpThreshold = 0.012
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function U {
    param([string]$Text)
    return [regex]::Unescape($Text)
}

function Convert-ToDoubleOrNull {
    param($Value)
    if ($null -eq $Value) { return $null }
    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) { return $null }
    $number = 0.0
    if ([double]::TryParse($text, [ref]$number)) { return $number }
    return $null
}

function Format-Percent {
    param($Value)
    if ($null -eq $Value) { return "" }
    return ("{0:P2}" -f [double]$Value)
}

function Format-Number {
    param(
        $Value,
        [int]$Digits = 4
    )
    if ($null -eq $Value) { return "" }
    return ("{0:N$Digits}" -f [double]$Value).Replace(",", "")
}

function Read-CsvFile {
    param([string]$Path)
    return @(Import-Csv -Path $Path -Encoding UTF8)
}

function Build-CalibrationMaps {
    param(
        [object[]]$Rows,
        [double]$Threshold
    )

    $sorted = @($Rows | Sort-Object date)
    $prevValue = $null
    $prevByDate = @{}
    $changeByDate = @{}
    $flagByDate = @{}

    foreach ($row in $sorted) {
        $date = [string]$row.date
        $currValue = Convert-ToDoubleOrNull $row.calibration_value
        $prevByDate[$date] = $prevValue

        $change = $null
        if ($null -ne $currValue -and $null -ne $prevValue -and $prevValue -gt 0) {
            $change = ($currValue - $prevValue) / $prevValue
        }
        $changeByDate[$date] = $change
        $flagByDate[$date] = ($null -ne $change -and [math]::Abs($change) -ge $Threshold)

        if ($null -ne $currValue -and $currValue -gt 0) {
            $prevValue = $currValue
        }
    }

    return @{
        PrevByDate = $prevByDate
        ChangeByDate = $changeByDate
        FlagByDate = $flagByDate
    }
}

function Get-MetricSummary {
    param(
        [object[]]$Rows,
        [string]$EstField,
        [switch]$NormalOnly,
        [switch]$AbnormalOnly
    )

    $usableRows = @()
    foreach ($row in $Rows) {
        $isAbnormal = [bool]$row.is_abnormal
        if ($NormalOnly -and $isAbnormal) { continue }
        if ($AbnormalOnly -and -not $isAbnormal) { continue }
        $usableRows += $row
    }

    $errorValues = @()
    $signalCount = 0
    $actualDiscountCount = 0
    $truePositive = 0

    foreach ($row in $usableRows) {
        $targetNav = $row.target_nav
        $est = $row.$EstField
        $price = $row.price

        if ($null -ne $targetNav -and $targetNav -gt 0 -and $null -ne $est -and $est -gt 0) {
            $errorValues += [math]::Abs(($est - $targetNav) / $targetNav)
        }

        if ($null -ne $targetNav -and $targetNav -gt 0 -and $null -ne $price -and $price -gt 0) {
            $actualPrem = ($price - $targetNav) / $targetNav
            if ($actualPrem -le -0.008) {
                $actualDiscountCount++
            }

            if ($null -ne $est -and $est -gt 0) {
                $estPrem = ($price - $est) / $est
                if ($estPrem -le -0.008) {
                    $signalCount++
                    if ($actualPrem -le -0.008) {
                        $truePositive++
                    }
                }
            }
        }
    }

    $mae = $null
    $rmse = $null
    if ($errorValues.Count -gt 0) {
        $mae = ($errorValues | Measure-Object -Average).Average
        $sumSquares = ($errorValues | ForEach-Object { $_ * $_ } | Measure-Object -Sum).Sum
        $rmse = [math]::Sqrt($sumSquares / $errorValues.Count)
    }

    $precision = $null
    $recall = $null
    if ($signalCount -gt 0) { $precision = $truePositive / $signalCount }
    if ($actualDiscountCount -gt 0) { $recall = $truePositive / $actualDiscountCount }

    return [pscustomobject]@{
        sample_count = $errorValues.Count
        signal_count = $signalCount
        actual_discount_days = $actualDiscountCount
        true_positive = $truePositive
        mae = $mae
        rmse = $rmse
        precision = $precision
        recall = $recall
    }
}

$procDir = Join-Path $RootDir "data\analysis_outputs_20260329\procedure fiels"
$mainDir = Join-Path $RootDir "data\analysis_outputs_20260329"

$fundMap = [ordered]@{
    "160723" = (U "\u5609\u5b9e\u539f\u6cb9")
    "161129" = (U "\u6613\u65b9\u8fbe\u539f\u6cb9")
    "501018" = (U "\u5357\u65b9\u539f\u6cb9")
}

$summaryPath = Join-Path $mainDir (U "00_\u539f\u6cb9\u7ec4\u7eafCL\u524d\u5411\u56de\u6d4b\u603b\u8868.csv")
$summaryMdPath = Join-Path $mainDir (U "\u539f\u6cb9\u7ec4_\u7eafCL\u4f30\u503c\u9aa8\u67b6\u8bf4\u660e.md")
$yesText = U "\u662f"
$noText = U "\u5426"
$occupiedText = U "\u5426(\u6587\u4ef6\u5360\u7528\uff0c\u4fdd\u7559\u539f\u6587\u4ef6)"

$colFundCode = U "\u57fa\u91d1\u4ee3\u7801"
$colFundName = U "\u57fa\u91d1\u540d\u79f0"
$colTradeDate = U "\u4ea4\u6613\u65e5\u671f"
$colNavAsOf = U "\u51c0\u503c\u5b9e\u9645\u5f52\u5c5e\u65e5"
$colKnownNav = U "\u5df2\u77e5\u51c0\u503c\u951a\u70b9"
$colTargetNav = U "T\u65e5\u771f\u5b9e\u51c0\u503c_\u6b21\u65e5\u516c\u5e03"
$colPrice = U "\u4ef7\u683c"
$colPosition = U "\u4f7f\u7528\u4ed3\u4f4d"
$colFuture = U "CL\u5f53\u65e5\u6536\u76d8\u4ef7"
$colBaseFuture = U "CL\u951a\u70b9\u6536\u76d8\u4ef7"
$colRmb = U "\u4eba\u6c11\u5e01\u4e2d\u95f4\u4ef7"
$colBaseRmb = U "\u951a\u70b9\u4eba\u6c11\u5e01\u4e2d\u95f4\u4ef7"
$colCal = U "\u6821\u51c6\u56e0\u5b50"
$colCalPrev = U "\u6821\u51c6\u56e0\u5b50\u524d\u4e00\u4ea4\u6613\u65e5"
$colCalChange = U "\u6821\u51c6\u56e0\u5b50\u65e5\u53d8\u5316"
$colAbnormal = U "\u6821\u51c6\u5f02\u5e38\u6807\u8bb0"
$colRatio = U "CLx\u4eba\u6c11\u5e01\u53d8\u5316\u500d\u6570"
$colReturn = U "CLx\u4eba\u6c11\u5e01\u6da8\u8dcc\u5e45"
$colCashAnchor = U "\u73b0\u91d1\u817f\u951a\u70b9"
$colRiskAnchor = U "\u98ce\u9669\u817f\u951a\u70b9"
$colNewLeg = U "\u7eafCL\u672a\u8c03\u4ed3\u98ce\u9669\u817f\u4f30\u503c"
$colStaticBeta = U "\u7eafCL\u9759\u6001Beta"
$colRollingBeta = U "\u7eafCL\u6eda\u52a8Beta"
$colStaticEst = U "\u7eafCL\u9759\u6001\u4f30\u503c"
$colRollingEst = U "\u7eafCL\u6eda\u52a8\u4f30\u503c"
$colStaticErr = U "\u7eafCL\u9759\u6001\u8bef\u5dee_\u6b21\u65e5\u9a8c\u8bc1"
$colRollingErr = U "\u7eafCL\u6eda\u52a8\u8bef\u5dee_\u6b21\u65e5\u9a8c\u8bc1"
$colStaticPremium = U "\u7eafCL\u9759\u6001\u6ea2\u4ef7"
$colRollingPremium = U "\u7eafCL\u6eda\u52a8\u6ea2\u4ef7"
$colOfficial = U "woody\u5b98\u65b9\u4f30\u503c"
$colCalEst = U "\u671f\u8d27\u6821\u51c6ETF\u4f30\u503c"
$colOldDirect = U "\u65e7\u7248\u76f4\u63a5\u671f\u8d27\u4f30\u503c"

$summaryRows = @()
$sampleFiles = @()

foreach ($fundCode in $fundMap.Keys) {
    $fundName = $fundMap[$fundCode]
    $methodPath = Join-Path $procDir ("method_compare_{0}.csv" -f $fundCode)
    $forwardPath = Join-Path $procDir ("pure_futures_forward_{0}.csv" -f $fundCode)
    $outCsv = Join-Path $mainDir ("{0}_{1}.csv" -f $fundCode, (U "\u7eafCL\u4f30\u503c\u6837\u677f"))

    $methodRows = Read-CsvFile $methodPath
    $forwardRows = Read-CsvFile $forwardPath
    $methodMap = @{}
    $forwardMap = @{}
    foreach ($row in $methodRows) { $methodMap[[string]$row.date] = $row }
    foreach ($row in $forwardRows) { $forwardMap[[string]$row.trade_date] = $row }

    $calMaps = Build-CalibrationMaps -Rows $methodRows -Threshold $CalibrationJumpThreshold
    $outRows = @()
    $evalRows = @()

    foreach ($tradeDate in ($methodMap.Keys | Sort-Object -Descending)) {
        $row = $methodMap[$tradeDate]
        $forward = if ($forwardMap.ContainsKey($tradeDate)) { $forwardMap[$tradeDate] } else { $null }
        $baseDate = [string]$row.nav_asof_date
        $baseRow = if ($methodMap.ContainsKey($baseDate)) { $methodMap[$baseDate] } else { $null }

        $knownNav = Convert-ToDoubleOrNull $row.nav
        $targetNav = if ($null -ne $forward) { Convert-ToDoubleOrNull $forward.target_nav_trade_date } else { $null }
        $price = Convert-ToDoubleOrNull $row.price
        $position = Convert-ToDoubleOrNull $row.position_used
        $futureClose = Convert-ToDoubleOrNull $row.future_close
        $rmbMid = Convert-ToDoubleOrNull $row.rmb_mid
        $baseFuture = if ($null -ne $baseRow) { Convert-ToDoubleOrNull $baseRow.future_close } else { $null }
        $baseRmb = if ($null -ne $baseRow) { Convert-ToDoubleOrNull $baseRow.rmb_mid } else { $null }
        $staticBeta = if ($null -ne $forward) { Convert-ToDoubleOrNull $forward.static_beta } else { $null }
        $rollingBeta = if ($null -ne $forward) { Convert-ToDoubleOrNull $forward.rolling_beta } else { $null }
        $calValue = Convert-ToDoubleOrNull $row.calibration_value
        $calPrev = $calMaps.PrevByDate[$tradeDate]
        $calChange = $calMaps.ChangeByDate[$tradeDate]
        $isAbnormal = [bool]$calMaps.FlagByDate[$tradeDate]

        $clCnyRatio = $null
        $clCnyReturn = $null
        $cashAnchor = $null
        $riskAnchor = $null
        $pureClNewLeg = $null
        $staticEst = $null
        $rollingEst = $null
        $staticErr = $null
        $rollingErr = $null
        $staticPremium = $null
        $rollingPremium = $null

        if (
            $null -ne $knownNav -and
            $null -ne $position -and
            $null -ne $futureClose -and $futureClose -gt 0 -and
            $null -ne $rmbMid -and $rmbMid -gt 0 -and
            $null -ne $baseFuture -and $baseFuture -gt 0 -and
            $null -ne $baseRmb -and $baseRmb -gt 0
        ) {
            $clCnyRatio = ($futureClose * $rmbMid) / ($baseFuture * $baseRmb)
            $clCnyReturn = $clCnyRatio - 1.0
            $cashAnchor = $knownNav * (1.0 - $position)
            $riskAnchor = $knownNav * $position
            $pureClNewLeg = $knownNav * $clCnyRatio

            if ($null -ne $staticBeta) {
                $staticEst = $cashAnchor + $riskAnchor * (1.0 + $staticBeta * $clCnyReturn)
            }
            if ($null -ne $rollingBeta) {
                $rollingEst = $cashAnchor + $riskAnchor * (1.0 + $rollingBeta * $clCnyReturn)
            }
        }

        if ($null -ne $targetNav -and $targetNav -gt 0) {
            if ($null -ne $staticEst) { $staticErr = ($staticEst - $targetNav) / $targetNav }
            if ($null -ne $rollingEst) { $rollingErr = ($rollingEst - $targetNav) / $targetNav }
        }

        if ($null -ne $price -and $price -gt 0) {
            if ($null -ne $staticEst -and $staticEst -gt 0) { $staticPremium = ($price - $staticEst) / $staticEst }
            if ($null -ne $rollingEst -and $rollingEst -gt 0) { $rollingPremium = ($price - $rollingEst) / $rollingEst }
        }

        $evalRows += [pscustomobject]@{
            fund_code = $fundCode
            trade_date = $tradeDate
            price = $price
            target_nav = $targetNav
            static_est = $staticEst
            rolling_est = $rollingEst
            is_abnormal = $isAbnormal
        }

        $obj = [ordered]@{}
        $obj[$colFundCode] = $fundCode
        $obj[$colFundName] = $fundName
        $obj[$colTradeDate] = $tradeDate
        $obj[$colNavAsOf] = $baseDate
        $obj[$colKnownNav] = Format-Number $knownNav 4
        $obj[$colTargetNav] = Format-Number $targetNav 4
        $obj[$colPrice] = Format-Number $price 3
        $obj[$colPosition] = Format-Number $position 4
        $obj[$colFuture] = Format-Number $futureClose 2
        $obj[$colBaseFuture] = Format-Number $baseFuture 2
        $obj[$colRmb] = Format-Number $rmbMid 4
        $obj[$colBaseRmb] = Format-Number $baseRmb 4
        $obj[$colCal] = Format-Number $calValue 4
        $obj[$colCalPrev] = Format-Number $calPrev 4
        $obj[$colCalChange] = Format-Percent $calChange
        $obj[$colAbnormal] = if ($isAbnormal) { $yesText } else { $noText }
        $obj[$colRatio] = Format-Number $clCnyRatio 6
        $obj[$colReturn] = Format-Percent $clCnyReturn
        $obj[$colCashAnchor] = Format-Number $cashAnchor 4
        $obj[$colRiskAnchor] = Format-Number $riskAnchor 4
        $obj[$colNewLeg] = Format-Number $pureClNewLeg 4
        $obj[$colStaticBeta] = Format-Number $staticBeta 4
        $obj[$colRollingBeta] = Format-Number $rollingBeta 4
        $obj[$colStaticEst] = Format-Number $staticEst 4
        $obj[$colRollingEst] = Format-Number $rollingEst 4
        $obj[$colStaticErr] = Format-Percent $staticErr
        $obj[$colRollingErr] = Format-Percent $rollingErr
        $obj[$colStaticPremium] = Format-Percent $staticPremium
        $obj[$colRollingPremium] = Format-Percent $rollingPremium
        $obj[$colOfficial] = $row.official_est
        $obj[$colCalEst] = $row.calibrated_est
        $obj[$colOldDirect] = $row.direct_est
        $outRows += [pscustomobject]$obj
    }

    $wroteOk = $true
    try {
        $outRows | Export-Csv -Path $outCsv -NoTypeInformation -Encoding UTF8
    } catch {
        $wroteOk = $false
    }

    $overallStatic = Get-MetricSummary -Rows $evalRows -EstField "static_est"
    $overallRolling = Get-MetricSummary -Rows $evalRows -EstField "rolling_est"
    $normalRolling = Get-MetricSummary -Rows $evalRows -EstField "rolling_est" -NormalOnly
    $abnormalRolling = Get-MetricSummary -Rows $evalRows -EstField "rolling_est" -AbnormalOnly
    $abnormalCount = @($evalRows | Where-Object { $_.is_abnormal }).Count
    $latest = $outRows[0]

    $sumObj = [ordered]@{}
    $sumObj[$colFundCode] = $fundCode
    $sumObj[$colFundName] = $fundName
    $sumObj[(U "\u6821\u51c6\u5f02\u5e38\u9608\u503c")] = ("|{0}| >= {1:P2}" -f $colCalChange, $CalibrationJumpThreshold)
    $sumObj[(U "\u6837\u672c\u6570")] = $overallRolling.sample_count
    $sumObj[(U "\u5f02\u5e38\u65e5\u6570")] = $abnormalCount
    $sumObj[(U "\u6b63\u5e38\u65e5\u6837\u672c\u6570")] = $normalRolling.sample_count
    $sumObj[(U "\u5f02\u5e38\u65e5\u6837\u672c\u6570")] = $abnormalRolling.sample_count
    $sumObj[(U "\u9759\u6001Beta_MAE")] = Format-Percent $overallStatic.mae
    $sumObj[(U "\u6eda\u52a8Beta_MAE")] = Format-Percent $overallRolling.mae
    $sumObj[(U "\u6b63\u5e38\u65e5_\u6eda\u52a8Beta_MAE")] = Format-Percent $normalRolling.mae
    $sumObj[(U "\u5f02\u5e38\u65e5_\u6eda\u52a8Beta_MAE")] = Format-Percent $abnormalRolling.mae
    $sumObj[(U "\u9759\u6001Beta_RMSE")] = Format-Percent $overallStatic.rmse
    $sumObj[(U "\u6eda\u52a8Beta_RMSE")] = Format-Percent $overallRolling.rmse
    $sumObj[(U "\u6eda\u52a8Beta_\u4f30\u503c\u6298\u4ef7\u4fe1\u53f7\u5929\u6570")] = $overallRolling.signal_count
    $sumObj[(U "\u5b9e\u9645\u6298\u4ef7\u5929\u6570")] = $overallRolling.actual_discount_days
    $sumObj[(U "\u6eda\u52a8Beta_\u67e5\u51c6\u7387")] = Format-Percent $overallRolling.precision
    $sumObj[(U "\u6eda\u52a8Beta_\u67e5\u5168\u7387")] = Format-Percent $overallRolling.recall
    $sumObj[(U "\u6b63\u5e38\u65e5_\u6eda\u52a8Beta_\u67e5\u51c6\u7387")] = Format-Percent $normalRolling.precision
    $sumObj[(U "\u6b63\u5e38\u65e5_\u6eda\u52a8Beta_\u67e5\u5168\u7387")] = Format-Percent $normalRolling.recall
    $sumObj[(U "\u6700\u65b0\u4ea4\u6613\u65e5\u671f")] = $latest.$colTradeDate
    $sumObj[(U "\u6700\u65b0\u7eafCL\u9759\u6001\u4f30\u503c")] = $latest.$colStaticEst
    $sumObj[(U "\u6700\u65b0\u7eafCL\u6eda\u52a8\u4f30\u503c")] = $latest.$colRollingEst
    $sumObj[(U "\u6700\u65b0\u7eafCL\u9759\u6001\u6ea2\u4ef7")] = $latest.$colStaticPremium
    $sumObj[(U "\u6700\u65b0\u7eafCL\u6eda\u52a8\u6ea2\u4ef7")] = $latest.$colRollingPremium
    $writeStatus = if ($wroteOk) { $yesText } else { $occupiedText }
    $sumObj[(U "\u6837\u677f\u6587\u4ef6\u5199\u5165\u6210\u529f")] = $writeStatus
    $sumObj[(U "\u6837\u677f\u6587\u4ef6")] = $outCsv
    $summaryRows += [pscustomobject]$sumObj

    $sampleFiles += $outCsv
}

$summaryRows | Export-Csv -Path $summaryPath -NoTypeInformation -Encoding UTF8

$bestMaKey = U "\u6b63\u5e38\u65e5_\u6eda\u52a8Beta_MAE"
$bestRow = $summaryRows |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_.$bestMaKey) } |
    Sort-Object { [double](($_.$bestMaKey -replace '%', '')) } |
    Select-Object -First 1

$lines = @()
$lines += (U "# \u539f\u6cb9\u7ec4\u7eafCL\u4f30\u503c\u9aa8\u67b6\u8bf4\u660e")
$lines += ""
$lines += (U "\u8fd9\u4efd\u603b\u8868\u5bf9\u5e94\u6587\u4ef6\uff1a")
$lines += ('- `{0}`' -f $summaryPath)
$lines += ""
$lines += (U "\u5355\u57fa\u91d1\u6837\u677f\u6587\u4ef6\uff1a")
foreach ($sampleFile in $sampleFiles) {
    $lines += ('- `{0}`' -f $sampleFile)
}
$lines += ""
$lines += (U "## \u901a\u7528\u9aa8\u67b6")
$lines += ""
$lines += (U "\u4e09\u53ea\u539f\u6cb9\u57fa\u91d1\u76ee\u524d\u7edf\u4e00\u6309\u4e0b\u9762\u8fd9\u6761\u9aa8\u67b6\u5c55\u5f00\uff1a")
$lines += ""
$lines += '```text'
$lines += "CL x RMB ratio = (CL_t x RMB_t) / (CL_0 x RMB_0)"
$lines += "Pure CL NAV = NAV0 x (1 - position) + NAV0 x position x (1 + Beta x (CL x RMB ratio - 1))"
$lines += '```'
$lines += ""
$lines += $(U "\u8fd9\u6761\u516c\u5f0f\u6cbf\u7528 woody \u7684\u4e09\u4ef6\u6838\u5fc3\u601d\u60f3\uff1a")
$lines += $(U "- \u4ee5\u6700\u8fd1\u53ef\u4fe1\u51c0\u503c\u4e3a\u951a\u70b9")
$lines += $(U "- \u4fdd\u7559\u73b0\u91d1\u4ed3\u4f4d\uff0c\u4e0d\u628a\u57fa\u91d1\u5f53\u6210 100% \u6ee1\u4ed3")
$lines += $(U "- \u53ea\u628a\u98ce\u9669\u817f\u4ea4\u7ed9 CL x \u4eba\u6c11\u5e01 \u8fd9\u4e00\u6761\u4e3b\u56e0\u5b50\u9a71\u52a8")
$lines += ""
$lines += $(U "## \u5f53\u524d\u989d\u5916\u5904\u7406")
$lines += ""
$lines += $(U "\u539f\u6cb9\u7ec4\u6bd4\u9ec4\u91d1\u7ec4\u66f4\u5bb9\u6613\u53d7\u6362\u6708\u3001\u671f\u9650\u7ed3\u6784\u3001\u5347\u8d34\u6c34\u548c USO \u6301\u4ed3\u673a\u5236\u5f71\u54cd\u3002")
$lines += $(U "\u56e0\u6b64\u8fd9\u7248\u6ca1\u6709\u628a\u6821\u51c6\u56e0\u5b50\u91cd\u65b0\u62ff\u6765\u505a\u4f30\u503c\u6838\u5fc3\uff0c\u800c\u662f\u53ea\u628a\u5b83\u5f53\u6210\u5f02\u5e38\u89c2\u6d4b\u5668\uff1a")
$lines += $((U "- \u5f53 |\u6821\u51c6\u56e0\u5b50\u65e5\u53d8\u5316| >= {0:P2} \u65f6\uff0c\u6807\u8bb0\u4e3a\u201c\u6821\u51c6\u5f02\u5e38\u65e5\u201d") -f $CalibrationJumpThreshold)
$lines += $(U "- \u5148\u770b\u6574\u4f53\u8bef\u5dee\uff0c\u518d\u5355\u72ec\u770b\u6392\u9664\u5f02\u5e38\u65e5\u540e\u7684\u6eda\u52a8Beta\u8868\u73b0")
$lines += ""
$lines += $(U "## \u5f53\u524d\u7ed3\u8bba")
$lines += ""
$lines += $(U "- \u539f\u6cb9\u7ec4\u6574\u4f53\u660e\u663e\u6bd4\u9ec4\u91d1\u7ec4\u96be\uff0c\u5355\u4e00 CL \u56e0\u5b50\u4e0d\u80fd\u5b8c\u5168\u8986\u76d6\u671f\u9650\u7ed3\u6784")
if ($null -ne $bestRow) {
    $lines += $((U "- \u6392\u9664\u5f02\u5e38\u65e5\u540e\uff0c\u5f53\u524d\u8bef\u5dee\u6700\u5c0f\u7684\u662f {0} {1}\uff0c\u6b63\u5e38\u65e5\u6eda\u52a8Beta_MAE = {2}") -f $bestRow.$colFundCode, $bestRow.$colFundName, $bestRow.$bestMaKey)
}
$lines += $(U "- \u5982\u679c\u67d0\u5929\u6821\u51c6\u56e0\u5b50\u8df3\u53d8\u5f88\u5927\uff0c\u8fd9\u4e00\u5929\u66f4\u9002\u5408\u964d\u6743\u6216\u4eba\u5de5\u590d\u6838\uff0c\u4e0d\u5b9c\u628a\u7eafCL\u4f30\u503c\u5f53\u6210\u552f\u4e00\u4ea4\u6613\u4f9d\u636e")
$lines += $(U "- \u8fd9\u7248\u7ed3\u679c\u66f4\u9002\u5408\u56de\u7b54\u201c\u54ea\u4e9b\u65e5\u5b50\u7eafCL\u53ef\u7528\uff0c\u54ea\u4e9b\u65e5\u5b50\u5e94\u56de\u907f\u201d\uff0c\u800c\u4e0d\u662f\u628a\u539f\u6cb9\u7ec4\u4e09\u53ea\u57fa\u91d1\u76f4\u63a5\u89c6\u4e3a\u9ec4\u91d1\u90a3\u6837\u7684\u7a33\u5b9a\u5355\u56e0\u5b50")
$lines += ""
$lines += $(U "## \u4e0b\u4e00\u6b65\u5efa\u8bae")
$lines += ""
$lines += $(U "- \u5148\u7ed3\u5408\u5355\u57fa\u91d1\u6837\u677f\u6587\u4ef6\uff0c\u89c2\u5bdf\u8bef\u5dee\u5927\u65e5\u662f\u5426\u96c6\u4e2d\u5728\u6821\u51c6\u5f02\u5e38\u65e5")
$lines += $(U "- \u5982\u679c\u8fd9\u79cd\u5bf9\u5e94\u5173\u7cfb\u660e\u663e\uff0c\u518d\u7ee7\u7eed\u52a0\u5165\u6362\u6708\u72b6\u6001\u6216\u8fd1\u8fdc\u6708\u4ef7\u5dee\u4fe1\u606f")
$lines += $(U "- \u5982\u679c\u4f60\u8981\u505a\u5b9e\u76d8\u76d1\u63a7\uff0c\u539f\u6cb9\u7ec4\u66f4\u9002\u5408\u201c\u7eafCL\u4f30\u503c + \u5f02\u5e38\u8fc7\u6ee4\u201d\u800c\u4e0d\u662f\u88f8\u7528\u7eafCL")

Set-Content -Path $summaryMdPath -Value $lines -Encoding UTF8
