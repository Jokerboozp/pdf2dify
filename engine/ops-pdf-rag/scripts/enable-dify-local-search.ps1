# Run in an Administrator PowerShell. Allows only the existing Dify VM to this service.
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Please open PowerShell as Administrator and run this script again.'
}
$ruleName = 'OpsPdfRagDify8765'
$existing = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    $address = $existing | Get-NetFirewallAddressFilter
    $port = $existing | Get-NetFirewallPortFilter
    if ($existing.Action -ne 'Allow' -or $existing.Direction -ne 'Inbound' -or
        $existing.Enabled -ne 'True' -or $address.LocalAddress -ne '192.168.24.1' -or
        $address.RemoteAddress -ne '192.168.24.133' -or $port.LocalPort -ne '8765' -or $port.Protocol -ne 'TCP') {
        throw 'An existing rule with this name has different settings; inspect it before changing anything.'
    }
    Write-Host 'The narrowly scoped Dify retrieval rule is already enabled.'
} else {
    New-NetFirewallRule -Name $ruleName -DisplayName 'Ops PDF RAG - Dify VM retrieval 8765' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -LocalAddress 192.168.24.1 -RemoteAddress 192.168.24.133 -Profile Any -Description 'Authenticated local retrieval for the existing Dify VM only' | Out-Null
    Write-Host 'Enabled: Dify VM 192.168.24.133 -> host 192.168.24.1 TCP 8765 only.'
}
