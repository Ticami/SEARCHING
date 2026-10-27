# Estado do projeto SEARCHING

Arquivo de continuidade: qualquer sessão nova deve ler isto primeiro e **atualizá-lo ao terminar cada tarefa** (mover o item
para "Feito" com o hash do commit, ajustar "Em andamento" e "Próximos passos" e incluir o arquivo no mesmo commit da tarefa).

Última atualização: extensão 2.1.1 (aba dedicada persistida) e menu lateral retrátil prontos; push ainda não feito (backend 323 testes, interface 40).

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

Nada no código. Concluídos: multiusuário (Fases 0 a 4), reforço de segurança (limite de requisições, sessões ativas, 2FA de admin, ids da
extensão, retenção de prints), validações (Docker, PostgreSQL real, página de opções por HTTPS, Magalu real em HTML salvo), tópico 3
(histórico de links, destinatários, assinaturas, resumo semanal) e **tópico 4 (qualidade)**:
- `server.py` dividido em blueprints por assunto em `backend/searching/web/` (`rotas_conta`, `rotas_links`, `rotas_relatorios`,
  `rotas_alertas`, `rotas_assistida`, `rotas_sistema`); os nomes das rotas na política mudaram para `blueprint.funcao`.
- Testes de interface com Vitest + Testing Library (`cd frontend && npm test`, 33 testes: Login, Minha conta, Usuários, Coleta assistida
  com extensão simulada, Histórico de links, Alertas), já no CI.
- Acessibilidade e responsividade das telas novas, sem mudar o design: nomes acessíveis em campos e botões repetidos, `autocomplete`,
  `role=status/alert`, `scope` e legenda nas tabelas, classe utilitária `.sr-only`; conferido num viewport de celular (375 px).
  Achado e corrigido: o CSP do modo hospedado bloqueava o Google Fonts do design (agora libera `fonts.googleapis.com`/`gstatic`).
- Atualização da extensão: `extensao/README.md` ("Atualizar a extensão"), `extensao/CHANGELOG.md`, extensão **2.1.0** que informa a
  versão ao servidor e `SEARCHING_EXTENSAO_VERSAO_MINIMA` para forçar a atualização (erro 426).
- **Extensão 2.1.1 (corrige janela duplicada):** a aba dedicada e o instante da última navegação agora ficam em `chrome.storage.session`
  (o service worker MV3 é encerrado por ociosidade e a variável em memória se perdia). `garantirAba()` restaura, confirma com
  `chrome.tabs.get` e só então reaproveita; se a aba foi fechada, cria outra. O e2e ganhou o passo "para o service worker (CDP
  `ServiceWorker.stopAllWorkers`) e confere que continua 1 janela" (reproduz o defeito com a versão antiga: 2 -> 3 abas). Os e2e passaram
  a apontar para o Chrome for Testing do cache do Selenium: o Chrome instalado (mesma versão) passou a ser preferido e não aceita `--load-extension`.
- **Menu lateral retrátil:** botão `«/»` no cabeçalho da barra (`frontend/src/sidebar.jsx`, usado em `App.jsx`), com `aria-expanded`,
  `aria-controls` e `aria-label`, acessível por teclado; a escolha fica em `localStorage` (com try/catch: sem ele a tela funciona igual).
  Recolhida, a barra vira uma faixa de 64 px só com o botão (o conteúdo ganha espaço); no celular (<= 860 px) começa recolhida, com o
  logo e o botão numa linha. Só acrescentei classes `.sidebar-recolhida`/`.sidebar-toggle`/`.sr-only`; o visual aberto é o mesmo.
  Recolhida, o menu vira uma faixa de **ícones** (os links mantêm nome acessível e `title`; o selo de revisões pendentes aparece como número). Aberta, não há ícones.
  Testes Vitest em `src/test/sidebar.test.jsx` (7).
**Validado em 2026-10-27:** e2e local e `--hospedado` com Chrome real e a extensão 2.1.0.
**Ainda não validado:** coleta ao vivo na Magalu real com a extensão (o usuário deve rodar e relatar); layouts de página diferentes
(vendedor terceiro, indisponível); o e2e de opções (`e2e_opcoes_extensao.py`) com a 2.1.0 e o stack Docker.

## Próximos passos (sugestões)

0. **Feito depois do multiusuário (tópico 3):** tela do histórico de trocas de link; destinatários de e-mail editáveis pela interface (senha continua no `.env`); alertas por usuário (assinaturas por produto); resumo semanal em Excel (`searching.operacao resumo-semanal`).
0. **Ainda de fora, com o motivo:** abstração de fontes de dados (API/feed oficial da Magalu: depende de acesso de parceiro; refatoração grande sem uma segunda fonte para validar); adaptador do Mercado Livre (falta o HTML real da página do anúncio, como foi feito com a Magalu); exportar/importar o espaço de trabalho em formato próprio e arquivamento do histórico de preços (o backup/restauração já cobre o essencial; arquivar exige decidir o que vale apagar); prints em armazenamento de objetos; áreas privadas por pessoa (só desenhadas, ver `docs/DESENHO_MULTIUSUARIO.md` 7.2).
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
