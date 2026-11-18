# Atualização do software

Este documento trata da atualização do **sistema** (servidor e agente), não do vídeo. A troca de vídeo é feita pelo operador na interface.

## Compatibilidade

- Servidor e cliente da mesma série (0.x) são compatíveis entre si. A API é aditiva: campos novos não quebram clientes antigos.
- Atualize o **servidor primeiro**, depois os ônibus. Um cliente antigo continua funcionando contra um servidor novo.
- A versão instalada aparece em `/api/health` (`app_version`) e no heartbeat de cada ônibus (`app_version`, coluna visível em `/api/devices`).

## Servidor

1. Faça backup:

```bash
sudo tar czf /root/busvideo-server-backup-$(date +%F).tgz /opt/busvideo-server/config /opt/busvideo-server/data
```

2. Copie a nova versão do repositório para o servidor.
3. Reexecute o instalador. Ele preserva `config/server.env` e `data/`:

```bash
cd raspberry/server
sudo ./install_server.sh
```

4. Confira: `systemctl status busvideo-server` e `curl -k https://localhost/api/health`.

**Ao atualizar de uma versão anterior à 0.1.1 (um só login):** a conta `admin` continua com a senha antiga e passa a ser a do responsável técnico; a conta `operador` nasce sem senha. Entre como `admin`, clique em **Senha**, defina a senha do `operador` e entregue essa à operação; depois troque a do `admin` para uma só sua. No Windows, o `instalar.bat` faz a mesma migração.

Rollback: restaure o código anterior e reexecute o instalador, ou restaure o backup. O banco SQLite não muda de esquema dentro da série 0.x.

## Raspberry Pi (por ônibus)

Requer acesso ao Pi na garagem (SSH ou teclado). Não interrompe o vídeo por mais do que o reinício do serviço.

Opção A, instalador (preserva `client.env`, mídia e estado):

```bash
cd raspberry/client
sudo ./install_client.sh --device-id BUS-001 --server-url https://192.168.100.10 --token 'TOKEN' --skip-apt
```

Use os mesmos valores já configurados (veja `/opt/busvideo-player/config/client.env`).

Opção B, cópia manual do código:

```bash
sudo rsync -a --delete raspberry/client/busvideo_client/ /opt/busvideo-player/app/busvideo_client/
sudo chown -R busvideo:busvideo /opt/busvideo-player/app
sudo systemctl restart busvideo-sync
sudo systemctl restart busvideo-player
```

Se os arquivos em `client/systemd/` mudaram, copie-os para `/etc/systemd/system/` e rode `systemctl daemon-reload` antes do restart.

Confira: `journalctl -u busvideo-sync -n 20` deve mostrar `busvideo-sync v<nova> starting`.

Rollback: copie o diretório `busvideo_client/` da versão anterior e reinicie os serviços. Mídia e estado não mudam de formato dentro da série 0.x.

## Atualização em lote (fase 2)

O mecanismo de download validado do agente (tamanho, SHA-256, troca atômica) será reutilizado para distribuir pacotes do próprio agente pelo servidor, sem visita ao ônibus. Não disponível neste protótipo.
