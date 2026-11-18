# bus-video-distribution

Distribuição offline de vídeo para as telas internas de ônibus: servidor na garagem + Raspberry Pi em cada veículo.

> Versão de portfólio anonimizada de um projeto desenvolvido para cliente; marcas e dados reais removidos.

## O que faz

- O operador publica um vídeo numa interface web (login obrigatório) no servidor da garagem.
- Cada ônibus tem um Raspberry Pi 3B+ que toca o vídeo em loop, em tela cheia, a partir do armazenamento local.
- Ao entrar no Wi-Fi da garagem, o Pi consulta o servidor, baixa a versão nova em segundo plano (com retomada), valida tamanho, SHA-256 e formato e troca o vídeo de forma atômica, com rollback em caso de falha.
- Sem rede ou sem servidor, o ônibus continua exibindo o último vídeo válido.
- O painel mostra o estado de cada ônibus via heartbeat (pendente, atualizado, offline).

## Destaques técnicos

- HTTPS com CA própria da garagem; cada ônibus fixa (pin) a CA. Redirecionamento HTTP → HTTPS.
- Autenticação com PBKDF2 (stdlib), sessão assinada em cookie `HttpOnly`/`SameSite`, rate limit de login, papéis operador/admin, token de dispositivo para a API.
- Cliente embarcado só com a biblioteca padrão do Python; supervisor do `mpv` com systemd (watchdog via `sd_notify`).
- Instaladores para Ubuntu (systemd) e Windows (PowerShell/tarefa agendada), provisionamento por pendrive/arquivo na partição de boot e instalação em frota via SSH.
- Suíte de testes de servidor, cliente e integração ponta a ponta (incluindo TLS) e um scanner de segurança para a demo.

## Stack

Python 3.11+, FastAPI, SQLite, Jinja2, ffprobe/ffmpeg (servidor) · Python 3 stdlib + mpv, systemd (Raspberry Pi) · pytest.

## Como rodar

```bash
uv venv --python 3.12 .venv
uv pip install -p .venv/bin/python -e "server[dev]" -e "client[dev]"
.venv/bin/python -m pytest              # servidor, cliente e integração

./demo/make_videos.sh                   # gera vídeos de teste (ffmpeg)
./demo/run_demo.sh                      # https://localhost:8443  usuário operador ou admin / senha demo
```

Configuração: copie `server/server.env.example` e `client/config/client.env.example` e preencha. Hashes, `SECRET_KEY` e `DEVICE_TOKEN` são gerados com `python -m busvideo_server.tools gen-env`.

Certificados: nenhum certificado ou chave acompanha o repositório. Gere a CA e o certificado do servidor com
`python -m busvideo_server.tools gen-cert --out <pasta> --ip <IP_DO_SERVIDOR>` e distribua só o `ca.crt` aos ônibus.

## Estrutura

```
server/busvideo_server/   FastAPI: api/, services/, web/ (templates + static), auth, TLS, hardening, fleet
server/tests/             testes do servidor
server/windows/           instalador Windows
client/busvideo_client/   sync, supervisor, download, validação, player/ (mpv e fake)
client/scripts/           diagnóstico, benchmark, Wi-Fi, provisionamento
client/systemd/           units do player, sync e provisionamento
tests_integration/        servidor real + cliente real, incluindo TLS
demo/                     demo no notebook, tela simulada, teste de carga, scan de segurança
docs/                     arquitetura, API, manuais e troubleshooting
```

## Direitos autorais

© 2026 Gustavo Fiedler Calegari. Todos os direitos reservados.

Este código está publicado apenas para avaliação de portfólio. Não é permitido copiar, modificar, distribuir ou usar comercialmente, no todo ou em parte, sem autorização por escrito do autor.
