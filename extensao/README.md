# Extensão do Chrome/Edge: coleta assistida

Algumas lojas bloqueiam navegadores controlados por programa (Selenium) e recusam a coleta automática. Esta extensão permite
coletar **do jeito humano**: você abre cada produto no seu navegador de sempre, com **um clique por produto**, e a extensão lê a
página, tira o print e envia tudo ao SEARCHING. Validação, histórico, alertas por e-mail e relatórios funcionam como na coleta
automática.

Funciona em dois modos do SEARCHING:

| Modo | Servidor | Login | Token |
|---|---|---|---|
| **Local** (padrão) | `http://127.0.0.1:5000`, no seu computador | não há | arquivo `backend/data/assistida.token`, pareamento automático |
| **Hospedado** | `https://…` (site da equipe) | sim, com papéis | **um token por usuário**, revogável na tela Usuários |

Em ambos, **a navegação acontece no seu computador, no seu IP e na sua sessão**. O servidor só recebe dados estruturados, o HTML
lido e o print; ele nunca abre as lojas.

## Como funciona

1. No SEARCHING, abra **Coleta assistida** e clique em **Começar**. A extensão abre uma janela do navegador só para a loja
   (arraste-a para o outro monitor e deixe lá).
2. Para cada produto: a extensão **pede autorização ao servidor** (intervalo mínimo, limite por loja, ninguém mais coletando o
   mesmo produto), abre o link na aba dedicada, espera a página carregar, **tira o print**, lê título, vendedor e PIX, abre o menu
   "Ver opções de pagamento" para ler o **cartão 1x** e envia ao servidor.
3. O resultado aparece preenchido na tela do SEARCHING. Você confere e aperta **Próximo** (ou espaço, ou a seta →).
4. Ao final, **Encerrar** fecha a execução.

Intervalo mínimo: **uma página a cada 3 segundos**, imposto pela extensão **e pelo servidor** (por usuário). No modo hospedado há
também um limite global por loja por hora (`limite_loja_hora`, padrão 120, somando todos os usuários); excedido, o servidor nega a
abertura e registra o alerta na auditoria.

Se um produto sair com erro, o SEARCHING mostra um **aviso amarelo fixo no topo** com a contagem, o motivo e um Refazer por produto
(também um clique, uma página). Se a loja bloquear a página, o resultado é registrado como `BLOQUEIO` e a coleta para depois de
2 bloqueios seguidos.

## Por que não há "Coletar tudo"

A extensão abre uma página **por clique seu**, e isso é intencional. Um modo que percorresse a fila sozinho, com pausas
aleatórias, seria automação de navegação feita para passar despercebida pelo anti-bot da loja. A extensão não faz isso: não tem
temporizador, não encadeia páginas e não esconde que é uma extensão.

## Instalação

### Desenvolvedor / uso local (uma vez)

1. No Chrome, abra `chrome://extensions` (no Edge, `edge://extensions`).
2. Ligue o **Modo do desenvolvedor**.
3. Clique em **Carregar sem compactação** e escolha esta pasta (`extensao`).
4. Recarregue a tela **Coleta assistida** do SEARCHING: ela deve mostrar "Extensão conectada".

### Pessoas da equipe (modo hospedado)

1. Instale a extensão (veja **Distribuição** abaixo).
2. Abra as **opções da extensão** (`chrome://extensions` → Detalhes → *Opções da extensão*) e informe o **endereço HTTPS do
   servidor** (por exemplo `https://searching.suaempresa.com`). Só a página de opções muda esse endereço; nenhum site consegue
   trocá-lo. O endereço precisa ser HTTPS (`http` só vale para `127.0.0.1`).
3. Entre no site e abra **Coleta assistida**: a tela cria o **seu token** e o entrega à extensão (pareamento automático). Se
   preferir, crie o token em **Minha conta** e cole nas opções.
4. Para sair de uma conta ou trocar de servidor: **Desparear** nas opções. O administrador também pode **revogar** o token na tela
   Usuários; a extensão deixa de funcionar na hora e pede um novo pareamento.

### Distribuição para quem não é desenvolvedor

| Opção | Quando usar |
|---|---|
| **Chrome Web Store, não listada** (recomendada) | Link privado, atualizações automáticas. Publique o pacote de `python scripts/empacotar_extensao.py` (`dist/searching-extensao-<versão>.zip`). A publicação exige uma conta de desenvolvedor (taxa única) e uma revisão do Google. |
| **Política corporativa** | Em Google Workspace/Intune/GPO, força a instalação por `ExtensionInstallForcelist` (id da loja) e pode pré-definir o servidor. |
| **Edge Add-ons** | O mesmo pacote funciona no Edge (Chromium); publique pelo portal Edge Add-ons ou use `edge://extensions` em modo desenvolvedor. |
| **Pacote .zip + "Carregar sem compactação"** | Só para quem é técnico: descompacte numa pasta fixa e carregue. Não atualiza sozinho. |

> A extensão pede a permissão `<all_urls>`: é a única forma de o navegador deixar uma extensão **tirar o print** da aba sem exigir
> um clique no ícone a cada produto. O código restringe o que ela faz (veja abaixo) e é pequeno o bastante para auditar.

## Segurança do pareamento (modo hospedado)

- **Token por usuário**, com escopo mínimo: serve apenas para pedir autorização de abertura e enviar capturas **da sessão de coleta do
  próprio dono**. Não lê relatórios nem edita nada. O token de uma pessoa não funciona na sessão de outra.
- O servidor guarda só o **hash** do token; o valor aparece uma vez, na criação.
- **Revogação imediata**: o servidor confere o token a cada chamada. Desativar ou rebaixar o usuário também invalida o token.
- **Servidor fixado**: a extensão só envia dados ao endereço configurado nas opções. A página do SEARCHING só consegue entregar o
  token se estiver nesse mesmo endereço.
- **Lista de ids** (opcional, recomendada): com `SEARCHING_EXTENSAO_IDS` no servidor, só capturas vindas de `chrome-extension://<id oficial>`
  são aceitas, mesmo com token válido. O id da loja do Chrome e o do Edge Add-ons são diferentes; coloque os dois.
- **CORS/Origin**: o servidor não libera CORS para a extensão. Ele aceita a chamada porque ela traz um token válido no cabeçalho
  (algo que outro site não consegue enviar); sem token, qualquer `Origin` de fora é recusada.

## Privacidade do print

O print sai do **seu** navegador e, no modo hospedado, fica guardado no servidor da equipe. Se você estiver logado na loja, ele pode
mostrar seu **nome ou CEP** no topo da página. Recomendações:

- use um **perfil do navegador sem login na loja** para coletar;
- configure o **recorte do topo** (opções da extensão ou campo na tela Coleta assistida) para cortar essa faixa;
- lembre que os prints ficam visíveis a todos os usuários com acesso (inclusive leitores) e ficam gravados com o nome de quem capturou.

## Permissões, e por quê

| Permissão | Motivo |
|---|---|
| `tabs`, `scripting` | abrir a aba dedicada, ler a página que ela mesma abriu e registrar o `ponte.js` no seu servidor |
| `storage` | guardar o endereço do servidor, o token e a preferência de recorte do print |
| `<all_urls>` | o navegador só deixa uma extensão **tirar print** da aba com esta permissão (ou `activeTab`, que exige clicar no ícone). |

O que a extensão **não faz**: não abre links por conta própria (só quando você clica Próximo), só navega por
`magazineluiza.com.br` e `magazinevoce.com.br`, só age na aba dedicada, só fala com o servidor configurado, não resolve captcha e
não tenta esconder que é uma extensão. Se a loja bloquear a página, o resultado é registrado como `BLOQUEIO`, com o print.

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| "Extensão não detectada" | Instale a extensão e **recarregue** a página. No modo hospedado, confira se o endereço nas opções é o do site. |
| "Extensão configurada para outro servidor" | Abra as opções da extensão e informe o endereço deste site. |
| "O servidor não aceita mais este pareamento" | O token foi revogado: recarregue a tela Coleta assistida para parear de novo. |
| "Aguarde: uma página a cada 3 segundos" | O servidor impõe o intervalo; espere e clique de novo. |
| "Limite de N páginas por hora" | A loja atingiu o limite global; tente mais tarde ou peça ao administrador. |
| "Este produto está em coleta por outra pessoa" | Outra pessoa tem este produto na fila agora; espere ela encerrar. |
| "Não consegui tirar o print" | A janela da loja não pode estar minimizada. Use Refazer. |
| Cartão 1x vazio | A extensão não achou o menu de pagamento. Abra "Ver opções de pagamento" na janela e use Refazer. |

## Teste automatizado

`scripts/e2e_assistida.py` carrega a extensão num Chrome real contra uma loja simulada e confere o fluxo inteiro. Com
`--hospedado`, roda o modo hospedado (site servido pelo Flask, login de um coletor de teste, token por usuário e captura registrada
em nome dele). Veja o cabeçalho do script. O Chrome oficial não aceita extensões por linha de comando, então o teste usa o
*Chrome for Testing*, que o Selenium baixa sozinho na primeira vez (cerca de 460 MB).
