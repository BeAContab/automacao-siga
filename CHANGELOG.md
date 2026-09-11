# Changelog

## [2026-09-11] — Versão 2.5.1

### Corrigido
- **Modo NFC-e não reconhecia chaves quando a "Pasta de chaves" apontava direto para a pasta de uma empresa específica** (ex.: `Teste Siga\7 - PLANOS HOTEIS - 10484384000119`), só funcionando se apontasse para a pasta raiz de saída do SIGA. `_company_folder_for_cnpj` (`src/extraction/nfce_extractor.py`) procurava o CNPJ só nas subpastas diretas de `keys_folder`; agora também reconhece quando o próprio `keys_folder` já é a pasta da empresa (o CNPJ está no nome dela). Testado contra dados reais: nenhuma chave "vaza" entre empresas quando se aponta para a pasta de uma empresa específica com o CNPJ errado.
  - Continua não suportado apontar para uma pasta abaixo do nível da empresa (ex. a pasta do mês ou "NFC-e" em si) — de propósito, para não arriscar atribuir documentos de uma empresa a outra num lote com várias empresas.

## [2026-09-11] — Versão 2.5.0

### Adicionado
- **Modo NF-e (Meu DANFE): retentativa automática das chaves que falharem na primeira passada.** Análise de um lote real (2.294 chaves, 406 falhas) mostrou que a maioria dos erros não tinha relação com o conteúdo do documento (chave com dígito verificador válido, status/CNPJ na mesma proporção das que deram certo, falhas espalhadas uniformemente pelo arquivo) — indício de instabilidade/bloqueio intermitente do site sob volume alto, não de dado ruim. Até aqui, só o alerta "captcha invalido" tinha nova tentativa automática ([meudanfe_extractor.py](src/extraction/meudanfe_extractor.py)); qualquer outro erro (como o genérico "Falha ao consultar!") falhava a chave de vez, exigindo que o operador reparasse no log e rodasse a planilha inteira de novo manualmente.
  - `MeudanfeBatchExtractor.executar_lote` agora roda uma segunda passada automática só com as chaves que falharam, após uma espera configurável (`Settings.nf_meudanfe_retry_wait_seconds`, padrão 60s) — o espaçamento no tempo tende a ser mais eficaz contra instabilidade transitória do que repetir na hora. Uma retentativa por chave (2 tentativas no total); respeita Pausar/Continuar/Encerrar durante a espera. O log `chaves_falhas_meudanfe.log` e os contadores da planilha passam a refletir só a falha definitiva (depois das duas tentativas).

### Alterado
- **Pasta de saída do modo NFC-e padronizada no mesmo formato do SIGA: "COD - EMPRESA - CNPJ"** (antes: "IE - EMPRESA", sem CNPJ). `load_cnpj_ie_base` (`src/extraction/nfce_extractor.py`) passa a também ler uma coluna "COD" opcional da planilha-base CNPJ/IE, se existir — sem quebrar planilhas que não tenham essa coluna (cai em "SEM-COD", igual ao SIGA quando falta o COD na planilha dele). O modo NF-e já era consistente com o SIGA por construção (reproduz a estrutura da pasta de entrada), então não precisou de alteração.

## [2026-09-11] — Versão 2.4.1

### Alterado
- **"Pasta de saída" do modo SIGA não vem mais pré-preenchida** — sempre exigia que o usuário reparasse e trocasse a sugestão antes de executar; agora o campo começa em branco e precisa ser escolhido explicitamente a cada execução (pedido do usuário).
- **"Planilha-base CNPJ/IE" do modo NFC-e (e da mesma etapa na Cadeia Completa) agora vem pré-preenchida** com a planilha de rede do escritório (`Settings.DEFAULT_NFCE_BASE_SPREADSHEET_PATH`, `src/config.py`) — é sempre o mesmo arquivo para qualquer operador, então deixa de ser necessário selecioná-lo manualmente toda vez; continua trocável pelo seletor de arquivo normalmente.

## [2026-09-11] — Versão 2.4.0

### Adicionado
- **Novo modo "Cadeia Completa": SIGA → NF-e (Meu DANFE) → NFC-e em uma única execução.** Até aqui os 3 modos eram sempre disparados separadamente, exigindo reselecionar manualmente pastas/planilhas de um modo para alimentar o próximo. A pasta de saída do SIGA já é estruturalmente compatível com a entrada dos outros dois modos (mesma convenção `COD - EMPRESA - CNPJ`, coluna "Chave NF-e"), então o novo modo só orquestra os três extratores existentes em sequência, sem alterar nenhum deles.
  - Novo módulo `src/extraction/chain_extractor.py` (`ChainBatchExtractor`): roda a extração SIGA, depois usa a própria pasta de saída do SIGA como `input_folder` do NF-e e `keys_folder` do NFC-e (descoberta automática das empresas elegíveis via `discover_selectable_companies`, sem etapa manual de revisão). Se a etapa SIGA terminar com falhas parciais, a cadeia segue para as duas etapas seguintes mesmo assim, processando o que foi baixado — só um cancelamento explícito do usuário interrompe a cadeia entre etapas.
  - Novo método `Api.start_chain_extraction` (`src/webui/api.py`), reaproveitando o `_start_worker` genérico já existente; `stop_extraction` passou a também derrubar o navegador de depuração quando o modo ativo é "chain" (mesma razão de SIGA/NFC-e: a etapa NFC-e da cadeia também usa `BrowserSession`).
  - Interface: novo 4º item "Cadeia Completa" na navegação lateral, que reaproveita a própria tela/grade do modo SIGA (mesma planilha/entrada manual, mesmos checkboxes por documento) e acrescenta um bloco de campos extras (CPF/senha e planilha-base CNPJ/IE do NFC-e; Chrome.exe opcional e Chromes em paralelo do NF-e), visível só nesse modo. As pastas "NFe" e "NFCe" são criadas automaticamente dentro da pasta de saída escolhida.

## [2026-09-10] — Versão 2.3.4

### Alterado
- **Modo NF-e (Meu DANFE): teto de Chromes em paralelo subiu de 4 para 8** (`MAX_WORKERS_PERMITIDO`, `src/extraction/meudanfe_extractor.py`) — mesmo limite do script original de onde este modo foi portado; o teto de 4 era uma margem de segurança deliberada contra bloqueio anti-bot, reduzida a pedido do usuário mesmo após um caso real de captcha travando um worker com só 2 instâncias simultâneas (risco assumido conscientemente). Validação e campo da interface (`api.py`, `web/src/index.html`, `web/src/js/screens.js`) atualizados para aceitar 1 a 8.

## [2026-09-10] — Versão 2.3.3

### Alterado
- **Modo NF-e (Meu DANFE) agora preserva a estrutura de pastas por empresa da entrada, em vez de agrupar tudo só pelo nome do relatório.** Antes, `montar_pasta_destino_planilha` (`src/extraction/meudanfe_extractor.py`) usava só o nome do arquivo da planilha (ex.: "Informacoes Fiscais - NF-e - Destinatario - Detalhamento Agosto de 2026 - Interestadual") — igual para qualquer empresa —, então os XMLs/PDFs de empresas diferentes caíam juntos numa única pasta, sem nada além da chave de 44 dígitos para diferenciar a origem. Avaliado e descartado usar o CNPJ embutido na própria chave de acesso: ele identifica só o *emitente* da nota, não a empresa rastreada quando o relatório é do tipo "Destinatário" (quem recebeu a nota, não quem emitiu). A pasta de entrada (tipicamente a própria saída do modo SIGA) já tem essa informação — só não estava sendo aproveitada.
  - `montar_pasta_destino_planilha`/`extrair_registros_planilha_nfe` passam a receber também a pasta de entrada, calculando o caminho da planilha relativo a ela e reconstruindo a mesma estrutura no destino: `<destino>/downloads-meudanfe/<COD - EMPRESA - CNPJ>/<mês>/<aba>/<relatório>/{XML,PDF}/<chave>.{xml,pdf}` — mesmo padrão já usado pelo modo SIGA.

## [2026-09-10] — Versão 2.3.2

### Corrigido
- **Resumo final do modo NF-e (Meu DANFE) mostrava "Planilhas concluídas: X de X" mesmo quando o lote foi encerrado bem no início** — descoberto num teste real em que o usuário clicou "Encerrar" (v2.3.0) após um dos 2 Chromes paralelos travar na resolução do captcha: só 6 de 2190 chaves haviam sido baixadas, mas o log disse "24 de 24 planilhas concluídas". Causa: `MeudanfeBatchResult.status` (`src/extraction/meudanfe_extractor.py`) considerava "concluído" qualquer planilha com `chaves_com_falha == 0`, sem checar se as chaves dela chegaram a ser tentadas — uma planilha cujo processamento nunca começou (por causa do corte antecipado) também bate `chaves_com_falha == 0`. A tabela ao vivo da interface (`_serialize_nfe_result`, `src/webui/api.py`) já tinha essa checagem certa para o estado "em andamento"; o resumo final do lote (`executar_lote`) nunca a reaproveitou, porque antes do botão Encerrar existir esse caminho não era alcançável.
  - Novo estado `"interrompido"` na property `status`: dispara sempre que `chaves_baixadas + chaves_puladas + chaves_com_falha` for menor que `chaves_total` — a mensagem genérica de "incompleta" já existente passa a cobrir esse caso corretamente, sem mudança de UI.

## [2026-09-10] — Versão 2.3.1

### Corrigido
- **Modo NF-e (Meu DANFE) falhava na hora com `ModuleNotFoundError: No module named 'undetected_chromedriver'`** no instalador da v2.3.0 — o pacote está declarado em `requirements.txt`, mas não estava instalado no venv usado para gerar aquele build, então o PyInstaller empacotou o app sem ele (sem nenhum aviso visível durante o build). Reinstalado (`pip install -r requirements.txt`) e instalador regerado — confirmado que `undetected_chromedriver` agora entra no bundle (presente no grafo de dependências do PyInstaller, antes ausente). Sem mudança de código; só do ambiente de build.

## [2026-09-10] — Versão 2.3.0

### Corrigido
- **Loop de polling da Central de Downloads travava por minutos e derrubava a sessão do navegador** — diagnosticado a partir de um lote real de 11 CNPJs (`ARQUIVOS/Teste Siga/log.txt`): dentro do laço de espera de `_find_pending_download_matches` (`src/extraction/siga_extractor.py`), `page.reload(wait_until="domcontentloaded")` só espera o HTML inicial parsear, não o Angular buscar/renderizar a tabela e o paginador — quando isso não terminava a tempo, `_select_max_downloads_page_size`/`_go_to_next_downloads_page` não encontravam os elementos esperados (sem auto-wait) e a varredura ficava travada na página 1, silenciosamente, por até 91 ciclos seguidos (~5 minutos) num caso real, terminando com `invalid session id` (sessão do navegador perdida). As duas mensagens que explicavam o problema eram `LOGGER.info`, que nunca chega ao console da interface (só `narrate()`/`LOGGER.WARNING+` chegam) — o usuário só via uma linha idêntica se repetindo, indistinguível de travamento.
  - Novo `_wait_for_downloads_table_ready` confirma de verdade (com timeout real, não um sleep fixo) que a tabela/paginador renderizou após cada reload, antes de tentar ler/paginar — mesmo padrão já usado em `_wait_for_taxpayer_list_ready`.
  - Falhas consecutivas de renderização (`Settings.downloads_render_retry_count`, padrão 3) agora escalam para reabrir a Central de Downloads do zero (novo `_open_downloads_screen`, extraído do início de `_download_pending_detail_requests`) em vez de recarregar cegamente — só dispara se sobrar tempo suficiente no prazo atual, para não travar um checkpoint curto (v2.2.0) numa recuperação cara.
  - Novo heartbeat periódico (`Settings.download_wait_heartbeat_interval_ms`, padrão 60s) narrado no console ("Ainda aguardando N arquivo(s)... Xmin decorrido(s)") e backoff leve entre reloads durante falhas consecutivas.
  - Novos campos em `Settings` (`src/config.py`): `downloads_table_ready_timeout_ms`, `downloads_render_retry_count`, `download_wait_heartbeat_interval_ms`.

### Adicionado
- **Pausar/Continuar e Encerrar, disponíveis nos 3 modos de extração** — até aqui a única forma de parar uma execução em andamento era fechar a janela do aplicativo inteiro. Novo módulo compartilhado `src/utils/execution_control.py` (`wait_if_paused`, generalização do `_aguardar_execucao` que já existia só no modo NF-e) é checado nos pontos seguros de cada laço: início de cada empresa (SIGA, NFC-e) e também dentro da própria chave sendo processada (NFC-e, já que uma empresa pode ter centenas de chaves), além de dentro da espera pela Central de Downloads (SIGA).
  - Novo painel na interface (`<aside>`, junto do botão "Executar"): "Pausar"/"Continuar" (um único botão, alterna) e "Encerrar" — visíveis só durante uma execução. "Encerrar" pede confirmação (ação destrutiva para o que ainda não foi processado do lote) e, para SIGA/NFC-e, também derruba o navegador de depuração na hora (`shutdown_debug_browser`, já usado ao fechar a janela do app) — o cancelamento cooperativo sozinho não interrompe uma chamada Selenium já em andamento.
  - `Api` (`src/webui/api.py`) ganhou um par de `threading.Event` compartilhado (só uma execução roda por vez no processo inteiro, então um par cobre qualquer um dos 3 modos) e os métodos `pause_extraction`/`resume_extraction`/`stop_extraction`, expostos à interface.
  - **Limitação conhecida**: a pausa é cooperativa — não interrompe uma chamada Selenium/undetected_chromedriver já em andamento, só tem efeito no próximo ponto seguro do laço; uma pausa muito longa pode deixar a sessão do SIGA/NFC-e expirar antes de "Continuar", exigindo reautenticação manual.
- **Modo NF-e (Meu DANFE): novo campo obrigatório "Pasta de destino dos downloads"** — antes, os downloads sempre caíam numa subpasta fixa ao lado de cada planilha de entrada (`<planilha>/downloads-meudanfe/...`), sem opção de escolher outro lugar. Agora o usuário escolhe a pasta de destino (mesmo padrão de "Pasta de saída"/"Pasta de saída dos XMLs" do SIGA/NFC-e); a estrutura interna continua a mesma, só a base muda: `<destino>/downloads-meudanfe/<planilha>/{XML,PDF}`. O `log.txt` e o log de chaves com falha desta execução também passam a ser gravados na pasta de destino, alinhando com o padrão dos outros 2 modos (antes ficavam na pasta de entrada).
  - Novo campo `Settings.nf_meudanfe_output_folder` (`src/config.py`).
- **Tag "EM TESTES" reintroduzida nos 3 modos** (SIGA, NFC-e, NF-e) no menu lateral — removida do NFC-e na v2.2.2, agora reaplicada uniformemente aos 3.

## [2026-09-10] — Versão 2.2.2

### Alterado
- **Removido o selo "EM TESTES" do item "Extração NFC-e" no menu lateral** (`web/src/index.html`) — pedido direto do usuário, sinalizando que o modo NFC-e não é mais considerado em fase de testes. SIGA e NF-e já não tinham esse selo.

## [2026-09-10] — Versão 2.2.1

### Corrigido
- **Alerta nativo do portal SEFAZ-CE ("Tempo limite excedido! Será necessário reiniciar a operação") derrubava o modo NFC-e com um stacktrace cru do Selenium** (`unexpected alert open`), sem nenhuma mensagem clara — reportado pelo usuário ao clicar "Carregar Empresas do Portal". Diagnosticado: esse alerta acontece tanto por expiração real de sessão quanto quando já existe **outra sessão ativa com o mesmo CPF** em outro computador/navegador (o portal derruba a sessão nova); nenhum ponto do código tratava esse alerta, então qualquer comando Selenium seguinte propagava a exceção crua.
  - Novo `Page.dismiss_alert_if_present()` e alias `UnexpectedAlertError` (`src/utils/selenium_compat.py`) — camada de abstração do driver, para não espalhar exceções cruas do Selenium pelo resto do código.
  - `NfceSessionManager` (`src/extraction/nfce_extractor.py`) ganhou `_describe_unexpected_alert`, usado em `fazer_login`, `acessar_area_empresas` e `listar_empresas`: fecha o alerta (destravando o navegador) e converte em mensagem clara, ex.: *"O portal SEFAZ-CE encerrou a sessão inesperadamente ("Tempo limite excedido!..."). Isso costuma acontecer quando já existe outra sessão ativa com o mesmo CPF em outro computador ou navegador — feche a outra sessão e tente novamente."*
  - Sem retentativa automática nesse caso específico (causa externa — repetir sozinho não resolve): `fazer_login` falha na hora em vez de gastar as 3 tentativas padrão contra o mesmo alerta.

## [2026-09-10] — Versão 2.2.0

### Adicionado
- **Varreduras periódicas da Central de Downloads durante o lote, em vez de só uma no final** — diagnosticado a partir de um lote real de 155 CNPJs (`documentos-solicitados.csv` + `log.txt`): as 660 solicitações fiscais são enviadas ao SIGA ao vivo, uma a uma, ao longo das ~2h04min do loop principal (confirmado: primeiro clique de download às 16:46:32, último às 18:50:15), mas a busca na Central de Downloads só começava depois de todo o lote terminar, com uma única janela de 600s (`download_generation_timeout_ms`) para "colher" tudo de uma vez — e só achou 95 de 660 (`A Central de Downloads expirou antes de concluir todas as linhas pendentes; varredura final de confirmacao localizou 95 de 660 solicitacoes`), gerando 565 avisos de "download indisponível". Como as solicitações já são enviadas em tempo real, o problema era só a busca ser tardia demais.
  - Novo checkpoint a cada `Settings.download_checkpoint_interval` empresas processadas (padrão 10): aguarda `download_checkpoint_pause_ms` (padrão 30s, sugestão do usuário), depois abre a Central de Downloads e baixa o que já estiver pronto — com um timeout curto e não bloqueante (`download_checkpoint_scan_timeout_ms`, padrão 10s), já que o objetivo não é esperar, é só colher o que já ficou pronto desde o checkpoint anterior. O que não for encontrado fica pendente para o próximo checkpoint (ou para a varredura final), **sem** gravar aviso de "download indisponível" nem status de erro na planilha ainda — só a varredura final (ao término de todas as empresas) é que de fato desiste de um item, exatamente como hoje.
  - `download_checkpoint_interval: int = 0` desliga os checkpoints e volta ao comportamento anterior (só a varredura final).
  - `_find_pending_download_matches` e `_download_found_pending_requests` (`src/extraction/siga_extractor.py`) ganharam parâmetros (`timeout_ms`, `give_up_on_missing`) para suportar os dois modos de uso (checkpoint rápido vs. varredura final completa) sem duplicar a lógica de matching/paginação já existente.
  - Novos campos em `Settings` (`src/config.py`): `download_checkpoint_interval: int = 10`, `download_checkpoint_pause_ms: int = 30_000`, `download_checkpoint_scan_timeout_ms: int = 10_000`.

## [2026-09-09] — Versão 2.1.4

### Corrigido
- **Regressão da v2.1.2: colisão de nomes quebrava a solicitação de detalhamento de NF-e/NFC-e** — `_display_label` (adicionado na v2.1.2 para mostrar o COD no console) tinha o **mesmo nome** de um método já existente, `_display_label(self, label, display_label=None)` (usado internamente em `_collect_fiscal_tab_requests` para resolver o texto do perfil Emissor/Destinatário na Central de Downloads). Em Python, a segunda definição de um método com o mesmo nome dentro da classe substitui silenciosamente a primeira — a chamada de 2 argumentos passou a cair na função de 1 argumento, gerando `TypeError: SigaContributorExtractor._display_label() takes 2 positional arguments but 3 were given` e derrubando a solicitação de qualquer aba NF-e/NFC-e/CT-e após as 3 tentativas de retentativa (`fiscal_tab_retry_count`). Identificado analisando um log real de teste manual (`documentos-solicitados.csv` + `log.txt`) em que a empresa cujo detalhamento falhou só teve os resumos (Emissor/Destinatário) registrados no novo log de solicitações, nunca o detalhamento em si.
  - Método renomeado para `_company_display_label` (`src/extraction/siga_extractor.py`) em suas 12 chamadas de 1 argumento; o método original `_display_label` (2 argumentos, resolução de perfil) permanece intacto e sem conflito.

## [2026-09-09] — Versão 2.1.3

### Adicionado
- **Novo log separado e simples de "documentos solicitados"** (`documentos-solicitados.csv`, gravado na própria pasta de saída escolhida pelo usuário, junto ao `log.txt` já existente) — pedido explícito do usuário para poder recuperar manualmente de um erro no final do lote: se a Central de Downloads falhar ao reabrir (como no caso do v2.1.2) ou qualquer outra etapa falhar, o usuário pode abrir esse CSV (formato simples, separado por `;`, compatível com Excel PT-BR) e ver exatamente o que já foi solicitado ao SIGA — empresa, aba do documento, mês, e o texto exato da tela na Central de Downloads — para buscar e baixar manualmente cada item, sem precisar garimpar o `log.txt` técnico/narração.
  - Novo `_append_request_log_row` (`src/extraction/siga_extractor.py`), chamado a partir do único ponto de construção de solicitações (`_build_pending_request`), cobrindo automaticamente todos os tipos (Malha Fiscal, Débitos Fiscais, NF-e, NFC-e, CT-e e seus resumos). Cada linha é gravada e o arquivo fechado na hora (sem handler de vida longa atrelado ao lote), garantindo que nada se perca mesmo se a execução travar minutos depois. Falha ao gravar o CSV é isolada (`try/except`) e nunca interrompe a extração fiscal em si.
  - Colunas: `data_hora`, `empresa` (`COD - EMPRESA - CNPJ`), `aba_documento`, `perfil`, `mes_referencia`, `tela_na_central`, `arquivo_esperado`, `chave_solicitacao` — a última pensada para uma futura função (fora do escopo desta versão) que retome downloads automaticamente a partir deste mesmo log.

## [2026-09-09] — Versão 2.1.2

### Corrigido
- **Batimento de CNPJ genuinamente ausente levava até ~5 minutos** — `_open_taxpayer_from_home` (`src/extraction/siga_extractor.py`) fazia 3 tentativas completas de busca ao receber `TaxpayerNotFoundError`, mas cada busca já esgota sozinha um teto interno generoso de 90s em `_wait_for_taxpayer_search_result` antes de concluir "não encontrado" (confirmado ao vivo: cada tentativa levou ~91s, e o debounce de 10s introduzido na v1.7.10 nunca chegou a disparar em nenhum caso real — todo `taxpayer-search-timeout-*` salvo em `diagnostico/` veio do teto de 90s, nunca do debounce de 10s). Num lote real de 155 CNPJs com 30 não encontrados, isso custou **~2h30 das 4h08 totais** — mais que a própria Central de Downloads. Reduzido para 1 tentativa quando o erro é especificamente "não encontrado" (as demais falhas — timeout, página em branco — continuam com as 3 tentativas, que servem a um propósito diferente: recuperar de instabilidade transitória, não repetir uma busca já confirmada).
- **Perda total de um lote de 155 CNPJs (675 arquivos) por instabilidade de sessão exatamente na etapa final** — diagnosticado a partir de uma execução real de 4h08min: a página do SIGA ficou vazia (`empty-app-root`) 274 vezes ao longo do lote (recuperando na maioria das vezes com as 2 recargas padrão de `stabilize_after_navigation`), até que a última ocorrência, bem no momento de reautenticar para acessar a Central de Downloads após terminar todos os 155 CNPJs, não se recuperou nem após as 2 recargas — o erro não tratado subiu até a GUI e abortou a execução sem buscar nenhum dos 675 arquivos já solicitados com sucesso ao SIGA.
  - `_prepare_downloads_context` (`src/extraction/siga_extractor.py`) ganhou uma camada de retentativa dedicada e mais tolerante (`Settings.downloads_context_retry_count`, padrão 5, com `downloads_context_retry_delay_ms` de 5s) especificamente para essa reautenticação — é o ponto mais caro de se perder de todo o fluxo, já que todo o trabalho fiscal do lote já foi enviado ao SIGA nesse momento.
  - Se mesmo assim falhar, `_run_batch_from_spreadsheet_in_context` agora captura o erro em vez de propagá-lo: o lote termina de forma graciosa, com um aviso explícito de que as solicitações já foram enviadas ao SIGA e podem ser buscadas manualmente na Central de Downloads, em vez de abortar sem explicação.

### Alterado
- **Console de execução do modo SIGA mostra o COD da empresa em vez do CNPJ** — novo `_display_label` (`src/extraction/siga_extractor.py`), que resolve o COD a partir de um mapa CNPJ→COD montado uma vez por lote (`SpreadsheetRow.cod`). Aplicado nas 12 mensagens de `narrate*` que identificam a empresa em processamento (início do CNPJ, não encontrado, reenfileiramento, solicitação de cada aba fiscal, contribuinte localizado). O log técnico (`logs/run.log`/`errors.log`) continua usando o CNPJ em todos os pontos, sem alteração — é o identificador preciso para diagnóstico e bate com o nome das pastas de saída. A mensagem "Digitando o CNPJ ... na busca..." também continua mostrando o CNPJ, propositalmente — é o valor literalmente digitado na busca do SIGA, não o COD.
  - Novo campo `Settings.fiscal_tab_retry_count`/`fiscal_tab_retry_delay_ms` (v2.1.1) e `Settings.downloads_context_retry_count`/`downloads_context_retry_delay_ms` (esta versão) documentados juntos por serem parte do mesmo esforço de resiliência.

## [2026-09-09] — Versão 2.1.1

### Corrigido
- **Solicitação de uma aba fiscal (Malha Fiscal, Débitos Fiscais, NF-e, NFC-e, CT-e) falhava definitivamente na primeira tentativa, mesmo sendo uma falha tipicamente transitória** (timeout, overlay travado, lentidão momentânea do SIGA) — diagnosticado analisando `_extract_fiscal_tables` (`src/extraction/siga_extractor.py`): a abertura do contribuinte (`_open_taxpayer_from_home`) já ganha até 3 tentativas para essa mesma classe de erro, mas a solicitação de cada aba fiscal individual, feita minutos depois já dentro do contribuinte, não tinha retentativa alguma — uma instabilidade momentânea ali perdia aquela aba de forma permanente para o CNPJ na execução, exigindo reprocessamento manual.
  - Novo `_request_fiscal_tab_with_retry` (`src/extraction/siga_extractor.py`), envolvendo as três chamadas dentro de `_extract_fiscal_tables` (`_request_malha_fiscal`, `_request_debitos_fiscais` e `_collect_fiscal_tab_requests` para NF-e/NFC-e/CT-e) com até `Settings.fiscal_tab_retry_count` tentativas (padrão 3, mesmo número já usado na abertura do contribuinte) e `Settings.fiscal_tab_retry_delay_ms` (padrão 2s) de espera entre elas — mesmo padrão de narração/log já usado no reenfileiramento de contribuinte.
  - Novos campos em `Settings` (`src/config.py`): `fiscal_tab_retry_count: int = 3`, `fiscal_tab_retry_delay_ms: int = 2_000`.
- **Timeout de espera pela geração do relatório na Central de Downloads elevado de 240s para 600s** (`Settings.download_generation_timeout_ms`, `src/config.py`) — um lote real de 22 solicitações (2 CNPJs × 5 abas fiscais) mostrou a maioria das solicitações ainda ausente da Central passados os 240s, com a fila do backend do SIGA sob carga real de outros usuários do escritório compartilhando a mesma Central de Downloads (não um bug do lado cliente; ver `ARQUIVOS/PASTA DE SAIDA/log.txt`). Ressalva documentada no próprio comentário do código: sob concorrência real observada (fila crescendo ~15 solicitações/minuto de outros usuários), nem 600s garante que todas as solicitações de um lote apareçam a tempo — o gargalo é a fila compartilhada, não o timeout em si.

## [2026-09-03] — Versão 2.1.0

### Alterado
- **Modo NFC-e: empresas agora vêm direto do portal SEFAZ-CE, não mais de planilha.** Removidas as abas "Importar Planilha"/"Entrada Manual" da tela de seleção do NFC-e (exclusivo desse modo — SIGA e NF-e não foram tocados). No lugar, o botão "Carregar Empresas do Portal" (antigo "Validar Empresas") faz login automático e raspa IE + nome reais da sessão logada (`NfceSessionManager.listar_empresas`, já usada durante a execução), resolve o CNPJ de cada uma via a planilha-base IE/CNPJ e mantém só as que têm arquivo de chaves correspondente na pasta configurada — mostrando também a quantidade de chaves encontradas (nova coluna "Chaves" na grade). Reduz de 3 fontes de dados manuais para 2 (planilha-base + pasta de chaves), sempre com nomes corretos e a lista já filtrada ao que há para baixar.
  - Nova `NfceBatchExtractor.discover_selectable_companies` (`src/extraction/nfce_extractor.py`), reaproveitando `listar_empresas`, `load_cnpj_ie_base` e `extract_keys_from_spreadsheet`, já existentes.
  - Novo `Api.load_nfce_companies` (`src/webui/api.py`), assíncrono (mesmo padrão de `start_browser`), e novo atalho `JsBridge.nfce_companies_loaded` (`src/webui/bridge.py`).
  - `start_nfce_extraction`/`run_batch_in_context` não mudaram — continuam recebendo as linhas selecionadas no mesmo formato de sempre.
- **Timeout de espera pela geração do relatório na Central de Downloads do SIGA (NF-e/NFC-e/CT-e/Malha/Débitos) aumentado de 90s fixos para um timeout dedicado de 240s** (`Settings.download_generation_timeout_ms`, novo em `src/config.py`), separado do timeout de download do navegador em si (`download_wait_timeout_ms`, continua 90s) — os dois reaproveitavam a mesma constante, mas representam esperas de naturezas bem diferentes (geração no backend do SIGA, potencialmente de minutos, vs. download de um XLSX já pronto). `_find_pending_download_matches` (`src/extraction/siga_extractor.py`) passou a usar o novo timeout.
- **Modo NFC-e: "Pasta de chaves" agora aceita direto uma pasta de resultado do SIGA, sem preparo manual.** O próprio modo SIGA já gera, por contribuinte, `<COD> - <EMPRESA> - <CNPJ>/<mês>/NFC-e/*.xlsx` com uma coluna "Chave de acesso" — as mesmas chaves que o NFC-e precisa. `find_keys_file_for_cnpj` (1 arquivo) virou `find_keys_files_for_cnpj` (`src/extraction/nfce_extractor.py`): acha a subpasta `<CNPJ>` e varre toda subpasta chamada exatamente `NFC-e` dentro dela (qualquer profundidade), somando com o formato antigo (arquivo `.xlsx` solto nomeado com o CNPJ) — os dois formatos funcionam ao mesmo tempo, sem configuração. Novo agregador `collect_nfce_keys_for_cnpj` una as chaves de múltiplos arquivos, usado tanto na descoberta (`discover_selectable_companies`) quanto na execução (`run_batch_in_context`).
  - **Proteção contra mistura com NF-e/CT-e**: NF-e, NFC-e e CT-e usam o mesmo formato de chave de 44 dígitos, e o SIGA cria pastas irmãs (`NF-e/`, `NFC-e/`, `CT-e/`) dentro do mesmo `<empresa>/<mês>/` — só a pasta `NFC-e/` é varrida, nunca as irmãs. Segunda rede de segurança independente: `extract_keys_from_spreadsheet` agora valida o dígito do modelo do documento embutido na própria chave (posições 21-22 do padrão nacional de chave de acesso: `65` = NFC-e), descartando qualquer sequência de 44 dígitos que não seja NFC-e mesmo que apareça dentro da pasta certa por engano. Testado com fixture fabricada (pastas `NF-e`/`NFC-e`/`CT-e` irmãs + arquivo intruso de modelo errado dentro da própria pasta `NFC-e`): só a chave de modelo `65` passa.

### Corrigido
- **Execução do NFC-e nunca conseguia abrir a tela da empresa ("Timeout aguardando estado 'visible' em a[ui-sref='taxpayers.fiscalCouponsNfceList']"), sempre acionando recuperação até a sessão do navegador cair** — diagnosticado ao vivo abrindo o portal manualmente (Claude in Chrome) e inspecionando o DOM: o link de cada empresa (`javascript:submete(...)`, raspado por `listar_empresas`) abre a empresa numa **aba/janela nova** via `window.open()`, nunca navega a aba atual — igual ao script original (`xml nfce.py`), que já tratava isso com `wait.until(lambda d: len(d.window_handles) > 1)` + `switch_to.window(...)`. A versão portada (`_abrir_empresa`, `src/extraction/nfce_extractor.py`) nunca fazia essa troca de aba, então ficava procurando o link "Consultar NFC-e" na aba antiga (a lista de empresas), que nunca tem esse link. Some ainda a isso: o Chrome bloqueia por padrão pop-ups abertos via script (só permite os disparados por clique real do usuário), então mesmo com a troca de aba corrigida a empresa não abriria sem essa segunda peça.
  - `_start_debug_browser_process` (`src/utils/browser.py`) ganhou a flag `--disable-popup-blocking` no navegador da automação.
  - `_abrir_empresa` agora compara os handles de aba antes/depois de executar o script, identifica a aba nova e devolve essa `Page` (levanta `TimeoutError` se nenhuma aba nova abrir — ex.: pop-up bloqueado). `_processar_empresa` passou a usar essa aba para baixar as chaves (`_baixar_xml_chave`) e a fechá-la ao fim de cada passada via nova `_fechar_aba_empresa` (fecha a aba da empresa e volta para a lista) — evita acumular abas abertas a cada nova tentativa, mesmo padrão de higiene do script original.
  - Validado com testes unitários simulando um `WebDriver` falso: `_abrir_empresa` levanta `TimeoutError` quando nenhuma aba nova aparece; `_fechar_aba_empresa` fecha exatamente a aba da empresa e retorna à aba da lista.
- **Execução do NFC-e falhava no login logo após "Carregar Empresas do Portal" (descoberta) ter logado com sucesso** — `NfceSessionManager.fazer_login()` (`src/extraction/nfce_extractor.py`) sempre navegava primeiro para `nfce_login_url` antes de checar se já estava logado; ao ser chamado de novo (execução) segundos depois de a descoberta já ter autenticado a mesma sessão, navegar de volta para a tela de login com o portal já autenticado tinha comportamento imprevisível (o redirecionamento não caía nem na tela de login nem era reconhecido como "já logado"), derrubando as 3 tentativas com `NoSuchElementException` em `#txtUsuario` e abortando a execução com "Falha no login automático do modo NFC-e." `fazer_login()` agora checa a página atual (sem navegar) por links `submete` antes de tudo — como a descoberta deixa o navegador parado exatamente na área de empresas, a execução reconhece a sessão já ativa na hora, sem precisar navegar de novo. Sem regressão no login do zero nem em `renovar_login`/`reset_completo_com_espera` (que fazem logout explícito antes, então a checagem nova corretamente não encontra nada e cai no fluxo normal) — validado com testes unitários simulando `page` (sessão já ativa: retorna sem chamar `goto`; sem sessão: fluxo de login normal preservado).
- **"Iniciar Navegador" sempre abria a tela de login do SIGA, mesmo no modo NFC-e** — `_start_debug_browser_process` (`src/utils/browser.py`) tinha `settings.siga_url` fixo na URL inicial do navegador, então quem clicava "Iniciar Navegador" no modo NFC-e via a tela errada, apesar do login desse modo ser automático (CPF/senha) e não depender de navegação manual nenhuma. `launch_debug_browser`/`_start_debug_browser_process` ganharam um parâmetro opcional `initial_url`; `Api.start_browser` (`src/webui/api.py`) agora recebe o modo ativo da interface e escolhe `settings.nfce_login_url` para NFC-e, mantendo `settings.siga_url` como padrão para SIGA. Mensagens de status (`sigaOnBrowserStarted`, `web/src/js/main.js`) também passaram a variar por modo.
- **Taxa real de download de detalhamentos NFC-e ficava em 0% mesmo quando o resumo final da execução dizia "Detalhamentos baixados: N"** — diagnosticado analisando `ARQUIVOS/PASTA DE CHAVES NFCE/log.txt` de uma execução real (2 CNPJs, 8 solicitações NFC-e, 0 arquivos `.xlsx` de fato salvos em disco, apesar do resumo reportar 4) e reproduzindo manualmente o mesmo fluxo pelo portal. Duas causas raiz distintas, ambas em `src/extraction/siga_extractor.py`:
  - `_capture_download_for_match` levantava `TimeoutError` **direto na primeira tentativa** quando a linha não era reencontrada na Central de Downloads (`Nao foi possivel reencontrar a linha`), **ignorando por completo** o mecanismo de retry já existente (`Settings.download_retry_count`) — o `raise` acontecia fora do bloco `try/except` que trata as demais falhas com nova tentativa. Isso é exatamente o cenário mais comum: um match "encontrado" num ciclo de espera intermediário (ainda com status "Processando") ou que mudou de página com a chegada de novas solicitações de outros usuários na mesma Central compartilhada. Agora, quando a linha não é reencontrada, o código espera (`download_retry_delay_ms`) e revarre a Central inteira (`_scan_downloads_table_once(..., full_scan=True)`) antes de desistir, em vez de falhar na hora.
  - `_find_pending_download_matches` só fazia a varredura de confirmação final (`full_scan=True`, resolve duplicatas e reconfirma a página de cada match) quando **todas** as solicitações do lote haviam sido localizadas dentro do timeout (`all_settled=True`). Quando o timeout expirava com solicitações ainda pendentes — cada vez mais provável com o timeout curto de 90s corrigido acima —, o código pulava direto para retornar os matches "encontrados até agora" sem revalidá-los, e `_capture_download_for_match` tentava clicar numa posição de tabela potencialmente obsoleta. A varredura de confirmação final agora roda sempre, mesmo com timeout expirado.
  - **Contagem do resumo "Detalhamentos baixados: N" estava sempre certa em contar solicitações *tentadas*, não downloads que de fato aconteceram** — `Api._execute_siga` (`src/webui/api.py`) somava `len(result.fiscal_results)` para todos os CNPJs, mas `fiscal_results` inclui uma entrada para cada detalhamento solicitado independentemente de sucesso (erro, aviso de indisponibilidade `.txt` ou XLSX real). O campo `FiscalDownloadResult.downloaded_at` já existia para essa distinção mas nunca era consultado; a contagem agora soma apenas entradas com `downloaded_at is not None`.
  - Validado corrigindo manualmente, ao vivo, o mesmo caso do log original pelo portal (mesmos 2 CNPJs, mesmos 8 documentos NFC-e de Agosto/2026): 8/8 localizados e baixados com sucesso.

## [2026-08-24] — Versão 2.0.3

### Adicionado
- **`installer/siga-automacao.iss` (Inno Setup) recriado**, cobrindo o build "onedir" do PyInstaller pós-migração para pywebview (copia a pasta `dist\siga-automacao\` inteira — `.exe` + `_internal\` — em vez de um único arquivo, diferente do `.iss` original anterior à migração, removido junto com `pré-lixo/`). Gera `dist\installer\Setup <versão>.exe`; testado com instalação e desinstalação silenciosas (`/VERYSILENT`) antes de publicar.

### Corrigido
- **"Falha ao solicitar Malha Fiscal"/"Débitos Fiscais" mesmo com o botão de download presente e clicável na tela** — investigado ao vivo (CNPJs 00.384.193/0001-21 e 19.412.918/0004-19, ambos no log `testes/log.txt`): o botão existia, estava visível e habilitado, e o clique via o mesmo XPath do código funcionava quando testado manualmente segundos depois. Causa raiz confirmada como bug de código, não do site: `_request_malha_fiscal`/`_request_debitos_fiscais` (`src/extraction/siga_extractor.py`) esperavam só 1,5s fixo após trocar de tela e então tentavam clicar **uma única vez, sem retry** (`_click_xpath`/`_click_text_action` fazem uma checagem imediata só) — se o SIGA (SPA Angular/PrimeNG) demorasse um pouco mais que isso pra renderizar, a checagem única falhava e o código desistia na hora, mesmo o botão aparecendo pouco depois. Mesma classe de falso-negativo que `_wait_for_detail_xlsx_button_ready` já resolvia para o botão de detalhamento, nunca aplicada aqui.
  - Novo `_click_with_retry`, genérico: tenta em loop (XPath, com fallback por texto) por até 20s antes de desistir, em vez de checar uma vez só. Usado agora pelos dois botões de ação de Malha Fiscal e Débitos Fiscais.
  - Testado ao vivo contra os 2 CNPJs que falhavam no log: os dois agora completam `_request_malha_fiscal` com sucesso.

## [2026-08-24] — Versão 2.0.2

### Corrigido
- **Barra de "Progresso da Operação" do modo SIGA não se movia durante a execução** — ficava parada em 0% e só ia para 100% no final (comportamento herdado da própria GUI Tkinter anterior, que também nunca teve progresso incremental real). `SigaContributorExtractor.run_batch_from_spreadsheet_in_context` (`src/extraction/siga_extractor.py`) ganhou um parâmetro opcional `on_row_processed`, chamado com `(linhas_concluidas, total_linhas)` a cada empresa definitivamente resolvida (achada, não achada, ou erro após esgotar as retentativas) — reenfileiramentos por falha temporária não contam. `src/webui/api.py` usa isso para atualizar a barra em tempo real, reservando os últimos ~10% para a varredura final única da Central de Downloads (que não tem granularidade por CNPJ). Retrocompatível: sem o callback, nada muda.

## [2026-08-24] — Versão 2.0.1

### Corrigido
- **Download do resumo (Indicadores) de NF-e/NFC-e/CT-e abria a Central de Downloads individualmente, uma vez por resumo, antes mesmo de terminar de solicitar o resto do CNPJ** — diferente de Malha Fiscal/Débitos Fiscais/detalhamentos, que já ficavam enfileirados para uma única varredura no final do lote (`brain/2026-06-12-downloads-globais-no-final.md`). Descoberto ao analisar `saida/log.txt`: **30 viagens individuais** à Central de Downloads num lote de 5 CNPJs (~13s cada, 6,5 minutos desperdiçados), e pelo menos um detalhamento genuinamente perdido (`Informacoes Fiscais - NF-e - Emissor - Detalhamento Julho de 2026 - Interna` do CNPJ 19412918000176: o resumo intercalado inseria linhas novas na Central entre a solicitação do detalhamento e a varredura em lote dele, empurrando-o para trás do corte por timestamp — `cutoff_dt` em `_find_pending_download_matches` — até estourar o timeout de 12 minutos). `_download_current_table` (`src/extraction/siga_extractor.py`) foi renomeada para `_request_summary_download` e não busca mais o arquivo na hora: devolve a `PendingDetailRequest` do resumo, que entra na mesma lista enfileirada e é resolvida na única varredura final do lote junto com os detalhamentos.
  - `PendingDetailRequest` ganhou `is_summary_request: bool` (exclui o próprio resumo da montagem de `FiscalDownloadResult` — ele só serve de metadado) e `summary_request_key: str | None` (resolve o `Path` real do resumo depois da varredura em lote, já que ele deixou de ser buscado sincronamente).
  - **Bug pego em teste ao vivo durante a implementação, antes de qualquer commit:** a Central de Downloads mostra o texto idêntico ("Informações Fiscais - {aba} - Indicadores - {ano}") para o resumo de Emissor e o de Destinatário/Tomador da mesma aba — sem Emissor/Destinatário no rótulo. Como os dois passaram a coexistir na mesma varredura em lote, a chave interna (`request_key`, antes derivada só de CNPJ+mês+texto) colidia e o segundo resumo sobrescrevia o `Path` do primeiro. Corrigido incluindo `profile_name` na `request_key` (`_build_pending_request`).

## [2026-08-21] — Versão 2.0.0

### Alterado
- **Interface migrada de Tkinter para pywebview** (mudança de versão maior: a camada de apresentação foi inteiramente reescrita). A janela agora renderiza HTML/CSS/JS pelo WebView2 do Edge, partindo dos mockups gerados no Stitch (`design/`), em vez de widgets `ttk` montados à mão. **O backend de extração não mudou em nada**: `SigaContributorExtractor`, `NfceBatchExtractor`, `MeudanfeBatchExtractor`, `SigaLoginFlow` e `BrowserSession` continuam exatamente como estavam — só a camada de interface foi trocada.
  - Novo pacote `src/webui/`: `app.py` (janela e ciclo de vida), `api.py` (métodos expostos ao JavaScript via `js_api`), `bridge.py` (canal Python → JS), `assets.py` (resolução de caminhos em dev e empacotado) e `windows_integration.py` (AppUserModelID).
  - Nova pasta `web/` com a fonte da interface (HTML, JS e Tailwind) e `web/build.py`, que compila tudo para `src/web_dist/` — a única pasta lida em tempo de execução. **Node é dependência apenas de build**; o `.exe` empacota o CSS/JS já compilado.
  - **Nada depende de CDN nem de internet para a interface abrir**: o Tailwind é compilado localmente e as fontes (Inter, JetBrains Mono, Material Symbols) ficam vendorizadas em `src/web_dist/fonts/`.
  - Os dois canais de tempo real (console de log e tabela de resultados NF-e) deixaram de usar fila + polling (`root.after`), necessários só por causa da regra do Tkinter de atualizar widgets apenas na thread principal. O `window.run_js` do pywebview é seguro a partir de qualquer thread, então as threads de trabalho empurram os eventos direto. Um buffer de replay cobre a janela entre abrir a aplicação e o JavaScript registrar as funções do contrato, para nenhuma mensagem se perder.
  - Os ~20 `messagebox` viraram modais em HTML (o pywebview não tem equivalente nativo para avisos), e a confirmação ao fechar com execução em andamento passou a usar o diálogo nativo `create_confirmation_dialog`, com o encerramento gracioso preservado (`shutdown_debug_browser` + espera pela thread de trabalho) e proteção contra reentrância.
  - Novo `--webui-debug` em `main.py`, que abre o DevTools do WebView2 (F12) para desenvolvimento.
  - Erros de JavaScript agora são registrados em `logs/run.log` (`Api.report_client_error`) — antes uma falha na interface só apareceria no DevTools, que o operador não abre.
  - Nova dependência: `pywebview==6.2.1` (`requirements.txt`).

### Adicionado
- **`siga-automacao.spec` (PyInstaller) recriado**, cobrindo o novo bundle da interface (`src/web_dist/`) e os imports dinâmicos de backend do pywebview. O spec havia sido removido numa limpeza anterior e não existia mais no repositório.

### Removido
- **`src/gui.py`** (2194 linhas, a GUI Tkinter) — substituída pela interface em `src/webui/` + `web/`. Continua recuperável pelo histórico do git (`git show HEAD:src/gui.py`).

## [2026-08-21] — Versão 1.10.0

### Adicionado
- **Painel de trabalho central dedicado por modo de operação** (`src/gui.py`), substituindo a antiga "Controle de Empresas" única e igual nos 3 modos:
  - **NF-e (Meu DANFE):** a grade de empresas (que esse modo nunca usou de verdade) foi substituída por uma **tabela de resultados ao vivo**, uma linha por planilha da pasta de entrada (colunas Planilha/Chaves/Baixadas/Puladas/Falhas/Status), atualizada em tempo real conforme cada worker (`MeudanfeBatchExtractor`, até 4 Chromes em paralelo) termina um pedaço do trabalho — novos `_build_nfe_results_panel`/`_upsert_nfe_result_row`/`_drain_nfe_results_queue` em `src/gui.py`. O botão "Iniciar Navegador" também some nesse modo, já que ele não usa `BrowserSession`.
  - `MeudanfeBatchExtractor.executar_lote` (`src/extraction/meudanfe_extractor.py`) ganhou um parâmetro opcional `on_planilha_concluida`, chamado a cada worker que termina (não só ao final do lote inteiro) — retrocompatível, sem mudança de comportamento quando omitido.
  - **NFC-e:** a grade de empresas continua, mas as 5 colunas de tipo de documento do SIGA (que não fazem sentido aqui — o NFC-e sempre baixa todos os XMLs da empresa) viraram uma única coluna "Incluir" por linha; painel de parâmetros ganhou os rótulos "ARQUIVOS"/"AUTENTICAÇÃO" para separar visualmente os grupos de campos.
  - **SIGA:** sem mudança estrutural — a grade de 5 checkboxes por documento já fazia sentido para esse fluxo.

### Corrigido
- **Botão "Executar" ficava desabilitado para sempre no modo NF-e**, criado nesta mesma versão: `execute_button` só era reabilitado pelo fluxo de "Iniciar Navegador" (`_on_browser_start_succeeded`/`_restore_browser_controls_state`, condicionados a `self._browser_started`), mas esse botão foi propositalmente escondido no modo NF-e (item acima) — sem ele, `_browser_started` nunca virava `True` e o botão Executar nunca saía do estado inicial `disabled`. Corrigido tornando `_restore_browser_controls_state` ciente do modo: no modo NF-e, o Executar é habilitado direto, sem depender de navegador nenhum; `_set_operation_mode` agora chama esse método a cada troca de modo (exceto com uma execução em andamento, para não reabilitar o botão no meio de um lote).

## [2026-08-20] — Versão 1.9.0

### Adicionado
- **Modo de operação NF-e implementado** (antes só mostrava "não implementado nesta versão", por causa do motor Playwright incompatível do script `importação/NFE/NFE_XML.py` — ver `brain/2026-08-19-nfe-playwright-nao-integrado.md`). Novo módulo `src/extraction/meudanfe_extractor.py`, portado de `importação/NFE 2/automacao-meu-danfe/main.py` (projeto standalone já maduro, com histórico de 6 iterações até estabilizar a resolução do captcha Cloudflare Turnstile do site): consulta pública, sem login, por chave de acesso de 44 dígitos no site Meu DANFE, lendo a coluna "Chave NF-e" de qualquer planilha `.xlsx` numa pasta (tipicamente a própria saída do modo SIGA, que já tem essa coluna) e baixando XML + PDF para `<pasta>/downloads-meudanfe/<planilha>/{XML,PDF}/<chave>.{xml,pdf}`.
  - **Diferente de SIGA/NFC-e, este modo não usa `BrowserSession`**: gerencia seus próprios drivers `undetected_chromedriver` (1 a 4 instâncias em paralelo, configurável — o script original permite até 8), já que é uma consulta anônima sem estado de sessão para compartilhar, e a resolução de captcha foi validada especificamente contra as camuflagens do `undetected_chromedriver`. Por isso o modo NF-e não depende do botão "Iniciar Navegador".
  - A lógica de captcha (busca em iframes → checkbox → clique por offset via CDP `Input.dispatchMouseEvent`, com fallback em `ActionChains`), o preenchimento do campo de busca via JS (foco + `.value` + eventos `input`/`change`, sem `send_keys` físico) e a otimização de sessão via botão "Nova Consulta" foram portados como estavam, sem simplificar — são o resultado de iterações já validadas contra o site real.
  - Novos campos em `Settings` (`src/config.py`): `nf_meudanfe_url`, `nf_meudanfe_chrome_path`, `nf_meudanfe_input_folder`, `nf_meudanfe_max_workers` (1–4), `nf_meudanfe_captcha_timeout_seconds`, `nf_meudanfe_download_timeout_seconds`.
  - Nova dependência: `undetected-chromedriver==3.5.5` (`requirements.txt`).
  - O código de sugestão de navegadores por IA (Gemini/Groq) e a GUI PySide6 do projeto-fonte não foram portados — o primeiro já era código morto no próprio projeto original, e o segundo foi substituído pela mesma GUI Tkinter do resto do projeto.

## [2026-08-20] — Versão 1.8.4

### Corrigido
- **"Não localizado na Central de Downloads" para arquivos que na verdade estavam lá** (falso-negativo), e **detalhamentos de NF-e/NFC-e de alguns CNPJs que nunca eram gerados de verdade**. Descoberto porque o usuário conferiu manualmente a Central de Downloads e viu que "pelo menos alguns" dos itens marcados como indisponíveis estavam presentes — investigação cruzou os 24 avisos de um lote real (`testes/`) contra as 65 linhas reais da Central (2 páginas, histórico completo) e achou duas causas independentes, ambas em `src/extraction/siga_extractor.py`:
  - **Malha Fiscal/Débitos Fiscais perdidos por instabilidade de varredura (falso-negativo confirmado):** o SIGA reaproveita a mesma linha, com o timestamp **original**, ao reabrir um relatório já gerado no mesmo dia — então `preferred` (que compara `requested_at` contra a hora do clique) nunca fica `True` para esses casos. Como `_find_pending_download_matches` só "travava" (`resolved_matches`) um match `preferred`, e a varredura por ciclo é instável (contagem de itens localizados oscilando entre ciclos por causa do reload + reseleção do tamanho de página), um item corretamente encontrado num ciclo intermediário podia "sumir" se um ciclo posterior — inclusive a varredura final antes do timeout — não o visse de novo. Corrigido acumulando o melhor match já visto em `best_matches_ever` (via `_store_best_download_match`, já existente) ao longo de todos os ciclos, em vez de descartar tudo e usar só o resultado da última varredura.
  - **Detalhamentos de NF-e/NFC-e de 4 CNPJs nunca apareciam na Central (ausência real, não falso-negativo):** confirmado ao vivo (CNPJ 19.412.918/0001-76 e 19.412.918/0002-57) que a tela sempre tem **dois** botões idênticos "Baixar Tabela (XLSX)" quando o resumo e o detalhamento estão ambos na página — um da seção "1. Indicadores por Mês" (resumo) e outro da "2. Detalhamento ..." — e `_wait_for_detail_xlsx_button_ready`/`_click_detail_xlsx_button` sempre clicavam no **primeiro**, que é sempre o do resumo (a seção "2." vem depois da "1." no DOM). O clique de detalhamento nunca acionava o relatório certo, então nenhuma linha nova era gerada e o "não localizado" na Central era, na verdade, um relatório que nunca chegou a ser solicitado de verdade. Corrigido para escolher o **último** candidato pronto em vez do primeiro — confirmado ao vivo que isso agora seleciona corretamente o botão da seção "2.".

## [2026-08-20] — Versão 1.8.3

### Corrigido
- **Resumo (NF-e/NFC-e/CT-e) e detalhamentos ainda falhavam mesmo depois da v1.8.1**, confirmado ao analisar um lote de teste real (`testes/`) e testando ao vivo no SIGA. Duas causas independentes, ambas em `src/extraction/siga_extractor.py`:
  - **Texto de busca do resumo errado:** `_download_current_table` (v1.8.1) usava o nome interno do arquivo (ex. `"resumo-emissor"`) como `tela_aba` para localizar a linha na Central de Downloads, mas a Central rotula a solicitação como `"Informações Fiscais - {aba} - Indicadores - {ano}"` — sem Emissor/Destinatário/Tomador no texto (isso só aparece em "Filtros Aplicados"). Toda solicitação de resumo falhava 100% das vezes e caía no arquivo de aviso "não localizado" — confirmado no log (`Downloads não localizados apos a varredura completa: ... - resumo-emissor`) e ao vivo (CNPJ 04.419.796/0001-72). Corrigido construindo o texto real (`"Informacoes Fiscais - {tab} - Indicadores - {ano}"`, ano lido da página) para a busca, mantendo o nome de arquivo final curto de sempre através de um novo campo `PendingDetailRequest.output_basename` (usado por `_download_output_basename`, que substitui o uso direto de `_build_download_output_basename(tela_aba)` nos três pontos de salvamento). `_extract_download_match_fragments_from_title`/`_row_contains_signature_fragments` também passam a reconhecer o padrão "Indicadores" (como já faziam para Malha Fiscal/Débitos Fiscais), dando uma segunda chance de casamento por fragmentos caso o texto exato varie por aba.
  - **Detalhamentos de NF-e/NFC-e/CT-e (relatórios pesados, com centenas de notas) somem da varredura final do lote:** `_download_keys_still_processing` só continuava esperando uma solicitação se ela já tivesse sido *avistada* com status "processando/aguardando/gerando" — mas um relatório grande pode levar minutos só para o SIGA inserir a linha na Central, não apenas para concluí-la. Uma solicitação que ainda não apareceu como nenhuma linha (nem "processando") era tratada como definitivamente ausente na primeira varredura, mesmo tendo sido pedida minutos antes (confirmado no log: pedido às 08:58:08, varredura final às 09:04:08, ainda ausente). Corrigido para também aguardar (dentro do mesmo orçamento de `download_wait_timeout_ms` já configurado) uma solicitação que simplesmente ainda não apareceu em nenhum estado, e não só as que já apareceram como "processando".

## [2026-08-20] — Versão 1.8.2

### Removido
- **Modo assistido via terminal (`--live-assist`/`--live-command`, `src/live_assist.py`):** nunca funcionava de forma confiável para o operador (seleção do certificado digital era concluída, mas o fluxo travava depois) e nunca chegou a ser usado em produção — a depuração ao vivo passou a ser feita conectando diretamente num Chrome real via automação de navegador externa. Removidos o módulo, os argumentos `--live-assist`/`--live-command`/`--target`/`--value` e o roteamento correspondente em `src/main.py`. A GUI continua sendo o único modo de extração e agora também o único modo de execução do `main.py`.

## [2026-08-20] — Versão 1.8.1

### Corrigido
- **Download de resumo (NF-e/NFC-e/CT-e) nunca completava, travando a extração desses três documentos em todo lote de teste:** duas causas encadeadas, ambas em `src/extraction/siga_extractor.py`, diagnosticadas a partir da análise de um lote real (`teste-19082026/`) e confirmadas ao vivo no próprio SIGA.
  - **Causa raiz:** o clique em "Baixar Tabela" do resumo era tratado como download direto do navegador (`page.expect_download()`, 2 tentativas de até 90s cada — até 3 minutos desperdiçados por perfil). Na prática o SIGA processa esse botão de forma assíncrona, exatamente como Malha Fiscal e Débitos Fiscais: o clique só enfileira a solicitação na Central de Downloads ("Downloads"), nunca dispara um evento de download real no navegador — confirmado ao vivo (CNPJ 04.419.796/0001-72, aba NF-e): o mesmo toast "A solicitação de download foi realizada com sucesso" do Malha Fiscal aparece, e a solicitação é concluída em segundos na Central de Downloads, sem download direto algum. `_download_current_table` foi reescrito para clicar, aguardar esse toast (`_wait_for_download_request_toast`, novo método) e resgatar o arquivo direto na Central de Downloads — eliminando a espera de até 3 minutos por perfil e a causa raiz da falha. Os métodos `_capture_direct_download`/`_download_from_download_center` (a tentativa direta e seu fallback) foram removidos por ficarem obsoletos.
  - **Efeito colateral que mascarava o problema:** o fallback (única via que já funcionava) usava `requested_after=datetime.min` para estimar quando a solicitação foi enfileirada, o que quebrava `_scan_downloads_table_once` com `OverflowError: date value out of range` assim que ele tentava `earliest - timedelta(seconds=60)` no corte de paginação — então mesmo quando o fallback seria acionado, a extração inteira travava com um erro não tratado em vez de simplesmente baixar o arquivo.

## [2026-08-19] — Versão 1.8.0

### Adicionado
- **Modo de operação NFC-e:** novo módulo `src/extraction/nfce_extractor.py` (`NfceBatchExtractor`, `NfceSessionManager`, `NfceDownloadManager`), portado de um script standalone (`importação/NFCE/codigo-fonte/xml nfce.py`) para reutilizar `BrowserSession`/`selenium_compat.py` em vez de gerenciamento próprio de Chrome/driver. Faz login automático no portal `servicos.sefaz.ce.gov.br`, resolve empresas por IE/CNPJ, busca chaves de 44 dígitos numa pasta configurável por empresa e baixa os XMLs com renovação proativa de sessão e protocolo de recuperação em caso de sessão instável.
- **CPF/senha do modo NFC-e digitados na própria GUI:** campos dedicados (senha mascarada) na barra de parâmetros — os valores ficam só em memória (`Settings.nfce_cpf`/`nfce_senha`) pelo tempo da execução e nunca são persistidos em `.env`, planilha ou log.
- **Interface reformulada do zero:** header com logo + nome/slogan do escritório + nome e versão do programa; rail de navegação com um card por função (SIGA/NF-e/NFC-e), cada um com badge, tag de maturidade ("APROVADA"/"EM TESTES") e realce dourado no ativo; barra horizontal de parâmetros que troca de conteúdo por modo; tabela de empresas e console de execução lado a lado; rodapé com o nome do escritório. Paleta clara baseada nas cores do logo oficial (dourado `#ECAC4C` como única cor de ação/CTA, petróleo `#3C5464` estrutural, slate `#84949C` de apoio) combinada com os neutros já usados em produção pela identidade "Barreira & Associados" (fundo, bordas, texto, sucesso/erro — constantes `BA_*` de `importação/NFCE/codigo-fonte/xml nfce.py`). O modo NF-e mostra um aviso de "não implementado" (motor Playwright incompatível com o resto do projeto — ver `brain/2026-08-19-nfe-playwright-nao-integrado.md`).
- **Versão visível na GUI:** o título da janela e um badge no header agora mostram `v{versão}`, lida de `src/__init__.py::__version__` (única fonte de verdade).
- Novos campos em `Settings` (`src/config.py`) para o modo NFC-e: URLs do portal, planilha-base de IE/CNPJ, pasta de chaves, timeouts de renovação/recuperação de sessão (`nfce_cpf`/`nfce_senha` também existem como campos, mas só são preenchidos em runtime pela GUI).
- `.env.example` promovido da raiz do projeto (antes vivia em `pré-lixo/.env.example`).
- **`log.txt` por execução, salvo na pasta de saída:** além dos arquivos fixos `logs/run.log`/`logs/errors.log`/`logs/atividades.log` (relativos à instalação do app), cada execução (SIGA ou NFC-e) agora também grava um `log.txt` combinado (log técnico completo + narração) na pasta de saída escolhida pelo usuário — `SigaAutomationGUI._open_run_log_file`/`_close_run_log_file` (`src/gui.py`) anexam um `logging.FileHandler` temporário só pela duração da execução.

### Alterado
- Ícones do aplicativo (`images/icons/*`) regenerados a partir de `images/logo/logo.png` (16/32/64/128/256px + `.ico` multi-resolução), substituindo a arte solta anterior (`siga-automacao-icon.jpg`, removida).
- **Ícone correto na barra de tarefas do Windows:** registrado um AppUserModelID próprio (`BarreiraAssociados.SigaAutomacao`) antes de criar a janela — sem isso, rodar via `python main.py` fazia o Windows agrupar o processo sob o ícone do `python.exe` na barra de tarefas, mesmo com `iconbitmap`/`iconphoto` corretos na própria janela.
- Removido código morto em `src/gui.py`: atribuições duplicadas de `title()`/`geometry()`/`bg` no `__init__` (sobrescritas sem uso em `_build_ui`).
- `CLAUDE.md` atualizado: descrição da GUI, regra de sincronização de versão (agora só `src/__init__.py`, já que o `.iss` do instalador foi removido) e notas sobre a pasta `importação/`.

### Corrigido
- `src/__init__.py::__version__` estava desatualizado (`1.4.2`, sem relação com as releases reais) — corrigido e agora sincronizado com esta entrada do changelog.

### Removido
- Duplicatas soltas fora do controle de versão: `logo.png` (raiz, idêntico a `images/logo/logo.png`), `testes/live_test_log.txt` (96 MB) e `perf_after.log`.
- Botão "Ajuda" da GUI (e o método `_show_help_dialog`) — removido a pedido; `manual_instrucoes.html` continua no repositório mas não é mais aberto de dentro do app.
- **Pasta `pré-lixo/` inteira removida do repositório** (movida para a lixeira do Windows, não hard-delete): documentação de planejamento (`PRD.md`, `PLANO_CORRECOES.md`), specs de build/instalador (`siga-automacao-gui.spec` do PyInstaller, `installer/siga-automacao.iss` do Inno Setup), o script de teste manual `run_test_live.py` e os exports de design do Stitch. **Consequência:** não há mais caminho configurado para gerar `.exe`/instalador — esses arquivos precisam ser recriados caso o empacotamento seja necessário de novo.

## [2026-08-10] — Versão 1.7.11

### Corrigido
- **Build do PyInstaller quebrado após a reorganização em `pré-lixo/`:** `siga-automacao-gui.spec` usava caminhos relativos (`main.py`, `images/...`) que o PyInstaller resolve em relação à pasta do próprio `.spec` (`SPECPATH`), não à raiz do projeto — algo que passou despercebido na v1.7.9 porque o build não havia sido testado após a mudança. Como o `.spec` ficou um nível mais fundo dentro de `pré-lixo/`, o build falhava com `script 'pré-lixo\main.py' not found`. Corrigido calculando a raiz do projeto via `os.path.join(SPECPATH, os.pardir)` e usando-a em `Analysis()` e no `icon` do `EXE()`.

## [2026-08-10] — Versão 1.7.10

### Corrigido
- **Falso "Contribuinte não encontrado" em máquinas com rede/SIGA mais lentos:** `_wait_for_taxpayer_search_result` em `src/extraction/siga_extractor.py` podia declarar um contribuinte como não encontrado antes do resultado real da busca chegar, quando a tabela ficava momentaneamente sem linhas e sem o indicador de carregamento (`skeleton`) visível — janela essa curta demais (3s) em ambientes de rede mais lentos. O debounce foi elevado para 10s e o teto geral de espera da busca, de `max(30, timeout_ms/1000)` para `max(90, timeout_ms/1000)` segundos.

### Alterado
- **Artefatos de diagnóstico salvos junto da planilha:** `SigaPageInspector.save_debug_artifacts` (`src/utils/siga_page.py`), usado para capturar screenshot/HTML sempre que a automação encontra um estado problemático (ex.: contribuinte não encontrado, página em branco), passa a salvar em uma subpasta `diagnostico/` dentro de `settings.output_dir` — que a GUI mantém sincronizado com a pasta da planilha selecionada — em vez da pasta interna `logs/` do aplicativo. Isso facilita localizar a evidência de um problema relatado em outra máquina.

## [2026-07-23] — Versão 1.7.9

### Alterado
- **Reorganização de arquivos não essenciais em `pré-lixo/`:** Documentação de planejamento (`PRD.md`, `PLANO_CORRECOES.md`), artefatos de design (`design/`), specs de build/instalador (`siga-automacao-gui.spec`, `installer/siga-automacao.iss`), o script de teste manual (`testes/run_test_live.py`) e o `.env.example` foram movidos para a pasta `pré-lixo/`, mantendo o histórico do git via `git mv`. Nenhum desses arquivos é lido pelo código em `src/` ou por `main.py`; os caminhos relativos internos ao `siga-automacao.iss` foram ajustados para o novo nível de aninhamento. `README.md`, `CHANGELOG.md`, `LICENSE`, `requirements.txt` e `.gitignore` permanecem na raiz por exigência de estrutura do projeto.

## [2026-07-17] — Versão 1.7.8

### Melhorado
- **Localização da linha de download também otimizada:** A análise dos logs de execução mostrou que, após a Versão 1.7.7 acelerar a fase de espera/localização (de ~90 minutos para ~2 segundos numa varredura de 12 arquivos), o gargalo restante era `_find_download_row_for_match_on_current_page` — chamada uma vez por arquivo dentro de `_capture_download_for_match`, ainda escaneando a página inteira linha a linha via Selenium (sem o timeout reduzido por célula) só para reencontrar a linha antes do clique de download. Ela passa a reaproveitar a mesma leitura em lote via JavaScript (`_iter_downloads_table_rows`) já usada no loop de espera, resolvendo um `Locator` real apenas para a linha vencedora ao final.

## [2026-07-17] — Versão 1.7.7

### Melhorado
- **Loop de espera da Central de Downloads mais rápido:** Três otimizações no ciclo de espera pelo processamento dos relatórios (`_find_pending_download_matches` em `src/extraction/siga_extractor.py`):
  1. A leitura das linhas da tabela passa a ser feita em uma única chamada JavaScript por página (`_read_downloads_table_rows_js`/`_iter_downloads_table_rows`), no lugar de um round-trip Selenium por linha/célula (`.is_visible()`, `.inner_text()`), com fallback automático para o método antigo caso o `evaluate` falhe.
  2. Solicitações já confirmadas (match preferido) deixam de ser reprocuradas nos ciclos de retry seguintes, reduzindo o número de páginas percorridas a cada reload enquanto o restante ainda está em processamento no SIGA.
  3. O índice da opção "maior valor" no dropdown de linhas por página é cacheado após a primeira descoberta, evitando reler o texto de todas as opções a cada reload em `_select_max_downloads_page_size`.

## [2026-07-17] — Versão 1.7.6

### Adicionado
- **Simulação de atividade na Central de Downloads:** Durante os ciclos de espera pelo processamento dos relatórios na Central de Downloads (`_find_pending_download_matches` em `src/extraction/siga_extractor.py`), o robô agora simula uma pequena interação do usuário (Page Down seguido de Page Up) antes de cada nova varredura. Isso evita que a sessão do SIGA seja encerrada por inatividade quando o robô fica muito tempo parado nessa tela aguardando os arquivos ficarem prontos.

## [2026-07-16] — Versão 1.7.5

### Corrigido
- **Avanço Desnecessário de Páginas na Central de Downloads:** Corrigido o problema onde o robô continuava avançando pelas páginas da Central de Downloads na varredura final (`full_scan=True`) mesmo depois de já ter localizado todos os arquivos do lote. Como a tabela é ordenada da solicitação mais recente para a mais antiga, essa varredura excedente não gerava nenhum ganho e causava lentidão excessiva e expiração de sessão.

## [2026-07-16] — Versão 1.7.4

### Adicionado
- **Log individual para arquivos da Central de Downloads:** Agora a automação informa explicitamente no console e no log (ex: *"Arquivo localizado na Central: Malha Fiscal (CNPJ: 123...)"*) para cada arquivo de relatório detectado com sucesso na Central de Downloads, antes mesmo do processo físico de download iniciar. Isso fornece muito mais visibilidade do progresso de espera para o operador.

## [2026-07-16] — Versão 1.7.3

### Alterado
- **Governança do Instalador:** A regra de atualização obrigatória do instalador Inno Setup (`siga-automacao.iss`) juntamente com o lançamento de uma nova versão foi documentada no `CLAUDE.md` e em regras globais (`GEMINI.md`). Além de atualizar a variável `MyAppVersion`, o arquivo executável final gerado pelo instalador foi padronizado para usar o formato dinâmico `OutputBaseFilename=Setup {#MyAppVersion}`, gerando arquivos nomeados como `Setup <versão>.exe`. A versão atual no `.iss` foi sincronizada com a base (1.7.2/1.7.3).

## [2026-07-16] — Versão 1.7.2

### Melhorado
- **Corte por Timestamp na Central de Downloads (~90% mais rápido por ciclo):** `_scan_downloads_table_once` e `_scan_downloads_current_page_for_targets` em `src/extraction/siga_extractor.py` passam a usar um corte por timestamp nas varreduras intermediárias (`full_scan=False`). Como a Central de Downloads é ordenada por data de solicitação decrescente (mais recente primeiro), ao detectar uma linha com data anterior ao início do lote atual (com 60s de margem), a paginação é interrompida imediatamente — os arquivos do lote atual estarão sempre nas páginas iniciais. Redução estimada de **~90% no número de páginas varridas por ciclo** e **~51% no tempo total** da fase de downloads, especialmente em históricos grandes. A varredura final (`full_scan=True`), executada uma única vez ao confirmar que todos os arquivos estão prontos, continua percorrendo tudo para garantir resolução de duplicatas históricas.

## [2026-07-16] — Versão 1.7.1

### Alterado
- **Consolidação do Ponto de Entrada:** `main_gui.py` foi excluído e sua lógica de inicialização (injeção de `--skip-certificate-policy` para não bloquear a abertura da interface gráfica) foi incorporada diretamente em `main.py`. O projeto agora possui um único ponto de entrada que inicia a GUI automaticamente.

### Removido
- **`main_gui.py`:** Arquivo excluído da raiz do projeto. `main.py` é agora o único ponto de entrada.

## [2026-07-16] — Versão 1.7.0

### Removido
- **Modo de Lote via Terminal (CLI) Descontinuado:** o produto passa a ser exclusivamente GUI. Removidos de `src/main.py`: `run_interactive_terminal`, `_prompt_months`, `_prompt_year`, `_prompt_spreadsheet`, `_prompt_document_tabs`, `_print_batch_summary`, `_normalize_selected_months`, `_normalize_selected_tabs`, `DOCUMENT_TAB_OPTIONS`, e o argumento `--docs`. O flag `--gui` também foi removido — a GUI passa a ser o destino padrão de `main()` sempre que nenhum outro modo (assistido/limpeza de política) é selecionado, então `python main.py` (sem argumentos) já abre a interface gráfica diretamente. Removido também o build `siga-automacao.spec` (console CLI), cujo único propósito era esse modo — o instalador já só empacotava `siga-automacao-gui.exe`. `README.md`, `PRD.md` e `CLAUDE.md` atualizados para refletir o produto GUI-only. Mantidos: `--live-assist`/`--live-command` (ferramenta de depuração interna, não é um modo de extração do usuário final) e `--clear-certificate-policy`/`--keep-certificate-policy` (utilitários de linha de comando independentes do modo de extração).

## [2026-07-16] — Versão 1.6.0

### Adicionado
- **Canal de Narração Amigável ("Digitando o CNPJ...", "Clicando em...", "Baixando..."):** Novo módulo `src/utils/narration.py` introduz um canal de log separado do técnico, dedicado a narrar as ações da automação em português simples para o operador (equipe contábil, não técnica). Funções `narrate`/`narrate_success`/`narrate_warning`/`narrate_error`, com logger próprio (`siga.narracao`, `propagate=False`) que nunca se mistura com o log técnico existente (`run.log`/`errors.log`, que continuam intactos, com todo o detalhe de XPath/seletor preservado para diagnóstico de mudanças de layout do SIGA). A narração é gravada em `logs/atividades.log` e, na CLI, também aparece diretamente no terminal (sem prefixo técnico).
- **Console da GUI Simplificado:** `QueueLogHandler` em `src/gui.py` foi reescrito para trabalhar com duas fontes: o canal de narração (nível INFO, mostrado com um horário curto `HH:MM:SS` e cor por tom) e uma "rede de segurança" técnica (root logger, nível WARNING+, para que nenhum erro real fique invisível mesmo em pontos ainda não narrados explicitamente — erros de nível ERROR ganham um aviso "mais detalhes em logs\errors.log"). A varredura por palavra-chave que antes tentava adivinhar a cor da linha (`_append_text`) foi removida — a cor agora vem explicitamente da origem do registro.
- Instrumentados ~26 pontos de ação ao longo do fluxo principal com narração amigável: login, progresso por CNPJ do lote (início/não encontrado/nova tentativa/falha definitiva/resumo final), busca e abertura do contribuinte, cliques genéricos (`_click_xpath`/`_click_text_action`, que cobrem dezenas de botões/menus/abas), solicitação de Malha Fiscal/Débitos Fiscais/NF-e/NFC-e/CT-e, e todo o fluxo da Central de Downloads (abertura, ajuste de linhas por página, progresso por página, download concluído/repetição/não localizado).

### Alterado
- **Terminal da CLI sem Ruído Técnico:** em `src/utils/logging_setup.py`, o `stream_handler` (console) subiu de nível INFO para WARNING — a narração agora cobre o fluxo informativo do terminal, então deixar o log técnico solto no mesmo console só duplicaria a poluição que a narração existe para eliminar. WARNING/ERROR continuam aparecendo como rede de segurança. Em `src/main.py`, as linhas de status que eram `print()` (abertura de navegador, login confirmado, progresso por mês, resumo do lote) passaram a usar o canal de narração, unificando o texto que também aparece na GUI; os menus/prompts interativos (seleção de mês, ano, planilha, certificado) continuam como `print()`, por não serem narração de ação automatizada.

## [2026-07-16] — Versão 1.5.6

### Adicionado
- **Log de Progresso na Varredura da Central de Downloads:** `_scan_downloads_table_once` em `src/extraction/siga_extractor.py` agora registra uma linha de log a cada página varrida (com a contagem de solicitações já localizadas) e um resumo ao final. Antes, uma varredura de muitas linhas podia ficar minutos em silêncio total no log, indistinguível de um travamento — foi exatamente o que levou o usuário a encerrar manualmente um processo que na verdade ainda estava trabalhando.

### Corrigido
- **Timeout por Célula Reduzido na Varredura em Lote:** `_row_cell_texts` (mesmo arquivo) ganhou um parâmetro `cell_timeout_ms`, usado pela varredura em lote da Central de Downloads com um valor bem menor (400ms em vez do padrão de 2000ms). Uma linha obsoleta logo após um re-render grande da tabela (ex.: após a mudança de linhas por página da v1.5.4) fazia cada célula dela esperar o timeout inteiro antes de cair no fallback — em uma tabela com dezenas de linhas, isso somava minutos de espera. Os demais pontos do código que leem células de linha continuam com o timeout padrão de 2000ms (sem alteração de comportamento).

## [2026-07-16] — Versão 1.5.5

### Corrigido
- **`_find_elements` Podia Devolver `None` e Escapar dos Tratamentos de Erro:** `src/utils/selenium_compat.py` (`Page._find_elements` e `Page._descendants`) agora normaliza qualquer retorno `None` do Selenium para lista vazia. Em raros casos, quando o elemento raiz consultado está no meio de uma re-renderização do DOM (comum na SPA Angular do SIGA), o Selenium pode devolver `None` em vez de uma lista vazia — como `Error` (usado em quase todo `except` do projeto) é um apelido para `WebDriverException`, o `TypeError: 'NoneType' object is not iterable` resultante escapava sem tratamento, derrubando a extração inteira (reportado em produção: `_row_cell_texts` → `_scan_downloads_current_page_for_targets`, logo após a seleção de linhas por página da v1.5.4 aumentar a chance de pegar essa condição de corrida). Reforçado também em `_select_max_downloads_page_size` (`src/extraction/siga_extractor.py`), aumentando a espera após trocar o tamanho de página (500ms → 1.500ms) para dar mais tempo ao Angular de terminar de renderizar a tabela maior antes da varredura começar.

## [2026-07-16] — Versão 1.5.4

### Adicionado
- **Varredura Mais Rápida da Central de Downloads (Máximo de Linhas por Página):** Nova função `_select_max_downloads_page_size` em `src/extraction/siga_extractor.py` seleciona automaticamente a maior opção de "linhas por página" disponível no paginador da Central de Downloads (localizado via `[aria-label='Rows per page']`, com fallbacks por classe), reduzindo proporcionalmente o número de páginas a percorrer numa varredura (ex.: de 100 páginas de 10 linhas para 10 páginas de 100). A seleção é reaplicada automaticamente após cada `page.reload()` do fluxo de download em lote, já que o recarregamento da SPA reseta essa preferência para o padrão. Totalmente resiliente: se o seletor não for encontrado (mudança de layout do SIGA), a automação apenas registra aviso e segue com o comportamento anterior, sem quebrar.

## [2026-07-16] — Versão 1.5.3

### Corrigido
- **Falha de Paginação na Central de Downloads Não Derruba Mais o Lote Inteiro:** `_download_found_pending_requests` em `src/extraction/siga_extractor.py` levantava uma exceção não tratada quando não conseguia avançar para a próxima página da Central de Downloads no meio de um lote (diagnosticado a partir de uma execução real: `logs/run.log`, 2026-07-15 16:27), abortando toda a extração e descartando downloads já concluídos com sucesso. Agora, uma nova função `_advance_to_next_downloads_page_with_retry` tenta uma recuperação (recarregar a página e reavançar até a posição esperada) antes de desistir; se mesmo assim não for possível prosseguir, `_mark_unreached_download_pages_as_unavailable` marca apenas os itens das páginas ainda não alcançadas como "Erro: Falha ao navegar na Central de Downloads" (gerando o aviso `.txt` e o status na planilha), e o lote é encerrado de forma graciosa em vez de travar com uma mensagem de erro genérica na GUI.

## [2026-07-15] — Versão 1.5.2

### Adicionado
- **Re-enfileiramento de CNPJs Fiel a Falhas Temporárias:** O laço de orquestração do lote `_run_batch_from_spreadsheet_in_context` em `src/extraction/siga_extractor.py` foi convertido em uma fila dinâmica (`while queue:`). Se a abertura de um contribuinte falhar por erros de rede, navegador ou página em branco (exceto quando explicitamente não encontrado), o CNPJ é recolocado no final da lista para processamento posterior. Limitado a no máximo 2 re-enfileiramentos por linha (3 tentativas no total) para evitar loops infinitos, maximizando as chances de obter 100% de sucesso da planilha.

## [2026-07-15] — Versão 1.5.1

### Corrigido
- **Recuperação de Página em Branco Entre Retentativas:** Em `_open_taxpayer_from_home` (`src/extraction/siga_extractor.py`), após qualquer falha de navegador (`TimeoutError`/`Error`), a automação agora inspeciona o estado da página com `SigaPageInspector.inspect()` antes de aguardar e retentar. Se a página estiver em estado de recuperação necessária (`empty-app-root`, `missing-app-root`, `nearly-empty-body`), chama `stabilize_after_navigation` imediatamente — garantindo que cada nova tentativa comece com uma interface válida e evitando que uma tela inutilizável consuma retentativas desnecessárias.

## [2026-07-15] — Versão 1.5.0

### Corrigido
- **Resiliência contra Página em Branco:** `_wait_for_taxpayer_list_ready` em `src/extraction/siga_extractor.py` agora levanta `TimeoutError` em vez de retornar `False` silenciosamente se a página permanecer completamente vazia ou sem renderizar a estrutura básica ao fim do tempo de espera. Isso aciona o ciclo automático de retentativas para recarregar a página e tentar novamente.
- **Retentativas de Busca de Contribuinte:** A rotina `_open_taxpayer_from_home` foi atualizada para capturar `TaxpayerNotFoundError` e realizar até 3 tentativas de busca antes de propagar o erro definitivamente. Isso evita falsos-negativos (como falhas causadas por lentidão de rede na transição de busca) e garante que o CNPJ de fallback da Central de Downloads seja aberto com sucesso.

## [2026-07-15] — Versão 1.4.9

### Adicionado
- **Validação Prévia de CNPJ/CGF:** Nova função `_is_likely_valid_document` em `src/extraction/spreadsheet.py` que rejeita documentos com comprimento diferente de 14 caracteres ou sequências puramente numéricas com todos os dígitos iguais (ex: `00000000000000`, `11111111111111`), emitindo aviso explícito no log antes de tentar a busca no SIGA — evita que o robô gaste até 30 segundos por CNPJ obviamente malformado.
- **Verificação de PID Após Encerramento do Navegador:** Nova função `_wait_for_pids_to_exit` em `src/utils/browser.py` que, após o `taskkill`, verifica via PowerShell se os processos do navegador realmente terminaram (não apenas se a porta CDP fechou). Registra `WARNING` se o processo ainda existir após o timeout — detecta processos zumbi que fecharam o listener sem de fato encerrar.
- **Seletores Semânticos para Toggle do Menu Lateral:** `_ensure_side_menu_open` em `src/extraction/siga_extractor.py` agora tenta três seletores em ordem de robustez — atributo ARIA, componente Angular e, como último fallback, o XPath posicional anterior. Quando o fallback posicional for necessário, registra `WARNING` indicando possível mudança de layout no SIGA.

### Alterado
- **Deduplicação da Lógica de Cabeçalho da Planilha:** Aliases de cabeçalho (`_REQUIRED_DOCUMENT_HEADERS`, `_COD_HEADERS`, `_COMPANY_HEADERS`) extraídos para constantes de módulo em `src/extraction/spreadsheet.py`; nova função `_scan_header_row` compartilhada entre leitura (`load_cnpjs_from_xlsx`) e escrita de status (`_build_status_header_map`), eliminando a reimplementação duplicada e garantindo que qualquer ajuste futuro de alias seja feito em um único lugar.
- **Botão Ajuda usa Caminho de Asset Consistente:** `_show_help_dialog` em `src/gui.py` substituiu `os.path.abspath("manual_instrucoes.html")` (relativo ao CWD) por `self._resolve_asset_path("manual_instrucoes.html")`, que funciona corretamente tanto no desenvolvimento quanto no executável PyInstaller independentemente do diretório de trabalho atual.
- **Aviso de Limite Atingido em `_find_row_by_digits`:** Quando o loop de varredura atinge o limite de `max_candidates` sem encontrar o alvo em `src/extraction/siga_extractor.py`, registra `WARNING` explícito com o total real de linhas na página — facilita o diagnóstico em tabelas que cresceram além do limite padrão de 80 candidatos.

## [2026-07-15] — Versão 1.4.8

### Alterado
- **Varredura Mais Eficiente da Central de Downloads:** `_scan_downloads_table_once` em `src/extraction/siga_extractor.py` passou a parar de paginar assim que todas as solicitações do lote são localizadas (concluídas ou em processamento) nas varreduras intermediárias do laço de espera, evitando reler páginas finais irrelevantes a cada ciclo — o que degradava de forma aproximadamente quadrática em lotes grandes (muitas linhas × muitas abas). Isso é seguro porque, como todas as solicitações são feitas antes de abrir a tela, a paginação permanece estável durante a espera (nenhuma linha nova aparece; apenas o status muda de "processando" para "concluído" no mesmo lugar). Para preservar integralmente a resolução de duplicatas independentemente da ordenação da tela, uma varredura completa (`full_scan=True`, sem parada antecipada) é sempre executada antes de retornar o resultado final. Nenhuma mudança no resultado esperado — apenas menos leituras de página durante a espera.

## [2026-07-15] — Versão 1.4.7

### Adicionado
- **Planilha de Resultados para Entrada Manual de CNPJ:** A GUI agora gera uma planilha de resultados (`resultados_manual_<timestamp>.xlsx`) também para CNPJs digitados manualmente (`build_manual_entry_workbook` em `src/extraction/spreadsheet.py`), mantendo o mesmo rastro de status em tempo real que já existia para o fluxo de importação por planilha.

### Corrigido
- **Matching de Documento por Igualdade Exata:** `_row_matches_taxpayer_document` em `src/extraction/siga_extractor.py` deixou de aceitar correspondência por prefixo (`startswith`), que podia atribuir um número mais longo (ex.: um processo interno da SEFAZ que começa com os mesmos dígitos) ao contribuinte errado.
- **Prevenção de Vazamento de Processo do Navegador:** `BrowserSession.__enter__` em `src/utils/browser.py` passou a fechar explicitamente o driver/contexto já criado quando uma etapa posterior falha, já que o protocolo de context manager não aciona `__exit__` se `__enter__` não retornar.
- **Localização do Navegador em Instalações Não Padrão:** `resolve_browser_executable` em `src/utils/browser.py` agora usa `shutil.which` como fallback quando o Chrome/Edge não está nos caminhos fixos do Program Files.
- **Sem Reuso de Linha da Central de Downloads entre Solicitações:** `_scan_downloads_current_page_for_targets` em `src/extraction/siga_extractor.py` passou a controlar as linhas já reivindicadas nesta passada de varredura, impedindo que duas solicitações com títulos parecidos (mesmo mês/ano/aba) acabem usando a mesma linha e dupliquem o arquivo em pastas diferentes.
- **Falha Explícita sem Terminal Interativo:** `wait_for_manual_login` em `src/auth/siga_login.py` agora verifica `sys.stdin.isatty()` antes do `input()` bloqueante, levantando um erro claro em vez de travar/lançar exceção obscura quando não há console interativo disponível.

## [2026-07-15] — Versão 1.4.6

### Alterado
- **Seleção de Certificado com Confirmação do Operador:** `configure_auto_certificate_selection` em `src/utils/certificate_policy.py` deixou de escolher silenciosamente o certificado de maior validade quando há mais de um certificado de autenticação elegível. Agora, com apenas um certificado, a aplicação continua automática; com vários, a escolha é solicitada ao operador no terminal (`_prompt_certificate_choice` em `src/main.py`), exibindo CN e validade de cada opção. Sem terminal interativo ou se o operador cancelar, a política não é aplicada e o navegador exibe o prompt padrão de certificado, evitando o risco de usar o certificado (CNPJ) de outra empresa.
- **Abertura do Navegador sem Congelar a Interface (GUI):** `_start_browser_if_needed` em `src/gui.py` passou a iniciar o navegador em uma thread de trabalho, atualizando a interface via `root.after`. Antes, a espera pela disponibilidade do CDP (até 15s) rodava na thread principal do Tkinter, deixando a janela "Não respondendo".
- **Fechamento Seguro da GUI Durante uma Execução:** `_on_close` em `src/gui.py` passou a detectar execuções em andamento e pedir confirmação antes de sair. Ao confirmar, sinaliza o encerramento (`_closing`/`_stop_requested`), encerra o navegador da automação para liberar a thread de trabalho e aguarda seu término com timeout antes de destruir a janela. As atualizações de interface disparadas por threads passaram a usar um agendador protegido (`_ui_after`), eliminando exceções `TclError` quando a janela é fechada durante o processamento.

## [2026-07-15] — Versão 1.4.5

### Adicionado
- **Flag `--keep-certificate-policy`:** Nova opção de linha de comando para manter a política de seleção automática de certificado ativa após o fim da execução (comportamento anterior). Por padrão, a política agora é removida automaticamente ao final de cada execução.

### Corrigido
- **Remoção Automática da Política de Certificado:** `main()` em `src/main.py` passou a aplicar a política de seleção automática de certificado dentro de um bloco `try/finally`, removendo-a ao final da execução (sucesso ou erro). Antes, a política gravada em `HKCU` permanecia ativa indefinidamente no navegador do usuário, mesmo fora da automação, até que `--clear-certificate-policy` fosse executado manualmente.

### Alterado
- **Escrita de Status em Lote sem Reabertura Repetida da Planilha:** `write_status_to_spreadsheet_cell` em `src/extraction/spreadsheet.py` deixou de reabrir e reescanear o cabeçalho da planilha de resultados a cada célula gravada. O workbook agora é mantido em cache (por caminho de planilha) durante todo o lote — `close_status_workbook` libera o arquivo ao final de `run_batch_from_spreadsheet_in_context` — reduzindo custo de I/O repetido e risco de colisão com o arquivo aberto no Excel. A gravação em tempo real (uma escrita em disco por atualização de status) foi preservada. Como efeito colateral, uma coluna de aba fiscal não encontrada na planilha agora gera aviso explícito no log em vez de falhar silenciosamente.
- **Remoção de Código Morto no Extrator:** Removidas do `src/extraction/siga_extractor.py` as funções não referenciadas em nenhum ponto do código (`_extract_download_match_fragments`, `_download_row_matches_taxpayer`, `_document_key`, `_find_latest_download_row`, `_click_xlsx_detail_download_button`, `_find_xlsx_detail_download_button`, `_return_from_detail_to_fiscal_menu`, `_is_zero_cnpj_base_row`, `_row_cnpj_base_key`), remanescentes de refatorações anteriores do fluxo de correspondência de downloads. Nenhum comportamento em produção foi alterado — os fluxos ativos usam as funções equivalentes já em uso (`_extract_download_match_fragments_from_title`, `_row_matches_download_target`, `_row_matches_taxpayer_document`).

## [2026-07-15] — Versão 1.4.4

### Corrigido
- **Correspondência Exata vs. Aproximada na Central de Downloads:** Corrigido `_row_matches_download_target` em `src/extraction/siga_extractor.py`, onde os dois ramos da checagem `exact_only` executavam a mesma lógica, anulando o desempate por pontuação (`_download_match_score`) entre relatórios pendentes com títulos parecidos no mesmo mês/aba. Agora uma correspondência só é tratada como exata quando o título completo bate literalmente com a linha da Central de Downloads.
- **Gravação de Status Resiliente a Planilha Aberta no Excel:** `write_status_to_spreadsheet_cell` em `src/extraction/spreadsheet.py` passou a tratar `PermissionError`/`OSError` ao abrir ou salvar a planilha de resultados, registrando aviso no log em vez de abortar o lote inteiro quando o arquivo `_resultados.xlsx` está aberto no Excel.
- **Resiliência a Erros Inesperados na Abertura do Contribuinte:** `run_batch_from_spreadsheet_in_context` em `src/extraction/siga_extractor.py` passou a capturar também exceções genéricas (além de `TaxpayerNotFoundError`) ao abrir cada contribuinte, registrando o erro na planilha de resultados e seguindo para o próximo CNPJ, em vez de abortar o lote e descartar downloads já solicitados no SIGA para as linhas anteriores.
- **Encerramento Seguro de Processos do Navegador:** `terminate_browser_processes` em `src/utils/browser.py` deixou de encerrar indiscriminadamente todos os processos `chrome.exe`/`msedge.exe` da máquina. Agora identifica, via PowerShell, apenas os processos cuja linha de comando referencia o perfil de depuração da automação, preservando janelas pessoais do usuário. Quando o perfil do sistema está em uso (`--system-browser-profile`), o encerramento forçado é ignorado por segurança.

## [2026-07-14] — Versão 1.4.3

### Corrigido
- **Resiliência a Overlays e Bloqueios:** Implementada a rotina de espera automática por elementos de carregamento (loaders, spinners e overlays do PrimeNG) na interface do SIGA, prevenindo que cliques e digitações sejam perdidos pela automação.
- **Detecção Eficiente de Erros de Busca:** Expandido o mapeamento de mensagens de "registro não encontrado" (como "não foram localizados", "sem registros", etc.) e inserida a detecção de tabelas vazias instantâneas, evitando a perda de 30 segundos de timeout para CNPJs sem cadastro.

## [2026-07-13] — Geração de Binários (Versão 1.4.2)

### Adicionado
- **Distribuição Atualizada:** Compilação de novo executável autônomo (`siga-automacao-gui.exe`) e empacotamento do instalador atualizado (`SIGA-Automacao-Setup.exe`) via Inno Setup, contendo todas as alterações de correções de CNPJ e suporte alfanumérico da versão 1.4.2.

## [2026-07-07] — Versão 1.4.2

### Alterado
- **Busca por CNPJ Completo:** Alterada a correspondência da Central de Downloads para buscar pelo CNPJ inteiro de 14 caracteres em vez de apenas os 8 primeiros dígitos (CNPJ base), evitando que downloads de empresas filiais (com mesmo radical) se misturem e sejam salvos nas pastas umas das outras.
- **Suporte a CNPJ Alfanumérico:** Atualizada a lógica de higienização de CNPJs e documentos no extrator, no leitor de planilhas e na interface gráfica para reter tanto letras quanto números, adequando a ferramenta à nova regulamentação de CNPJ alfanumérico.

## [2026-07-02] — Versão 1.4.1

### Adicionado
- **Manual de Ajuda em HTML:** Criação da página `manual_instrucoes.html` contendo regras e instruções completas para manuseio da ferramenta pela equipe da Barreira & Associados.
- **Abertura do Manual na GUI:** O botão "Ajuda" do Tkinter foi integrado para abrir o manual local em HTML diretamente no navegador padrão do usuário via biblioteca padrão `webbrowser`.

### Alterado
- **Gravação de Logs em Tempo Real:** A gravação na planilha Excel foi reestruturada para ocorrer em tempo real (célula a célula), registrando imediatamente data/hora de downloads concluídos ou descrições de erros de solicitações/downloads/empresas não encontradas.
- **Resiliência do Lote de Downloads:** O processamento e download físico de arquivos na Central de Downloads foi isolado por bloco try-except individual. Erros de timeout ou falhas em um arquivo são registrados no Excel correspondente, mas não interrompem o restante da extração das outras empresas do lote.
- **Preservação do Excel Original (Cópia de Resultados):** A planilha de entrada importada pelo usuário é mantida 100% inalterada. A ferramenta cria automaticamente uma cópia chamada `[Nome da Planilha]_resultados.xlsx` no mesmo diretório de origem e realiza todas as gravações e logs nela.
- **Preenchimento Automático da Pasta de Saída:** Ao selecionar/importar uma planilha de CNPJs na GUI, a pasta de saída é automaticamente preenchida com o diretório onde a planilha selecionada está localizada.

## [2026-07-01] — Versão 1.4.0

### Alterado
- **Motor de GUI (Reversão de PyWebView para Tkinter):** Remoção completa da biblioteca PyWebView, do HTML local e da ponte em Base64. A interface gráfica voltou a rodar inteiramente no motor nativo do **Tkinter/ttk**.
- **Aparência e Design System (DESIGN.md):** Aplicação de uma estilização completa na interface do Tkinter, definindo a paleta de cores (fundo geral `#f7f9ff`, sidebar `#0d1d2a`, botões em `#006e25` e outline `#bfcaba`) e escala tipográfica baseadas no protótipo de design.
- **Suporte a 5 Abas de Documentos:** A grade de empresas do Tkinter foi expandida para 7 colunas no total, integrando checkboxes individuais para seleção de **Malha Fiscal** e **Débitos Fiscais** na interface, mantendo paridade com as extrações suportadas pelo backend.
- **Diálogos de Sistema:** Retorno ao uso dos métodos `filedialog.askopenfilename` e `askdirectory` do Tkinter, eliminando travamentos de UI e a dependência de chamadas externas de PowerShell.
- **Otimização de Largura da Tabela e Console (Tkinter):** Redução dos espaçamentos da grade de checkboxes no `src/gui.py` de `712px` para `500px` (redimensionando colunas `COD`, `EMPRESA`, e as abas fiscais) e limitação do console de logs para largura inicial `width=40`. Isso resolve o problema de corte visual no grid, permitindo que todas as 5 colunas de checkboxes de extração fiquem integralmente visíveis e alinhadas na tela.
- **Pasta de Saída em Branco por Padrão:** Ajuste da inicialização da variável `output_dir_var` no `src/gui.py` para começar vazia (`""`), forçando o usuário a selecionar explicitamente a pasta de destino antes de iniciar as extrações.

### Corrigido
- **Parâmetro de Referência de Mês:** Correção das chamadas a `_build_pending_request` nos métodos `_request_malha_fiscal` e `_request_debitos_fiscais` do `src/extraction/siga_extractor.py`, repassando corretamente o argumento nomeado `month_reference`. Isso sana o `TypeError` e garante o download correto dos arquivos correspondentes na Central de Downloads.
- **Conflito de Tipo de Data (TypeError):** Correção do tipo de dados da data de solicitação (`requested_after`) nas abas de Malha Fiscal e Débitos Fiscais no `src/extraction/siga_extractor.py`, alterando de float timestamp (`_time.time()`) para objeto `datetime.datetime`. Isso resolve o `TypeError` durante o escaneamento da Central de Downloads e restabelece o fluxo de download.
- **Confusão de Download (Malha vs Débitos Fiscais):** Aplicação da função `strip_accents` sobre o título de download normalizado no método `_extract_download_match_fragments_from_title` do `src/extraction/siga_extractor.py`. Isso resolve o problema de correspondência causado pela acentuação de "Débitos Fiscais" e impede que o robô confunda e duplique o download do relatório de Malha Fiscal.

### Removido
- Pasta `src/gui/` com arquivos legados `gui.html` e `gui_webview.py`.

## [2026-07-01] — Versão 1.3.2

### Adicionado
- **Interface Drag and Drop (HTML5):** A dependência de diálogos nativos do Windows (PowerShell/WinForms) para seleção de planilhas foi integralmente substituída por uma área de Arrastar e Soltar na GUI.
- **Leitura via Base64:** O JavaScript nativo agora intercepta o arquivo solto ou selecionado, converte a planilha para Base64 usando `FileReader` e a envia de forma segura à API Python, eliminando qualquer risco de travamento de UI ou bloqueios de permissão do sistema operacional.

## [2026-07-01] — Versão 1.3.1

### Corrigido
- Arquivos:
  - `src/gui/gui_webview.py`
- Motivo: os diálogos nativos do Windows (`OpenFileDialog` e `FolderBrowserDialog`) falhavam silenciosamente porque o PowerShell estava sendo instanciado em modo Multi-Threaded Apartment (MTA). Componentes WinForms requerem execução em Single-Threaded Apartment (STA).
- Impacto: adicionada a flag `-STA` e as chamadas do subprocesso foram alteradas para o formato de lista segura. As janelas de seleção de arquivo e diretório voltam a abrir corretamente.

### Alterado
- Arquivos:
  - `src/gui/gui.html`
- Motivo: reposicionamento do botão "Importar Planilha" que ficava preso junto ao cabeçalho da grade, ocupando espaço indevido e gerando alertas excessivos na tela.
- Impacto: o botão foi desmembrado para um card elegante e centralizado acima da tabela, deixando a grade mais limpa e focada exclusivamente na exibição dos CNPJs.

## [2026-07-01] — Versão 1.3.0

### Adicionado
- **Interface Baseada em Webview (HTML5/Tailwind/JS):** A interface anterior desenvolvida em Tkinter foi inteiramente removida e substituída por uma tela desktop web view moderna, implementada através do **PyWebView**.
  - O design visual foi migrado a partir do protótipo `design/code.html` (Stitch).
  - A barra lateral de configurações conta com seletores integrados de Mês (iniciando com o mês atual por padrão), Ano (ano atual por padrão) e caixas de marcação globais (todas iniciando desmarcadas).
  - A sidebar pode ser redimensionada dinamicamente pelo usuário (entre 200px e 450px) arrastando o divisor lateral, ajustando automaticamente o alinhamento esquerdo da grade e do console inferior.
  - A grade principal foi otimizada para carregar dinamicamente os CNPJs, códigos internos e empresas da planilha.
  - O console inferior agora exibe em tempo real o fluxo de logs do Python (`INFO`, `WARNING`, `SUCCESS`, `ERROR`) com formatação e cores adequadas, facilitando o diagnóstico visual pelo usuário.

### Alterado
- Arquivos:
  - `src/main.py`
  - `src/__init__.py`
  - `siga-automacao-gui.spec`
  - `installer/siga-automacao.iss`
- **Ponte de Dados (Bridge):** Comunicação bidirecional implementada no arquivo `src/gui/gui_webview.py` através do objeto exposto `js_api` do `pywebview`, permitindo a coleta das configurações, seleção e a injeção dinâmica de registros.
- **Diálogos Nativos do SO:** Substituição das janelas de diálogo de arquivos e pastas do Tkinter pelas funções nativas do PyWebView (`window.create_file_dialog`).
- **Execução Assíncrona:** A extração agora ocorre em uma Thread secundária no backend, mantendo a responsividade do HTML e a animação do console sem travamento.

### Removido
- Arquivo `src/gui.py` (antiga interface gráfica em Tkinter).

## [2026-07-01] — Versão 1.2.0

### Adicionado
- **Malha Fiscal:** nova aba de extração que navega até o menu "Malha Fiscal" no portal SIGA/SEFAZ-CE, solicita o download dos indícios de irregularidades em XLSX e aguarda a confirmação de solicitação antes de resgatar o arquivo na Central de Downloads.
- **Débitos Fiscais:** nova aba de extração que navega até o menu "Débitos Fiscais", solicita o download em XLSX e segue o mesmo fluxo de espera e resgate da Central de Downloads.
- Ambas as abas foram integradas à GUI (checkboxes na barra lateral + colunas "Malha" e "Débitos" na grade de CNPJs) e ao CLI (opções `4` e `5` no prompt interativo e suporte via `--docs`).

### Alterado
- Arquivos:
  - `src/__init__.py`
  - `installer/siga-automacao.iss`
  - `src/gui.py`
  - `src/main.py`
  - `src/extraction/siga_extractor.py`
- Motivo: adição das novas abas de extração fiscal especial (Malha Fiscal e Débitos Fiscais) à GUI, ao CLI e ao motor de extração.
- Impacto:
  - `DOCUMENT_TABS` e `DOCUMENT_TAB_OPTIONS` expandidos de 3 para 5 opções.
  - `RowSelectionWidgets` recebeu dois novos campos `malha_var` e `debitos_var`.
  - Grade de CNPJs expandida de 5 para 7 colunas.
  - `_normalize_selected_tabs` agora reconhece as abas especiais sem exigir `FiscalTabConfig`.
  - `_extract_fiscal_tables` despacha as abas especiais para `_request_malha_fiscal` e `_request_debitos_fiscais` antes do loop padrão.
  - `_extract_download_match_fragments_from_title` e `_row_contains_signature_fragments` atualizados para reconhecer os títulos de Malha Fiscal e Débitos Fiscais na Central de Downloads.
  - Versão de lançamento incrementada para `1.2.0`.

## [2026-06-23] — Versão 1.1.2

### Alterado
- Arquivos:
  - `README.md`
- Motivo: adequação do arquivo às diretrizes corporativas de governança e proteção intelectual.
- Impacto: reescrita completa da documentação com foco puramente comercial e institucional da Barreira & Associados, com a total eliminação de termos e instruções técnicas que pudessem comprometer a segurança.

- Arquivos:
  - `src/__init__.py`
  - `installer/siga-automacao.iss`
- Motivo: incremento do número da versão de distribuição e do instalador.
- Impacto: atualização da versão de lançamento do patch para `1.1.2`.

## [2026-06-23] — Versão 1.1.1

### Alterado
- Arquivos:
  - `src/gui.py`
  - `src/__init__.py`
  - `installer/siga-automacao.iss`
- Motivo: alinhamento integral da interface gráfica ao `DESIGN.md` (SIGA Design System).
- Impacto:
  - **Paleta de cores:** Success Green ajustado para `#006e25` (cor secundária oficial); Warning/Action Orange `#e97000` adicionado para alertas e avisos; cor de desabilitado do botão de execução alterada para cinza suave `#c5ddc9`.
  - **Tipografia:** fontes Inter (UI geral) e JetBrains Mono (terminal de logs) configuradas conforme os tokens `body-md`, `title-sm`, `label-caps` e `console-code` do design system.
  - **Espaçamento e layout:** largura da sidebar reduzida de 300px para 240px (`sidebar-width` do design system); paddings padronizados com múltiplos de 4px.
  - **Bordas suaves:** cards e área de entrada de texto receberam bordas de 1px na cor `#c5c6ce` (`outline-variant`) via `tk.Frame` wrapper, eliminando as bordas grossas do tema `clam`.
  - **Separadores visuais:** linhas divisórias de 1px em `#c5c6ce` inseridas entre a topbar e o corpo da aplicação, e entre o corpo e o rodapé.
  - **Zebra striping:** listagem de CNPJs passou a alternar fundos brancos e `#f3f4f5` (surface_low) para melhorar a legibilidade de lotes longos.
  - **Console colorido (Rich Log):** o painel de log agora aplica cores automaticamente por nível: branco (info), verde `#6db33f` (sucesso/conclusão), laranja `#e97000` (aviso/não encontrado), vermelho `#f14c4c` (erro/falha).
  - **Notebook sem bordas:** abas "Importar Planilha" e "Entrada Manual" com visual mais limpo sem borda preta padrão do ttk.
  - **Botões refinados:** botões Primary, Success, Ghost, Action e Danger sem bordas pretas ásperas; hover states suavizados.


### Alterado
- Arquivos:
  - README.md
- Motivo: deixar a apresentação do produto mais comercial, clara e orientada a adoção por equipes contábeis e fiscais.
- Impacto: a documentação passou a comunicar melhor a proposta de valor, os diferenciais e os pontos de execução/distribuição.

### Corrigido
- Arquivos:
  - installer/siga-automacao.iss
- Motivo: os atalhos instalados podiam ficar sem o icone correto em algumas instalacoes do Windows.
- Impacto: o instalador passa a copiar o arquivo `.ico` junto com a aplicacao e os atalhos do desktop/menu Iniciar usam esse recurso instalado como fonte do icone, reduzindo a dependencia do cache do sistema.

### Corrigido
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: o acesso a `Downloads Assincronos` ainda dependia do ultimo CNPJ da fila ter sido localizado, o que quebrava o lote quando a ultima pesquisa retornava vazio.
- Impacto: a automacao agora identifica o estado atual da pagina, reutiliza o ultimo CNPJ aberto com sucesso como fallback de navegacao e continua o fluxo de downloads mesmo se a ultima empresa nao for encontrada.

### Corrigido
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: uma chamada do fluxo de detalhamento por relatórios ainda usava a assinatura antiga de `_build_pending_request()` e não repassava `taxpayer_folder_name`.
- Impacto: a automação deixa de falhar com `TypeError` logo após solicitar o detalhamento e volta a montar corretamente os downloads pendentes com a pasta `COD - EMPRESA - CNPJ`.

### Alterado
- Arquivos:
  - src/gui.py
- Motivo: simplificar a lateral da interface removendo o botão `Padrão` e padronizar o texto da área de saída para `Pasta de Saída`.
- Impacto: a sidebar ficou mais limpa e a nomenclatura visual da aplicação ficou mais direta para o usuário.

### Alterado
- Arquivos:
  - src/gui.py
  - siga-automacao-gui.spec
  - installer/siga-automacao.iss
- Motivo: compactar a grade para exibir NF-e, NFC-e e CT-e ao mesmo tempo, centralizar o título no topo e integrar os novos assets visuais ao executável e ao instalador.
- Impacto: a interface ficou mais equilibrada visualmente e o pacote gerado passa a carregar ícone e logo próprios.

### Alterado
- Arquivos:
  - src/gui.py
- Motivo: reduzir a logo do cabeçalho para proporção de identidade visual e reposicioná-la à esquerda, mantendo o título centralizado e a ação de ajuda à direita.
- Impacto: o topo da aplicação ganhou hierarquia visual mais profissional, sem competir com a área principal da interface.

### Alterado
- Arquivos:
  - src/gui.py
  - src/extraction/spreadsheet.py
  - src/extraction/siga_extractor.py
- Motivo: ajustar a interface para sugerir o mês anterior por padrão, manter o ano atual como referência, exibir `COD` e `EMPRESA` na listagem e organizar as pastas de saída com `COD - EMPRESA - CNPJ`.
- Impacto: a experiência inicial ficou mais automática e a estrutura de saída passou a refletir melhor os dados reais da planilha.

### Documentação
- Arquivos:
  - README.md
- Motivo: atualizar a descrição do fluxo de uso e do padrão de organização dos arquivos gerados.
- Impacto: a documentação ficou alinhada ao comportamento atual da aplicação.

## [2026-06-16]

### Alterado
- Arquivos:
  - src/gui.py
  - README.md
- Motivo: remover elementos visuais auxiliares que não faziam parte do fluxo principal e transformar o botão de ajuda em um guia prático para o usuário.
- Impacto: a interface ficou mais limpa e o usuário passa a receber instruções objetivas de uso diretamente na aplicação.

### Alterado
- Arquivos:
  - src/gui.py
  - README.md
  - PRD.md
- Motivo: o visual da interface foi alinhado ao `design-model`, com layout em três colunas, painel lateral de parâmetros, abas de entrada e console escuro à direita.
- Impacto: a GUI ficou mais próxima de um dashboard corporativo, com navegação mais clara e melhor separação entre configuração, entrada de CNPJs e acompanhamento da execução.

### Documentação
- Arquivos:
  - PRD.md
  - CHANGELOG.md
- Motivo: formalizar o produto em um documento de requisitos com escopo, objetivos, riscos e criterios de aceite.
- Impacto: facilita a manutencao, a evolucao do software e a comunicacao do valor do produto.

## [2026-06-12]

### Alterado
- Arquivos:
  - src/gui.py
  - src/extraction/spreadsheet.py
  - README.md
- Motivo: a interface passou a aceitar CNPJs informados manualmente, sem depender de planilha XLSX, mantendo o fluxo antigo como alternativa.
- Impacto: o usuario pode colar um ou varios CNPJs diretamente na GUI, carregar a lista na tela e executar a automacao normalmente.

### Alterado
- Arquivos:
  - src/extraction/siga_extractor.py
  - src/gui.py
- Motivo: a localizacao de contribuintes voltou a usar apenas a barra de pesquisa do SIGA, sem paginar a lista de CNPJs, e o lote passou a tratar CNPJ nao encontrado como aviso recuperavel.
- Impacto: quando um CNPJ como `04.419.796/0003-34` nao aparece na pesquisa, a automacao gera `CNPJ nao encontrado.txt`, segue para o proximo contribuinte e informa a contagem na GUI sem interromper o processamento.

## [2026-06-12]

### Corrigido
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: a leitura do mês de referência estava falhando em alguns CNPJs apesar da tabela já estar visível, causando interrupção precoce do lote.
- Impacto: a automação agora aguarda a tabela de indicadores ficar visível e tenta a leitura do mês com mais folga antes de desistir.

### Alterado
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: reorganizar o lote para solicitar primeiro os downloads de todos os CNPJs e abrir a Central de Downloads apenas uma vez no final.
- Impacto: o fluxo reduz alternâncias repetidas para a aba de Downloads e mantém o vínculo de cada arquivo com o CNPJ e o mês corretos durante o download em lote.

## [2026-06-11]

### Adicionado
- Arquivos:
  - dist/siga-automacao-gui.exe
- Motivo: gerar novamente o executável da GUI com a versão atual do projeto para uso na criação do instalador via Inno Setup.
- Impacto: a build da interface gráfica ficou atualizada com as correções mais recentes e pronta para empacotamento.

## [2026-06-10]

### Alterado
- Arquivos:
  - src/extraction/siga_extractor.py
  - src/live_assist.py
  - src/config.py
- Motivo: aumentar a tolerância do fluxo de download com timeout maior e uma nova tentativa automática, além de preservar a extensão real informada pelo arquivo baixado.
- Impacto: o processo ficou mais resiliente quando o SIGA demora para disparar o download e os arquivos finais passaram a manter a extensão coerente com o que o navegador informou.

## [2026-06-10]

### Alterado
- Arquivos:
  - src/extraction/siga_extractor.py
  - src/gui.py
  - src/main.py
  - src/utils/browser.py
  - src/utils/certificate_policy.py
  - src/utils/siga_page.py
  - src/live_assist.py
- Motivo: padronizar as mensagens exibidas no terminal e nos logs da execução para português, facilitando o acompanhamento do fluxo pelo usuário.
- Impacto: a saída da automação ficou mais clara para operação e diagnóstico, com logs e mensagens de console em português na maior parte do fluxo.

## [2026-06-10]

### Corrigido
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: o splitbutton do detalhamento podia ser localizado, mas o clique ainda podia atingir um elemento interno do texto em vez do botao principal.
- Impacto: o programa agora dispara o clique diretamente no `button` principal do `Baixar Tabela (XLSX)` por JavaScript quando o componente estiver pronto.

### Corrigido
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: a espera do detalhamento precisava reconhecer quando o splitbutton novo estava pronto de verdade, e nao apenas quando o texto aparecia.
- Impacto: o fluxo agora inspeciona o estado visual e funcional do botao `Baixar Tabela (XLSX)` antes de clicar, com log de progresso durante a espera.

### Corrigido
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: o detalhamento novo usa um splitbutton cujo botao principal precisa ficar visivel e habilitado antes do clique apos a selecao do mes ou do subitem.
- Impacto: o fluxo agora aguarda o botao `p-element p-splitbutton-defaultbutton p-button p-component ng-star-inserted` ficar clicavel antes de solicitar o `Baixar Tabela (XLSX)`.

### Corrigido
- Arquivos:
  - src/extraction/siga_extractor.py
  - src/gui.py
- Motivo: a busca da linha na Central de Downloads exigia correspondencia exata demais e podia falhar depois da varredura; a GUI ainda mascarava a falha original com um `NameError` no callback de erro.
- Impacto: a rotina de download agora aceita a melhor linha concluida compatível com os fragmentos da TELA/ABA, e a interface passa a exibir corretamente o erro real quando houver falha.

### Corrigido
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: a leitura do mes de referencia e o clique nos itens de detalhamento ficaram sensiveis ao layout novo do SIGA, especialmente antes do botao `Baixar Tabela (XLSX)`.
- Impacto: o fluxo agora usa fallback direto na tabela para localizar o mes e tenta clicar o relatorio e o botao XLSX com mais tolerancia ao DOM antes de desistir.

### Alterado
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: o fluxo de detalhamento passou a buscar explicitamente o botão `Baixar Tabela (XLSX)`, que agora representa a solicitação dos downloads assíncronos.
- Impacto: todos os detalhamentos passam a acionar o novo botão do layout atual, sem depender do rótulo antigo `Baixar Tabela`.

### Alterado
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: a Central de Downloads passou a montar a lista completa de TELA/ABA, varrer todas as paginas uma unica vez por ciclo e so depois baixar em lote os arquivos encontrados.
- Impacto: reduz a repaginacao repetitiva por item, prioriza o registro mais recente por data/hora e continua gerando `.txt` para o que nao for localizado.

### Corrigido
- Arquivos:
  - main_gui.py
- Motivo: a entrada dedicada da GUI estava herdando a configuração automática de certificado na inicialização, o que podia travar a abertura da interface ao consultar o PowerShell.
- Impacto: a GUI passa a iniciar com `--skip-certificate-policy`, evitando bloqueio logo na abertura; a política continua disponível no fluxo de terminal quando necessário.

### Alterado
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: o fluxo de extração passou a preparar todas as solicitações de NF-e, NFC-e e CT-e antes de abrir a Central de Downloads.
- Impacto: o sistema agora solicita primeiro todos os arquivos de uma linha de contribuinte e só depois executa o download em lote, reduzindo alternâncias desnecessárias entre as abas do SIGA.

### Corrigido
- Arquivos:
  - src/utils/browser.py
  - siga-automacao-gui.spec
  - siga-automacao.spec
- Motivo: o executável empacotado falhava ao resolver dinamicamente `selenium.webdriver.chrome.webdriver` durante a abertura da GUI.
- Impacto: a criação do WebDriver passou a usar imports explícitos e os specs passaram a incluir os módulos do driver do Chrome e do Edge, reduzindo risco de erro no instalador e na build.

### Alterado
- Arquivos:
  - src/gui.py
- Motivo: a barra de ações da GUI foi reorganizada para expor botões separados por documento, com marcação e desmarcação direta de NF-e, NFC-e e CT-e.
- Impacto: o usuario consegue controlar cada tipo de documento com mais clareza, sem depender apenas das seleções individuais da grade.

## [2026-06-09]

### Corrigido
- Arquivos:
  - LICENSE
- Motivo: ajuste da titularidade da licença proprietaria para `Barreira & Associados`, conforme a regra do projeto.
- Impacto: o repositório passa a exibir o proprietario correto no arquivo de licenciamento.

### Corrigido
- Arquivos:
  - src/utils/browser.py
  - siga-automacao-gui.spec
  - siga-automacao.spec
- Motivo: corrigido o erro de empacotamento que impedia a GUI de iniciar em outro computador por falha ao resolver `selenium.webdriver.chrome.options`.
- Impacto: o executavel passa a incluir os modulos de opcoes do Selenium e usa importacao direta para reduzir dependencia de carregamento dinamico.

## [2026-06-05]

### Corrigido
- Arquivos:
  - .gitignore
- Motivo: arquivos de log temporarios fora da pasta `logs/`, como `perf_after.log`, nao devem ficar no status do Git.
- Impacto: reduz ruido no repositorio e evita versionamento acidental de logs locais.

### Adicionado
- Arquivos:
  - main_gui.py
  - siga-automacao-gui.spec
- Motivo: criar uma build dedicada para a interface grafica, sem depender do parametro `--gui`.
- Impacto: o instalador pode distribuir um executavel especifico da GUI, mais simples para o usuario final.

### Corrigido
- Arquivos:
  - dist/siga-automacao-gui.exe
- Motivo: a build da GUI foi gerada com sucesso a partir do novo spec dedicado.
- Impacto: o instalador ja pode apontar para o binario grafico pronto para uso.

### Corrigido
- Arquivos:
  - installer/siga-automacao.iss
- Motivo: o instalador tentava criar atalho no desktop comum, o que pode falhar com `0x80070005` em instalacoes sem permissao elevada.
- Impacto: o atalho passa a ser criado no desktop do usuario (`{userdesktop}`), reduzindo risco de erro de acesso negado.

### Corrigido
- Arquivos:
  - installer/siga-automacao.iss
  - README.md
- Motivo: o instalador inicial apontava para o binario geral, mas a distribuicao desejada e a versao com GUI aberta por padrao.
- Impacto: os atalhos e a execucao pos-instalacao agora iniciam a interface grafica diretamente com `--gui`.

### Adicionado
- Arquivos:
  - installer/siga-automacao.iss
- Motivo: criar um script de instalador para o Inno Setup apontando para o executável do PyInstaller.
- Impacto: o projeto passa a ter um caminho padronizado para gerar um instalador Windows.

### Adicionado
- Arquivos:
  - dist/siga-automacao.exe
- Motivo: o executável Windows foi gerado com sucesso a partir do spec do PyInstaller.
- Impacto: a aplicação já pode ser distribuída e executada como `.exe` no Windows.

### Alterado
- Arquivos:
  - src/gui.py
- Motivo: a interface grafica passou a permitir a escolha da pasta de saida antes da execucao.
- Impacto: o usuario agora controla onde os downloads finais serao gravados sem depender do diretorio padrao `saida/`.

### Documentação
- Arquivos:
  - README.md
  - brain/2026-06-05-escolha-pasta-downloads.md
- Motivo: registrar o novo fluxo da GUI e a decisao tecnica de sincronizar a pasta escolhida com `Settings.output_dir`.
- Impacto: melhora a rastreabilidade da alteracao e facilita a consulta futura.

### Documentação
- Arquivos:
  - README.md
- Motivo: documentar o comando de build do PyInstaller e o caminho do executavel gerado.
- Impacto: facilita a reproducao do pacote Windows em novas maquinas.

### Documentação
- Arquivos:
  - README.md
  - brain/2026-06-05-inno-setup-installer.md
- Motivo: registrar como compilar o instalador com o Inno Setup e onde o `.exe` final será produzido.
- Impacto: melhora a rastreabilidade e reduz dúvidas no empacotamento.

## [2026-06-03]

### Corrigido
- Arquivos:
  - src/main.py
  - src/gui.py
- Motivo: a interface grafica ainda estava abrindo o navegador cedo demais.
- Impacto: a GUI agora abre sozinha e o navegador só inicia ao clicar em `Iniciar navegador`.

## [2026-06-03]

### Alterado
- Arquivos:
  - src/gui.py
- Motivo: separar a abertura do navegador da execução e exigir login manual antes de processar.
- Impacto: o usuário passa a controlar a etapa de autenticação por um botão próprio na interface.

### Documentação
- Arquivos:
  - README.md
- Motivo: documentar o fluxo de `Iniciar navegador` seguido de login manual e depois `Executar`.
- Impacto: reduz confusão no uso da GUI.

## [2026-06-03]

### Alterado
- Arquivos:
  - src/gui.py
- Motivo: alinhar melhor as colunas da lista de CNPJs na interface grafica.
- Impacto: a grade ficou mais legivel e estavel para selecao por linha.

## [2026-06-03]

### Adicionado
- Arquivos:
  - src/gui.py
- Motivo: criar uma interface gráfica para selecionar CNPJs e abas fiscais por item.
- Impacto: permite operação visual, sem depender do terminal para escolher o lote.

### Alterado
- Arquivos:
  - src/main.py
  - src/extraction/siga_extractor.py
- Motivo: integrar o novo modo `--gui` e permitir seleção de abas por CNPJ.
- Impacto: o backend passou a aceitar filtragem individual por contribuinte.

### Documentação
- Arquivos:
  - README.md
- Motivo: documentar o uso da interface gráfica.
- Impacto: facilita descoberta e adoção do novo modo.

## [2026-06-03]

### Alterado
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: abrir automaticamente o menu lateral quando ele estiver recolhido, evitando bloqueios ao acessar Informacoes Fiscais e Downloads.
- Impacto: reduz TimeoutError de navegacao quando o menu lateral esta fechado.

## [2026-06-03]

### Alterado
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: reduzir esperas fixas e tornar a varredura da Central de Downloads mais leve.
- Impacto: menor tempo gasto em cliques, abertura de seções e polling de arquivos assíncronos.

### Documentação
- Arquivos:
  - brain/2026-06-03-performance-download-optimization.md
- Motivo: registrar o plano de otimização e a medição antes/depois.
- Impacto: melhora a rastreabilidade da rodada de performance.

## [2026-06-03]

### Documentação
- Arquivos:
  - README.md
  - .gitignore
- Motivo: o projeto passou a documentar melhor a entrada `cnpj.xlsx`, a preservação de CNPJs com zero à esquerda e a referência de validação `testes.csv`.
- Impacto: reduz ambiguidade na configuração inicial e mantém a árvore local limpa sem ruídos desnecessários.

## [2026-06-03]

### Corrigido
- Arquivos:
  - src/extraction/spreadsheet.py
  - src/extraction/siga_extractor.py
- Motivo: a normalização de CNPJ estava removendo zeros à esquerda, o que quebrava casos como `02843131000166`.
- Impacto: a planilha agora preserva os 14 dígitos completos e a comparação com a fila do SIGA continua funcionando com a base `02843131`.

## [2026-06-03]

### Corrigido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: a extração de NFC-e/Emissor em Maio de 2026 passou a reencontrar a linha visível da fila de downloads e a clicar no item vivo do DOM antes de salvar o arquivo.
- Impacto: o CSV final `Informacoes Fiscais - NFC-e - Emissor - Detalhamento Maio de 2026.csv` agora fica byte a byte igual ao `testes.csv` de referência para o CNPJ de teste utilizado.

## [2026-06-03]

### Corrigido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: a seleção do download assíncrono deixou de aceitar filas antigas como fallback quando a solicitação nova ainda não apareceu.
- Impacto: reduz a chance de baixar um arquivo velho e salvar com o nome da execução atual.

## [2026-06-03]

### Corrigido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: a NFC-e deixou de acrescentar o sufixo `Autorizadas` no nome solicitado para download assíncrono.
- Impacto: o relatório passa a ser procurado e salvo como `Informacoes Fiscais - NFC-e - Emissor - Detalhamento Maio de 2026`, conforme pedido.

## [2026-06-03]

### Alterado
- Arquivo: src/extraction/siga_extractor.py
- Motivo: os downloads assíncronos voltaram a ser renomeados pelo padrão da TELA/ABA solicitada.
- Impacto: o nome final do arquivo passa a refletir a consulta esperada pela automação, independentemente do nome sugerido pelo navegador.

## [2026-06-03]

### Corrigido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: a abertura do mês de referência passou a tentar novamente quando a lista ainda não terminou de carregar.
- Impacto: reduz falhas intermitentes ao trocar de seção e procurar o mês `Maio` antes do DOM estabilizar.

## [2026-06-03]

### Alterado
- Arquivo: src/extraction/siga_extractor.py
- Motivo: os downloads assíncronos passaram a ser salvos com o `suggested_filename` original do SIGA em vez de um nome renomeado pela automação.
- Impacto: reduz o mascaramento de arquivos errados com nomes “bonitos” e facilita a auditoria do que foi realmente baixado.

## [2026-06-03]

### Corrigido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: o matcher da Central de Downloads passou a exigir a correspondencia completa da linha, incluindo o recorte final `Interna`, `Interestadual` ou `Externa`.
- Impacto: evita baixar um arquivo valido, mas de outro recorte, com nome renomeado de forma incorreta.

## [2026-06-03]

### Alterado
- Arquivo: src/extraction/siga_extractor.py
- Motivo: a leitura das métricas anuais ganhou tentativas curtas com espera entre elas antes de concluir que o campo não apareceu.
- Impacto: reduz erro por carregamento incompleto da página em seções como NFC-e/Destinatario.

## [2026-06-03]

### Removido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: o fallback de CNPJ BASE zerado foi removido da Central de Downloads.
- Impacto: a automação agora baixa apenas quando encontra o CNPJ correto da planilha; caso contrário, gera o TXT de indisponibilidade.

## [2026-06-03]

### Alterado
- Arquivo: src/extraction/siga_extractor.py
- Motivo: o matcher da Central de Downloads passou a varrer as células da linha para localizar a TELA/ABA completa, validar CNPJ na mesma linha e aguardar 5 segundos quando o status ainda estiver em processamento.
- Impacto: reduz falso negativo quando a linha existe na tabela, mas a posição das colunas ou a formatação do CNPJ variam.

## [2026-06-02]

### Corrigido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: o clique no item da Central de Downloads podia falhar quando o `Locator` da linha ficava inválido após a atualização do DOM.
- Impacto: a automação agora reencontra a linha pelo texto da `TELA/ABA` antes de clicar no download, reduzindo `NoSuchElementException`.

## [2026-06-02]

### Alterado
- Arquivos:
  - src/extraction/spreadsheet.py
  - src/main.py
  - src/extraction/siga_extractor.py
  - README.md

- Motivo:
  Migração da entrada da automação de CGF para CNPJ, incluindo leitura da planilha `cnpj.xlsx`, mensagens do terminal e documentação de uso.

- Impacto:
  O fluxo passa a aceitar planilhas com coluna `cnpj` e exibe CNPJ nas mensagens visíveis ao usuário.

## [2026-06-02]

### Corrigido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: a busca na Central de Downloads rejeitava arquivos já concluídos quando a linha não era mais recente que a solicitação atual, mesmo com a TELA/ABA correta disponível.
- Impacto: o matcher agora aceita a última linha concluída compatível com a TELA/ABA quando nenhuma linha nova aparece, reduzindo avisos falsos de indisponibilidade.

## [2026-06-02]

### Alterado
- Arquivo: src/extraction/siga_extractor.py
- Motivo: alinhar o fluxo fiscal ao `fluxo.docx`, padronizando nomes de resumos, liberando a abertura do mês com base em quantidade positiva e mantendo o detalhamento por reportes do mês.
- Impacto: a automação agora segue melhor a regra operacional descrita para NF-e, NFC-e e CT-e e reduz cliques desnecessários.

### Alterado
- Arquivo: src/live_assist.py
- Motivo: espelhar no modo assistido o mesmo critério de quantidade positiva usado pela extração principal.
- Impacto: os comandos manuais passam a relatar o fluxo com mensagens coerentes com a lógica atual.

### Documentação
- Arquivo: brain/2026-06-02-fluxo-docx.md
- Motivo: registrar a decisão técnica adotada para aplicar as mudanças do documento de fluxo.
- Impacto: mantém rastreabilidade da alteração nesta sessão.

## [2026-06-02]

### Documentação
- Arquivos:
  - src/main.py
  - src/auth/siga_login.py
  - src/config.py
  - src/extraction/spreadsheet.py
  - src/extraction/siga_extractor.py
  - src/live_assist.py
  - src/utils/browser.py
  - src/utils/certificate_policy.py
  - src/utils/logging_setup.py
  - src/utils/selenium_compat.py
  - src/utils/siga_page.py
  - src/utils/text.py

- Motivo:
  Inserção de comentários e docstrings em português para explicar fluxo de terminal, autenticação, leitura de planilha, extração fiscal, modo assistido e utilitários de navegação.

- Impacto:
  O código ficou mais fácil de manter e revisar, principalmente nas partes com regras de negócio e fallback de automação.

## [2026-06-02]

### Removido
- Arquivos e pastas:
  - browser-debug-profile/
  - .browser-profile/
  - build/
  - dist/
  - logs/
  - saida/
  - teste-navegador/
  - main.spec
  - cgf.xlsx
  - xpath-download-assincrono.xlsx

- Motivo:
  Limpeza de artefatos locais gerados por navegador, empacotamento, logs e planilhas soltas que não fazem parte do código-fonte.

- Impacto:
  Reduz ruído no repositório, evita versionamento de dados temporários e deixa o projeto mais previsível para manutenção.

### Documentação
- Arquivo: brain/2026-06-02-limpeza-repositorio.md
- Motivo:
  Registro da decisão de limpeza e dos itens removidos.
- Impacto:
  Mantém rastreabilidade do que foi tratado nesta sessão.

## [2026-06-02]

### Corrigido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: na lista de contribuintes do SIGA, a célula que corresponde ao CGF é a segunda coluna (`td[2]` no XPath), e ela é o alvo mais consistente para abrir o detalhe.
- Impacto: a automação passa a clicar prioritariamente na célula do CGF da linha encontrada, reduzindo o risco de acionar outros elementos da tabela.

## [2026-06-02]

### Corrigido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: a abertura do contribuinte podia clicar no último alvo da linha, o que acabava acionando o link errado em vez de entrar no detalhe.
- Impacto: a automação passa a priorizar o primeiro `td` da linha encontrada pelo CGF antes de tentar o clique genérico na linha.

## [2026-06-02]

### Segurança
- Arquivo: .gitignore
- Motivo: diretórios locais de build (`build/` e `dist/`) estavam aparecendo no status do Git e não devem ser versionados.
- Impacto: reduz ruído no controle de versão e evita o envio acidental de artefatos gerados localmente.

## [2026-06-02]

### Corrigido
- Arquivo: src/extraction/spreadsheet.py
- Motivo: a planilha podia fornecer CGF com zero à esquerda, o que fazia a busca do contribuinte falhar no SIGA.
- Impacto: o CGF agora é normalizado sem zeros à esquerda ao ser lido da planilha, permitindo a pesquisa correta com valores como `065579828` -> `65579828`.

## [2026-06-01]

### Corrigido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: a abertura do contribuinte podia travar após a pesquisa do CGF quando a tabela ainda estava renderizando ou quando a varredura de texto via Selenium ficava lenta.
- Impacto: a automação passa a aguardar o resultado filtrado, tenta abrir o detalhamento com seletores mais específicos, usa fallback por DOM e só prossegue após confirmar a tela de detalhes.
- Arquivo: src/extraction/siga_extractor.py
- Motivo: a lista de contribuintes podia terminar de carregar somente depois do timeout inicial, interrompendo o fluxo antes da pesquisa do CGF.
- Impacto: a espera inicial pela lista virou permissiva, o ciclo de pesquisa/abertura ganhou retentativas e a validação forte passou a ocorrer após o envio do CGF.

### Adicionado
- Arquivo: LICENSE
- Motivo: inclusão da licença proprietária privada obrigatória do projeto.
- Impacto: formaliza que o projeto é privado e possui todos os direitos reservados.

### Dependências
- Arquivo: requirements.txt
- Motivo: instalação do `pyinstaller==6.20.0` para permitir empacotamento da automação em executável.
- Impacto: o ambiente Python passa a ter a ferramenta de build necessária para gerar distribuições locais do projeto.

### Corrigido
- Arquivo: siga-automacao.spec
- Motivo: o executável `onefile` falhava ao iniciar com `ModuleNotFoundError` para `selenium.webdriver.common.action_chains`.
- Impacto: inclusão de `hiddenimports` do Selenium no build, permitindo inicialização correta do executável empacotado.

### Segurança
- Arquivo: .gitignore
- Motivo: inclusão do padrão `*.sqlite-journal` na lista de bancos locais ignorados.
- Impacto: reduz risco de versionar arquivos auxiliares de banco local.

### Documentação
- Arquivo: brain/2026-06-01-abertura-contribuinte.md
- Motivo: registro da decisão técnica aplicada ao fluxo de abertura do contribuinte.
- Impacto: mantém rastreabilidade do diagnóstico e da correção.
- Arquivo: brain/2026-06-01-pyinstaller.md
- Motivo: registro da instalação do PyInstaller como ferramenta de empacotamento local.
- Impacto: mantém rastreabilidade da decisão de dependência.
- Arquivo: brain/2026-06-01-pyinstaller-onefile-fix.md
- Motivo: registro da correção aplicada ao empacotamento `onefile` com `hiddenimports`.
- Impacto: mantém histórico técnico do ajuste necessário para execução do `.exe`.

## 1.1.0 - 2026-05-27

- Migrada a automacao principal de Playwright para Selenium WebDriver.
- Mantido o fluxo de login manual no mesmo Chrome/Edge com CDP ativo, agora por `debuggerAddress` do Selenium.
- Adicionada uma camada interna de compatibilidade para preservar seletores, abas, comandos assistidos e captura deterministica de downloads.
- Alterada a ordem do fluxo: o Selenium passa a ser anexado somente depois do login manual, evitando controle WebDriver durante certificado/recaptcha.
- Corrigido o clique de download na central assíncrona do SIGA para acionar a última célula da linha, onde o texto `Download` dispara o arquivo.
- A busca de downloads assíncronos agora valida o CNPJ do contribuinte na linha da central, permitindo reaproveitar arquivos ainda válidos do mesmo contribuinte e evitando escolher histórico de outro contribuinte quando o texto da tela é parecido.
- Otimizada a extração de métricas por rótulo para evitar varreduras lentas de texto no Selenium.
- Substituida a dependencia `playwright` por `selenium==4.44.0`.

## 1.0.9 - 2026-05-27

- Adicionado fallback para ambientes que bloqueiam escrita em `HKCU\Software\Policies`: o programa agora gera `logs/chrome-certificate-policy.reg` com a politica pronta para aplicacao manual.
- Ajustado o fluxo para informar no terminal quando a politica nao foi gravada automaticamente por falta de permissao.

## 1.0.8 - 2026-05-27

- Adicionada configuracao automatica da politica `AutoSelectCertificateForUrls` no Registro do Windows para Chrome/Edge, usando o certificado de cliente instalado no usuario atual.
- Incluidos os argumentos `--skip-certificate-policy` e `--clear-certificate-policy` para controlar ou remover a politica local quando necessario.
- Documentado o fluxo de selecao automatica de certificado digital para os dominios `sso.sefaz.ce.gov.br` e `siga.sefaz.ce.gov.br`.

## 1.0.7 - 2026-05-27

- Alterado o padrao de abertura do Chrome para usar novamente um perfil dedicado de automacao com `--user-data-dir`, evitando bloqueios do Chrome ao tentar ativar CDP no perfil normal do usuario.
- Adicionado o argumento `--system-browser-profile` para tentativa explicita de uso do perfil normal, quando necessario.
- Atualizada a documentacao para esclarecer que a selecao de certificado digital no Windows depende dos certificados instalados no repositario do usuario do Windows.

## 1.0.6 - 2026-05-27

- Adicionado fallback automatico na abertura do navegador: quando o CDP em `127.0.0.1:9222` nao sobe na primeira tentativa, o fluxo encerra processos antigos do navegador e tenta iniciar novamente uma vez.
- Mantida a opcao manual `--force-restart-browser`; o fallback agora reduz falhas mesmo quando a flag nao e informada.

## 1.0.5 - 2026-05-27

- Adicionado o argumento `--force-restart-browser` para encerrar os processos do navegador (`chrome.exe` ou `msedge.exe`) antes de abrir uma nova sessao com CDP.
- O fluxo de abertura agora pode limpar processos antigos que bloqueavam a porta de depuracao e causavam falha de conexao em `http://127.0.0.1:9222`.

## 1.0.4 - 2026-05-27

- Alterada a abertura manual do Chrome para usar o perfil normal do usuario por padrao, permitindo que a opcao `Seu certificado digital` liste os certificados instalados no navegador/Windows.
- Adicionado o argumento `--isolated-browser-profile` para voltar ao perfil isolado da automacao quando necessario.
- Adicionado o argumento `--chrome-profile-directory` para escolher explicitamente um perfil do Chrome, como `Default` ou `Profile 1`.
- Documentado o cuidado de fechar o Chrome antes de iniciar o fluxo, evitando que um processo antigo sem CDP bloqueie o anexo da automacao.
- Incluidos perfis locais de navegador no `.gitignore`.

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

# 0.2.7 - 2026-06-02

- Corrigida a chamada de captura de download na central para repassar `tela_aba` ao clicar na linha encontrada.
- Motivo: o fluxo havia avançado até a seleção da linha, mas quebrava com `TypeError` por desencontro entre assinatura e chamada em `src/extraction/siga_extractor.py`.

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
