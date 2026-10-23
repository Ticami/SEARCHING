# Extensão do Chrome: coleta assistida

Algumas lojas bloqueiam navegadores controlados por programa (Selenium) e recusam a coleta automática. Esta extensão permite
coletar **do jeito humano**: você abre cada produto no seu Chrome de sempre, com **um clique por produto**, e a extensão lê a
página, tira o print e envia tudo ao SEARCHING. Validação, histórico, alertas por e-mail e relatórios funcionam como na coleta
automática.

## Como funciona

1. No SEARCHING, abra **Coleta assistida** e clique em **Começar**. A extensão abre uma janela do Chrome só para a loja
   (arraste-a para o outro monitor e deixe lá).
2. Para cada produto: a extensão abre o link na aba dedicada, espera a página carregar, **tira o print**, lê título, vendedor e
   PIX, abre o menu "Ver opções de pagamento" para ler o **cartão 1x** e envia ao servidor local.
3. O resultado aparece preenchido na tela do SEARCHING. Você confere e aperta **Próximo** (ou espaço, ou a seta →).
4. Ao final, **Encerrar** fecha a execução.

Intervalo mínimo: a extensão nunca abre mais de **uma página a cada 3 segundos**, mesmo que a tela peça.

Se um produto sair com erro, o SEARCHING mostra um **aviso amarelo fixo no topo** com a contagem, o motivo e um Refazer por produto
(também um clique, uma página).

## Por que não há "Coletar tudo"

A extensão abre uma página **por clique seu**, e isso é intencional. Um modo que percorresse a fila sozinho, com pausas
aleatórias, seria automação de navegação feita para passar despercebida pelo anti-bot da loja. A extensão não faz isso: não tem
temporizador, não encadeia páginas e não esconde que é uma extensão.

## Instalação (uma vez)

1. No Chrome, abra `chrome://extensions`.
2. Ligue o **Modo do desenvolvedor** (canto superior direito).
3. Clique em **Carregar sem compactação** e escolha esta pasta (`extensao`).
4. Recarregue a tela **Coleta assistida** do SEARCHING: ela deve mostrar "Extensão conectada".

O pareamento é automático: a tela entrega à extensão um token secreto (guardado em `backend/data/assistida.token`, fora do Git),
e só quem tem esse token consegue enviar capturas ao servidor.

## Permissões, e por quê

| Permissão | Motivo |
|---|---|
| `tabs`, `scripting` | abrir a aba dedicada e ler a página que ela mesma abriu |
| `storage` | guardar o token e a preferência de recorte do print |
| `<all_urls>` | o Chrome só deixa uma extensão **tirar print** da aba com esta permissão (ou `activeTab`, que exige clicar no ícone). Veja os limites abaixo. |

O que a extensão **não faz**: não abre links por conta própria (só quando você clica Próximo), só navega por
`magazineluiza.com.br` e `magazinevoce.com.br`, só age na aba dedicada, só fala com o servidor local
(`127.0.0.1`), não resolve captcha e não tenta esconder que é uma extensão. Se a loja bloquear a página, o resultado é
registrado como `BLOQUEIO`, com o print.

## Privacidade do print

O print sai do seu Chrome e pode mostrar seu nome ou CEP no topo da página, se você estiver logado na loja. Na tela
**Coleta assistida** há um campo para cortar uma faixa do topo do print (em pixels). O ideal é usar um perfil do Chrome só
para isso, sem login.

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| "Extensão não detectada" | Instale a extensão e **recarregue** a página. Confira se ela está ativada em `chrome://extensions`. |
| "Token inválido" | Recarregue a tela Coleta assistida (ela refaz o pareamento). |
| "Não consegui tirar o print" | A janela da loja não pode estar minimizada. Use Refazer. |
| Cartão 1x vazio | A extensão não achou o menu de pagamento. Abra "Ver opções de pagamento" na janela e use Refazer. |
| Muda a porta do servidor | Defina `SEARCHING_PORT`; a tela informa o endereço certo à extensão no pareamento. |

## Teste automatizado

`scripts/e2e_assistida.py` carrega a extensão num Chrome real contra uma loja simulada e confere o fluxo inteiro (veja o
cabeçalho do script). O Chrome oficial não aceita extensões por linha de comando, então o teste usa o *Chrome for Testing*,
que o Selenium baixa sozinho na primeira vez (cerca de 460 MB).
