# Para o servidor Bus Video. Para ligar de novo: iniciar.bat (em C:\BusVideo) ou reinicie o PC.
$TaskName = "Bus Video Servidor"
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*busvideo_server.main*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Write-Host "Servidor parado. Para ligar de novo: C:\BusVideo\iniciar.bat ou reinicie o PC." -ForegroundColor Yellow
Read-Host "Tecle Enter para fechar"
