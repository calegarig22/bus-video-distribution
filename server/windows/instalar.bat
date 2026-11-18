@echo off
rem Instala o servidor Bus Video neste PC com Windows. Clique duas vezes e aceite o pedido de administrador.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"%~dp0instalar.ps1\"'"
