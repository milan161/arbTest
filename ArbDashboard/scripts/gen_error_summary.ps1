$outMd = "D:\Study\codexTest\CodexLOFarb\data\backtest_error_vs_calibration_summary.md"
$funds = @(
  [pscustomobject]@{code="160719"; file="D:\Study\codexTest\CodexLOFarb\data\backtest_futures_nav_160719.csv"},
  [pscustomobject]@{code="501018"; file="D:\Study\codexTest\CodexLOFarb\data\backtest_futures_nav_501018.csv"}
)
$md = @()
$md += "# 误差 vs 校准变化（摘要）"
$md += ""
foreach($f in $funds){
  $rows = Import-Csv $f.file | Sort-Object { [datetime]$_.日期 }
  $prevCal = $null
  $with = @()
  foreach($r in $rows){
    $cal = if($r.校准值 -ne ""){ [double]$r.校准值 } else { $null }
    $calChg = $null
    $calChgPct = $null
    if($cal -ne $null -and $prevCal -ne $null){
      $calChg = $cal - $prevCal
      if($prevCal -ne 0){ $calChgPct = $calChg / $prevCal }
    }
    $o = $r | Select-Object *
    Add-Member -InputObject $o -NotePropertyName 校准变化 -NotePropertyValue $calChg
    Add-Member -InputObject $o -NotePropertyName 校准变化率 -NotePropertyValue $calChgPct
    $with += $o
    if($cal -ne $null){ $prevCal = $cal }
  }
  $csvOut = "D:\Study\codexTest\CodexLOFarb\data\backtest_error_vs_calibration_$($f.code).csv"
  $with | Sort-Object { [datetime]$_.日期 } -Descending | Export-Csv -Path $csvOut -NoTypeInformation -Encoding UTF8

  $valid = $with | Where-Object { $_.'raw误差' -ne "" }
  $top = $valid | ForEach-Object {
    [pscustomobject]@{
      日期 = $_.日期
      raw误差 = [double]$_.raw误差
      adj误差 = if($_.'adj误差' -ne ""){ [double]$_.adj误差 } else { $null }
      校准值 = if($_.'校准值' -ne ""){ [double]$_.校准值 } else { $null }
      校准变化 = $_.'校准变化'
      校准变化率 = $_.'校准变化率'
      官方EST误差 = $_.'官方EST误差'
    }
  } | Sort-Object { [math]::Abs($_.raw误差) } -Descending | Select-Object -First 8

  $md += "## $($f.code)"
  $md += ""
  $md += "- 详细表：D:\\Study\\codexTest\\CodexLOFarb\\data\\backtest_error_vs_calibration_$($f.code).csv"
  $md += ""
  $md += "| 日期 | raw误差 | adj误差 | 校准值 | 校准变化 | 校准变化率 | 官方EST误差 |"
  $md += "|---|---|---|---|---|---|---|"
  foreach($t in $top){
    $rawStr = ("{0:F6}" -f $t.raw误差)
    $adjStr = if($t.adj误差 -ne $null){ "{0:F6}" -f $t.adj误差 } else { "" }
    $calStr = if($t.校准值 -ne $null){ "{0:F6}" -f $t.校准值 } else { "" }
    $calChgStr = if($t.校准变化 -ne $null){ "{0:F6}" -f $t.校准变化 } else { "" }
    $calPctStr = if($t.校准变化率 -ne $null){ "{0:P2}" -f $t.校准变化率 } else { "" }
    $estErrStr = $t.官方EST误差
    $md += ("| {0} | {1} | {2} | {3} | {4} | {5} | {6} |" -f $t.日期, $rawStr, $adjStr, $calStr, $calChgStr, $calPctStr, $estErrStr)
  }
  $md += ""
}
$md | Set-Content -Path $outMd -Encoding UTF8
