param(
    [string]$MainDir = "D:\Study\codexTest\CodexLOFarb\data\analysis_outputs_20260329",
    [string]$ProcedureDir = "D:\Study\codexTest\CodexLOFarb\data\analysis_outputs_20260329\procedure fiels"
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

function Format-NumberOrNull {
    param(
        $Value,
        [int]$Digits = 4
    )
    $number = Convert-ToDoubleOrNull $Value
    if ($null -eq $number) {
        return ""
    }
    return $number.ToString("F$Digits")
}

function Get-MethodName {
    param([string]$Method)
    switch ($Method) {
        "static_beta_forward" { return "纯期货静态Beta" }
        "rolling_beta_forward" { return "纯期货滚动Beta" }
        default { return $Method }
    }
}

$summaryPath = Join-Path $ProcedureDir "pure_futures_forward_summary.csv"
if (-not (Test-Path -LiteralPath $summaryPath)) {
    throw "Summary file not found: $summaryPath"
}

$summaryRows = Import-Csv -LiteralPath $summaryPath
$summaryChinese = foreach ($row in $summaryRows) {
    [pscustomobject]@{
        '基金代码'           = $row.fund_code
        '方法'               = Get-MethodName $row.method
        '样本数'             = $row.sample_count
        '平均绝对误差_次日验证' = $row.mae_abs_error_pct
        '误差均方根_次日验证'   = $row.rmse_error_pct
        '估值折价信号天数'     = $row.est_discount_signals
        '实际折价天数'         = $row.actual_discount_days
        '真阳性天数'           = $row.true_positive_signals
        '查准率'             = $row.precision
        '查全率'             = $row.recall
    }
}

$summaryChinese |
    Export-Csv -LiteralPath (Join-Path $MainDir "01_纯期货前向回测总表.csv") -NoTypeInformation -Encoding UTF8

$mainFundFiles = Get-ChildItem -LiteralPath $MainDir -Filter "*_单基金三种估值对比.csv" | Sort-Object Name
foreach ($mainFile in $mainFundFiles) {
    $fundCode = ($mainFile.BaseName -split "_")[0]
    $forwardPath = Join-Path $ProcedureDir ("pure_futures_forward_{0}.csv" -f $fundCode)
    if (-not (Test-Path -LiteralPath $forwardPath)) {
        continue
    }

    $mainRows = Import-Csv -LiteralPath $mainFile.FullName
    $forwardRows = Import-Csv -LiteralPath $forwardPath
    $forwardMap = @{}
    foreach ($row in $forwardRows) {
        $forwardMap[[string]$row.trade_date] = $row
    }

    $mergedRows = foreach ($row in $mainRows) {
        $tradeDate = [string]$row.'交易日期'
        $forward = $null
        if ($forwardMap.ContainsKey($tradeDate)) {
            $forward = $forwardMap[$tradeDate]
        }

        [pscustomobject]@{
            '交易日期'               = $row.'交易日期'
            '净值实际归属日'         = $row.'净值实际归属日'
            '价格'                   = $row.'价格'
            '基金净值'               = $row.'基金净值'
            '实际溢价'               = $row.'实际溢价'
            '使用仓位'               = $row.'使用仓位'
            '期货代码'               = $row.'期货代码'
            '期货收盘价'             = $row.'期货收盘价'
            '人民币中间价'           = $row.'人民币中间价'
            '校准因子'               = $row.'校准因子'
            '校准样本数'             = $row.'校准样本数'
            '期货映射ETF价格'        = $row.'期货映射ETF价格'
            '官方估值'               = $row.'官方估值'
            '官方误差'               = $row.'官方误差'
            '官方溢价'               = $row.'官方溢价'
            '校准估值基准日'         = $row.'校准估值基准日'
            '校准ETF估值'            = $row.'校准ETF估值'
            '校准ETF误差'            = $row.'校准ETF误差'
            '校准ETF溢价'            = $row.'校准ETF溢价'
            '直接估值基准日'         = $row.'直接估值基准日'
            '直接期货估值'           = $row.'直接期货估值'
            '直接期货误差'           = $row.'直接期货误差'
            '直接期货溢价'           = $row.'直接期货溢价'
            'T日真实净值_次日公布'   = if ($null -ne $forward) { $forward.target_nav_trade_date } else { "" }
            'T日真实溢价_次日验证'   = if ($null -ne $forward) { $forward.actual_premium_next_pct } else { "" }
            '纯期货静态Beta'         = if ($null -ne $forward) { Format-NumberOrNull $forward.static_beta 4 } else { "" }
            '纯期货滚动Beta'         = if ($null -ne $forward) { Format-NumberOrNull $forward.rolling_beta 4 } else { "" }
            '纯期货静态估值'         = if ($null -ne $forward) { Format-NumberOrNull $forward.static_beta_est 4 } else { "" }
            '纯期货静态误差_次日验证' = if ($null -ne $forward) { $forward.static_beta_error_pct } else { "" }
            '纯期货静态溢价'         = if ($null -ne $forward) { $forward.static_beta_premium_pct } else { "" }
            '纯期货滚动估值'         = if ($null -ne $forward) { Format-NumberOrNull $forward.rolling_beta_est 4 } else { "" }
            '纯期货滚动误差_次日验证' = if ($null -ne $forward) { $forward.rolling_beta_error_pct } else { "" }
            '纯期货滚动溢价'         = if ($null -ne $forward) { $forward.rolling_beta_premium_pct } else { "" }
        }
    }

    $mergedRows | Export-Csv -LiteralPath $mainFile.FullName -NoTypeInformation -Encoding UTF8
}

Write-Host ("Exported Chinese pure futures summary to {0}" -f (Join-Path $MainDir "01_纯期货前向回测总表.csv"))
Write-Host "Merged pure futures forward columns into main per-fund Chinese files."
