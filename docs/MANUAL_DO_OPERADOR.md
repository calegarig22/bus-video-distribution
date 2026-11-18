# Manual do Operador

Este manual explica como trocar o vídeo que passa nas telas dos ônibus. Não é preciso saber de computador além do básico. Nunca é preciso mexer no ônibus.

## O que você precisa

- Um computador ou celular conectado à rede da garagem.
- O endereço do sistema (exemplo: `https://192.168.100.10`). Peça ao técnico se não souber.
- Usuário e senha.
- O arquivo do vídeo novo (MP4).

## Passo a passo

### 1. Abrir o sistema

1. Abra o navegador (Chrome, Edge, Firefox).
2. Digite o endereço do sistema e aperte Enter.
3. Digite o usuário `operador` e a senha da equipe. Clique em **ENTRAR**.

Para trocar a sua senha: botão **Senha** no canto superior direito, informe a atual e a nova (mínimo 8 caracteres).

### 2. Ver o vídeo atual

No alto da tela aparece o **Vídeo atual**: nome do arquivo, número da versão, data de publicação, duração e tamanho. O status **● Publicado** confirma que esse é o vídeo que os ônibus devem exibir. Clique em **Pré-visualizar** para assistir.

### 3. Selecionar o vídeo novo

1. Clique em **SELECIONAR NOVO VÍDEO**.
2. Escolha o arquivo no seu computador.
3. O nome e o tamanho aparecem abaixo do botão.

### 4. Enviar

1. Clique em **ENVIAR**.
2. Acompanhe a barra de progresso. Um vídeo grande pode levar alguns minutos. Não feche a página.
3. Ao terminar aparece **Validando o vídeo…** e em seguida o resultado.

### 5. Conferir o resultado

O sistema mostra duração, resolução, codec, FPS, tamanho e o status:

- **✓ Compatível**: pode publicar.
- **✗ Incompatível**: aparece o motivo. O vídeo **não** pode ser publicado. Veja a tabela abaixo.

| Motivo mostrado | O que fazer |
|---|---|
| Codec de vídeo não suportado | Peça a quem fez o vídeo para exportar em **MP4 com H.264** |
| Resolução acima do limite | Exportar em no máximo **1920x1080 (Full HD)** |
| FPS acima do limite | Exportar em no máximo **30 quadros por segundo** |
| Codec de áudio não suportado | Exportar o áudio em **AAC** ou sem áudio |
| Tamanho acima do limite | Reduzir a qualidade ou a duração |
| Duração acima do limite | Encurtar o vídeo |
| Arquivo não é um vídeo válido | O arquivo está corrompido ou não é um vídeo. Peça um novo. |
| Extensão não permitida | O arquivo precisa terminar em `.mp4` |

Resumo para quem produz o vídeo: **MP4, H.264, até 1920x1080, até 30 fps, áudio AAC ou sem áudio.**

### 6. Publicar

1. Com o status **✓ Compatível**, clique em **PUBLICAR**.
2. Aparece a mensagem *Publicado como versão N*.
3. O quadro **Vídeo atual** passa a mostrar o vídeo novo com a versão nova.

Pronto. A partir daqui tudo é automático.

### 7. Acompanhar os ônibus

A lista **Dispositivos** mostra cada ônibus:

| Status | Significado |
|---|---|
| **Atualizado** | Já está com o vídeo mais recente |
| **Pendente** | Ainda não pegou o vídeo novo. Vai pegar quando entrar na garagem |
| **Baixando** | Está na garagem, recebendo o vídeo agora |
| **Offline** | Não se comunica há mais de 15 minutos. Normal quando está na rua |
| **Erro** | Algo deu errado. A observação ao lado explica. Avise o técnico se persistir |

A coluna **Último contato** mostra há quanto tempo o ônibus falou com o sistema. A lista se atualiza sozinha a cada 10 segundos.

Para tirar da lista um ônibus que saiu da frota (ou um registro de teste), clique no **×** no fim da linha e confirme. Se o ônibus ainda existir e voltar à garagem, ele reaparece sozinho.

## Quanto tempo leva

- O ônibus só recebe o vídeo quando está **na garagem, no alcance do Wi-Fi**.
- Ao chegar, ele consulta o sistema em até 1 minuto e começa a baixar.
- Um vídeo de 800 MB leva de 2 a 5 minutos para baixar.
- O vídeo novo entra no ar ao fim do vídeo atual, sem cortar no meio.
- Ônibus que estão na rua aparecem **Offline** ou **Pendente** até voltarem. Isso é normal.

## O que não fazer

- Não desligue o computador do sistema.
- Não feche a página durante o envio.
- Não publique um vídeo **✗ Incompatível** (o botão fica bloqueado).
- Não mexa no equipamento dentro do ônibus. Ele se atualiza sozinho.
- Não compartilhe a senha.

## Perguntas frequentes

**Publiquei, mas o ônibus continua Pendente.**
Ele ainda não entrou na garagem, ou entrou há menos de 1 minuto. Espere. Se ficou na garagem por mais de 30 minutos e continua Pendente, avise o técnico.

**Enviei o vídeo errado. E agora?**
Envie o certo e publique. O anterior é substituído. Cada publicação gera um número de versão novo.

**Quero voltar ao vídeo anterior.**
Envie o arquivo do vídeo anterior de novo e publique. Ele vira a versão mais nova.

**O vídeo aparece Offline em todos os ônibus.**
Se todos estão na garagem, o Wi-Fi ou o computador do sistema pode estar com problema. Avise o técnico.

**Posso publicar vários vídeos?**
Neste protótipo, um vídeo por vez. O último publicado é o que passa.

**Esqueci a senha.**
Avise o responsável técnico. Ele entra com a conta `admin` e define uma senha nova para `operador` em um minuto, sem reinstalar nada. A senha antiga deixa de valer.

## Quem chamar

Suporte técnico: Empresa Exemplo. Informe o nome do ônibus (exemplo `BUS-003`), o status mostrado e a observação ao lado.
