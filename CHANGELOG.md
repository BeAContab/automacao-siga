# Changelog

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
