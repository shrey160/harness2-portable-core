param(
    [Parameter(Position=0)]
    [ValidateSet('setup','test','demo','reliability','run','status','stop')]
    [string]$Action = 'demo',
    [string]$Distro = 'Ubuntu',
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$JobArguments
)
$ErrorActionPreference = 'Stop'
$taskSource = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskConverted = & wsl -d $Distro -- wslpath -a ($taskSource.Replace('\', '/'))
if ($LASTEXITCODE -ne 0) { throw 'Could not resolve this project in WSL.' }
$taskLinuxSource = ($taskConverted -join '').Trim()
& wsl -d $Distro -- bash "$taskLinuxSource/scripts/launch.sh" $taskLinuxSource $Action @JobArguments
exit $LASTEXITCODE
