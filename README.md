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

## Dados locais

`backend/links.csv`, `backend/data/` e `backend/prints/` são gerados/editados localmente e não são versionados.

## Aviso

Uso pessoal e demonstrativo, em ritmo moderado. Respeite os termos de uso e o `robots.txt` das lojas.
