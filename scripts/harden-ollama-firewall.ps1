#requires -Version 5.1
<#
.SYNOPSIS
    Restrict host Ollama's port (11434) to the Docker subnet only, so it is NOT
    reachable from the LAN when the laptop roams onto untrusted networks.

.DESCRIPTION
    The hybrid architecture sets OLLAMA_HOST=0.0.0.0 so the API *container* can
    reach the host's Ollama via host.docker.internal. But 0.0.0.0 also exposes
    Ollama's UNAUTHENTICATED API on every interface (Wi-Fi included). Ollama has
    no built-in auth, so the only real control is at the network layer.

    Windows blocks unsolicited inbound traffic by default, so the exposure
    almost always comes from a broad "Allow" rule that the Ollama (or Docker)
    installer added for port 11434. This script does the following:

      1. Finds inbound Allow rules for the port whose scope is "Any" and
         DISABLES them (reversible - it does not delete third-party rules).
      2. Adds ONE scoped Allow rule that permits the port only from the Docker /
         WSL subnet(s). The default-block then covers the physical LAN.
      3. Records what it changed so -Revert can undo it cleanly.

    Run it in an ELEVATED PowerShell. It is idempotent - safe to re-run.

    TIP: run it while the stack is UP (a chat in flight) so it can detect the
    exact subnet the container connects from and write the tightest possible
    rule. With the stack down it falls back to the well-known Docker ranges.

.PARAMETER DockerSubnet
    One or more CIDR subnets to allow (e.g. "172.18.0.0/16"). Overrides
    auto-detection. Use this if auto-detection picks the wrong range.

.PARAMETER Port
    The Ollama port. Defaults to 11434.

.PARAMETER Audit
    Report the current inbound rules for the port and exit. Makes no changes.

.PARAMETER Revert
    Undo a previous run: remove this script's Allow rule and re-enable any rules
    it disabled.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\harden-ollama-firewall.ps1

.EXAMPLE
    # Inspect only, change nothing
    powershell -ExecutionPolicy Bypass -File .\scripts\harden-ollama-firewall.ps1 -Audit

.EXAMPLE
    # Force a specific subnet
    .\scripts\harden-ollama-firewall.ps1 -DockerSubnet "192.168.65.0/24","172.16.0.0/12"

.EXAMPLE
    # Undo everything this script did
    .\scripts\harden-ollama-firewall.ps1 -Revert
#>
[CmdletBinding()]
param(
    [string[]]$DockerSubnet,
    [int]$Port = 11434,
    [switch]$Audit,
    [switch]$Revert
)

$ErrorActionPreference = 'Stop'

$AllowRuleName = "EM_B Hybrid - Ollama (Docker only)"
$StateDir = Join-Path $env:LOCALAPPDATA 'em_b_hybrid'
$StateFile = Join-Path $StateDir 'ollama-firewall-state.json'


function Assert-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Error "This script changes Windows Firewall rules and must run in an elevated (Administrator) PowerShell."
        exit 1
    }
}


function Get-InboundAllowRulesForPort {
    # Returns the inbound Allow firewall rules that apply to $Port/TCP.
    Get-NetFirewallPortFilter -Protocol TCP |
        Where-Object { "$($_.LocalPort)" -eq "$Port" } |
        ForEach-Object { $_ | Get-NetFirewallRule } |
        Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Allow' }
}


function Show-Audit {
    Write-Host ""
    Write-Host "Inbound Allow rules for TCP/$Port :" -ForegroundColor Cyan
    $rules = Get-InboundAllowRulesForPort
    if (-not $rules) {
        Write-Host "  (none - the port is blocked from inbound by the default policy)"
        return
    }
    foreach ($r in $rules) {
        $scope = ($r | Get-NetFirewallAddressFilter).RemoteAddress -join ', '
        $flag = if ($scope -eq 'Any') { '  <-- OPEN TO ALL NETWORKS' } else { '' }
        $state = if ($r.Enabled -eq 'True') { 'enabled' } else { 'disabled' }
        Write-Host ("  [{0}] {1}`n        scope: {2}{3}" -f $state, $r.DisplayName, $scope, $flag)
    }
    Write-Host ""
}


function Get-DockerSubnets {
    # Best-effort detection of the subnet(s) the container reaches the host from.
    $found = New-Object System.Collections.Generic.List[string]

    # 1) Most accurate: live established connections to the port (needs the
    #    stack up with a request in flight).
    try {
        Get-NetTCPConnection -LocalPort $Port -State Established -ErrorAction Stop |
            Where-Object { $_.RemoteAddress -notin @('127.0.0.1', '::1') -and $_.RemoteAddress -match '^\d+\.\d+\.\d+\.\d+$' } |
            ForEach-Object {
                $p = $_.RemoteAddress.Split('.')
                $found.Add(("{0}.{1}.{2}.0/24" -f $p[0], $p[1], $p[2]))
            }
    } catch {}

    # 2) Docker Desktop / WSL virtual adapters on the host.
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.InterfaceAlias -match 'WSL|Docker|vEthernet' } |
        ForEach-Object {
            $p = $_.IPAddress.Split('.')
            $found.Add(("{0}.{1}.{2}.0/24" -f $p[0], $p[1], $p[2]))
        }

    # 3) Well-known Docker Desktop VM network (last-resort fallback).
    $found.Add('192.168.65.0/24')

    return ($found | Select-Object -Unique)
}


function Invoke-Revert {
    if (-not (Test-Path $StateFile)) {
        Write-Host "No state file found ($StateFile). Nothing recorded to revert." -ForegroundColor Yellow
        # Still remove our allow rule if it happens to exist.
    } else {
        $state = Get-Content $StateFile -Raw | ConvertFrom-Json
        foreach ($name in @($state.DisabledRules)) {
            try {
                Enable-NetFirewallRule -Name $name -ErrorAction Stop
                Write-Host "Re-enabled previously disabled rule: $name"
            } catch {
                Write-Host "Could not re-enable rule '$name' (it may have been removed): $($_.Exception.Message)" -ForegroundColor Yellow
            }
        }
        Remove-Item $StateFile -Force
    }

    Get-NetFirewallRule -DisplayName $AllowRuleName -ErrorAction SilentlyContinue |
        ForEach-Object {
            Remove-NetFirewallRule -Name $_.Name
            Write-Host "Removed scoped allow rule: $($_.DisplayName)"
        }

    Write-Host "Revert complete." -ForegroundColor Green
}


# ---- main ------------------------------------------------------------------

Assert-Admin

if ($Audit) {
    Show-Audit
    return
}

if ($Revert) {
    Invoke-Revert
    Show-Audit
    return
}

Write-Host "BEFORE:" -ForegroundColor Cyan
Show-Audit

# 1) Disable any broad ("Any") inbound Allow rules for the port (reversible).
$disabledNames = @()
foreach ($rule in Get-InboundAllowRulesForPort) {
    if ($rule.DisplayName -eq $AllowRuleName) { continue }   # never touch our own
    if ($rule.Enabled -ne 'True') { continue }
    $scope = ($rule | Get-NetFirewallAddressFilter).RemoteAddress
    if ($scope -contains 'Any') {
        Disable-NetFirewallRule -Name $rule.Name
        $disabledNames += $rule.Name
        Write-Host "Disabled broad (Any-scope) allow rule: $($rule.DisplayName)" -ForegroundColor Yellow
    }
}

# 2) Resolve the subnets to allow.
if ($DockerSubnet) {
    $subnets = $DockerSubnet
    Write-Host "Using subnets from -DockerSubnet: $($subnets -join ', ')"
} else {
    $subnets = Get-DockerSubnets
    Write-Host "Auto-detected Docker subnet(s): $($subnets -join ', ')"
    $liveDetected = $false
    try {
        $liveDetected = [bool](Get-NetTCPConnection -LocalPort $Port -State Established -ErrorAction Stop |
            Where-Object { $_.RemoteAddress -notin @('127.0.0.1', '::1') })
    } catch {}
    if (-not $liveDetected) {
        Write-Host "  NOTE: the stack didn't appear to be connected, so this used fallback ranges." -ForegroundColor Yellow
        Write-Host "        For the tightest rule, start the stack, send one chat, and re-run this script." -ForegroundColor Yellow
    }
}

# 3) (Re)create our single scoped allow rule.
Get-NetFirewallRule -DisplayName $AllowRuleName -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-NetFirewallRule -Name $_.Name }

New-NetFirewallRule -DisplayName $AllowRuleName `
    -Direction Inbound -Protocol TCP -LocalPort $Port `
    -RemoteAddress $subnets -Action Allow -Profile Any | Out-Null
Write-Host "Created scoped allow rule '$AllowRuleName' for: $($subnets -join ', ')" -ForegroundColor Green

# 4) Persist what we changed so -Revert can undo it.
if (-not (Test-Path $StateDir)) { New-Item -ItemType Directory -Path $StateDir | Out-Null }
[pscustomobject]@{
    AllowRuleName = $AllowRuleName
    DisabledRules = $disabledNames
    Subnets       = $subnets
    Port          = $Port
    Timestamp     = (Get-Date).ToString('o')
} | ConvertTo-Json | Set-Content -Path $StateFile -Encoding utf8

Write-Host ""
Write-Host "AFTER:" -ForegroundColor Cyan
Show-Audit

Write-Host "Done. Now VERIFY both halves:" -ForegroundColor Green
Write-Host "  1. App still works:  send a chat through the running stack (the container path must still reach Ollama)."
Write-Host "  2. LAN is closed:    from another device on the SAME network, run"
Write-Host "                         curl http://<this-laptop-ip>:11434/api/version"
Write-Host "                       it should TIME OUT / be refused."
Write-Host ""
Write-Host "If step 1 fails, the allowed subnet is too tight - re-run with the stack up, or pass -DockerSubnet."
Write-Host "To undo everything:  .\scripts\harden-ollama-firewall.ps1 -Revert"
