# Desenho: SEARCHING multiusuário

## 1. Decisão: a extensão em modo hospedado É viável (plano completo, não o plano B)

Em modo hospedado só trafegam **dados estruturados + HTML lido + print**, e a navegação acontece no Chrome/Edge da própria pessoa
(IP e sessão dela). O servidor hospedado **nunca abre lojas**. Validei cada ponto da premissa:

| Ponto | Conclusão |
|---|---|
| CORS / Origin | A extensão envia `fetch` do service worker com `Origin: chrome-extension://<id>`. O servidor **não** abre CORS para ela: ele aceita a requisição só se houver token válido **e** a rota for a da captura (mesma regra de hoje, agora por usuário). O navegador comum (sites) continua limitado à origem pública do próprio site. |
| Content script no domínio hospedado | O `manifest.json` não pode listar um domínio que ainda não existe. A extensão passa a ter uma **página de opções**: a pessoa informa a URL do servidor (HTTPS), a extensão pede a permissão **opcional** daquele domínio e registra o `ponte.js` só nele (`chrome.scripting.registerContentScripts`). |
| URL "fixada" | Depois de configurada, a URL só muda pela página de opções (ação explícita da pessoa). O `ponte.js` e o servidor nunca conseguem trocar a URL por mensagem; o pareamento só aceita token vindo do domínio já fixado. |
| Token por usuário | Tabela `tokens_api` (só o hash SHA-256 é guardado). Escopo `extensao`: enviar capturas e pedir autorização de abertura, **apenas para a sessão de coleta do dono do token**. Token de A não abre sessão de B. |
| Revogação | Revogar na tela de Usuários grava `revogado_em`; a próxima requisição já falha (o hash é consultado a cada chamada, sem cache). Desativar o usuário também derruba os tokens dele. |
| Distribuição | (a) Chrome Web Store **não listada** (recomendado: link privado, atualizações automáticas); (b) política corporativa (`ExtensionInstallForcelist`) via Google Workspace/Intune; (c) pacote `.zip` para "Carregar sem compactação" (só para quem é técnico; `scripts/empacotar_extensao.py`). Edge (Chromium) usa o mesmo pacote: `edge://extensions` ou o portal Edge Add-ons. |
| Privacidade dos prints | O print sai do navegador de quem coleta e pode mostrar nome/CEP da pessoa logada na loja. Mantido o **recorte do topo** (configurável na página de opções) e adicionado **aviso** na tela de coleta e no README: usar um perfil do navegador sem login na loja. |

Riscos aceitos e mitigações: o print armazenado no servidor é dado de terceiros (mitigação: recorte, aviso, acesso aos prints só
para usuários autenticados e HTTPS obrigatório); o HTML lido vem de um navegador não confiável (mitigação: o servidor só
**extrai** preços com BeautifulSoup e valida status/preço suspeito; nunca executa nada do HTML).

## 2. Modos de execução

`SEARCHING_MODO=local` (padrão) — idêntico a hoje: 127.0.0.1, **sem login**, token global em arquivo, coleta automática e assistida
disponíveis. Quem acessa é tratado como `admin` local.

`SEARCHING_MODO=hospedado` — exige `SEARCHING_URL_PUBLICA` em HTTPS. Login obrigatório, papéis, auditoria, tokens por usuário. As
rotas que abrem lojas (`/api/coletar`, `searching.run`, `Navegador`) ficam **bloqueadas para todos, até para admin**: a coleta
só acontece pela extensão no computador da pessoa. Escolhido o espaço de trabalho **compartilhado com papéis** (áreas privadas por
pessoa ficam para depois).

## 3. Modelo de dados (novas tabelas; as existentes ganham colunas nulas)

- `usuarios`: id, email (único), nome, papel (`admin|coletor|leitor`), senha_hash (Argon2id), ativo, deve_trocar_senha, falhas_login,
  bloqueado_ate, totp_segredo, totp_ativo, criado_em, ultimo_login.
- `sessoes_login`: hash do cookie, usuario_id, csrf, criada_em, ultimo_uso, expira_em, ip, user_agent, revogada.
- `tokens_api`: usuario_id, tipo (`extensao|leitura`), nome, prefixo, hash, criado_em, ultimo_uso, revogado_em.
- `redefinicoes_senha`: usuario_id, hash, expira_em, usado_em.
- `tentativas_login`: email, ip, em, sucesso (limite de tentativas por conta e por IP).
- `auditoria`: em, usuario_id, usuario_email, acao, alvo, detalhe (JSON), ip.
- `atribuicoes`: (produto_id, usuario_id).
- `aberturas_pagina`: em, usuario_id, produto_id, loja (intervalo mínimo e limite global por loja).
- Colunas novas: `execucoes.usuario_id`, `coletas.coletado_por_id` ("quem capturou cada coisa").

## 4. Papéis e matriz de permissões

Ordem: `leitor` < `coletor` < `admin`. **Deny by default**: o arquivo `searching/auth/politicas.py` declara a política de cada
endpoint; endpoint sem política responde 403 e um teste falha se existir rota sem política. "Dono" = `coletor` com o produto atribuído.

| Rota | Política |
|---|---|
| `GET /api/health`, `GET /api/modo`, `POST /api/auth/login`, `POST /api/auth/recuperar`, `POST /api/auth/redefinir`, arquivos estáticos | pública |
| `POST /api/auth/logout`, `GET /api/auth/eu`, `POST /api/auth/trocar-senha`, 2FA (`/api/auth/2fa/*`), `/api/meus-tokens*` | qualquer usuário logado |
| `GET` de links, histórico de links, revisões, prints, histórico, galeria, saúde, alertas, regras; `POST /api/historico/exportar` (Excel, só leitura) | leitor |
| `PUT /api/links`, `PUT /api/alertas/regras/<id>`, `POST /api/revisoes/<id>/resolver` | coletor **dono** do produto, ou admin |
| `/api/assistida/sessao\|iniciar\|pular\|encerrar\|link-quebrado\|autorizar-abertura` | coletor (sessão própria) |
| `POST /api/assistida/captura` | token `extensao` do dono da sessão |
| `POST /api/links`, `DELETE /api/links`, reversão de troca, `PUT /api/alertas/config`, `POST /api/alertas/teste` | admin |
| `POST /api/coletar` | admin, **e só em modo local** |
| `/api/usuarios*`, `/api/atribuicoes*`, `/api/auditoria`, `/api/tokens*` (de outros) | admin |
| `GET /api/assistida/token` (token global) | só modo local; inexistente em hospedado |

`leitor` com token `leitura`: aceita só métodos GET/HEAD (integração com planilha/BI).

## 5. Segurança da sessão

Cookie `searching_sessao` (`HttpOnly`, `Secure` em hospedado, `SameSite=Lax`), valor aleatório de 256 bits (guardado só o hash).
CSRF: escritas por sessão exigem `X-CSRF-Token` + `Origin` igual à URL pública. Login: 5 falhas seguidas bloqueiam a conta por 15 min;
mais de 20 falhas por IP em 15 min recebem 429; resposta idêntica para e-mail inexistente. Senhas: mínimo 12 caracteres. 2FA TOTP opcional
(RFC 6238, implementação própria sem dependência). Recuperação: link de uso único (30 min) enviado ao e-mail do usuário pelo SMTP do `.env`.

Reforços adicionados depois (ver `docs/IMPLANTACAO.md`): limite de requisições por minuto em toda a API, tela de sessões ativas com
encerramento (própria e, para o admin, de qualquer pessoa), 2FA obrigatório para administradores, lista de ids permitidos da
extensão e retenção configurável dos prints.

## 6. Fluxo de pareamento da extensão

1. Instalar a extensão e abrir a **página de opções**: informar a URL do servidor (HTTPS) → a extensão pede a permissão do domínio.
2. Entrar no site, tela **Coleta assistida** → "Parear extensão": o servidor cria um token `extensao` do usuário e a página o entrega
   à extensão pelo `ponte.js` (só aceito se a página for do domínio fixado). Alternativa: criar o token em "Minha conta" e colar nas opções.
3. A cada clique em Próximo, a extensão chama `autorizar-abertura` (servidor valida sessão do dono, intervalo mínimo de 3 s por usuário,
   produto não está em coleta por outra pessoa, limite global por loja); só então abre a página. Depois envia a captura.
4. Em modo local nada muda: pareamento automático com o token global.

## 7. Coordenação (Fase 3)

Produtos atribuídos a usuários; a fila de um coletor contém só o que lhe foi atribuído (admin: tudo). Produto numa sessão ativa de outra
pessoa fica fora da fila ("em coleta por fulano"). Limite global por loja: `limite_loja_hora` (padrão 120 aberturas/hora): excedido, o servidor
nega a abertura (429) e registra `limite_loja` na auditoria, visível ao admin.

## 7.1 Alertas por usuário e resumo semanal

Cada usuário pode **assinar produtos** (tela Alertas): os e-mails de queda daquele produto vão para a lista de destinatários **mais** os
assinantes. A lista de destinatários é editável pelo admin na interface (vazia = vale `ALERTA_DESTINATARIOS` do `.env`; a senha do SMTP
nunca sai do `.env`). O leitor continua sem escrever: quem assina por ele é o admin (`PUT /api/usuarios/<id>/assinaturas`). O **resumo
semanal em Excel** (`python -m searching.operacao resumo-semanal`, agendado 1x por semana, ligado em Alertas) manda a planilha de tudo
para a lista e, para cada assinante, só dos produtos dele.

## 7.2 Áreas privadas por pessoa (desenhado, NÃO implementado)

Hoje há um espaço de trabalho compartilhado com papéis. Para áreas privadas, o caminho seria: coluna `espaco_id` em `produtos`, `usuarios`
(ou tabela de associação com papel por espaço), filtro por espaço em toda consulta (`listar_ativos`, `historico`, `galeria`, `saude`,
`alertas`, `atribuicoes`) e nos prints (`prints/<espaco>/<data>/`), papel avaliado **por espaço**, e `espaco_id` nas sessões de coleta, nos
tokens e na auditoria. Migração: tudo que existe vai para o espaço 1. É uma mudança transversal (toda rota passa a depender do espaço),
por isso ficou para uma etapa própria, com testes de isolamento entre espaços antes de qualquer outra coisa.

## 8. Migração

Banco existente: `iniciar_banco` cria tabelas e colunas novas sozinho. Dados atuais ficam no espaço compartilhado; coletas antigas têm
`coletado_por_id` nulo. Modo local não exige nenhuma ação. Para hospedar: criar o primeiro admin (`python -m searching.usuarios criar-admin`),
definir as variáveis do guia de implantação e (opcional) migrar SQLite → PostgreSQL com `python -m searching.operacao migrar-banco`.
