param(
    [string]$RootDir = "D:\Study\codexTest\CodexLOFarb"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function U {
    param([string]$Text)
    return [regex]::Unescape($Text)
}

$mainDir = Join-Path $RootDir "data\analysis_outputs_20260329"
$fundCodes = @("160723", "161129", "501018")

$colTradeDate = U "\u4ea4\u6613\u65e5\u671f"
$newCols = @(
    $(U "\u6821\u51c6\u56e0\u5b50\u524d\u4e00\u4ea4\u6613\u65e5"),
    $(U "\u6821\u51c6\u56e0\u5b50\u65e5\u53d8\u5316"),
    $(U "\u6821\u51c6\u5f02\u5e38\u6807\u8bb0"),
    $(U "\u7eafCL\u9759\u6001Beta"),
    $(U "\u7eafCL\u6eda\u52a8Beta"),
    $(U "\u7eafCL\u9759\u6001\u4f30\u503c"),
    $(U "\u7eafCL\u6eda\u52a8\u4f30\u503c"),
    $(U "\u7eafCL\u9759\u6001\u8bef\u5dee_\u6b21\u65e5\u9a8c\u8bc1"),
    $(U "\u7eafCL\u6eda\u52a8\u8bef\u5dee_\u6b21\u65e5\u9a8c\u8bc1"),
    $(U "\u7eafCL\u9759\u6001\u6ea2\u4ef7"),
    $(U "\u7eafCL\u6eda\u52a8\u6ea2\u4ef7")
)

foreach ($fundCode in $fundCodes) {
    $mainPath = Join-Path $mainDir ("{0}_{1}.csv" -f $fundCode, (U "\u5355\u57fa\u91d1\u4e09\u79cd\u4f30\u503c\u5bf9\u6bd4"))
    $samplePath = Join-Path $mainDir ("{0}_{1}.csv" -f $fundCode, (U "\u7eafCL\u4f30\u503c\u6837\u677f"))

    if (-not (Test-Path $mainPath) -or -not (Test-Path $samplePath)) {
        continue
    }

    $mainRows = @(Import-Csv -Path $mainPath -Encoding UTF8)
    $sampleRows = @(Import-Csv -Path $samplePath -Encoding UTF8)
    $sampleMap = @{}
    foreach ($row in $sampleRows) {
        $sampleMap[[string]$row.PSObject.Properties[$colTradeDate].Value] = $row
    }

    $mergedRows = @()
    foreach ($row in $mainRows) {
        $tradeDate = [string]$row.PSObject.Properties[$colTradeDate].Value
        $sample = $sampleMap[$tradeDate]

        $obj = [ordered]@{}
        foreach ($p in $row.PSObject.Properties) {
            if ($p.Name -like "* U") { continue }
            if ($newCols -contains $p.Name) { continue }
            $obj[$p.Name] = $p.Value
        }

        foreach ($col in $newCols) {
            $obj[$col] = if ($null -ne $sample -and $null -ne $sample.PSObject.Properties[$col]) { $sample.PSObject.Properties[$col].Value } else { "" }
        }

        $mergedRows += [pscustomobject]$obj
    }

    $mergedRows | Export-Csv -Path $mainPath -NoTypeInformation -Encoding UTF8
}
