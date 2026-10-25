# Guia de implantação (modo hospedado)

Para usar o SEARCHING com várias pessoas, em um servidor ou na nuvem. O modo local (um computador, sem login) não muda e não precisa
de nada daqui.

> **Lembrete central:** o servidor **nunca abre as lojas**. A coleta acontece no computador de cada pessoa, pela extensão do
> navegador (veja `extensao/README.md`). O servidor só recebe dados lidos e prints.

## 1. O que você precisa

- Um servidor Linux (ou serviço de contêineres) com um **domínio** apontando para ele.
- **HTTPS obrigatório.** O sistema recusa iniciar com `SEARCHING_URL_PUBLICA` em `http://` (exceto `localhost`, para testes). O
  cookie de sessão sai com `Secure`; a extensão só aceita servidor HTTPS.
- Uma conta de e-mail SMTP (alertas e recuperação de senha). Gmail: ative a verificação em duas etapas e crie uma *senha de app*.

## 2. Segredos: só por variável de ambiente

Nenhum segredo vai para o Git, para a imagem ou para o código. Use variáveis de ambiente, o arquivo `deploy/hospedado.env` (ignorado
pelo Git, permissão `600`) ou o gerenciador de segredos do seu provedor.

| Variável | Para quê |
|---|---|
| `SEARCHING_MODO=hospedado` | Liga login, papéis, auditoria e bloqueia a coleta automática. |
| `SEARCHING_URL_PUBLICA` | `https://searching.suaempresa.com` (obrigatória, sem caminho). Também define quais `Host` e `Origin` são aceitos. |
| `SEARCHING_PROXIES` | Número de proxies reversos confiáveis à frente (`1` com Caddy/nginx). Sem isso o IP dos logs/limites é o do proxy. |
| `SEARCHING_DATABASE_URL` | `postgresql://usuario:senha@host:5432/banco`. Sem ela, usa SQLite (`SEARCHING_DB`). |
| `SEARCHING_PRINTS` | Pasta dos prints (um volume persistente). |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERTA_DESTINATARIOS` | E-mail. A senha de app nunca é guardada no banco. |
| `SEARCHING_LOG_FORMATO` / `SEARCHING_LOG_NIVEL` | `json` (padrão no hospedado) ou `texto`; `INFO`, `WARNING`... |
| `SEARCHING_ORIGENS` | Origens `https://` extras permitidas no CORS (raro). |
| `SEARCHING_2FA_ADMIN` | `1` (padrão): administradores **precisam** ativar o 2FA para usar o sistema. `0` desliga. |
| `SEARCHING_EXTENSAO_IDS` | Ids oficiais da extensão, separados por vírgula (o do Chrome e o do Edge são diferentes). Com a lista, o servidor só aceita capturas vindas de `chrome-extension://<id da lista>`, além do token. Vazio = só o token. |
| `SEARCHING_RETENCAO_PRINTS_DIAS` | Apaga prints com mais de N dias (0 = guardar para sempre). Também configurável na tela Usuários. |
| `SEARCHING_PRINTS_ARQUIVO` | Se definido, os prints vencidos são movidos para esta pasta em vez de apagados. |
| `SEARCHING_LIMITE_REQ_MIN`, `SEARCHING_LIMITE_ESCRITA_MIN`, `SEARCHING_LIMITE_EXPORTAR_MIN` | Limites por minuto, por usuário (ou por IP sem login): leitura 600, escrita 120, exportação 10. `0` desliga. Contados por processo do gunicorn. |

## 3. Opção A: Docker Compose (recomendada)

```bash
cp deploy/hospedado.env.example deploy/hospedado.env     # preencha domínio, senha do banco e SMTP
docker compose --env-file deploy/hospedado.env up -d --build
```

Sobe três serviços: `app` (gunicorn), `db` (PostgreSQL 16) e `proxy` (Caddy, que obtém o certificado HTTPS sozinho; as portas 80 e
443 precisam estar abertas e o DNS apontando para o servidor). Os dados ficam nos volumes `pgdados` e `prints`.

Primeiro administrador (a senha é pedida no terminal, nunca por argumento):

```bash
docker compose exec app python -m searching.usuarios criar-admin --email voce@suaempresa.com --nome "Seu Nome"
```

> Os arquivos Docker foram escritos e revisados, mas **ainda não foram construídos nem executados** em nenhuma máquina; teste num
> ambiente de homologação antes de usar de verdade.

## 4. Opção B: sem Docker

```bash
cd backend
python -m venv venv && venv/bin/pip install -r requirements-hospedado.txt
cd ../frontend && npm ci && npm run build && cd ../backend
export SEARCHING_MODO=hospedado SEARCHING_URL_PUBLICA=https://searching.suaempresa.com SEARCHING_PROXIES=1 \
       SEARCHING_DATABASE_URL=postgresql://searching:SENHA@localhost/searching SEARCHING_PRINTS=/var/lib/searching/prints
python -m searching.usuarios criar-admin --email voce@suaempresa.com
venv/bin/gunicorn -b 127.0.0.1:8000 -w 2 --threads 4 server:app
```

Coloque nginx/Caddy na frente fazendo HTTPS e repassando `Host`, `X-Forwarded-For`, `X-Forwarded-Proto` e `X-Forwarded-Host`. O
servidor de desenvolvimento do Flask (`python server.py`) **recusa** iniciar no modo hospedado.

## 5. PostgreSQL

- **Banco novo:** basta definir `SEARCHING_DATABASE_URL`; as tabelas são criadas no primeiro início.
- **Migrar o que já existe em SQLite** (com o servidor parado): `python -m searching.operacao migrar-banco --destino postgresql+psycopg://...`.
  O destino precisa estar vazio; as sequências de id são realinhadas.
- O SQLite continua sendo o padrão do modo local. Dentro do hospedado, SQLite só serve para poucas pessoas (um único processo gravando).

## 6. Prints

Ficam em arquivos, na pasta `SEARCHING_PRINTS`. Em contêiner, use **volume persistente**. O acesso é só pela API, com login (o
papel mínimo é `leitor`). Armazenamento em nuvem de objetos (S3 etc.) não foi implementado: monte o bucket como volume se precisar.

## 7. Backup e restauração

```bash
python -m searching.operacao backup --destino /backups            # SQLite + prints num .zip
pg_dump -h HOST -U searching -Fc searching > banco.dump          # com PostgreSQL; some "backup --so-prints" para os prints
python -m searching.operacao restaurar /backups/searching-backup-AAAAMMDD-HHMMSS.zip --confirmar   # servidor parado
```

A restauração **não apaga** o banco atual: ele vira `searching.db.antes-<data>`. Agende o backup (cron) e guarde cópias fora do
servidor. **Teste a restauração** antes de precisar dela.

## 8. Retenção dos prints

Prints podem mostrar nome/CEP de quem coletou logado na loja. Defina um prazo (tela Usuários → *Retenção dos prints*, ou
`SEARCHING_RETENCAO_PRINTS_DIAS`). A política roda a cada início do servidor; para rodar todo dia, agende:

```bash
python -m searching.operacao reter-prints              # usa o prazo configurado
python -m searching.operacao reter-prints --dias 90 --simular   # só mostra o que seria removido
```

O histórico de preços fica; só o arquivo do print sai (ou vai para `SEARCHING_PRINTS_ARQUIVO`).

## 9. Logs

Uma linha JSON por evento, na saída padrão (o Docker/provedor recolhe). Cada requisição registra `request_id` (também devolvido no
cabeçalho `X-Request-ID`), método, caminho, status, duração, usuário e IP. **Não** entram corpos, cookies, tokens nem query strings.
A trilha de auditoria (quem fez o quê) fica no banco e aparece na tela Usuários (`/api/auditoria`).

## 10. Lista de verificação de segurança

- [ ] Domínio com HTTPS válido; `SEARCHING_URL_PUBLICA` em `https://`.
- [ ] Banco e volume de prints **não expostos** à internet (só o proxy publica portas).
- [ ] Primeiro admin criado pelo comando; sem senha padrão. O 2FA do admin é obrigatório (ative em *Minha conta* no primeiro acesso; se perder o aparelho: `python -m searching.usuarios desativar-2fa --email ...`).
- [ ] `SEARCHING_EXTENSAO_IDS` com o(s) id(s) oficial(is) da extensão publicada.
- [ ] Prazo de retenção dos prints definido.
- [ ] Sessões ativas revisadas de vez em quando (tela Usuários) e encerradas as suspeitas.
- [ ] `deploy/hospedado.env` com permissão restrita e fora do Git; senha do banco longa e aleatória.
- [ ] Backup agendado e restauração testada.
- [ ] Usuários com o **menor papel** possível (`leitor` por padrão); coletores com produtos atribuídos.
- [ ] Extensão distribuída por canal controlado (loja não listada ou política corporativa) e com o servidor correto nas opções.
- [ ] Aviso de privacidade dos prints comunicado à equipe (nome/CEP de quem está logado na loja).
- [ ] Atualizações: `git pull && docker compose up -d --build`; faça um backup antes.
