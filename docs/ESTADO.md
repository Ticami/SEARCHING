# Estado do projeto SEARCHING

Arquivo de continuidade: qualquer sessão nova deve ler isto primeiro e **atualizá-lo ao terminar cada tarefa** (mover o item
para "Feito" com o hash do commit, ajustar "Em andamento" e "Próximos passos" e incluir o arquivo no mesmo commit da tarefa).

Última atualização: Fases 1 a 3 do multiusuário prontas (contas/papéis, extensão hospedada, coordenação); push ainda não feito (testes: 278 passando).

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
| Etapa 1: base (README, recharts, código morto) | `829ee42` |
| Etapa 2: SQLite, modelos e migração idempotente dos CSVs | `7366b4c` |
| Etapa 3: coleta robusta (adaptador Magalu, status, CLI `python -m searching.run`, trava, print pelo navegador) | `bcc3bad` |
| Etapa 4: agendamento do Windows (**removido depois**, ver limpeza) | `24c84d1`, `992715f` |
| Etapa 5: recuperação automática de links, nota de confiança, fila e tela de Revisão | `8c5cccf` |
| Etapa 6: alertas de queda por e-mail (print anexado, anti-duplicidade, reenvio, resumo) | `37c7840` |
| Etapa 7: relatórios no banco, Excel, galeria de prints com preço, painel de saúde | `990541a` |
| Etapa 8: segurança do servidor local (127.0.0.1, sem debug, CORS, Host/Origin) | `6ad4006` |
| Etapa 9: demonstração fictícia, imagens/GIF, README final, CI | `7727785` |
| Chrome do coletor sem opções que escondem a automação | `135000c` (já no GitHub) |
| Coleta assistida: extensão do Chrome, fila na tela, captura no servidor, teste ponta a ponta | `b8e8ddd` |
| Aviso amarelo fixo com os erros e Refazer por produto | `78b0ee3` |
| Limpeza (modo automático, agendamento, componentes e CSS mortos, rotas antigas) e nova tela Início explicativa | `a400004` |
| `docs/ESTADO.md` criado | `a555ba0` |
| Tarefa do Windows "SEARCHING - Coleta" removida a pedido do usuário (ação fora do repositório, conferida: não existe mais) | `cfe4efc` |
| **Push** de tudo para o GitHub (branch de segurança `backup/antes-das-etapas` mantida) | `ca7b715` |
| Multiusuário, Fase 0: `docs/DESENHO_MULTIUSUARIO.md` (extensão hospedada viável; modelo, matriz, pareamento) | `cdfcf5f` |
| Multiusuário, Fase 1: contas, papéis deny-by-default, sessões/CSRF, bloqueio, recuperação de senha, 2FA, auditoria, CLI `searching.usuarios`, telas Login/Conta/Usuários | `b3c746c` |
| Multiusuário, Fases 2 e 3 (no mesmo commit): extensão v2 (página de opções, servidor fixado em HTTPS, token por usuário, `autorizar` no servidor), intervalo de 3 s e limite por loja impostos pelo servidor, pausa após 2 BLOQUEIOS, atribuição de produtos, "em coleta por fulano", captura registrada em nome de quem coletou, token de leitura (BI), e2e `--hospedado` (escrito, **não executado**) | commit seguinte a `b3c746c` |

## Em andamento

Transformação em sistema multiusuário (`docs/DESENHO_MULTIUSUARIO.md`). Concluídas as Fases 0 a 3; falta a **Fase 4 (operação)**: guia de
implantação, Docker/compose, PostgreSQL opcional, armazenamento de prints configurável, backup/restauração e logs estruturados.
Decisão: extensão hospedada é viável, **plano B não foi usado**. Modo local segue idêntico (sem login).
**Pendente de validação humana:** `python scripts/e2e_assistida.py` (local) e `... --hospedado` não foram rodados após a extensão v2
(abrem janelas e baixam o Chrome for Testing, ~460 MB); a extensão só passou em `node --check` e nos testes do servidor.

## Próximos passos (sugestões)

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
- **Push só quando o usuário mandar.** Antes de um push, criar branch de segurança no GitHub (existe `backup/antes-das-etapas`).
- **Commits não incluem `iniciar_searching.bat`** (edição antiga do usuário) e terminam com a linha `Co-Authored-By` definida pela sessão.
- E-mail dos alertas **fixo no `.env`** por ora (credenciais nunca no Git nem no chat; `.env.example` no repositório).
- O usuário deu autonomia para construir sem perguntar cada detalhe; ainda assim avisar antes de abrir janelas na tela dele e
  relatar o que foi baixado/alterado fora do projeto. Não alterar configurações do Windows sem o aval dele.
- Dados reais (`backend/data/`, `backend/prints/`) ficam fora do Git; as imagens do README usam só dados fictícios.

## Pendências do usuário

- Extensão do Chrome: **já carregada pelo usuário** (pasta `extensao`). Falta testar a coleta assistida na Magalu real e relatar o que aparecer (cartão 1x vazio, preço não encontrado etc.).
- Reiniciar o programa (`iniciar_searching.bat`) para usar a versão nova (a tela e o servidor antigos não têm a coleta assistida).
