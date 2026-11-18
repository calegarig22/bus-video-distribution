# Checklist de hardware e ambiente

Uso: pré-venda e instalação na operadora. Preencher no ônibus real e no PC da garagem. `scripts/diagnose.sh` coleta os itens marcados com (D) automaticamente em `/tmp/busvideo-diagnose-<data>.txt`.

Operadora: ____________________ Ônibus: __________ Data: ____/____/______ Técnico: ____________________

## A. Raspberry Pi

| # | Item | Comando | Valor encontrado | Decisão que depende |
|---|---|---|---|---|
| 1 | [ ] Versão do Ubuntu, arquitetura, Server/Desktop (D) | `lsb_release -a; uname -m; systemctl get-default` | ______________ | Pacotes; DRM sem X11; RAM livre |
| 2 | [ ] Overlay gráfico e DRM (D) | `grep -E 'vc4|gpu_mem|hdmi' /boot/firmware/config.txt; ls /dev/dri` | ______________ | Saída do mpv (`--gpu-context=drm`) |
| 3 | [ ] Decodificador H.264 por hardware (D) | `ls /dev/video*; v4l2-ctl --list-devices; ffmpeg -decoders \| grep v4l2m2m` | `/dev/video10`: [ ] sim [ ] não | **Viabilidade de 1080p**; mpv vs GStreamer vs 720p |
| 4 | [ ] Benchmark 1080p30 por 120 s | `scripts/benchmark-player.sh /tmp/teste.mp4 120` | CPU ____ % · temp ____ °C · throttled ______ · frames perdidos ____ | Política de mídia definitiva (`MEDIA_MAX_*`) |
| 5 | [ ] Cartão SD: modelo, classe, tamanho, espaço livre (D) | `df -h /; cat /sys/block/mmcblk0/device/{name,oemid}` | ______ GB · livre ______ GB | `KEEP_VERSIONS`; `MEDIA_MAX_SIZE_MB`; troca por High Endurance |
| 6 | [ ] Alimentação e throttling (D) | `vcgencmd get_throttled` (0x0 = ok) | ______________ | Risco de corrupção do SD; fonte/DC-DC |
| 7 | [ ] Temperatura em repouso (D) | `vcgencmd measure_temp` | ______ °C | Dissipador/gabinete |
| 8 | [ ] Usuário, sudo, SSH, senha padrão (D) | `id; ls /etc/ssh/sshd_config; sudo -n true` | ______________ | Instalação e hardening |
| 9 | [ ] Software já existente: serviços, cron, autostart, player atual (D) | `systemctl list-units --type=service --state=running; crontab -l; ls ~/.config/autostart; ps aux` | ______________ | Conflito por HDMI/áudio/CPU; coexistência com sistema da operadora |
| 10 | [ ] Vídeo em uso hoje (codec, resolução, fps, bitrate, áudio) | `ffprobe -show_streams ARQUIVO` | ______________ | Política de mídia compatível com o acervo |

## B. Telas

| # | Item | Como verificar | Valor encontrado | Decisão que depende |
|---|---|---|---|---|
| 11 | [ ] Ligação física das 3 telas | Inspeção: splitter, daisy-chain, distribuidor ativo, um Pi por tela, outro | [ ] splitter [ ] daisy-chain [ ] distribuidor [ ] 1 Pi/tela [ ] outro: ______ | 1 player (padrão) ou N terminais por ônibus |
| 12 | [ ] Modelo do distribuidor e alimentação | Etiqueta | ______________ | EDID; `hdmi_force_hotplug` |
| 13 | [ ] Modo HDMI negociado e EDID (D) | `cat /sys/class/drm/card*-HDMI*/status; cat /sys/class/drm/card*-HDMI*/modes \| head` | ______________ | `hdmi_group/hdmi_mode` fixos |
| 14 | [ ] Comportamento ao ligar as telas depois do Pi | Teste de boot com telas desligadas | [ ] ok [ ] tela preta | `hdmi_force_hotplug=1` |
| 15 | [ ] Áudio nas telas | Inspeção | [ ] sim [ ] não | `AUDIO=off` ou `alsa`; `hdmi_drive=2` |

## C. Rede

| # | Item | Como verificar | Valor encontrado | Decisão que depende |
|---|---|---|---|---|
| 16 | [ ] Stack de rede no Pi (D) | `ls /etc/netplan; nmcli general status` | [ ] netplan+wpa [ ] NetworkManager | `wifi-setup.sh` / instalador |
| 17 | [ ] Wi-Fi já configurado no Pi (D) | `iw dev wlan0 link; iw wlan0 get power_save` | SSID atual: ______ · power_save: ______ | Reaproveitar ou configurar; desligar power-save |
| 18 | [ ] SSID da garagem, banda, cobertura do pátio | Site survey com celular/notebook | SSID: ______ · [ ] 2,4 [ ] 5 GHz · sinal no pátio: ______ dBm | Velocidade; `DOWNLOAD_RATE_LIMIT_MBPS` |
| 19 | [ ] Isolamento de clientes no AP | Configuração do AP | [ ] ligado [ ] desligado | Precisa estar desligado entre servidor e ônibus |
| 20 | [ ] Roteador permite reserva DHCP e DNS local | Configuração | [ ] sim [ ] não | `SERVER_URLS` (IP fixo vs hostname) |
| 21 | [ ] Sub-rede da garagem | Roteador | ______________ | Regras de `ufw` no servidor |
| 22 | [ ] Internet disponível na instalação (para `apt`/pip) | `ping -c1 archive.ubuntu.com` | [ ] sim [ ] não | `--offline-debs`; pacotes Python preparados |
| 22b | [ ] Política de TI no PC: antivírus com firewall, proxy, domínio, bloqueio de instalação | Perguntar à TI | ______________ | Liberar 443/80; TI presente na instalação |

## D. Servidor da garagem

| # | Item | Como verificar | Valor encontrado | Decisão que depende |
|---|---|---|---|---|
| 23 | [ ] Sistema operacional do PC | Perguntar / inspecionar | [ ] Ubuntu [ ] outro Linux [ ] Windows 10/11 | Ubuntu: `install_server.sh`; Windows: `server\windows\instalar.bat`; outro Linux: mini-PC Ubuntu |
| 24 | [ ] CPU, RAM, disco livre | `nproc; free -h; df -h` | ______________ | Histórico de vídeos |
| 25 | [ ] Cabo Ethernet até o roteador e IP fixo possível | Inspeção | IP planejado: ______________ | `SERVER_URLS` |
| 26 | [ ] Nobreak | Inspeção | [ ] sim [ ] não | Recomendação |
| 27 | [ ] Navegador do operador e dispositivo (PC/celular) | Perguntar | ______________ | Teste da interface |

## E. Operação

| # | Item | Como verificar | Valor encontrado | Decisão que depende |
|---|---|---|---|---|
| 28 | [ ] Tempo médio do ônibus na garagem | Operação | ______ h/dia | Tamanho máximo de vídeo; retomada |
| 29 | [ ] Quantidade de ônibus e chegadas simultâneas | Operação | ______ ônibus · ______ ao mesmo tempo | `DOWNLOAD_RATE_LIMIT_MBPS`; AP |
| 30 | [ ] Frequência de troca de vídeo | Operação | ______ por mês | Espaço no servidor |
| 31 | [ ] Finalidade do Bluetooth para a operadora | Perguntar | ______________ | Fase 2 |
| 32 | [ ] Quem produz os vídeos e em que formato | Perguntar | ______________ | Orientação de exportação; transcodificação (fase 2) |

## Resultado

| Decisão | Marcar |
|---|---|
| Player | [ ] mpv 1080p30 [ ] mpv 720p [ ] GStreamer [ ] a definir |
| Telas | [ ] 1 player, mesma imagem [ ] N terminais por ônibus |
| Descoberta | [ ] IP fixo ______________ [ ] hostname ______________ |
| Servidor | [ ] PC existente [ ] mini-PC novo |
| Bloqueios encontrados | ______________________________________________ |
