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
$archiveDir = Join-Path $mainDir (U "archive_\u8fc7\u7a0b\u4e0e\u6837\u677f")
$tradeDateCol = U "\u4ea4\u6613\u65e5\u671f"

$fundConfigs = @(
    [pscustomobject]@{ code = "160719"; sample = "160719_" + (U "\u7eafGC\u4f30\u503c\u6837\u677f") + ".csv"; beta = (U "\u7eafGC\u6eda\u52a8Beta"); est = (U "\u7eafGC\u6eda\u52a8\u4f30\u503c"); err = (U "\u7eafGC\u6eda\u52a8\u8bef\u5dee_\u6b21\u65e5\u9a8c\u8bc1"); prem = (U "\u7eafGC\u6eda\u52a8\u6ea2\u4ef7"); oil = $false },
    [pscustomobject]@{ code = "161116"; sample = "161116_" + (U "\u7eafGC\u4f30\u503c\u6837\u677f") + ".csv"; beta = (U "\u7eafGC\u6eda\u52a8Beta"); est = (U "\u7eafGC\u6eda\u52a8\u4f30\u503c"); err = (U "\u7eafGC\u6eda\u52a8\u8bef\u5dee_\u6b21\u65e5\u9a8c\u8bc1"); prem = (U "\u7eafGC\u6eda\u52a8\u6ea2\u4ef7"); oil = $false },
    [pscustomobject]@{ code = "164701"; sample = "164701_" + (U "\u7eafGC\u4f30\u503c\u6837\u677f") + ".csv"; beta = (U "\u7eafGC\u6eda\u52a8Beta"); est = (U "\u7eafGC\u6eda\u52a8\u4f30\u503c"); err = (U "\u7eafGC\u6eda\u52a8\u8bef\u5dee_\u6b21\u65e5\u9a8c\u8bc1"); prem = (U "\u7eafGC\u6eda\u52a8\u6ea2\u4ef7"); oil = $false },
    [pscustomobject]@{ code = "165513"; sample = "165513_" + (U "\u7eafGC\u4f30\u503c\u6837\u677f") + ".csv"; beta = (U "\u7eafGC\u6eda\u52a8Beta"); est = (U "\u7eafGC\u6eda\u52a8\u4f30\u503c"); err = (U "\u7eafGC\u6eda\u52a8\u8bef\u5dee_\u6b21\u65e5\u9a8c\u8bc1"); prem = (U "\u7eafGC\u6eda\u52a8\u6ea2\u4ef7"); oil = $false },
    [pscustomobject]@{ code = "160723"; sample = "160723_" + (U "\u7eafCL\u4f30\u503c\u6837\u677f") + ".csv"; beta = (U "\u7eafCL\u6eda\u52a8Beta"); est = (U "\u7eafCL\u6eda\u52a8\u4f30\u503c"); err = (U "\u7eafCL\u6eda\u52a8\u8bef\u5dee_\u6b21\u65e5\u9a8c\u8bc1"); prem = (U "\u7eafCL\u6eda\u52a8\u6ea2\u4ef7"); oil = $true },
    [pscustomobject]@{ code = "161129"; sample = "161129_" + (U "\u7eafCL\u4f30\u503c\u6837\u677f") + ".csv"; beta = (U "\u7eafCL\u6eda\u52a8Beta"); est = (U "\u7eafCL\u6eda\u52a8\u4f30\u503c"); err = (U "\u7eafCL\u6eda\u52a8\u8bef\u5dee_\u6b21\u65e5\u9a8c\u8bc1"); prem = (U "\u7eafCL\u6eda\u52a8\u6ea2\u4ef7"); oil = $true },
    [pscustomobject]@{ code = "501018"; sample = "501018_" + (U "\u7eafCL\u4f30\u503c\u6837\u677f") + ".csv"; beta = (U "\u7eafCL\u6eda\u52a8Beta"); est = (U "\u7eafCL\u6eda\u52a8\u4f30\u503c"); err = (U "\u7eafCL\u6eda\u52a8\u8bef\u5dee_\u6b21\u65e5\u9a8c\u8bc1"); prem = (U "\u7eafCL\u6eda\u52a8\u6ea2\u4ef7"); oil = $true }
)

$removeCols = @(
    $(U "\u76f4\u63a5\u4f30\u503c\u57fa\u51c6\u65e5"),
    $(U "\u76f4\u63a5\u671f\u8d27\u4f30\u503c"),
    $(U "\u76f4\u63a5\u671f\u8d27\u8bef\u5dee"),
    $(U "\u76f4\u63a5\u671f\u8d27\u6ea2\u4ef7"),
    $(U "\u7eafGC\u9759\u6001Beta"),
    $(U "\u7eafGC\u6eda\u52a8Beta"),
    $(U "\u7eafGC\u9759\u6001\u4f30\u503c"),
    $(U "\u7eafGC\u6eda\u52a8\u4f30\u503c"),
    $(U "\u7eafGC\u9759\u6001\u8bef\u5dee_\u6b21\u65e5\u9a8c\u8bc1"),
    $(U "\u7eafGC\u6eda\u52a8\u8bef\u5dee_\u6b21\u65e5\u9a8c\u8bc1"),
    $(U "\u7eafGC\u9759\u6001\u6ea2\u4ef7"),
    $(U "\u7eafGC\u6eda\u52a8\u6ea2\u4ef7"),
    $(U "\u7eafCL\u9759\u6001Beta"),
    $(U "\u7eafCL\u6eda\u52a8Beta"),
    $(U "\u7eafCL\u9759\u6001\u4f30\u503c"),
    $(U "\u7eafCL\u6eda\u52a8\u4f30\u503c"),
    $(U "\u7eafCL\u9759\u6001\u8bef\u5dee_\u6b21\u65e5\u9a8c\u8bc1"),
    $(U "\u7eafCL\u6eda\u52a8\u8bef\u5dee_\u6b21\u65e5\u9a8c\u8bc1"),
    $(U "\u7eafCL\u9759\u6001\u6ea2\u4ef7"),
    $(U "\u7eafCL\u6eda\u52a8\u6ea2\u4ef7"),
    $(U "\u6821\u51c6\u56e0\u5b50\u524d\u4e00\u4ea4\u6613\u65e5"),
    $(U "\u6821\u51c6\u56e0\u5b50\u65e5\u53d8\u5316"),
    $(U "\u6821\u51c6\u5f02\u5e38\u6807\u8bb0"),
    $(U "\u671f\u8d27\u76f4\u63a5Beta"),
    $(U "\u671f\u8d27\u76f4\u63a5\u4f30\u503c"),
    $(U "\u671f\u8d27\u76f4\u63a5\u8bef\u5dee"),
    $(U "\u671f\u8d27\u76f4\u63a5\u6ea2\u4ef7")
)

$newBetaCol = U "\u671f\u8d27\u76f4\u63a5Beta"
$newEstCol = U "\u671f\u8d27\u76f4\u63a5\u4f30\u503c"
$newErrCol = U "\u671f\u8d27\u76f4\u63a5\u8bef\u5dee"
$newPremCol = U "\u671f\u8d27\u76f4\u63a5\u6ea2\u4ef7"
$oilPrevCalCol = U "\u6821\u51c6\u56e0\u5b50\u524d\u4e00\u4ea4\u6613\u65e5"
$oilCalChangeCol = U "\u6821\u51c6\u56e0\u5b50\u65e5\u53d8\u5316"
$oilAbnormalCol = U "\u6821\u51c6\u5f02\u5e38\u6807\u8bb0"

foreach ($cfg in $fundConfigs) {
    $mainPath = Join-Path $mainDir ("{0}_{1}.csv" -f $cfg.code, (U "\u5355\u57fa\u91d1\u4e09\u79cd\u4f30\u503c\u5bf9\u6bd4"))
    $samplePath = Join-Path $archiveDir $cfg.sample
    if (-not (Test-Path $mainPath) -or -not (Test-Path $samplePath)) { continue }

    $mainRows = @(Import-Csv -Path $mainPath -Encoding UTF8)
    $sampleRows = @(Import-Csv -Path $samplePath -Encoding UTF8)
    $sampleMap = @{}
    foreach ($s in $sampleRows) {
        $sampleMap[[string]$s.PSObject.Properties[$tradeDateCol].Value] = $s
    }

    $outRows = @()
    foreach ($row in $mainRows) {
        $tradeDate = [string]$row.PSObject.Properties[$tradeDateCol].Value
        $sample = $sampleMap[$tradeDate]

        $obj = [ordered]@{}
        foreach ($p in $row.PSObject.Properties) {
            if ($removeCols -contains $p.Name) { continue }
            $obj[$p.Name] = $p.Value
        }

        if ($cfg.oil) {
            $obj[$oilPrevCalCol] = if ($sample -and $sample.PSObject.Properties[$oilPrevCalCol]) { $sample.PSObject.Properties[$oilPrevCalCol].Value } else { "" }
            $obj[$oilCalChangeCol] = if ($sample -and $sample.PSObject.Properties[$oilCalChangeCol]) { $sample.PSObject.Properties[$oilCalChangeCol].Value } else { "" }
            $obj[$oilAbnormalCol] = if ($sample -and $sample.PSObject.Properties[$oilAbnormalCol]) { $sample.PSObject.Properties[$oilAbnormalCol].Value } else { "" }
        }

        $obj[$newBetaCol] = if ($sample -and $sample.PSObject.Properties[$cfg.beta]) { $sample.PSObject.Properties[$cfg.beta].Value } else { "" }
        $obj[$newEstCol] = if ($sample -and $sample.PSObject.Properties[$cfg.est]) { $sample.PSObject.Properties[$cfg.est].Value } else { "" }
        $obj[$newErrCol] = if ($sample -and $sample.PSObject.Properties[$cfg.err]) { $sample.PSObject.Properties[$cfg.err].Value } else { "" }
        $obj[$newPremCol] = if ($sample -and $sample.PSObject.Properties[$cfg.prem]) { $sample.PSObject.Properties[$cfg.prem].Value } else { "" }

        $outRows += [pscustomobject]$obj
    }

    $outRows | Export-Csv -Path $mainPath -NoTypeInformation -Encoding UTF8
}
