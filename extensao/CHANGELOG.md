# Histórico de versões da extensão

Siga [versionamento semântico](https://semver.org/lang/pt-BR/): **PATCH** (2.1.1) correção sem mudar o comportamento; **MINOR** (2.2.0)
funcionalidade nova compatível; **MAJOR** (3.0.0) mudança que exige servidor mais novo. As lojas só aceitam um pacote com versão
**maior** que a publicada.

## 2.1.1
- Corrige a **janela duplicada**: quando o service worker (MV3) era encerrado por ociosidade, a aba dedicada se perdia da memória e a
  extensão abria outra janela. Agora a aba dedicada (e o instante da última navegação) ficam em `chrome.storage.session`; ao acordar, a
  extensão confirma com `chrome.tabs.get` que a aba ainda existe e a reaproveita. Se a pessoa fechar a aba, a próxima captura cria uma nova.

## 2.1.0
- Envia a versão da extensão ao servidor (`X-Searching-Ext-Versao`), para o administrador poder **exigir uma versão mínima**
  (`SEARCHING_EXTENSAO_VERSAO_MINIMA`) e forçar a atualização.

## 2.0.0
- Modo hospedado: página de opções com o endereço HTTPS do servidor (fixado), token por usuário revogável, registro dinâmico do
  `ponte.js` no domínio do servidor e pedido de autorização ao servidor antes de abrir cada página.

## 1.0.0
- Coleta assistida local (servidor `127.0.0.1`, token em arquivo).
