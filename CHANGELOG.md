# Changelog

## 1.0.3 - 2026-05-27

- Removida a integracao com Gemini e seus fallbacks visuais.
- Removida a dependencia `google-genai` do `requirements.txt`.
- Removido o comando `click-visual` do `live-assist`, mantendo apenas comandos deterministas por texto, seletor, label, coordenadas e fluxos especificos.

## 1.0.2 - 2026-05-27

- Removido o anexo automatico do certificado A1 via Playwright (`client_certificates`), que criava um novo contexto CDP e podia abrir uma segunda janela do navegador.
- O `BrowserSession` agora reaproveita o contexto existente do Chrome conectado em `9222`, mantendo uma unica instancia no fluxo principal.

## 1.0.1 - 2026-05-27

- Corrigido o fluxo interativo para definir explicitamente `connect_browser_url` antes de abrir o navegador, garantindo anexo por CDP no mesmo processo.
- Evitada a abertura de segunda instancia no fluxo principal de terminal ao reaproveitar o navegador iniciado em `9222`.

## 1.0.0 - 2026-05-27

- Removida a GUI do fluxo principal e substituida por um assistente interativo via terminal.
- A execucao padrao agora solicita mes, planilha, abre o navegador para login manual e executa a extracao no mesmo contexto autenticado.
- Corrigida a perda de sessao entre login manual e extracao ao manter o lote dentro da mesma `BrowserSession`.
- Mantido o modo `live-assist` para diagnosticos assistidos.
- Reforcado o fluxo de erro para registrar falhas fatais em `logs/errors.log` por meio do logging central.

## 0.2.17 - 2026-05-26

- Corrigida a confirmacao de login manual na GUI para validar a sessao autenticada considerando os contextos ativos do browser conectado via CDP.
- Ajustado o fluxo do botao `Confirmar Login` para passar a referencia do browser conectado ao validador, reduzindo falso negativo apos login ja concluido.

## 0.2.16 - 2026-05-26

- Corrigido o fluxo da GUI no botao `Iniciar Navegador`: o navegador volta a abrir mesmo quando ha certificado A1 configurado.
- Mantida a protecao contra duplicidade: se ja existir navegador respondendo em CDP, o processo nao abre uma nova instancia.

## 0.2.15 - 2026-05-26

- Ajustada a selecao da linha na aba `Downloads` para priorizar sempre a solicitacao mais recente por data/hora (`Solicitado em`) ao baixar detalhamentos.
- Mantida a busca por correspondencia exata de `TELA/ABA` e, quando necessario, fallback `fuzzy`, ambos agora com criterio de desempate por recencia.
- Preservado o fallback de captura direta do arquivo quando a URL assinada nao e retornada, com logs mais claros indicando a estrategia escolhida.

## 0.2.14 - 2026-05-26

- Corrigida a etapa de download na central `Downloads` com busca mais tolerante da coluna `TELA/ABA`, evitando dependencia de correspondencia textual estrita (ex.: variacoes com/sem `Autorizadas`).
- Adicionado fallback para captura direta do arquivo via navegador quando a URL assinada nao e retornada no evento de resposta.
- Ajustado o clique da acao de download da linha para usar seletores resilientes de botao/link, reduzindo falhas por coluna fixa.
- Incluidos logs explicitos da estrategia de match usada (`exact` ou `fuzzy`) e do modo de salvamento (`signed URL` ou captura direta).

## 0.2.13 - 2026-05-26

- Generalizado o extrator fiscal para processar duas abas de `Informacoes Fiscais`: `NF-e` e `NFC-e`.
- Na `NFC-e`, o resumo de `Emissor` e `Destinatario` agora so e baixado quando os totais anuais de quantidade e valor sao positivos.
- Na `NFC-e`, o detalhamento agora segue o fluxo validado em `live-assist`: abrir o mes apenas quando houver valores positivos, solicitar `Autorizadas`, ir a `Downloads`, localizar pela coluna `TELA/ABA` e salvar o CSV.
- Os arquivos passaram a ser separados por pasta de aba fiscal, por exemplo `saida/<cgf>/<mes>/NF-e/` e `saida/<cgf>/<mes>/NFC-e/`.
- Tornado mais robusto o clique dos radios `Emissor` e `Destinatario` com `force=True` via `XPath`, melhorando a troca de perfil em telas como `NFC-e`.
- A localizacao de solicitacoes em `Downloads` passou a comparar `TELA/ABA` de forma normalizada, sem depender de acentuacao exata.

## 0.2.12 - 2026-05-26

- Substituidos por `XPath` os cliques mais instaveis do fluxo fiscal: campo de busca, linha do contribuinte, menu `Informacoes Fiscais`, radios `Emissor`/`Destinatario`, linha do mes, linhas `Interna`/`Interestadual`/`Externa`, botao de detalhamento `Baixar Tabela` e menu `Downloads`.
- Adicionados logs explicitos para registrar quando um clique critico foi executado via `XPath`, facilitando diagnostico no `run.log`.

## 0.2.11 - 2026-05-26

- Ajustada a regra da automacao para so abrir o mes de referencia quando a linha do mes tiver `QTD > 0` e `VALOR R$ > 0`.
- Removido o fallback que solicitava detalhamentos apenas por texto visivel, impedindo downloads indevidos de linhas zeradas como `Externa`.
- Tornado estavel o clique entre `Emissor` e `Destinatario` usando os radios reais da pagina fiscal, evitando desvio para `Manifestacao Destinatario`.
- Adicionadas notificacoes finais mais claras na GUI para diferenciar conclusao com downloads, conclusao sem dados e erro.
- Ao final do processo na GUI, o navegador agora e encerrado automaticamente; o mesmo comportamento foi exposto no `live-assist` com novos comandos para validar mes positivo, detalhamentos positivos e fechamento do navegador.

## 0.2.10 - 2026-05-26

- Reordenado o fluxo de extracao para seguir a sequencia operacional definida: baixar tabelas de `Emissor`/`Destinatario`, solicitar todos os detalhamentos e so depois entrar em `Downloads` para baixar os arquivos solicitados.
- Ajustado o processamento para baixar os detalhamentos pendentes em lote na aba `Downloads` e retornar para o fluxo principal.

## 0.2.9 - 2026-05-26

- Corrigido o log de erro da GUI para registrar o traceback real da excecao em `errors.log`, evitando entradas sem pilha (`NoneType: None`).

## 0.2.8 - 2026-05-26

- Adicionado tratamento global de excecoes nao tratadas (`sys.excepthook` e `threading.excepthook`) para registrar erros com stack trace em log.
- Envolvido o fluxo principal em captura final com `logging.exception`, garantindo registro no `errors.log` para falhas fatais.

## 0.2.7 - 2026-05-26

- Automatizado o fluxo completo do detalhamento assíncrono: clique em `Downloads`, localizacao da linha correta pela coluna `TELA/ABA`, captura da URL assinada e salvamento do CSV.
- Os arquivos de detalhamento agora passam a ser salvos com base no texto da coluna `TELA/ABA`, sanitizando apenas caracteres invalidos para Windows.

## 0.2.6 - 2026-05-26

- Ajustado o fluxo de detalhamento fiscal para processar todos os tipos com `QTD > 0` e `VALOR R$ > 0`, em vez de apenas um unico tipo por perfil.
- Diferenciado o `Baixar Tabela` da secao `2. Detalhamento ...` do `Baixar Tabela` da secao `1. Indicadores por Mes`.
- Mantido o download do detalhamento pela aba `Downloads`, conforme o comportamento real observado no SIGA.

## 0.2.5 - 2026-05-26

- Alterado o fluxo para exigir a definicao do mes de referencia antes de iniciar o navegador na GUI.
- Reordenado o fluxo de `Informacoes Fiscais` para baixar primeiro as tabelas de `Emissor` e `Destinatario` e somente depois abrir o mes selecionado para o detalhamento.

## 0.2.4 - 2026-05-26

- Corrigido o fluxo de download para manter nome final deterministico em CSV mesmo quando o SIGA retorna nome tecnico (UUID/sem extensao).
- Adicionado comando `download-table` no modo assistido para capturar o download com `expect_download` e salvar com nome controlado em `saida/live-assist/`.
- Incluidos logs de diagnostico do nome sugerido pelo navegador versus caminho final salvo.

## 0.2.3 - 2026-05-26

- Adicionado modo assistido para abrir o SIGA, aguardar login manual e manter a sessao pronta para comandos guiados em tempo real.
- Adicionado registro das acoes assistidas em `brain/live_assist_actions.jsonl` para servir de base ao fluxo definitivo de automacao.

## 0.2.2 - 2026-05-25

- Corrigida a localizacao de contribuinte por `CGF` com suporte a formatos mascarados (ex.: `06.240.894-1`).
- Melhorada a confirmacao de entrada na tela do cliente apos clique visual, evitando falso negativo de "contribuinte nao encontrado".

## 0.2.1 - 2026-05-25

- Removido o fluxo de pesquisa e extracao avulsa por `CNPJ` no GUI.
- Removido tambem o argumento `--extract-cnpj` do CLI para manter o produto somente no fluxo em lote.
- GUI mantida somente com fluxo em lote por planilha `.xlsx` (coluna `cgf`) e mes de referencia.

## 0.2.0 - 2026-05-25

- Adicionada selecao de planilha `.xlsx` na GUI para processamento em lote via coluna `cgf`.
- Adicionada selecao de mes de referencia na GUI.
- Implementado fluxo em lote para pesquisar contribuinte por `CGF`, abrir `Informacoes Fiscais` e baixar arquivos fiscais de `Emissor` e `Destinatario`.
- Padronizada a saida por contribuinte e mes dentro da pasta `saida/`.
