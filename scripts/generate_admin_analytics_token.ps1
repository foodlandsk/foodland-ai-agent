param(
    [int] $Bytes = 32
)

if ($Bytes -lt 16) {
    throw "Use at least 16 random bytes for an admin token."
}

$buffer = New-Object byte[] $Bytes
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)

[Convert]::ToBase64String($buffer)
