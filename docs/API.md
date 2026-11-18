# API REST

Base: `https://<IP_DO_SERVIDOR>` (porta 443, certificado da CA da garagem; clientes devem confiar no `ca.crt`, disponível em `/ca.crt`). Sem HTTPS configurado: `http://<IP>:8080`. Não há Swagger público.

## Autenticação

| Tipo | Como | Quem usa |
|---|---|---|
| Pública | Sem credencial | `GET /api/health` |
| Painel (sessão) | Cookie `busvideo_session` obtido em `POST /api/auth/login`. Válido por `SESSION_TTL_S` (12 h). Duas contas: `operador` (role `operator`) e `admin` (role `admin`); ambas acessam tudo que está marcado **admin** abaixo. Só a role `admin` redefine senhas de outros usuários. | Interface web, scripts do técnico |
| Dispositivo | Header `Authorization: Bearer <DEVICE_TOKEN>` | `busvideo-sync` no Raspberry Pi |

Rotas marcadas como **admin ou device** aceitam qualquer um dos dois.

## Códigos de erro

| Código | Significado |
|---|---|
| 400 | Requisição inválida (JSON, `device_id`, upload rejeitado, publicar vídeo incompatível) |
| 401 | Sem sessão ou token inválido |
| 404 | Versão, vídeo ou dispositivo inexistente; nenhum vídeo publicado |
| 410 | Arquivo da versão não está mais no disco |
| 413 | Upload maior que `MEDIA_MAX_SIZE_MB` |
| 416 | `Range` fora do arquivo |
| 429 | Muitas tentativas de login (5 por minuto por IP) |

Erros retornam `{"detail": "mensagem"}`.

## Saúde

### `GET /api/health` (público)

```json
{"status": "ok", "server_time": "2026-09-09T13:30:00+00:00", "app_version": "0.1.0", "product": "Bus Video"}
```

`server_time` permite ao Pi (sem RTC) ajustar o relógio quando `SET_TIME_FROM_SERVER=true`.

## Autenticação

### `POST /api/auth/login`

```json
{"username": "operador", "password": "..."}
```

Resposta `200`: `{"ok": true, "user": "operador", "role": "operator"}` e cookie `busvideo_session`. `401` se inválido, `429` se excedeu tentativas.

### `POST /api/auth/logout` → `{"ok": true}` e remove o cookie.

### `GET /api/auth/me` (admin) → `{"user": "operador", "role": "operator"}`.

### `GET /api/auth/users` (só role `admin`) → `[{"user", "role", "has_password", "updated_at"}]`. Nunca devolve hashes. `403` para o operador.

### `POST /api/auth/password` (admin)

```json
{"username": "operador", "current_password": "...", "new_password": "..."}
```

Troca de senha. `username` opcional (padrão: o próprio). Trocar a **própria** senha exige `current_password` (`403` se errada; 5 erros por minuto por IP → `429`). A role `admin` redefine a senha de **outro** usuário sem `current_password` (recuperação de senha esquecida do operador). O operador só troca a própria (`403` para outro usuário). Mínimo 8 caracteres (`400`); `404` se o usuário não existe. Resposta: `{"ok": true, "user": "operador"}`. As senhas ficam como hash PBKDF2 na tabela `users` do banco; `OPERATOR_PASSWORD_HASH`/`ADMIN_PASSWORD_HASH` do `server.env` só semeiam contas sem senha.

## Vídeo

### `GET /api/video/latest` (admin ou device)

Versão publicada. `204 No Content` se nada foi publicado.

```json
{
  "version": 12,
  "filename": "campanha_setembro.mp4",
  "size": 123456789,
  "sha256": "9f2c...",
  "duration": 932.4,
  "width": 1920,
  "height": 1080,
  "video_codec": "h264",
  "published_at": "2026-09-09T13:30:00+00:00",
  "download_url": "/api/video/download/12"
}
```

### `GET|HEAD /api/video/download/{version}` (admin ou device)

Stream do arquivo (`Content-Type: video/mp4`). Cabeçalhos: `Accept-Ranges: bytes`, `ETag: "<sha256>"`, `Content-Length`, `Content-Disposition: inline; filename="video_v12.mp4"`.

Semântica de retomada:

| Requisição | Resposta |
|---|---|
| Sem `Range` | `200` com o arquivo inteiro |
| `Range: bytes=1000-` | `206`, `Content-Range: bytes 1000-<fim>/<total>` |
| `Range: bytes=1000-1999` | `206` com o trecho |
| `Range` + `If-Range: "<sha256>"` igual ao `ETag` | `206` (retomada aceita) |
| `Range` + `If-Range` diferente | `200` com o arquivo inteiro (conteúdo mudou) |
| Início além do tamanho | `416`, `Content-Range: bytes */<total>` |

`HEAD` devolve só os cabeçalhos. Use para conferir tamanho e hash antes de baixar.

### `GET|HEAD /api/video/download` (admin ou device)

Atalho para a versão publicada. `404` se nada publicado. Prefira a rota com número de versão no cliente.

### `POST /api/video/upload` (admin)

Corpo **bruto** (não multipart), em streaming. Nome do arquivo no header `X-Filename` (ou `?filename=`). O servidor grava em `incoming/`, calcula SHA-256, executa `ffprobe`, aplica a política e move para `versions/`. O vídeo **não** é publicado.

```bash
curl -c cookies -X POST https://IP/api/auth/login \
     -H "Content-Type: application/json" -d '{"username":"admin","password":"SENHA"}'
curl -b cookies -X POST --data-binary @video.mp4 -H "X-Filename: video.mp4" \
     https://IP/api/video/upload
```

Resposta `200` (mesmo quando incompatível, para mostrar os motivos):

```json
{
  "id": 7, "filename": "video.mp4", "size": 850123456, "sha256": "9f2c...",
  "duration": 932.4, "width": 1920, "height": 1080,
  "video_codec": "h264", "audio_codec": "aac", "fps": 30.0,
  "bitrate_kbps": 7200, "h264_level": 40, "status": "uploaded",
  "compatible": true, "reasons": [],
  "uploaded_at": "2026-09-09T13:25:00+00:00", "uploaded_by": "admin"
}
```

Incompatível: `"status": "rejected"`, `"compatible": false`, `"reasons": ["Resolução 3840x2160 acima do limite 1920x1080", "FPS 60 acima do limite 30"]`.

Erros `400`: extensão não permitida, arquivo vazio, não é vídeo (ffprobe falhou), tamanho recebido difere do `Content-Length`. `413`: acima do limite.

### `POST /api/video/{id}/publish` (admin)

Cria nova versão (contador) apontando para o vídeo `id`. Resposta: o mesmo JSON de `/api/video/latest`. `400` se o vídeo foi rejeitado. Publicar um vídeo antigo de novo gera um número novo (rollback do operador).

### `GET /api/video/history` (admin)

```json
[{"version": 12, "published_at": "...", "published_by": "admin", "note": null,
  "video_id": 7, "original_filename": "video.mp4", "size_bytes": 850123456, "sha256": "...", "duration_s": 932.4}]
```

### `GET /api/video/list` (admin) → últimos 50 vídeos enviados (mesmo formato do upload).

### `GET /api/video/{id}` (admin) → um vídeo enviado. `404` se não existe.

## Dispositivos

### `POST /api/devices/heartbeat` (device)

Enviado pelo `busvideo-sync` a cada ciclo com servidor alcançável, e após cada mudança de estado.

```json
{
  "device_id": "BUS-001",
  "hostname": "bus001",
  "ip": "192.168.100.51",
  "current_version": 11,
  "sha256": "abc...",
  "app_version": "0.1.0",
  "free_space_mb": 21000,
  "uptime_s": 5400,
  "status": "ok",
  "last_error": null,
  "player": "playing"
}
```

| Campo | Regra |
|---|---|
| `device_id` | Obrigatório. `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`. Senão `400`. |
| `ip` | Se ausente, o servidor usa o IP de origem. |
| `status` | `ok`, `downloading` ou `error` (o que o cliente informa). |
| `last_error` | Texto livre até 500 caracteres. Gera evento `ERROR` quando muda. |

Resposta: `{"ok": true, "published_version": 12}`.

Primeiro heartbeat registra o dispositivo (evento "Dispositivo registrado"). Mudança de `current_version` gera evento "Atualizado para versão N" e atualiza `last_update`.

### `POST /api/devices/register` (device) → mesmo comportamento do heartbeat.

### `DELETE /api/devices/{device_id}` (admin) → `{"ok": true}`. Remove o ônibus da lista (desativado ou registro de teste). Um ônibus em operação volta sozinho no próximo heartbeat. `404` se não existe.

### `GET /api/devices` (admin)

```json
[{"device_id": "BUS-001", "hostname": "bus001", "ip": "192.168.100.51",
  "current_version": 12, "sha256": "...", "app_version": "0.1.0",
  "free_space_mb": 21000, "uptime_s": 5400, "reported_status": "ok",
  "status": "updated", "last_error": null,
  "last_seen": "...", "last_update": "...", "first_seen": "...", "seconds_since_seen": 42}]
```

`status` é **derivado** no momento da consulta:

| Condição (na ordem) | `status` |
|---|---|
| Sem heartbeat há mais de `OFFLINE_AFTER_S` (900 s) | `offline` |
| `reported_status == downloading` | `downloading` |
| `reported_status == error` | `error` |
| Nada publicado ou `current_version == versão publicada` | `updated` |
| Caso contrário | `pending` |

### `GET /api/devices/{id}` (admin) → detalhe + `"events": [{"id", "device_id", "at", "level", "message"}]` (últimos 50).

### `GET /api/devices/{id}/status` (admin)

```json
{"device_id": "BUS-001", "status": "updated", "current_version": 12, "last_seen": "...", "last_error": null}
```

## Interface web

| Rota | Descrição |
|---|---|
| `GET /` | Tela do operador. Redireciona para `/login` sem sessão. |
| `GET /login` | Tela de login. |
| `GET /static/...` | CSS e JS locais. |
