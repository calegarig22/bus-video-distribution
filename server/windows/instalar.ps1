# Instala/atualiza o servidor Bus Video num PC com Windows 10/11.
# Executar por instalar.bat (que pede permissão de administrador). Rodar de novo atualiza sem apagar dados.
#
# O que faz:
#   1. Encontra o Python 3 (ou instala pelo winget)
#   2. Cria C:\BusVideo\venv e instala o servidor + ffprobe embutido (static-ffmpeg)
#   3. Gera C:\BusVideo\config\server.env (senhas do operador e do administrador, chaves) se ainda não existir
#   4. Libera a porta no firewall do Windows
#   5. Registra uma tarefa agendada que liga o servidor junto com o Windows (sem login)
#   6. Impede o PC de dormir e mostra o endereço e o DEVICE_TOKEN

$ErrorActionPreference = "Stop"
trap { Write-Host "ERRO: $_" -ForegroundColor Red; Read-Host "Tecle Enter para fechar"; exit 1 }
$Base      = "C:\BusVideo"
$Port      = 443          # HTTPS
$HttpPort  = 80           # só redireciona para HTTPS e entrega o ca.crt
$TlsDir    = "C:\BusVideo\config\tls"
$TaskName  = "Bus Video Servidor"
$ServerSrc = Split-Path -Parent $PSScriptRoot        # ...\raspberry\server
$Venv      = "$Base\venv"
$Py        = "$Venv\Scripts\python.exe"
$Conf      = "$Base\config\server.env"

function Info($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Fail($m) { Write-Host "ERRO: $m" -ForegroundColor Red; Read-Host "Tecle Enter para fechar"; exit 1 }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Fail "Execute pelo instalar.bat (ele pede permissão de administrador)."
}
if (-not (Test-Path "$ServerSrc\pyproject.toml") -or -not (Test-Path "$ServerSrc\busvideo_server")) {
    Fail "Pasta do servidor não encontrada em $ServerSrc. Mantenha este script dentro de raspberry\server\windows."
}

# ---------- 1. Python ----------
function Find-Python {
    foreach ($cmd in @("py -3", "python", "python3")) {
        try {
            $v = & cmd /c "$cmd -c ""import sys;print(sys.version_info[0]*100+sys.version_info[1])""" 2>$null
            if ($LASTEXITCODE -eq 0 -and [int]$v -ge 310) { return $cmd }
        } catch {}
    }
    return $null
}
Info "Procurando o Python 3.10 ou mais novo"
$SysPy = Find-Python
if (-not $SysPy) {
    Info "Python não encontrado. Tentando instalar pelo winget (precisa de internet)..."
    try {
        & winget install --id Python.Python.3.12 -e --scope machine --accept-source-agreements --accept-package-agreements --silent
    } catch {}
    # recarrega o PATH desta janela
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    $SysPy = Find-Python
    if (-not $SysPy) {
        Fail "Não consegui instalar o Python automaticamente. Instale pelo site python.org (marque 'Add python.exe to PATH') e rode o instalar.bat de novo."
    }
}
Info "Python encontrado: $SysPy"

# ---------- 2. Ambiente e pacotes ----------
New-Item -ItemType Directory -Force -Path $Base, "$Base\config", "$Base\data", "$Base\logs" | Out-Null
if (-not (Test-Path $Py)) {
    Info "Criando o ambiente em $Venv"
    & cmd /c "$SysPy -m venv ""$Venv"""
    if ($LASTEXITCODE -ne 0) { Fail "Falha ao criar o ambiente Python." }
}
Info "Instalando o servidor e o ffprobe embutido (precisa de internet; 1 a 3 minutos)"
& $Py -m pip install --quiet --upgrade pip
& $Py -m pip install --quiet --upgrade "${ServerSrc}[windows]"
if ($LASTEXITCODE -ne 0) { Fail "Falha ao instalar os pacotes. Verifique a internet e rode de novo." }
# static-ffmpeg imprime o progresso do download no stdout; o caminho é a última linha
$FfprobeOut = @(& $Py -c "import static_ffmpeg.run as r; print(r.get_or_fetch_platform_executables_else_raise()[1])")
$FfprobePath = [string]($FfprobeOut | Select-Object -Last 1)
$FfprobePath = $FfprobePath.Trim()
if ($LASTEXITCODE -ne 0 -or -not $FfprobePath -or -not (Test-Path $FfprobePath)) { Fail "Não consegui baixar o ffprobe. Verifique a internet e rode de novo." }
Info "ffprobe em $FfprobePath"

# ---------- 3. Configuração ----------
if (-not (Test-Path $Conf)) {
    Write-Host ""
    function Read-Password([string]$Label) {
        Write-Host $Label -ForegroundColor Yellow
        $s1 = Read-Host "Senha" -AsSecureString
        $s2 = Read-Host "Repita a senha" -AsSecureString
        $a = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s1))
        $b = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s2))
        if ($a -ne $b -or $a.Length -lt 8) { Fail "As senhas não conferem ou são curtas demais (mínimo 8 caracteres)." }
        return $a
    }
    $p1 = Read-Password "Senha do OPERADOR (usuário: operador). Uso diário do painel: publicar vídeo e acompanhar a frota."
    Write-Host ""
    $p3 = Read-Password "Senha do ADMINISTRADOR (usuário: admin). Só para o responsável técnico: redefine a senha do operador se ela for esquecida."
    $envBlock = & $Py -m busvideo_server.tools gen-env $p1 $p3
    if ($LASTEXITCODE -ne 0) { Fail "Falha ao gerar a configuração." }
    $extra = @(
        "BUSVIDEO_HOST=0.0.0.0",
        "BUSVIDEO_PORT=$Port",
        "BUSVIDEO_TLS_CERT=$TlsDir\server.crt",
        "BUSVIDEO_TLS_KEY=$TlsDir\server.key",
        "BUSVIDEO_HTTP_REDIRECT_PORT=$HttpPort",
        "BUSVIDEO_DATA_DIR=$Base\data",
        "BUSVIDEO_LOG_DIR=$Base\logs",
        "FFPROBE_BIN=$FfprobePath",
        "PRODUCT_NAME=Bus Video",
        "COMPANY_NAME=Empresa Exemplo"
    )
    ($envBlock + $extra) | Set-Content -Path $Conf -Encoding UTF8
    Info "Configuração criada em $Conf"
} else {
    # atualiza só o caminho do ffprobe (pode mudar quando o pacote é atualizado) e conserta acentos gravados errado por versões antigas
    $lines = @(Get-Content $Conf -Encoding UTF8 | Where-Object { $_ -notmatch '^(FFPROBE_BIN|BUSVIDEO_TLS_CERT|BUSVIDEO_TLS_KEY|BUSVIDEO_HTTP_REDIRECT_PORT)=' } | ForEach-Object {
        if ($_ -match '^PRODUCT_NAME=.*Ã') { "PRODUCT_NAME=Bus Video" }
        elseif ($_ -match '^BUSVIDEO_PORT=') { "BUSVIDEO_PORT=$Port" }      # migra instalações antigas (8080) para HTTPS 443
        else { $_ } })
    ($lines + @("FFPROBE_BIN=$FfprobePath", "BUSVIDEO_TLS_CERT=$TlsDir\server.crt", "BUSVIDEO_TLS_KEY=$TlsDir\server.key",
                "BUSVIDEO_HTTP_REDIRECT_PORT=$HttpPort")) | Set-Content -Path $Conf -Encoding UTF8
    Info "Configuração existente mantida ($Conf); HTTPS na porta $Port"
}

# ---------- 3b. Certificados HTTPS (CA da garagem + certificado do servidor) ----------
Info "Gerando/renovando os certificados HTTPS em $TlsDir"
$ipArgs = @()
foreach ($ip in (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } | Select-Object -ExpandProperty IPAddress)) { $ipArgs += @("--ip", $ip) }
$dnsArgs = @(); $hostName = [System.Net.Dns]::GetHostName(); if ($hostName) { $dnsArgs = @("--dns", $hostName) }
& $Py -m busvideo_server.tools gen-cert --out $TlsDir @dnsArgs @ipArgs
if ($LASTEXITCODE -ne 0) { Fail "Falha ao gerar os certificados HTTPS." }
# Toda a pasta só para SYSTEM e Administradores: nenhum outro usuário local pode alterar o programa, os scripts
# que rodam com privilégio, a configuração (senha, chaves, certificados) ou os vídeos.
& icacls "$Base" /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" 2>$null | Out-Null
Copy-Item "$TlsDir\ca.crt" "$Base\ca.crt" -Force      # cópia pública, fácil de achar, para PCs/celulares/ônibus

# ---------- 3c. Pasta "pendrive": tudo que o primeiro Raspberry precisa ----------
$Pen = "$Base\pendrive"; $ClientSrc = Join-Path (Split-Path -Parent $ServerSrc) "client"
if (Test-Path "$ClientSrc\install_client.sh") {
    Info "Preparando a pasta $Pen (copie-a inteira para um pendrive e leve ao primeiro Raspberry)"
    New-Item -ItemType Directory -Force -Path $Pen | Out-Null
    Remove-Item -Recurse -Force "$Pen\client" -ErrorAction SilentlyContinue
    Copy-Item -Recurse "$ClientSrc" "$Pen\client"
    Get-ChildItem -Recurse "$Pen\client" -Include "__pycache__" -Directory | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item "$ClientSrc\instalar-onibus.sh" "$Pen\instalar-onibus.sh" -Force
    Copy-Item "$TlsDir\ca.crt" "$Pen\ca.crt" -Force
    $tokenNow = (Get-Content $Conf -Encoding UTF8 | Where-Object { $_ -match '^DEVICE_TOKEN=' }) -replace '^DEVICE_TOKEN=', ''
    $firstIp = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } | Select-Object -First 1 -ExpandProperty IPAddress)
    @(
        "# Dados da garagem lidos pelo assistente instalar-onibus.sh (nao precisa editar)",
        "SERVER_URL=https://$firstIp",
        "DEVICE_TOKEN=$tokenNow",
        "# Opcional: preencha para o assistente nao perguntar",
        "WIFI_SSID=",
        "WIFI_PSK="
    ) | Set-Content -Path "$Pen\garagem.txt" -Encoding ASCII
    # Arquivos de texto para Linux: fim de linha LF
    foreach ($f in @("$Pen\garagem.txt", "$Pen\instalar-onibus.sh") + (Get-ChildItem -Recurse "$Pen\client" -Include "*.sh","*.service","*.conf","*.example","*.py" -File | ForEach-Object { $_.FullName })) {
        $fp = (Resolve-Path $f).ProviderPath
        $txt = [IO.File]::ReadAllText($fp) -replace "`r`n", "`n"; [IO.File]::WriteAllText($fp, $txt, (New-Object System.Text.UTF8Encoding($false)))
    }
}

# ---------- 4. Scripts de controle ----------
@"
@echo off
rem Liga o servidor Bus Video (usado pela tarefa agendada; pode ser executado manualmente)
set BUSVIDEO_SERVER_ENV=$Conf
cd /d "$Base"
"$Py" -m busvideo_server.main >> "$Base\logs\console.log" 2>&1
"@ | Set-Content -Path "$Base\iniciar.bat" -Encoding ASCII
foreach ($f in @("parar.bat", "parar.ps1", "desinstalar.bat", "desinstalar.ps1")) { Copy-Item "$PSScriptRoot\$f" "$Base\$f" -Force }

# Frota pela rede: atalho e lista de exemplo (para ônibus que já têm Raspberry na rede da garagem)
@"
@echo off
rem Instala/verifica os onibus PELA REDE. Exemplos:
rem   frota.bat descobrir --rede 192.168.100.0/24
rem   frota.bat instalar --lista C:\BusVideo\frota.csv --usuario pi --so BUS-001 --benchmark
rem   frota.bat instalar --lista C:\BusVideo\frota.csv --usuario pi
rem   frota.bat verificar --lista C:\BusVideo\frota.csv --usuario pi
"$Py" -m busvideo_server.fleet %*
"@ | Set-Content -Path "$Base\frota.bat" -Encoding ASCII
if (-not (Test-Path "$Base\frota.csv")) {
    @("# Um onibus por linha: NUMERO,ENDERECO (IP ou nome na rede). Linhas com # sao ignoradas.", "# BUS-001,192.168.100.51", "# BUS-002,192.168.100.52") | Set-Content -Path "$Base\frota.csv" -Encoding ASCII
}

# ---------- 5. Firewall ----------
Info "Liberando as portas $Port (HTTPS) e $HttpPort (redirecionamento) no firewall do Windows"
foreach ($pt in @($Port, $HttpPort, 8080)) { & netsh advfirewall firewall delete rule name="Bus Video $pt" | Out-Null }
& netsh advfirewall firewall add rule name="Bus Video $Port" dir=in action=allow protocol=TCP localport=$Port | Out-Null
& netsh advfirewall firewall add rule name="Bus Video $HttpPort" dir=in action=allow protocol=TCP localport=$HttpPort | Out-Null

# ---------- 6. Tarefa agendada (liga com o Windows, sem login) ----------
Info "Registrando a tarefa '$TaskName' (inicia com o Windows)"
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*busvideo_server.main*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
$action    = New-ScheduledTaskAction -Execute "$Base\iniciar.bat" -WorkingDirectory $Base
$trigger   = New-ScheduledTaskTrigger -AtStartup
$settings  = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$settings.ExecutionTimeLimit = "PT0S"     # sem limite de tempo (fica rodando para sempre)
# Conta de serviço: NETWORK SERVICE (sem privilégio) quando o Python está instalado para a máquina toda;
# com Python instalado só para o usuário, NETWORK SERVICE não consegue ler os arquivos dele e usa-se SYSTEM.
$PyBase = & cmd /c "$SysPy -c ""import sys;print(sys.base_prefix)"""
$machinePython = $false
foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramData, "C:\Python")) {
    if ($root -and $PyBase -and $PyBase.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { $machinePython = $true }
}
if ($machinePython) {
    & icacls "$Base" /grant:r "*S-1-5-20:(OI)(CI)RX" 2>$null | Out-Null
    foreach ($d in @("$Base\data", "$Base\logs")) { & icacls $d /grant:r "*S-1-5-20:(OI)(CI)M" 2>$null | Out-Null }
    $principal = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\NETWORK SERVICE" -LogonType ServiceAccount -RunLevel Limited
    Info "Servidor vai rodar como NETWORK SERVICE (conta sem privilégio)"
} else {
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    Write-Host "Aviso: Python instalado só para o usuário atual; o servidor vai rodar como SYSTEM. Para usar uma conta sem privilégio, reinstale o Python marcando 'Install for all users'." -ForegroundColor Yellow
}
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

# ---------- 7. Energia ----------
Info "Impedindo o PC de dormir (suspensão e hibernação desligadas na tomada)"
& powercfg /change standby-timeout-ac 0 | Out-Null
& powercfg /change hibernate-timeout-ac 0 | Out-Null

# ---------- 8. Verificação ----------
function Test-Port([int]$p) {
    try { $c = New-Object System.Net.Sockets.TcpClient; $c.Connect("127.0.0.1", $p); $c.Close(); return $true } catch { return $false }
}
function Wait-Server([int]$tries) {
    for ($i = 0; $i -lt $tries; $i++) { if (Test-Port $Port) { return $true }; Start-Sleep -Milliseconds 500 }
    return $false
}
Info "Aguardando o servidor responder na porta $Port (até 30 s)"
$ok = Wait-Server 60
if (-not $ok -and $machinePython) {
    Write-Host "Servidor não subiu como NETWORK SERVICE; registrando a tarefa como SYSTEM." -ForegroundColor Yellow
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    $ok = Wait-Server 40
}
if (-not $ok) {
    Write-Host "A tarefa agendada não deixou o servidor no ar. Iniciando diretamente para diagnosticar..." -ForegroundColor Yellow
    Start-Process -FilePath "$Base\iniciar.bat" -WorkingDirectory $Base
    $ok = Wait-Server 40
}
if (-not $ok) {
    Write-Host ""
    Write-Host "---------- DIAGNÓSTICO ----------" -ForegroundColor Red
    try { $ti = Get-ScheduledTaskInfo -TaskName $TaskName; Write-Host "Tarefa: última execução $($ti.LastRunTime), resultado $($ti.LastTaskResult)" } catch {}
    foreach ($lf in @("$Base\logs\console.log", "$Base\logs\server.log")) {
        if (Test-Path $lf) { Write-Host "--- $lf (últimas linhas) ---"; Get-Content $lf -Tail 25 | ForEach-Object { Write-Host "  $_" } }
        else { Write-Host "--- $lf não existe (o servidor nem chegou a iniciar) ---" }
    }
    Write-Host "Teste manual: clique duas vezes em $Base\iniciar.bat e leia a mensagem." -ForegroundColor Yellow
    Fail "O servidor não respondeu. Fotografe esta janela."
}
# saúde por HTTP, sem passar por proxy (só informativo)
try {
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }   # só para este teste local; o certificado é da nossa CA
    $req = [System.Net.WebRequest]::Create("https://127.0.0.1:$Port/api/health"); $req.Proxy = $null; $req.Timeout = 3000
    $resp = $req.GetResponse(); $sr = New-Object System.IO.StreamReader($resp.GetResponseStream()); Info ("Servidor: " + $sr.ReadToEnd()); $resp.Close()
} catch { Write-Host "Aviso: porta aberta, mas a resposta HTTP falhou ($($_.Exception.Message))." -ForegroundColor Yellow }

$ips = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } | Select-Object -ExpandProperty IPAddress)
$token = (Get-Content $Conf | Where-Object { $_ -match '^DEVICE_TOKEN=' }) -replace '^DEVICE_TOKEN=', ''

Write-Host ""
Write-Host "==================================================================" -ForegroundColor Green
Write-Host " SERVIDOR Bus Video INSTALADO E NO AR" -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Green
Write-Host " Painel neste PC : https://localhost"
foreach ($ip in $ips) { Write-Host " Painel na rede  : https://$ip" }
Write-Host " Operador        : operador   (uso diário; senha: a primeira que você escolheu)"
Write-Host " Administrador   : admin      (suporte; redefine a senha do operador pelo botão Senha do painel)"
Write-Host " Esqueceu a do admin? PowerShell como administrador: `$env:BUSVIDEO_SERVER_ENV='$Conf'; & '$Py' -m busvideo_server.tools set-password admin"
Write-Host ""
Write-Host " DEVICE_TOKEN (copie para o instalador de CADA ônibus):" -ForegroundColor Yellow
Write-Host " $token" -ForegroundColor Yellow
Write-Host ""
Write-Host " Certificado     : $Base\ca.crt  (instale nos PCs/celulares dos operadores e copie para cada ônibus)" -ForegroundColor Yellow
Write-Host "                   também em http://$($ips | Select-Object -First 1)/ca.crt"
Write-Host " Pendrive        : copie a pasta $Base\pendrive para um pendrive e leve ao primeiro Raspberry" -ForegroundColor Yellow
Write-Host " Pela rede       : $Base\frota.bat  (onibus que ja tem Raspberry na rede: descobrir / instalar / verificar)"
Write-Host " Pasta           : $Base   (config, data, logs, iniciar.bat, parar.bat, desinstalar.bat)"
Write-Host " O servidor liga sozinho quando o Windows liga, mesmo sem ninguém fazer login."
Write-Host "==================================================================" -ForegroundColor Green
Write-Host ""
Read-Host "Tecle Enter para fechar"
