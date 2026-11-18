# Remove o servidor Bus Video: tarefa agendada, regra de firewall e programa.
# Os vídeos e a configuração (C:\BusVideo\data e \config) são MANTIDOS.
$TaskName = "Bus Video Servidor"
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*busvideo_server.main*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
foreach ($pt in @(443, 80, 8080)) { & netsh advfirewall firewall delete rule name="Bus Video $pt" | Out-Null }
Remove-Item -Recurse -Force "C:\BusVideo\venv" -ErrorAction SilentlyContinue
Write-Host "Servidor removido. Dados mantidos em C:\BusVideo\data e C:\BusVideo\config." -ForegroundColor Yellow
Read-Host "Tecle Enter para fechar"
