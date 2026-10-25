# Estado do projeto SEARCHING

Arquivo de continuidade: qualquer sessão nova deve ler isto primeiro e **atualizá-lo ao terminar cada tarefa** (mover o item
para "Feito" com o hash do commit, ajustar "Em andamento" e "Próximos passos" e incluir o arquivo no mesmo commit da tarefa).

Última atualização: Multiusuário completo (Fases 0 a 4); push ainda não feito (testes: 287 passando).

## Resumo do projeto

Monitor de preços com **evidência em print**: lê o preço de produtos em lojas (PIX e cartão 1x), guarda um print da página,
valida o resultado (status explícito, preço suspeito), recupera links quebrados, avisa por e-mail quando o preço cai e gera
relatórios. Dados 100% locais.

- **Stack:** Python 3.12 (Flask, Selenium, SQLAlchemy/SQLite, BeautifulSoup, openpyxl) e React + Vite (recharts). Extensão do Chrome (Manifest V3).
- **Pastas:** `backend/searching/` (adapters, core, links, alerts, db, relatorios, assistida, seguranca), `backend/server.py` (API),
  `frontend/`, `extensao/`, `scripts/`, `docs/`, `backend/tests/`.
- **Rodar:** `iniciar_searching.bat` (backend 127.0.0.1:5000 + frontend http://localhost:5173).
  **Demonstração com dados fictícios:** `scripts\iniciar_demo.bat`. **Testes:** `cd backend && pytest` (e `ruff check --select F`).
  **Teste ponta a ponta da extensão:** `scripts/e2e_assistida.py` (baixa o Chrome for Testing, ~460 MB; abre janelas na tela).
- **Telas:** Início (explica o site), Relatórios, Curvas, Prints, Links, Coleta assistida, Alertas, Revisão.
- Detalhes de uso e decisões técnicas: `README.md` e `extensao/README.md`.

## Feito (hash do commit)

| Item | Commit |
|---|---|
| Senha fixa removida, `.gitignore` e histórico reescrito (sem senha, sem node_modules) | `bbc1342` |
| Etapa 1: base (README, recharts, código morto) | `d1fe20a` |
| Etapa 2: SQLite, modelos e migração idempotente dos CSVs | `b808429` |
| Etapa 3: coleta robusta (adaptador Magalu, status, CLI `python -m searching.run`, trava, print pelo navegador) | `9a0aec9` |
| Etapa 4: agendamento do Windows (**removido depois**, ver limpeza) | `cea36ee`, `6738fc4` |
| Etapa 5: recuperação automática de links, nota de confiança, fila e tela de Revisão | `06f4de6` |
| Etapa 6: alertas de queda por e-mail (print anexado, anti-duplicidade, reenvio, resumo) | `60c4f16` |
| Etapa 7: relatórios no banco, Excel, galeria de prints com preço, painel de saúde | `5a0791e` |
| Etapa 8: segurança do servidor local (127.0.0.1, sem debug, CORS, Host/Origin) | `15cb6b9` |
| Etapa 9: demonstração fictícia, imagens/GIF, README final, CI | `40d9725` |
| Chrome do coletor sem opções que escondem a automação | `67dad5b` (já no GitHub) |
| Coleta assistida: extensão do Chrome, fila na tela, captura no servidor, teste ponta a ponta | `91a27d6` |
| Aviso amarelo fixo com os erros e Refazer por produto | `d7b3e4f` |
| Limpeza (modo automático, agendamento, componentes e CSS mortos, rotas antigas) e nova tela Início explicativa | `598d759` |
| `docs/ESTADO.md` criado | `7dfe034` |
| Tarefa do Windows "SEARCHING - Coleta" removida a pedido do usuário (ação fora do repositório, conferida: não existe mais) | `147c872` |
| **Push** de tudo para o GitHub (branch de segurança `backup/antes-das-etapas` mantida) | `d4378c9` |
| Multiusuário, Fase 0: `docs/DESENHO_MULTIUSUARIO.md` (extensão hospedada viável; modelo, matriz, pareamento) | `2fe727c` |
| Multiusuário, Fase 1: contas, papéis deny-by-default, sessões/CSRF, bloqueio, recuperação de senha, 2FA, auditoria, CLI `searching.usuarios`, telas Login/Conta/Usuários | `24ba9e3` |
| Multiusuário, Fases 2 e 3 (no mesmo commit): extensão v2 (página de opções, servidor fixado em HTTPS, token por usuário, `autorizar` no servidor), intervalo de 3 s e limite por loja impostos pelo servidor, pausa após 2 BLOQUEIOS, atribuição de produtos, "em coleta por fulano", captura registrada em nome de quem coletou, token de leitura (BI), e2e `--hospedado` (escrito, **não executado**) | `c22aaa4` |
| Multiusuário, Fase 4: PostgreSQL opcional (`SEARCHING_DATABASE_URL`), `searching.operacao` (backup, restauração, migrar-banco), logs JSON com request id, `Dockerfile`/`docker-compose.yml`/Caddy (**não construídos**), `docs/IMPLANTACAO.md` | commit seguinte a `c22aaa4` |

## Em andamento

Nada no código. O sistema multiusuário (`docs/DESENHO_MULTIUSUARIO.md`, `docs/IMPLANTACAO.md`) está completo nas Fases 0 a 4; decisão: extensão
hospedada é viável, **plano B não foi usado**; modo local segue idêntico (sem login).
**Validado em 2026-10-25:** `scripts/e2e_assistida.py` (local) e `--hospedado` passaram com Chrome real (extensão v2). Ainda não validados: `Dockerfile`/`docker-compose.yml` (não construídos) e PostgreSQL real (só SQLite->SQLite).

## Próximos passos (sugestões)

0. **Multiusuário, o que ficou de fora:** alertas por usuário e resumo semanal em Excel, abstração de fontes de dados (API/feed oficial), retenção/arquivamento, exportação/importação do espaço de trabalho (o backup cobre o essencial), prints em armazenamento de objetos, edição dos destinatários pela interface, áreas privadas por pessoa.
1. **Validar os seletores reais da Magalu** na coleta assistida (PIX, vendedor, menu de pagamento/cartão 1x). Hoje só foram
   testados com HTML sintético e uma loja simulada. Opção: o usuário salva o HTML de um produto (F12, Copy outerHTML) para virar fixture.
2. **Adaptador do Mercado Livre** com coleta automática (a busca abriu normal no coletor: 43 resultados; falta ver a página do anúncio).
3. **Tela do histórico de trocas de link** (a API de histórico e reversão já existe e tem teste).
4. Edição dos destinatários de e-mail pela interface (hoje fixos no `.env`).
5. Alertas de alta de preço e de volta ao estoque; login opcional; adaptadores da Amazon (pediu captcha) e Casas Bahia.
6. Canal oficial da Magalu (API/feed para parceiros) para volume sem cliques.

## Decisões e limites

- **Nunca contornar o anti-bot da Magalu:** sem stealth, sem esconder automação, sem captcha, sem rotação de User-Agent. A coleta
  assistida é **um clique humano por página**, intervalo mínimo de 3 s; **não existe "Coletar tudo"** (decisão tomada e documentada).
- **Push só quando o usuário mandar** (a pedido dele o Claude pode fazer o push; regra de 2026-10-25). **Sempre sem coautoria/menção ao Claude** nos commits enviados. Antes de push que reescreva histórico, criar branch de segurança no GitHub e usar `--force-with-lease`.
- (antigo) Push só quando o usuário mandar. Antes de um push, criar branch de segurança no GitHub (existe `backup/antes-das-etapas`).
- **Commits não incluem `iniciar_searching.bat`** (edição antiga do usuário) e **NÃO levam `Co-Authored-By` nem qualquer menção ao Claude** (regra do usuário, 2026-10-25; vale mesmo que a sessão sugira o contrário).
- E-mail dos alertas **fixo no `.env`** por ora (credenciais nunca no Git nem no chat; `.env.example` no repositório).
- O usuário deu autonomia para construir sem perguntar cada detalhe; ainda assim avisar antes de abrir janelas na tela dele e
  relatar o que foi baixado/alterado fora do projeto. Não alterar configurações do Windows sem o aval dele.
- Dados reais (`backend/data/`, `backend/prints/`) ficam fora do Git; as imagens do README usam só dados fictícios.

## Pendências do usuário

- Extensão do Chrome: **já carregada pelo usuário** (pasta `extensao`). Falta testar a coleta assistida na Magalu real e relatar o que aparecer (cartão 1x vazio, preço não encontrado etc.).
- Reiniciar o programa (`iniciar_searching.bat`) para usar a versão nova (a tela e o servidor antigos não têm a coleta assistida).
