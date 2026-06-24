param(
    [Parameter(Mandatory = $true)][string]$FundCode,
    [Parameter(Mandatory = $true)][double]$LofPrice,
    [Parameter(Mandatory = $true)][double]$FuturePrice,
    [Parameter(Mandatory = $true)][double]$RmbMid,
    [string]$TradeDate = "",
    [double]$KnownNav = 0,
    [double]$Position = -1,
    [double]$Beta = -1,
    [double]$AnchorFuture = 0,
    [double]$AnchorRmb = 0,
    [string]$RootDir = "D:\Study\codexTest\CodexLOFarb"
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

$mainDir = Join-Path $RootDir "data\analysis_outputs_20260329"
$mainPath = Join-Path $mainDir ("{0}_{1}.csv" -f $FundCode, (U "\u5355\u57fa\u91d1\u4e09\u79cd\u4f30\u503c\u5bf9\u6bd4"))
if (-not (Test-Path $mainPath)) {
    throw "Fund report not found: $mainPath"
}

$rows = @(Import-Csv -Path $mainPath -Encoding UTF8)
if ($rows.Count -eq 0) {
    throw "No rows found in $mainPath"
}

$colTradeDate = U "\u4ea4\u6613\u65e5\u671f"
$colPrice = U "\u4ef7\u683c"
$colNav = U "\u57fa\u91d1\u51c0\u503c"
$colPosition = U "\u4f7f\u7528\u4ed3\u4f4d"
$colFuture = U "\u671f\u8d27\u6536\u76d8\u4ef7"
$colRmb = U "\u4eba\u6c11\u5e01\u4e2d\u95f4\u4ef7"
$colBeta = U "\u671f\u8d27\u76f4\u63a5Beta"

$anchorRow = $rows[0]
$anchorTradeDate = [string]$anchorRow.PSObject.Properties[$colTradeDate].Value
$anchorNavValue = Convert-ToDoubleOrNull $anchorRow.PSObject.Properties[$colNav].Value
$anchorPosValue = Convert-ToDoubleOrNull $anchorRow.PSObject.Properties[$colPosition].Value
$anchorFutureValue = Convert-ToDoubleOrNull $anchorRow.PSObject.Properties[$colFuture].Value
$anchorRmbValue = Convert-ToDoubleOrNull $anchorRow.PSObject.Properties[$colRmb].Value
$anchorBetaValue = Convert-ToDoubleOrNull $anchorRow.PSObject.Properties[$colBeta].Value

if ($KnownNav -le 0) { $KnownNav = $anchorNavValue }
if ($Position -lt 0) { $Position = $anchorPosValue }
if ($Beta -lt 0) { $Beta = $anchorBetaValue }
if ($AnchorFuture -le 0) { $AnchorFuture = $anchorFutureValue }
if ($AnchorRmb -le 0) { $AnchorRmb = $anchorRmbValue }
if ([string]::IsNullOrWhiteSpace($TradeDate)) { $TradeDate = (Get-Date).ToString("yyyy-MM-dd") }

if ($KnownNav -le 0 -or $Position -lt 0 -or $Beta -lt 0 -or $AnchorFuture -le 0 -or $AnchorRmb -le 0) {
    throw "Anchor inputs are incomplete. Check the latest row in the main fund csv or pass parameters manually."
}

$ratio = ($FuturePrice * $RmbMid) / ($AnchorFuture * $AnchorRmb)
$directEst = $KnownNav * (1 + $Position * $Beta * ($ratio - 1))
$premium = ($LofPrice - $directEst) / $directEst

$result = [pscustomobject]@{
    基金代码 = $FundCode
    交易日期 = $TradeDate
    参考锚点交易日 = $anchorTradeDate
    锚点净值 = [math]::Round($KnownNav, 4)
    使用仓位 = [math]::Round($Position, 4)
    期货直接Beta = [math]::Round($Beta, 4)
    当前LOF价格 = [math]::Round($LofPrice, 4)
    当前期货价格 = [math]::Round($FuturePrice, 4)
    当前人民币中间价 = [math]::Round($RmbMid, 4)
    锚点期货价格 = [math]::Round($AnchorFuture, 4)
    锚点人民币中间价 = [math]::Round($AnchorRmb, 4)
    期货人民币变化倍数 = [math]::Round($ratio, 6)
    期货直接估值 = [math]::Round($directEst, 4)
    期货直接溢价 = ("{0:P2}" -f $premium)
}

$result | Format-List
