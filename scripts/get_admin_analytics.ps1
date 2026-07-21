param(
    [Parameter(Mandatory = $true)]
    [string] $Token,

    [string] $BaseUrl = "https://foodland-ai-agent-production.up.railway.app",

    [ValidateSet("summary", "top-questions", "no-results", "intents")]
    [string] $Endpoint = "summary",

    [int] $Days = 7,

    [int] $Limit = 10
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$cleanToken = $Token.Trim()
if (-not $cleanToken) {
    throw "Token is empty. Pass the Railway ADMIN_ANALYTICS_TOKEN value with -Token '...'."
}

$cleanBaseUrl = $BaseUrl.TrimEnd("/")
$uri = "$cleanBaseUrl/admin/analytics/$Endpoint`?days=$Days"
if ($Endpoint -ne "intents") {
    $uri = "$uri&limit=$Limit"
}

Invoke-RestMethod `
    -Uri $uri `
    -Headers @{ "x-admin-token" = $cleanToken } |
ConvertTo-Json -Depth 6
