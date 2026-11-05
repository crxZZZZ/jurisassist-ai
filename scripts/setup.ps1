param([switch]$SkipModel)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    $dockerBin = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin'
    if (Test-Path -LiteralPath (Join-Path $dockerBin 'docker.exe')) { $env:PATH = "$dockerBin;$env:PATH" }
}
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    $ollamaBin = Join-Path $env:LOCALAPPDATA 'Programs\Ollama'
    if (Test-Path -LiteralPath (Join-Path $ollamaBin 'ollama.exe')) { $env:PATH = "$ollamaBin;$env:PATH" }
}
$freeBytes = [System.IO.DriveInfo]::new((Get-Location).Drive.Root).AvailableFreeSpace
if ($freeBytes -lt 15GB) { throw 'Reserve pelo menos 15 GiB livres antes da instalação.' }
foreach ($program in @('docker','ollama')) {
    if (-not (Get-Command $program -ErrorAction SilentlyContinue)) { throw "Instale $program e execute novamente. Consulte o README." }
}
if (-not (Test-Path -LiteralPath '.env')) {
    $passwordBytes = New-Object byte[] 24
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($passwordBytes)
    $rng.Dispose()
    $databasePassword = [Convert]::ToBase64String($passwordBytes).Replace('+','-').Replace('/','_').TrimEnd('=')
    (Get-Content -LiteralPath '.env.example' -Raw).Replace('change-this-local-password',$databasePassword) | Set-Content -LiteralPath '.env' -Encoding utf8
}
docker info --format '{{.ServerVersion}}'
if ($LASTEXITCODE -ne 0) { throw 'Inicie o Docker Desktop e tente novamente.' }
try { Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null }
catch {
    Start-Process -FilePath (Get-Command ollama).Source -ArgumentList 'serve' -WindowStyle Hidden
    $ollamaReady = $false
    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null
            $ollamaReady = $true
            break
        } catch { }
    }
    if (-not $ollamaReady) { throw 'O Ollama não iniciou. Abra o aplicativo e tente novamente.' }
}
if (-not $SkipModel) {
    ollama pull qwen3:4b
    if ($LASTEXITCODE -ne 0) { throw 'O download do modelo falhou.' }
}
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { throw 'A inicialização do Compose falhou. Consulte docker compose logs.' }
Write-Host 'Aplicação: http://localhost:8080'
Write-Host 'Crie seu usuário: docker compose exec api jurisassist create-user'
Write-Host 'Revise e aprove as fontes na área Administração.'
