# SEARCHING

Monitor de preços com evidência em print. Abre o link de cada produto em lojas concorrentes, coleta os preços, tira um print da página e guarda o histórico.

> Projeto em evolução (banco SQLite, coleta agendada, recuperação de links e alertas por e-mail estão no roadmap).

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
