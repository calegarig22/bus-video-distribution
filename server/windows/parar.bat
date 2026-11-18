@echo off
rem Para o servidor Bus Video (pede permissao de administrador).
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"%~dp0parar.ps1\"'"
