# Manual Técnico

Público: equipe técnica da Empresa Exemplo que instala e mantém o sistema na operadora.

## 1. Requisitos de hardware

### Servidor da garagem

| Item | Requisito |
|---|---|
| Computador | PC ou mini-PC x86-64, 2 núcleos, 4 GB RAM, 100 GB de disco |
| Sistema | Ubuntu Server ou Desktop 22.04 / 24.04 LTS |
| Rede | Cabo Ethernet até o roteador da garagem. **IP fixo por reserva DHCP** (ex.: `192.168.100.10`) |
| Energia | Nobreak recomendado |

### Ponto de acesso Wi-Fi

| Item | Requisito |
|---|---|
| SSID | Dedicado (ex.: `GARAGEM_EXEMPLO`), WPA2-PSK |
| Banda | Preferir **5 GHz** (Pi 3B+ alcança 50 a 90 Mbps; em 2,4 GHz, 20 a 40 Mbps) |
| Cobertura | Área onde os ônibus estacionam |
| Isolamento de clientes | Desligado entre a rede do servidor e a dos ônibus |

### Raspberry Pi (um por ônibus)

| Item | Requisito |
|---|---|
| Placa | Raspberry Pi 3 Model B+ |
| Cartão | microSD **32 GB ou mais, classe A1/A2, linha High Endurance** |
| Fonte | 5 V / 2,5 A estável a partir do conversor DC-DC do ônibus. Quedas de tensão corrompem o cartão |
| Refrigeração | Dissipador passivo, gabinete ventilado |
| Antena | Gabinete não metálico ou antena externa |
| Vídeo | Distribuidor HDMI existente alimentado e com EDID estável |
| Sistema | Ubuntu Server 22.04 ou 24.04 arm64 (sem desktop) |

## 2. Instalação do servidor

1. Instale o Ubuntu e configure IP fixo (reserva DHCP no roteador).
2. Copie o repositório para o servidor (pendrive ou `scp`).
3. Execute:

```bash
cd raspberry/server
sudo ./install_server.sh --operator-password 'SENHA_DO_OPERADOR' --admin-password 'SENHA_DO_ADMIN'
```

Opções: `--port PORTA` (padrão 443, HTTPS), `--operator-password SENHA` e `--admin-password SENHA` (senão pergunta as duas), `--no-ufw` (não configurar firewall).

O script cria o usuário `busvideo-server`, instala `ffmpeg`, Python e o venv em `/opt/busvideo-server`, gera `config/server.env` com hash da senha, `SECRET_KEY` e `DEVICE_TOKEN`, cria a **CA da garagem** e o certificado HTTPS em `config/tls/` (copiando `ca.crt` para `/opt/busvideo-server/ca.crt`), habilita `busvideo-server.service` e imprime a URL e o **DEVICE_TOKEN**. Anote o token e leve o `ca.crt`: os dois vão em cada Raspberry Pi. Re-executar renova o certificado do servidor e mantém a CA.

4. Abra `https://IP` no navegador e faça login. O aviso de certificado some depois de instalar o `ca.crt` no PC (ver seção 7).
5. Envie e publique o primeiro vídeo (ver Manual do Operador).

Estrutura instalada:

```
/opt/busvideo-server/
├── app/                  # código
├── venv/
├── config/server.env     # credenciais e limites (0600)
├── data/busvideo.db           # SQLite
├── data/videos/versions/ # vídeos armazenados
├── data/videos/incoming/ # uploads em andamento
└── logs/server.log
```

Ferramentas:

```bash
cd /opt/busvideo-server/app && ../venv/bin/python -m busvideo_server.tools hash-password   # novo hash de senha
../venv/bin/python -m busvideo_server.tools gen-token                                   # novo DEVICE_TOKEN
../venv/bin/python -m busvideo_server.tools gen-env                                     # bloco completo para server.env
```

Desinstalar: `sudo ./uninstall_server.sh` (mantém dados) ou `--purge` (apaga tudo).

### 2.1 Alternativa: servidor num PC com Windows

O servidor também roda nativamente em Windows 10/11 (64 bits), sem Linux e sem formatar o PC. O `ffprobe` vem embutido pelo pacote `static-ffmpeg` (extra `server[windows]`).

1. Copie a pasta do projeto para `C:\raspberry`.
2. Instale o Python 3.10+ (python.org, marcando *Add python.exe to PATH*). O instalador tenta fazê-lo pelo `winget` se faltar.
3. Clique duas vezes em `server\windows\instalar.bat` e aceite o pedido de administrador.

O `instalar.ps1` cria `C:\BusVideo` (venv, `config\server.env`, `data`, `logs`), instala `busvideo-server[windows]`, baixa o `ffprobe`, gera o `server.env` (pede as senhas do operador e do administrador), gera a CA e o certificado HTTPS em `C:\BusVideo\config\tls` (cópia pública em `C:\BusVideo\ca.crt`), restringe a pasta `config` a SYSTEM/Administradores, libera 443 e 80 no firewall, registra a tarefa agendada **Bus Video Servidor** (gatilho *ao iniciar*, conta SYSTEM, sem limite de tempo, religa em 1 min se cair), desliga suspensão/hibernação e imprime URL e `DEVICE_TOKEN`. Re-executar atualiza o código e mantém a configuração. `parar.bat` e `desinstalar.bat` (mantém `data` e `config`) ficam em `C:\BusVideo`. Guia para leigos: `docs/PASSO_A_PASSO_WINDOWS.html`.

## 3. Instalação do Raspberry Pi

### 3.1 Preparar o cartão

1. Grave **Ubuntu Server arm64** (22.04 ou 24.04) com o Raspberry Pi Imager. Configure usuário, senha e SSH no Imager.
2. No primeiro boot, com Ethernet ou Wi-Fi provisório, atualize: `sudo apt update && sudo apt upgrade -y`.
3. Em `/boot/firmware/config.txt`, confirme `dtoverlay=vc4-kms-v3d` e adicione:

```
hdmi_force_hotplug=1
gpu_mem=128
```

`hdmi_force_hotplug=1` evita tela preta quando o distribuidor HDMI liga depois do Pi. Se necessário, fixe o modo (`hdmi_group=1`, `hdmi_mode=16` para 1080p60 ou `hdmi_mode=4` para 720p60).

### 3.2 Diagnóstico e benchmark (obrigatório antes de instalar em campo)

```bash
cd raspberry/client
sudo ./scripts/diagnose.sh                       # relatório em /tmp/busvideo-diagnose-<data>.txt
./scripts/make-test-video.sh /tmp/teste.mp4 60 1920x1080
sudo ./scripts/benchmark-player.sh /tmp/teste.mp4 120
```

O diagnóstico coleta versão do Ubuntu, `/dev/video10` (decodificador), `/dev/dri`, EDID, rede, espaço e serviços existentes. O benchmark reproduz o vídeo por 120 s e reporta CPU, temperatura e throttling. Critério: 1080p30 com CPU abaixo de 60 % e sem frames perdidos. Se reprovar, teste 720p ou avalie o fallback GStreamer. Preencha o [Checklist de hardware](CHECKLIST_HARDWARE.md).

### 3.3 Instalar

Caminho simples (recomendado): o instalador do servidor cria a pasta `pendrive` (`C:\BusVideo\pendrive` ou `/opt/busvideo-server/pendrive`) com o assistente `instalar-onibus.sh`, a pasta `client`, o `ca.crt` e o `garagem.txt` (endereço e token). No Pi: `sudo mount /dev/sda1 /mnt && sudo bash /mnt/instalar-onibus.sh`; ele pergunta o número do ônibus e a senha do Wi-Fi, ajusta o HDMI, oferece o benchmark e chama o `install_client.sh` abaixo. Guia para leigos: `docs/GUIA_PRIMEIRA_VEZ.html`.

Caminho manual:


```bash
cd raspberry/client
sudo ./install_client.sh \
  --device-id BUS-001 \
  --server-url https://192.168.100.10 \
  --token 'DEVICE_TOKEN_DO_SERVIDOR' \
  --ca-cert /caminho/ca.crt \
  --wifi-ssid GARAGEM_EXEMPLO --wifi-psk 'SENHA_DO_WIFI' \
  --video /caminho/video_inicial.mp4
```

| Opção | Efeito |
|---|---|
| `--device-id` | Identificador único do ônibus (`BUS-001`) |
| `--server-url` | Um ou mais endereços separados por vírgula (cascata) |
| `--token` | `DEVICE_TOKEN` impresso pelo instalador do servidor |
| `--ca-cert ARQUIVO` | `ca.crt` da garagem (`/opt/busvideo-server/ca.crt` ou `C:\BusVideo\ca.crt`; também em `http://IP/ca.crt`). Obrigatório com servidor `https://`: o ônibus só aceita esse certificado |
| `--wifi-ssid` / `--wifi-psk` | Configura o Wi-Fi da garagem (netplan ou NetworkManager, detectado) |
| `--player mpv\|fake` | `mpv` em produção; `fake` só para bancada sem tela |
| `--video ARQUIVO` | Semeia o vídeo inicial como versão 1 (o ônibus já sai da oficina com conteúdo) |
| `--offline-debs DIR` | Instala `mpv`/`ffmpeg` a partir de `.deb` locais (sem internet) |
| `--skip-apt` | Não instala pacotes (já instalados) |

O script cria o usuário `busvideo`, instala `mpv` e `ffmpeg`, copia o código para `/opt/busvideo-player/app`, grava `config/client.env`, cria `/run/busvideo-player` (tmpfiles), habilita `busvideo-player.service` e `busvideo-sync.service`.

4. Reinicie: `sudo reboot`. O vídeo deve aparecer nas telas em até 30 s.
5. Na garagem, confira no servidor que `BUS-001` aparece como **Atualizado**.

Desinstalar: `sudo ./uninstall_client.sh` (mantém mídia) ou `--purge`.

### 3.4 Instalar a frota por clonagem (imagem-mestre)

Depois que o **primeiro** Raspberry está instalado e aprovado na bancada, os demais não precisam de monitor nem teclado:

1. No primeiro Pi: `sudo /opt/busvideo-player/scripts/prepare-master.sh`. Ele limpa identidade, estado, logs, chaves SSH e machine-id, mantém programa, configuração (servidor, token, `ca.crt`, Wi-Fi) e o vídeo inicial, e desliga.
2. Retire o cartão e grave a imagem: Mac `sudo dd if=/dev/rdiskN of=busvideo-onibus.img bs=4m status=progress`; Windows: Win32DiskImager (*Read*). Guarde o `.img`.
3. Para cada ônibus: grave o `.img` num cartão (Raspberry Pi Imager → *Use custom*), abra a partição de boot que aparece no PC (`system-boot`) e crie `busvideo-provision.txt`:

```
DEVICE_ID=BUS-017
# opcionais, só se diferirem da imagem:
# WIFI_SSID=GARAGEM_EXEMPLO
# WIFI_PSK=senha
# SERVER_URLS=https://192.168.100.10
```

4. Cartão no ônibus, liga. No primeiro boot o `busvideo-provision.service` aplica o arquivo (identidade, hostname, Wi-Fi), regenera chaves SSH e machine-id, renomeia o arquivo para `busvideo-provision.done` (sem a senha do Wi-Fi) e o ônibus se registra na garagem como `BUS-017`. Um clone ligado **sem** o arquivo aparece como `NOVO-<serial>` no painel, para não colidir com outros; basta colocar o arquivo e reiniciar para nomear.

Renomear um ônibus depois: mesmo arquivo, mesmo processo. Trocar servidor ou token em toda a frota: gerar nova imagem-mestre, ou usar `install_client.sh` de novo em cada um (ver [Atualização](ATUALIZACAO.md)).

### 3.5 Instalar a frota pela rede (Raspberries já existentes)

Quando os ônibus já têm Raspberry na rede da garagem com SSH, o PC do servidor instala em todos sem tocar nos cartões (`busvideo_server.fleet`, atalhos `C:\BusVideo\frota.bat` e `/opt/busvideo-server/frota.sh`):

```
frota descobrir --rede 192.168.100.0/24                       # aparelhos com SSH na rede
frota instalar --lista frota.csv --usuario pi --so BUS-001 --benchmark   # o primeiro, com benchmark
frota instalar --lista frota.csv --usuario pi                # todos (4 em paralelo; repetir é idempotente)
frota verificar --lista frota.csv --usuario pi               # DEVICE_ID, serviços, versão, SO, temperatura
```

`frota.csv`: `NUMERO,ENDERECO` por linha. Para cada ônibus a ferramenta envia a pasta `pendrive` (client, `ca.crt`, `garagem.txt`) por SFTP para `/tmp/busvideo-pendrive`, ajusta o HDMI, roda `install_client.sh` com `sudo` (senha do usuário SSH) e reinicia. Exige internet no Raspberry para o `apt`, ou uma pasta `pendrive/debs` com os `.deb` (`--offline-debs`). Funciona em Ubuntu e Raspberry Pi OS (Debian). Opções: `--senha`, `--chave` (arquivo de chave), `--wifi-ssid/--wifi-psk`, `--paralelo N`, `--sem-reiniciar`. Ônibus fora da garagem aparecem como "não conectou"; basta repetir depois.

### 3.6 Operação com vaga de atualização

Modelo combinado com a operadora: um ponto do pátio com o roteador; o ônibus que precisa atualizar estaciona ali, recebe o vídeo e sai. O agente foi ajustado para esse fluxo:

- **Detecção em segundos.** Sem rede, o agente faz uma checagem local (sem tráfego) a cada `NETWORK_CHECK_INTERVAL` (5 s). Ao associar ao Wi-Fi, a próxima checagem já fala com o servidor. Tempo típico entre estacionar e começar o download: 10 a 20 s (associação do Wi-Fi + checagem).
- **Mensagens nas telas do ônibus** (`OSD_MESSAGES=true`, via mpv): "Conectado à garagem. Verificando vídeo…", "Recebendo vídeo novo (350 MB)… não desligue" com o percentual a cada 5 %, "Conferindo o vídeo…", "Vídeo atualizado (versão N). Pode sair." ou "Vídeo já atualizado. Pode sair." Falhas mostram "Avise a garagem". O motorista sabe quando sair sem ninguém no painel.
- **Progresso no painel.** Durante o download o ônibus envia heartbeats a cada 10 % e a lista mostra "Baixando 45%".
- **Interrupção.** Se o ônibus sair no meio, o download continua de onde parou na próxima parada (Range).

Tempo na vaga = associação (5 a 10 s) + download (tamanho ÷ velocidade do Wi-Fi) + conferência (segundos). Exemplos a 40 Mbps: 200 MB ≈ 45 s; 800 MB ≈ 3 min. Vídeos menores reduzem a fila.

## 4. Referência de configuração

### 4.1 `/opt/busvideo-server/config/server.env`

| Chave | Padrão | Descrição |
|---|---|---|
| `BUSVIDEO_HOST` | `0.0.0.0` | Interface de escuta |
| `BUSVIDEO_PORT` | `443` | Porta (443 com HTTPS; o unit já permite portas baixas) |
| `BUSVIDEO_TLS_CERT` / `BUSVIDEO_TLS_KEY` | vazio | Certificado e chave do servidor (PEM). Com os dois, o servidor só fala HTTPS. Gerados por `tools gen-cert --out config/tls` |
| `BUSVIDEO_HTTP_REDIRECT_PORT` | `0` | Porta HTTP auxiliar que só redireciona para HTTPS e entrega `/ca.crt` (instalador usa 80) |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_WINDOW_S` | `5` / `60` | Limite de tentativas de login por IP |
| `BUSVIDEO_DATA_DIR` | `data` | Diretório de dados (banco e vídeos) |
| `BUSVIDEO_LOG_DIR` | `<data>/logs` | Logs |
| `PRODUCT_NAME` | `Bus Video` | Nome exibido na interface |
| `COMPANY_NAME` | `Empresa Exemplo` | Rodapé da interface |
| `OPERATOR_USER` | `operador` | Conta de uso diário do painel |
| `OPERATOR_PASSWORD_HASH` | vazio (sem login) | Hash PBKDF2 (`tools hash-password`). Só semeia a tabela `users`; depois o banco prevalece |
| `ADMIN_USER` | `admin` | Conta do responsável técnico: tudo do operador + redefinir senhas |
| `ADMIN_PASSWORD_HASH` | vazio (sem login) | Idem. Recuperação: `tools set-password admin` no servidor |
| `SECRET_KEY` | aleatório a cada boot | Assinatura das sessões. Defina para manter sessões após reinício |
| `DEVICE_TOKEN` | vazio (dispositivos negados) | Token dos Raspberry Pi |
| `SESSION_TTL_S` | `43200` | Duração da sessão |
| `OFFLINE_AFTER_S` | `900` | Sem heartbeat por esse tempo = Offline |
| `FFPROBE_BIN` | `ffprobe` | Caminho do ffprobe |
| `MEDIA_ALLOWED_EXTENSIONS` | `mp4,m4v,mov` | Extensões aceitas |
| `MEDIA_ALLOWED_VIDEO_CODECS` | `h264` | Codecs de vídeo |
| `MEDIA_ALLOWED_AUDIO_CODECS` | `aac,none` | Codecs de áudio (`none` = sem áudio) |
| `MEDIA_MAX_WIDTH` / `MEDIA_MAX_HEIGHT` | `1920` / `1080` | Resolução máxima |
| `MEDIA_MAX_FPS` | `30` | FPS máximo |
| `MEDIA_MAX_H264_LEVEL` | `41` | Level H.264 máximo (41 = 4.1) |
| `MEDIA_MAX_BITRATE_KBPS` | `12000` | Bitrate máximo |
| `MEDIA_MAX_DURATION_S` | `3600` | Duração máxima |
| `MEDIA_MAX_SIZE_MB` | `2048` | Tamanho máximo |

### 4.2 `/opt/busvideo-player/config/client.env`

| Chave | Padrão | Descrição |
|---|---|---|
| `DEVICE_ID` | `BUS-000` | Identificador do ônibus |
| `SERVER_URLS` | `https://192.168.100.10` | Cascata de endereços, separados por vírgula |
| `DEVICE_TOKEN` | vazio | Token do servidor |
| `BASE_DIR` | `/opt/busvideo-player` | Raiz de mídia, estado e logs |
| `NETWORK_CHECK_INTERVAL` | `5` | Sem rede: intervalo da checagem local (sem tráfego) para reagir ao estacionar |
| `OSD_MESSAGES` | `true` | Mensagens de atualização nas telas do ônibus (mpv OSD) |
| `SYNC_INTERVAL` | `60` | Segundos entre ciclos com servidor alcançável |
| `MAX_BACKOFF` | `60` | Intervalo máximo fora da garagem |
| `KEEP_VERSIONS` | `2` | Versões mantidas em disco (atual + rollback) |
| `DISK_MARGIN_MB` | `300` | Margem exigida além do tamanho do vídeo |
| `SWITCH_MODE` | `end_of_loop` | `end_of_loop` troca ao fim do vídeo; `immediate` troca na hora |
| `SWITCH_MAX_WAIT_S` | `0` | Espera máxima pela troca (0 = duração + 60 s) |
| `PLAYER` | `mpv` | `mpv`, `mpv-desktop` (notebook) ou `fake` |
| `AUDIO` | `off` | `off`, `alsa`, `auto` ou nome de saída do mpv |
| `MPV_EXTRA_ARGS` | vazio | Argumentos extras para o mpv |
| `DOWNLOAD_RATE_LIMIT_MBPS` | `0` | Limite de taxa (0 = sem limite) |
| `CHUNK_SIZE` | `1048576` | Bytes por gravação no SD |
| `HTTP_TIMEOUT` | `30` | Timeout de rede por operação |
| `HEALTH_TIMEOUT` | `3` | Timeout do `/api/health` |
| `VALIDATE_FORMAT` | `auto` | `auto`, `ffprobe`, `mpv` ou `off` |
| `MAX_FAILURES_PER_VERSION` | `3` | Falhas antes do cooldown |
| `FAILURE_COOLDOWN_S` | `1800` | Cooldown após falhas repetidas |
| `SET_TIME_FROM_SERVER` | `false` | Ajustar relógio pelo servidor (exige `CAP_SYS_TIME`) |
| `HOSTNAME_OVERRIDE` | hostname | Nome reportado no heartbeat |
| `LOG_LEVEL` | `INFO` | `DEBUG` para diagnóstico |

Após editar `client.env`: `sudo systemctl restart busvideo-sync busvideo-player`.

## 5. Operação dos serviços

### Servidor

```bash
sudo systemctl status busvideo-server
sudo systemctl restart busvideo-server
journalctl -u busvideo-server -f
tail -f /opt/busvideo-server/logs/server.log
```

### Raspberry Pi

```bash
sudo systemctl status busvideo-player busvideo-sync
sudo systemctl restart busvideo-sync          # forçar nova verificação
sudo systemctl restart busvideo-player        # reiniciar o player
journalctl -u busvideo-sync -f
journalctl -u busvideo-player -f
tail -f /opt/busvideo-player/logs/sync.log /opt/busvideo-player/logs/player.log
```

Verificar o estado local:

```bash
cat /opt/busvideo-player/state/state.json           # versão, sha256, status, last_error, falhas
cat /opt/busvideo-player/state/player_status.json   # o que está tocando, reinícios
ls -l /opt/busvideo-player/media/ /opt/busvideo-player/media/versions/
```

Rodar um ciclo manual com saída no terminal:

```bash
cd /opt/busvideo-player/app
sudo -u busvideo python3 -m busvideo_client.sync --config /opt/busvideo-player/config/client.env --once
```

(O cliente usa o `python3` do sistema, sem ambiente virtual; é o mesmo interpretador do unit `busvideo-sync.service`.)

## 6. Procedimentos

### Adicionar um ônibus

1. Prepare o cartão (3.1), rode diagnóstico e benchmark (3.2).
2. Instale com `--device-id BUS-00N` e o mesmo `--token`.
3. Semeie o vídeo atual com `--video` para o ônibus sair com conteúdo.
4. Confira na interface que aparece como Atualizado.

### Trocar o DEVICE_TOKEN

1. Gere: `python -m busvideo_server.tools gen-token`.
2. Edite `DEVICE_TOKEN` em `server.env` e `systemctl restart busvideo-server`.
3. Em cada Pi, edite `DEVICE_TOKEN` em `client.env` e `systemctl restart busvideo-sync`. Até lá o ônibus aparece com erro "Server rejected device token".

### Substituir o servidor

1. Copie `/opt/busvideo-server/config/` e `/opt/busvideo-server/data/` do antigo.
2. Instale no novo com `install_server.sh`, depois restaure os dois diretórios sobre os criados e ajuste dono (`chown -R busvideo-server:busvideo-server`).
3. Mantenha o **mesmo IP** ou atualize `SERVER_URLS` nos ônibus.

### Backup

```bash
sudo systemctl stop busvideo-server
sudo tar czf busvideo-server-backup-$(date +%F).tgz /opt/busvideo-server/config /opt/busvideo-server/data
sudo systemctl start busvideo-server
```

### Rollback de vídeo pelo operador

Reenviar e publicar o vídeo anterior. Gera nova versão. Não requer acesso ao Pi.

### Rollback forçado em um Pi (emergência)

```bash
cd /opt/busvideo-player/media
sudo -u busvideo ln -sfn versions/video_v11.mp4 current.mp4
sudo systemctl restart busvideo-player
```

O `busvideo-sync` vai reconciliar o `state.json` e, na próxima passagem pela garagem, baixar a versão publicada de novo. Para impedir, pare o sync: `systemctl stop busvideo-sync`.

## 7. Segurança

### HTTPS com a CA da garagem

A garagem não tem domínio público, então nenhuma autoridade pública emite certificado para ela. O servidor cria a sua própria autoridade (**CA da garagem**, `config/tls/ca.crt` + `ca.key`, 10 anos) e emite o certificado do servidor (`server.crt` + `server.key`, 5 anos, com os IPs e o hostname do PC). Tudo é feito pelo instalador; à mão: `python -m busvideo_server.tools gen-cert --out config/tls --ip 192.168.100.10`. Re-executar mantém a CA e só renova o certificado do servidor, então uma troca de IP não invalida os ônibus já instalados.

- **Ônibus:** `install_client.sh --ca-cert ca.crt` grava `CA_CERT` no `client.env`. O agente só aceita um servidor assinado por essa CA (fixação de certificado) e recusa qualquer outro, inclusive um servidor falso na mesma rede. Sem `CA_CERT`, um servidor `https://` é recusado.
- **Operadores:** instalar o `ca.crt` uma vez em cada PC/celular faz o navegador mostrar o cadeado. Windows: duplo clique em `ca.crt` → Instalar certificado → Usuário atual → "Colocar todos os certificados no repositório a seguir" → **Autoridades de Certificação Raiz Confiáveis**. Android: Configurações → Segurança → Instalar certificado → Certificado CA. iPhone: abrir o arquivo → Ajustes → Perfil baixado → Instalar → Ajustes → Geral → Sobre → Ajustes de confiança → ativar. O arquivo está em `/opt/busvideo-server/ca.crt` (Linux), `C:\BusVideo\ca.crt` (Windows) e em `http://IP/ca.crt`.
- A porta 80 só redireciona para HTTPS e entrega o `ca.crt`. Nada da aplicação é servido em HTTP.
- `ca.key` é o segredo mais importante do servidor: quem o tiver pode se passar pela garagem. Fica com permissão `0600` (Linux) ou acessível só a SYSTEM/Administradores (Windows) e entra no backup cifrado.

### Modelo de ameaça: alguém no Wi-Fi do ônibus

Requisito: **nenhum passageiro ou pessoa conectada a uma rede do ônibus pode trocar o vídeo das telas.** Como isso é garantido:

| Camada | Garantia |
|---|---|
| O terminal não escuta nada | O Raspberry nunca abre porta de rede: ele só faz conexões de saída para a garagem. Não existe "mandar um vídeo para o ônibus". O firewall (`ufw`, instalado pelo `install_client.sh`) bloqueia toda entrada; só SSH fica aberto, com limite de tentativas, e sem senha assim que houver chave instalada. |
| Só a garagem verdadeira é ouvida | O terminal só aceita servidor `https://` cujo certificado foi assinado pela CA da garagem (`CA_CERT`). Uma rede falsa com o mesmo nome de Wi-Fi, um roteador do ônibus, ou um notebook se passando pelo servidor são recusados antes de qualquer dado ser enviado. `http://` é recusado por padrão (`ALLOW_INSECURE_HTTP=false`). |
| O token não troca vídeo | Mesmo com o `DEVICE_TOKEN`, só é possível **ler** o vídeo publicado e reportar estado. Enviar ou publicar exige o login do operador, que só existe no painel da garagem. |
| O arquivo é conferido | Tamanho e SHA-256 anunciados pela garagem (por HTTPS) são verificados antes da troca. Arquivo diferente é descartado e o vídeo anterior continua. |
| O player só toca o arquivo local | `mpv` roda sem scripts, sem acesso a rede (`--ytdl=no`, `--load-scripts=no`), lendo apenas `current.mp4`, gravado só pelo usuário `busvideo`. O controle do player é um socket Unix local, não uma porta. |
| Sem rede do passageiro | O terminal conecta apenas ao Wi-Fi da garagem. Ele não deve ser ligado a Wi-Fi de passageiros nem a roteadores do ônibus; se o veículo tiver internet a bordo, o Raspberry fica fora dela. |
| Físico | O Raspberry vai em caixa fechada; cartão SD e portas USB fora do alcance. Quem tem acesso físico ao equipamento pode trocar qualquer coisa, em qualquer sistema. |

Verificação: `demo/security_scan.py` contra o servidor, e no Pi `sudo ss -tlnp` deve listar apenas o SSH.

### Medidas no servidor

- Login com senha em hash PBKDF2 (600 mil iterações), 5 tentativas por minuto por IP, sessão assinada com `HttpOnly`, `SameSite=Lax` e `Secure` (com HTTPS).
- Proteção contra CSRF: requisições que alteram estado com cookie de sessão só são aceitas da própria página (checagem de `Origin`/`Sec-Fetch-Site`).
- Sair invalida a sessão no servidor (lista de sessões revogadas até expirarem). Requisições JSON acima de 64 KB, ou sem tamanho declarado, são recusadas antes da leitura; só o upload de vídeo aceita corpo grande, com limite próprio.
- Cabeçalhos: `Content-Security-Policy` sem scripts inline nem terceiros, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Strict-Transport-Security` (com HTTPS), `Cache-Control: no-store` na API. Sem cabeçalho `Server`, sem Swagger público.
- Dispositivos autenticam com `Authorization: Bearer DEVICE_TOKEN`; sem token configurado, tudo é negado.
- Upload: limite de tamanho em streaming, extensão, `ffprobe` e política de mídia; nomes de arquivo gerados pelo sistema; nenhum arquivo enviado é executado.
- `server.env` e `client.env` contêm segredos: `0600`, dono do serviço. Logs nunca registram token ou senha.
- O servidor deve ficar só na LAN da garagem. O firewall do instalador abre apenas 443 e 80. Não exponha na internet.
- SSH no Pi: use chave e desative senha depois da instalação. Troque as senhas na entrega pelo painel (botão Senha) ou com `tools set-password operador|admin`. Só o `admin` redefine a senha do operador; a do `admin` só se recupera no próprio servidor (`set-password`).
- Dados vindos dos ônibus (nome, erro, hostname) são limpos de caracteres de controle no servidor e renderizados como texto no painel, nunca como HTML (sem XSS a partir de um ônibus comprometido). O IP mostrado é sempre o observado na conexão, não o informado pelo dispositivo.
- Certificado do servidor com validade de 2 anos (limite aceito por macOS/iOS/Chrome) e **renovação automática** 45 dias antes de vencer, com a mesma CA; o serviço reinicia sozinho para carregar o novo. Só TLS 1.2+ com cifras com sigilo futuro (ECDHE).
- Windows: a pasta `C:\BusVideo` inteira fica acessível só a SYSTEM e Administradores (nenhum usuário local altera scripts, programa ou vídeos). O serviço roda como NETWORK SERVICE (sem privilégio) quando o Python está instalado para todos os usuários; com Python por usuário, roda como SYSTEM e o instalador avisa.
- Senha do operador com no mínimo 8 caracteres nos instaladores.
- Varredura automática: `python demo/security_scan.py --server https://IP --ca-cert ca.crt --password SENHA --token TOKEN` testa 35 itens (TLS, acessos sem credencial, cabeçalhos, login, CSRF, cookie forjado, dados de dispositivo, Range). Rode após instalar e a cada atualização.
- Previsto para a fase 2: token por dispositivo com revogação individual, auditoria de publicações e atualização remota do agente.

## 8. Antes de fechar com a operadora

Preencha o [Checklist de hardware](CHECKLIST_HARDWARE.md) no ônibus real: versão do Ubuntu, decodificador, ligação das três telas, software já existente no Pi, rede, áudio, cartão e alimentação. As respostas definem a política de mídia e se o mpv é viável.
