# SEARCHING

Monitor de preços com evidência em print. Abre o link de cada produto em lojas concorrentes, coleta os preços, tira um print da página e guarda o histórico.

> Projeto em evolução. Já tem banco SQLite, coleta agendada pelo Windows, recuperação automática de links com fila de revisão e alertas de queda por e-mail. Relatórios, curvas, galeria de prints e painel de saúde leem do banco.

## Como surgiu

Em um contexto de pricing era preciso acompanhar o preço de celulares em lojas concorrentes e guardar prova visual da página, algo que a solução terceirizada não entregava.

## Stack

- Backend: Python, Flask, Selenium (ChromeDriver), pandas
- Frontend: React + Vite (react-router, framer-motion, recharts)
- Dados: CSV (migração para SQLite planejada)

## Como rodar (Windows)

Requisitos: Python 3.11+, Node.js 18+, Google Chrome.

```bash
iniciar_searching.bat
```

O script cria o ambiente virtual do backend, instala as dependências, sobe o servidor Flask e o frontend (http://localhost:5173).

Para instalar as dependências do frontend manualmente:

```bash
cd frontend
npm install
```

## Coleta pela linha de comando

A coleta roda como comando independente do servidor web (a partir de `backend/`):

```bash
python -m searching.run                                    # todos os produtos ativos
python -m searching.run --origem agendada --loja magalu    # só uma loja
python -m searching.run --incluir "Samsung Galaxy S25 256GB"
```

Cada produto recebe um status (`OK`, `LINK_QUEBRADO`, `PRODUTO_DIVERGENTE`, `PRECO_NAO_ENCONTRADO`, `INDISPONIVEL`, `TIMEOUT`, `BLOQUEIO`, `ERRO_INESPERADO` ou `SUSPEITO`). Nunca há `OK` sem preço. O print é o screenshot do próprio navegador, salvo em `backend/prints/AAAA-MM-DD/`. Só uma coleta roda por vez. O log fica em `backend/logs/searching.log`.

Se a loja bloquear o acesso automatizado (por exemplo, "Erro 403"), a coleta registra `BLOQUEIO` e segue em frente, sem tentar contornar.

## Agendamento (Windows)

A coleta diária roda pelo Agendador de Tarefas do Windows e não depende do servidor web aberto. Pela tela Home (aba de modo automático) ou pelo script:

```powershell
.\scripts\instalar_agendamento.ps1                       # todos os dias às 12:00
.\scripts\instalar_agendamento.ps1 -Horas 09:00,18:30 -Dias Mon,Tue,Wed,Thu,Fri
.\scripts\instalar_agendamento.ps1 -AcordarPC            # acorda o computador no horário
.\scripts\instalar_agendamento.ps1 -Desativar            # ou -Remover, ou -SomenteMostrar
```

- Se o computador estiver desligado ou dormindo no horário, a tarefa roda assim que possível depois.
- A tarefa roda com o seu usuário, com a sessão aberta (o Chrome abre visível). Os filtros de loja e modelo do modo automático ficam em `backend/config.json`.
- A tela Home mostra se a tarefa está instalada, a próxima execução e o resultado da última.

## Relatórios, prints e saúde

- **Relatórios:** filtros por loja, modelo, vendedor, data e período (de/até). **Exportar Excel** gera uma planilha das linhas filtradas, com preços numéricos e o caminho do print. O CSV continua disponível.
- **Curvas:** gráfico de preço por modelo e loja, só com coletas válidas, com filtro de período.
- **Prints:** galeria por data ou por produto, com o preço PIX e do cartão coletados naquele momento ao lado de cada print.
- **Home:** painel de saúde dos últimos 7 dias com a taxa de sucesso por loja, falhas por motivo, links aguardando revisão e alertas enviados.

## Alertas de preço por e-mail

Quando uma coleta válida mostra queda de preço, o sistema envia um e-mail com produto, loja, preço anterior e atual, percentual, link e **o print anexado**.

1. Copie `.env.example` para `.env` (na raiz; o arquivo nunca vai para o Git) e preencha. No Gmail, ative a verificação em duas etapas e crie uma **senha de app** em https://myaccount.google.com/apppasswords.
2. Abra a tela **Alertas**, confira a configuração e clique em "Enviar e-mail de teste".

Regras (padrão global, com exceções por produto): queda mínima (5%), comparação com o último preço válido, o menor ou a média dos últimos N dias, preço PIX ou cartão 1x, e preço-alvo opcional. O mesmo preço nunca é avisado duas vezes: um novo aviso exige cair mais um degrau (2%) ou o preço subir e voltar a cair. Coletas suspeitas ou com falha nunca geram alerta. Se o e-mail falhar, o alerta fica registrado e é reenviado na coleta seguinte. Um e-mail de resumo ao fim de cada coleta é opcional.

## Segurança

O SEARCHING é de uso local, e o servidor foi configurado para isso:

- **Só escuta em `127.0.0.1`.** Outros computadores da rede não conseguem acessar. `SEARCHING_HOST` não consegue mudar isso (valores fora do loopback são ignorados com aviso).
- **Sem modo debug** (o depurador do Flask permite executar código). Para ligá-lo em desenvolvimento: `SEARCHING_DEBUG=1`.
- **CORS restrito** ao frontend local (`localhost` e `127.0.0.1`, portas 5173 e 5000), sem `*`. Origens locais extras: `SEARCHING_ORIGENS=http://localhost:3000`.
- **Proteção contra sites maliciosos:** o servidor recusa `Host` que não seja local (DNS rebinding) e escritas (`POST`, `PUT`, `DELETE`) vindas de outro site aberto no seu navegador (CSRF).
- **Sem senha no código.** As credenciais de e-mail ficam só no `.env`, fora do Git. Não há login: quem usa o seu computador usa o sistema.
- Os filtros de coleta chegam ao coletor como `--opcao=valor`, sem shell, então um valor nunca vira outra opção ou comando.

## Testes

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

## Dados locais

`backend/links.csv`, `backend/data/` e `backend/prints/` são gerados/editados localmente e não são versionados.

## Aviso

Uso pessoal e demonstrativo, em ritmo moderado. Respeite os termos de uso e o `robots.txt` das lojas.
