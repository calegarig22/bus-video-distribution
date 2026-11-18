# Troubleshooting

Regra geral: em qualquer falha, o ônibus continua com o último vídeo válido. Os problemas abaixo afetam a atualização ou a instalação, não a reprodução em curso, salvo onde indicado.

## Como ler os logs

| Onde | Comando |
|---|---|
| Sync (Pi) | `journalctl -u busvideo-sync -f` ou `tail -f /opt/busvideo-player/logs/sync.log` |
| Player (Pi) | `journalctl -u busvideo-player -f` ou `tail -f /opt/busvideo-player/logs/player.log` |
| Servidor | `journalctl -u busvideo-server -f` ou `tail -f /opt/busvideo-server/logs/server.log` |
| Estado do Pi | `cat /opt/busvideo-player/state/state.json` e `player_status.json` |
| Interface | Coluna **Observação** da lista de dispositivos mostra `last_error` |

Linhas típicas do `busvideo-sync`:

```
INFO Server detected at https://192.168.100.10 (Bus Video v0.1.0)
INFO Local version: 11 | Server version: 12
INFO Download started: version 12, 850123456 bytes
INFO Download progress: 40% (324/810 MB)
INFO Download finished: 850123456 bytes in 210.3s (32.3 Mbps)
INFO Validating download (size, SHA-256, format)
INFO SHA256 validated
INFO Format validated (ffprobe)
INFO Video updated: current.mp4 -> video_v12.mp4
INFO Video updated: v11 -> v12
INFO Removed old version(s): v10
INFO No network; playback continues with local video (further attempts logged every 10 min)
INFO Server unavailable (...) for 180 min (36 attempts)
WARN Download interrupted (connection lost: ...); will resume on next contact
WARN Insufficient disk space; removing rollback copy video_v11.mp4
ERROR SHA256 mismatch: expected 9f2c…, got 1a7b…
ERROR Insufficient disk space: need 1150 MB, free 400 MB
ERROR Server rejected device token (401); check DEVICE_TOKEN
ERROR ffprobe rejected file: ...
WARN Version 12 failed 3 times; waiting cooldown before retrying
```

Linhas típicas do `busvideo-player`:

```
INFO Player started: /opt/busvideo-player/media/versions/video_v11.mp4
INFO New content detected: video_v12.mp4 (switch mode: end_of_loop)
INFO Switching player to video_v12.mp4
INFO Player restarted with new video: video_v12.mp4
ERROR Player not running (restart #1)
ERROR Player stalled for 15s at position 42.0; restarting
ERROR Player could not load video_v12.mp4; rolling back
WARN Rolled back current.mp4 -> video_v11.mp4
ERROR Player failed to start with video_v12.mp4: mpv not installed
```

## Tela e player

| Sintoma | Causa provável | Como verificar | Solução |
|---|---|---|---|
| Tela preta, serviço ativo | Distribuidor HDMI ligou depois do Pi ou EDID inválido | `cat /sys/class/drm/card*-HDMI*/status`; `journalctl -u busvideo-player` | `hdmi_force_hotplug=1` e modo fixo em `/boot/firmware/config.txt`; reboot |
| Tela preta, `Player failed to start ... mpv not installed` | mpv ausente | `which mpv` | `apt install mpv` ou `install_client.sh --offline-debs` |
| `mpv exited immediately` | Sem DRM (`/dev/dri` ausente) ou sem permissão | `ls /dev/dri`; `groups busvideo` (precisa de `video` e `render`) | Confirmar `dtoverlay=vc4-kms-v3d`; `usermod -aG video,render busvideo`; reboot |
| Player reinicia em loop, `restart #N` crescendo | Arquivo incompatível com o hwdec ou mpv sem v4l2m2m | `journalctl -u busvideo-player`; testar manualmente: `mpv --vo=gpu --gpu-context=drm --hwdec=v4l2m2m-copy ARQUIVO` | Após 5 falhas o supervisor faz rollback sozinho. Rode `benchmark-player.sh`; ajuste `MPV_EXTRA_ARGS` ou a política de mídia |
| Vídeo travando ou pulando frames | Decodificação por software (sem `/dev/video10`), bitrate alto, SD lento ou download simultâneo | `ls /dev/video*`; `top` durante reprodução; `vcgencmd get_throttled` | Confirmar decodificador; reduzir bitrate/resolução no servidor (`MEDIA_MAX_*`); `DOWNLOAD_RATE_LIMIT_MBPS=20`; cartão A1/A2 |
| Vídeo trava e volta | `Player stalled` no log | `journalctl -u busvideo-player` | Normal como recuperação. Se frequente: throttling térmico ou SD com defeito |
| Vídeo não troca depois de publicar | `SWITCH_MODE=end_of_loop` espera o fim do vídeo | `cat state/player_status.json`; `ls -l media/current.mp4` | Esperar um loop, ou `SWITCH_MODE=immediate` |
| Sem áudio | `AUDIO=off` (padrão) | `client.env` | `AUDIO=alsa` ou `auto` e `hdmi_drive=2` no `config.txt` |

## Sincronização

| Sintoma | Causa provável | Como verificar | Solução |
|---|---|---|---|
| Ônibus aparece **Offline** na garagem | Sem Wi-Fi, SSID/senha errados, servidor inalcançável, sync parado | `ip addr show wlan0`; `iw wlan0 link`; `curl https://IP/api/health`; `systemctl status busvideo-sync` | `scripts/wifi-setup.sh SSID PSK`; conferir `SERVER_URLS`; `systemctl restart busvideo-sync` |
| **Pendente** que nunca atualiza | Token errado, URL errada, sem espaço, cooldown após 3 falhas, hash divergente | `cat state/state.json` (`last_error`, `failures`); `journalctl -u busvideo-sync` | Ver linhas abaixo |
| `Server rejected device token` | `DEVICE_TOKEN` diferente | Comparar `client.env` com `server.env` | Corrigir e `systemctl restart busvideo-sync` |
| `Server unavailable` com Wi-Fi ok | Porta errada, firewall, servidor parado | `curl -v https://IP/api/health` do Pi | `systemctl status busvideo-server`; `ufw status` no servidor |
| `Insufficient disk space` | Cartão pequeno ou vídeo grande | `df -h /opt/busvideo-player`; `ls -l media/versions` | `KEEP_VERSIONS=1`; reduzir `MEDIA_MAX_SIZE_MB`; cartão maior |
| `SHA256 mismatch` repetido | Arquivo no servidor corrompido ou proxy alterando bytes | No servidor: `sha256sum data/videos/versions/video_N.mp4` vs banco | Reenviar o vídeo e publicar de novo |
| `waiting cooldown before retrying` | 3 falhas na mesma versão | `state.json` → `failures` | Corrigir a causa. Para forçar agora: editar `state.json` removendo `failures` e `systemctl restart busvideo-sync` |
| `Download interrupted` sempre no mesmo ponto | Wi-Fi caindo (power-save) ou ônibus saindo | `journalctl -u busvideo-sync`; `iw wlan0 get power_save` | `iw wlan0 set power_save off` (o instalador já faz); AP 5 GHz; retomada resolve ao voltar |
| `ffprobe rejected file` no Pi | Servidor aceitou algo que o Pi não lê, ou `ffmpeg` ausente no Pi | `which ffprobe` no Pi | Instalar `ffmpeg`; ou `VALIDATE_FORMAT=mpv` |
| Versão local maior que a do servidor | Servidor reinstalado sem restaurar `data/` | Comparar `state.json` com `/api/video/latest` | Publicar de novo no servidor (gera número maior) ou restaurar backup |

## Servidor e interface

| Sintoma | Causa provável | Como verificar | Solução |
|---|---|---|---|
| Página não abre | Serviço parado, porta ou firewall | `systemctl status busvideo-server`; `ss -ltnp \| grep 8080`; `ufw status` | `systemctl restart busvideo-server`; `ufw allow 8080/tcp` |
| Login falha sempre | Nenhuma conta com senha (`*_PASSWORD_HASH` vazios) ou senha trocada e esquecida | `journalctl -u busvideo-server \| grep -i senha` | `tools set-password operador` / `admin` no servidor (vale na hora, sem restart) |
| Operador esqueceu a senha | — | — | `admin` entra no painel → botão Senha → conta `operador` → nova senha |
| Erro 429 no login | 5 tentativas erradas em 1 min | Esperar 1 minuto | Conferir senha |
| Sessão cai a cada reinício | `SECRET_KEY` vazio | `server.env` | Definir `SECRET_KEY` fixo (`tools gen-token`) |
| Upload rejeitado: codec não suportado | Vídeo em HEVC/VP9/MPEG-4 | Cartão de validação | Exportar em H.264 |
| Upload rejeitado: resolução / FPS / level | Acima da política | Cartão de validação | Reexportar 1920x1080, 30 fps, level ≤ 4.1 ou ajustar `MEDIA_MAX_*` se o benchmark permitir |
| Upload rejeitado: áudio | MP3/AC3 | Cartão de validação | AAC ou sem áudio |
| Upload rejeitado: não é um vídeo válido | Arquivo corrompido ou não é MP4; ffprobe ausente | `journalctl -u busvideo-server`; `which ffprobe` | Pedir novo arquivo; `apt install ffmpeg` |
| Erro 413 | Maior que `MEDIA_MAX_SIZE_MB` | Cartão de validação | Reduzir ou ajustar limite |
| Upload para no meio | Rede do operador, navegador fechado | Barra de progresso | Reenviar. Restos em `incoming/` são apagados no próximo boot do serviço |
| Disco do servidor cheio | Muitas versões | `du -sh /opt/busvideo-server/data/videos` | Apagar `video_<id>.mp4` de versões antigas não publicadas (conferir em `/api/video/history`) |
| Todos os ônibus Offline | AP ou servidor fora | `ping` do Pi ao servidor | Rede |

## Sistema

| Sintoma | Causa provável | Como verificar | Solução |
|---|---|---|---|
| Datas erradas nos logs do Pi | Sem RTC e sem NTP | `date`; `timedatectl` | `SET_TIME_FROM_SERVER=true` (unit precisa de `CAP_SYS_TIME`), ou NTP local no servidor |
| Pi não sobe, erros de filesystem | Cartão corrompido por quedas de energia | `dmesg \| grep -i mmc`; `fsck` | Regravar o cartão; usar High Endurance; verificar alimentação (`vcgencmd get_throttled`) |
| Watchdog reiniciando serviço | Processo travado (I/O do SD) | `journalctl -u busvideo-sync \| grep -i watchdog` | Verificar cartão; o agente já alimenta o watchdog durante download e hash (limite 300 s); aumentar `WatchdogSec` só se o cartão SD estiver muito lento |
| `state.json corrupt` | Queda de energia durante escrita (raro, escrita é atômica) | `journalctl -u busvideo-sync` | O sync reconcilia com o symlink real. Nada a fazer |

## Ações de recuperação

Forçar uma nova verificação agora:

```bash
sudo systemctl restart busvideo-sync
```

Forçar rollback para a versão anterior no Pi:

```bash
cd /opt/busvideo-player/media
ls versions/
sudo -u busvideo ln -sfn versions/video_v11.mp4 current.mp4
sudo systemctl restart busvideo-player
```

Descartar um download parcial:

```bash
sudo rm -f /opt/busvideo-player/media/download/video.tmp /opt/busvideo-player/media/download/video.part.json
sudo systemctl restart busvideo-sync
```

Testar o player manualmente (para o serviço primeiro):

```bash
sudo systemctl stop busvideo-player
sudo -u busvideo mpv --vo=gpu --gpu-context=drm --hwdec=v4l2m2m-copy --fs --loop-file=inf /opt/busvideo-player/media/current.mp4
sudo systemctl start busvideo-player
```

Coletar tudo para enviar ao suporte:

```bash
sudo /opt/busvideo-player/app/../scripts/diagnose.sh 2>/dev/null || sudo ./client/scripts/diagnose.sh
journalctl -u busvideo-sync -u busvideo-player --since "-2h" > /tmp/busvideo-logs.txt
cat /opt/busvideo-player/state/*.json >> /tmp/busvideo-logs.txt
```
