@echo off
rem Remove o servidor Bus Video; mantem videos e configuracao (pede permissao de administrador).
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"%~dp0desinstalar.ps1\"'"
