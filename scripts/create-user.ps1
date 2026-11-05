param([ValidateSet('admin','user')][string]$Role = 'admin')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCommand) { $dockerExecutable = $dockerCommand.Source }
else {
    $dockerExecutable = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'
    if (-not (Test-Path -LiteralPath $dockerExecutable)) { throw 'Docker não encontrado. Adicione sua instalação ao PATH.' }
    $env:PATH = (Split-Path -Parent $dockerExecutable) + ';' + $env:PATH
}
& $dockerExecutable compose exec api jurisassist create-user --role $Role
if ($LASTEXITCODE -ne 0) { throw 'Não foi possível criar o usuário.' }
