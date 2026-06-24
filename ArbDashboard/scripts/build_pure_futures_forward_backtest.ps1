param(
    [string]$InputDir = "D:\Study\codexTest\CodexLOFarb\data\analysis_outputs_20260329\procedure fiels",
    [string]$OutputDir = "D:\Study\codexTest\CodexLOFarb\data\analysis_outputs_20260329\procedure fiels",
    [int]$WindowSize = 40,
    [int]$MinObs = 20
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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

function Get-RollingBetaMap {
    param(
        [hashtable]$TargetNavByDate,
        [hashtable]$TradeMap,
        [double]$DefaultBeta,
        [int]$WindowSize,
        [int]$MinObs
    )

    $actualDates = @($TargetNavByDate.Keys | Sort-Object)
    $returnRows = @()

    for ($i = 1; $i -lt $actualDates.Count; $i++) {
        $currDate = $actualDates[$i]
        $prevDate = $actualDates[$i - 1]
        $currNav = Convert-ToDoubleOrNull $TargetNavByDate[$currDate]
        $prevNav = Convert-ToDoubleOrNull $TargetNavByDate[$prevDate]

        if ($null -eq $currNav -or $null -eq $prevNav -or $prevNav -le 0) {
            continue
        }

        if (-not $TradeMap.ContainsKey($currDate) -or -not $TradeMap.ContainsKey($prevDate)) {
            continue
        }

        $currFuture = Convert-ToDoubleOrNull $TradeMap[$currDate].future_close
        $prevFuture = Convert-ToDoubleOrNull $TradeMap[$prevDate].future_close
        $currRmb = Convert-ToDoubleOrNull $TradeMap[$currDate].rmb_mid
        $prevRmb = Convert-ToDoubleOrNull $TradeMap[$prevDate].rmb_mid

        if ($null -eq $currFuture -or $null -eq $prevFuture -or $prevFuture -le 0 -or $null -eq $currRmb -or $null -eq $prevRmb -or $prevRmb -le 0) {
            continue
        }

        $navRet = ($currNav / $prevNav) - 1
        $futRet = (($currFuture * $currRmb) / ($prevFuture * $prevRmb)) - 1
        $returnRows += [pscustomobject]@{
            date    = $currDate
            nav_ret = $navRet
            fut_ret = $futRet
        }
    }

    $betaMap = @{}
    foreach ($actualDate in $actualDates) {
        $usable = @($returnRows | Where-Object { $_.date -le $actualDate } | Select-Object -Last $WindowSize)
        $beta = $DefaultBeta
        if ($usable.Count -ge $MinObs) {
            $x = @($usable | ForEach-Object { [double]$_.fut_ret })
            $y = @($usable | ForEach-Object { [double]$_.nav_ret })
            $avgX = ($x | Measure-Object -Average).Average
            $avgY = ($y | Measure-Object -Average).Average
            $cov = 0.0
            $var = 0.0
            for ($j = 0; $j -lt $x.Count; $j++) {
                $dx = $x[$j] - $avgX
                $dy = $y[$j] - $avgY
                $cov += $dx * $dy
                $var += $dx * $dx
            }
            if ($var -gt 0) {
                $beta = $cov / $var
                if ($beta -lt 0) { $beta = 0.0 }
                if ($beta -gt 3) { $beta = 3.0 }
            }
        }
        $betaMap[$actualDate] = [math]::Round($beta, 4)
    }

    return $betaMap
}

$defaultBetaMap = @{
    "160719" = 1.0
    "161116" = 1.0
    "164701" = 1.0
    "165513" = 1.0
    "160723" = 0.85
    "161129" = 0.85
    "501018" = 0.85
}

$summaryRows = @()
$allForwardRows = @()

foreach ($fundCode in ($defaultBetaMap.Keys | Sort-Object)) {
    $path = Join-Path $InputDir ("method_compare_{0}.csv" -f $fundCode)
    if (-not (Test-Path $path)) {
        continue
    }

    $rows = @(Import-Csv $path)
    $tradeRows = @()
    $tradeMap = @{}
    $targetNavByDate = @{}

    foreach ($row in $rows) {
        $tradeDate = [string]$row.date
        $navAsOfDate = [string]$row.nav_asof_date
        $tradeObj = [pscustomobject]@{
            trade_date   = $tradeDate
            nav_asof_date = $navAsOfDate
            price        = Convert-ToDoubleOrNull $row.price
            known_nav    = Convert-ToDoubleOrNull $row.nav
            position     = Convert-ToDoubleOrNull $row.position_used
            future_close = Convert-ToDoubleOrNull $row.future_close
            rmb_mid      = Convert-ToDoubleOrNull $row.rmb_mid
            future_code  = [string]$row.future_code
            static_beta  = $defaultBetaMap[$fundCode]
        }
        $tradeRows += $tradeObj
        $tradeMap[$tradeDate] = $tradeObj

        if (-not [string]::IsNullOrWhiteSpace($navAsOfDate) -and $null -ne $tradeObj.known_nav) {
            $targetNavByDate[$navAsOfDate] = $tradeObj.known_nav
        }
    }

    $betaMap = Get-RollingBetaMap -TargetNavByDate $targetNavByDate -TradeMap $tradeMap -DefaultBeta $defaultBetaMap[$fundCode] -WindowSize $WindowSize -MinObs $MinObs

    $forwardRows = @()
    foreach ($row in $tradeRows) {
        $tradeDate = $row.trade_date
        $baseDate = $row.nav_asof_date
        $targetNav = if ($targetNavByDate.ContainsKey($tradeDate)) { Convert-ToDoubleOrNull $targetNavByDate[$tradeDate] } else { $null }
        $actualPremium = $null
        $staticEst = $null
        $staticErr = $null
        $staticPremium = $null
        $rollingBeta = if ($betaMap.ContainsKey($baseDate)) { $betaMap[$baseDate] } else { $row.static_beta }
        $rollingEst = $null
        $rollingErr = $null
        $rollingPremium = $null

        if ($null -ne $targetNav -and $targetNav -gt 0 -and $null -ne $row.price -and $row.price -gt 0) {
            $actualPremium = ($row.price - $targetNav) / $targetNav
        }

        if (-not [string]::IsNullOrWhiteSpace($baseDate) -and $tradeMap.ContainsKey($baseDate)) {
            $baseRow = $tradeMap[$baseDate]
            $baseNav = $row.known_nav
            $baseFuture = $baseRow.future_close
            $baseRmb = $baseRow.rmb_mid
            $position = $row.position

            if ($null -ne $baseNav -and $baseNav -gt 0 -and $null -ne $row.future_close -and $row.future_close -gt 0 -and $null -ne $row.rmb_mid -and $row.rmb_mid -gt 0 -and $null -ne $baseFuture -and $baseFuture -gt 0 -and $null -ne $baseRmb -and $baseRmb -gt 0 -and $null -ne $position) {
                $grossReturn = (($row.future_close * $row.rmb_mid) / ($baseFuture * $baseRmb)) - 1

                $staticEst = $baseNav * (1 + $position * $row.static_beta * $grossReturn)
                if ($null -ne $targetNav -and $targetNav -gt 0) { $staticErr = ($staticEst - $targetNav) / $targetNav }
                if ($null -ne $row.price -and $row.price -gt 0 -and $staticEst -gt 0) { $staticPremium = ($row.price - $staticEst) / $staticEst }

                $rollingEst = $baseNav * (1 + $position * $rollingBeta * $grossReturn)
                if ($null -ne $targetNav -and $targetNav -gt 0) { $rollingErr = ($rollingEst - $targetNav) / $targetNav }
                if ($null -ne $row.price -and $row.price -gt 0 -and $rollingEst -gt 0) { $rollingPremium = ($row.price - $rollingEst) / $rollingEst }
            }
        }

        $outRow = [pscustomobject]@{
            fund_code                    = $fundCode
            trade_date                   = $tradeDate
            known_nav_asof_date          = $baseDate
            known_nav                    = $row.known_nav
            target_nav_trade_date        = $targetNav
            actual_premium_next_pct      = Format-PercentOrNull $actualPremium
            price                        = $row.price
            future_code                  = $row.future_code
            future_close                 = $row.future_close
            rmb_mid                      = $row.rmb_mid
            position_used                = $row.position
            static_beta                  = $row.static_beta
            rolling_beta                 = $rollingBeta
            static_beta_est              = if ($null -ne $staticEst) { [math]::Round($staticEst, 4) } else { $null }
            static_beta_error_pct        = Format-PercentOrNull $staticErr
            static_beta_premium_pct      = Format-PercentOrNull $staticPremium
            rolling_beta_est             = if ($null -ne $rollingEst) { [math]::Round($rollingEst, 4) } else { $null }
            rolling_beta_error_pct       = Format-PercentOrNull $rollingErr
            rolling_beta_premium_pct     = Format-PercentOrNull $rollingPremium
        }
        $forwardRows += $outRow
        $allForwardRows += $outRow
    }

    $detailPath = Join-Path $OutputDir ("pure_futures_forward_{0}.csv" -f $fundCode)
    $forwardRows | Export-Csv $detailPath -NoTypeInformation -Encoding UTF8
}

$methodDefs = @(
    @{ name = "static_beta_forward"; estCol = "static_beta_est"; premiumCol = "static_beta_premium_pct"; errorCol = "static_beta_error_pct" },
    @{ name = "rolling_beta_forward"; estCol = "rolling_beta_est"; premiumCol = "rolling_beta_premium_pct"; errorCol = "rolling_beta_error_pct" }
)

foreach ($scope in @("ALL") + @($defaultBetaMap.Keys | Sort-Object)) {
    $scopeRows = if ($scope -eq "ALL") { $allForwardRows } else { @($allForwardRows | Where-Object { $_.fund_code -eq $scope }) }
    foreach ($method in $methodDefs) {
        $errorValues = @()
        $signalCount = 0
        $actualDiscountCount = 0
        $truePositive = 0

        foreach ($row in $scopeRows) {
            $targetNav = Convert-ToDoubleOrNull $row.target_nav_trade_date
            $est = Convert-ToDoubleOrNull $row.($method.estCol)
            $price = Convert-ToDoubleOrNull $row.price
            if ($null -ne $targetNav -and $targetNav -gt 0 -and $null -ne $est -and $est -gt 0) {
                $errorValues += [math]::Abs(($est - $targetNav) / $targetNav)
            }
            if ($null -ne $targetNav -and $targetNav -gt 0 -and $null -ne $price -and $price -gt 0) {
                $actualPrem = ($price - $targetNav) / $targetNav
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
        $rmse = $null
        if ($errorValues.Count -gt 0) {
            $mae = ($errorValues | Measure-Object -Average).Average
            $rmse = [math]::Sqrt((($errorValues | ForEach-Object { $_ * $_ }) | Measure-Object -Average).Average)
        }

        $precision = if ($signalCount -gt 0) { $truePositive / $signalCount } else { $null }
        $recall = if ($actualDiscountCount -gt 0) { $truePositive / $actualDiscountCount } else { $null }

        $summaryRows += [pscustomobject]@{
            fund_code              = $scope
            method                 = $method.name
            sample_count           = $errorValues.Count
            mae_abs_error_pct      = Format-PercentOrNull $mae
            rmse_error_pct         = Format-PercentOrNull $rmse
            est_discount_signals   = $signalCount
            actual_discount_days   = $actualDiscountCount
            true_positive_signals  = $truePositive
            precision              = Format-PercentOrNull $precision
            recall                 = Format-PercentOrNull $recall
        }
    }
}

$summaryPath = Join-Path $OutputDir "pure_futures_forward_summary.csv"
$summaryRows | Export-Csv $summaryPath -NoTypeInformation -Encoding UTF8

Write-Output "Generated pure futures forward summary: $summaryPath"
Write-Output "Generated pure futures forward files: pure_futures_forward_*.csv"
