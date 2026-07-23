# Plano de Correção — SIGA Automação

Documento de planejamento gerado a partir da revisão de código do repositório. Reúne os 25 pontos identificados (bugs, falhas de robustez e melhorias), organizados por severidade, com a correção proposta para cada um. Este arquivo é atualizado conforme as fases são implementadas, conforme o workflow definido em `CLAUDE.md`.

## Como usar este documento

Cada item traz: localização, problema, cenário concreto que o dispara, correção proposta e esforço estimado. Os itens estão agrupados em fases sugeridas de execução (críticos primeiro). Para autorizar a implementação de uma fase, responda indicando quais itens/fases aprovar.

## Status geral

| Fase | Itens | Status | Modelo de IA | Esforço |
|---|---|---|---|---|
| 1 — Crítico | 1–4 | ✅ **Concluída** (2026-07-15, ver `CHANGELOG.md` v1.4.4) | Sonnet 5 | `high` |
| 2 — Alto | 5–10 | ✅ **Concluída** — itens 5, 7, 10 (v1.4.5, Sonnet 5) e itens 6, 8, 9 (v1.4.6, Opus 4.8) | Sonnet 5 + Opus 4.8 | `high` |
| 3 — Médio | 11–18 | ✅ **Concluída** — itens 11–15, 18 (Sonnet 5, v1.4.7); item 16 (Opus 4.8, v1.4.8); item 17 investigado e considerado não-bug | Sonnet 5 + Opus 4.8 | `high` |
| 4 — Baixo/Melhoria | 19–25 | ✅ **Concluída** — itens 19–24 (Claude Sonnet 4.6 Thinking, v1.4.9); item 25 é iniciativa contínua | Claude Sonnet 4.6 (Thinking) | `low` (item 25: `high`, iniciativa contínua) |

---

## Fase 1 — Crítico (risco de perda de dados ou de dado fiscal incorreto)

**Status:** ✅ Concluída em 2026-07-15 — implementada com **Sonnet 5**, esforço `high`. Detalhes registrados em `CHANGELOG.md` na versão **1.4.4**. Validação real contra o SIGA (login/navegador reais) ainda pendente — recomendado rodar `testes/run_test_live.py` ou o fluxo normal da GUI/CLI antes de considerar os itens fechados em produção.

### 1. Bug no matching exato/fuzzy da Central de Downloads
**Local:** `src/extraction/siga_extractor.py:3271-3286` (`_row_matches_download_target`)

**Problema:** os dois ramos do `if exact_only:` chamam exatamente a mesma função (`_row_contains_signature_fragments`). Isso faz com que toda linha que passa no filtro frouxo de fragmentos seja também classificada como correspondência "exata", eliminando na prática o balde de candidatos "fuzzy" usado para desempate por pontuação.

**Cenário de risco:** dois relatórios pendentes com títulos parecidos no mesmo mês/aba (ex.: NF-e Emissor vs. Destinatário) podem fazer o sistema escolher o arquivo errado sem aplicar o desempate por `_download_match_score`.

**Correção proposta:** quando `exact_only=True` e não houver correspondência literal do título completo (`normalized_target in row_text`), retornar `False` em vez de cair no fallback de fragmentos — restaurando a separação real entre "exato" e "fuzzy".

**Esforço estimado:** baixo (alteração de poucas linhas), mas requer atenção na verificação por tocar lógica central de correspondência.

**Status:** ✅ Aplicado (Sonnet 5, esforço `high`) — `src/extraction/siga_extractor.py:3283-3286`.

---

### 2. Lote inteiro aborta se a planilha de resultados estiver aberta no Excel
**Local:** `src/extraction/spreadsheet.py:151-193` (`write_status_to_spreadsheet_cell`), chamada sem proteção em `src/extraction/siga_extractor.py:235-237`

**Problema:** `workbook.save(spreadsheet_path)` lança `PermissionError` se o arquivo `_resultados.xlsx` estiver aberto no Excel — cenário comum, já que o usuário costuma deixar essa planilha aberta para acompanhar o andamento.

**Cenário de risco:** usuário abre a planilha de resultados durante a execução do lote → a próxima gravação de status lança exceção não tratada → todo o restante do lote é abortado.

**Correção proposta:** envolver a leitura/gravação do workbook em `try/except (PermissionError, OSError)` dentro da própria função, registrando aviso no log em vez de propagar a exceção.

**Esforço estimado:** baixo.

**Status:** ✅ Aplicado (Sonnet 5, esforço `high`) — `src/extraction/spreadsheet.py`, função `write_status_to_spreadsheet_cell`.

---

### 3. Erro não mapeado na abertura do contribuinte aborta o lote e descarta downloads pendentes
**Local:** `src/extraction/siga_extractor.py:239-266`

**Problema:** apenas `TaxpayerNotFoundError` é capturada ao redor de `_open_taxpayer_from_home`; qualquer outra exceção propaga e interrompe `run_batch_from_spreadsheet_in_context` antes de chegar ao trecho que baixa os relatórios já solicitados (linha ~298).

**Cenário de risco:** um erro inesperado de driver/rede na linha N faz o processo abortar sem nunca buscar na Central de Downloads os relatórios que o SIGA já havia começado a gerar para as linhas 1..N-1 — trabalho perdido silenciosamente.

**Correção proposta:** ampliar a captura para `Exception` genérica também nesse trecho (seguindo o padrão já usado no bloco de `_extract_fiscal_tables` logo abaixo), registrando erro, marcando status "Erro: {mensagem}" na planilha e seguindo para a próxima linha com `continue`.

**Esforço estimado:** baixo.

**Status:** ✅ Aplicado (Sonnet 5, esforço `high`) — `src/extraction/siga_extractor.py:267-287`, novo bloco `except Exception` após o `except TaxpayerNotFoundError`.

---

### 4. `terminate_browser_processes` mata todos os processos de navegador da máquina
**Local:** `src/utils/browser.py:127-145`

**Problema:** `taskkill /IM chrome.exe /T /F` (ou `msedge.exe`) encerra **qualquer** instância do navegador em execução, não apenas a da automação.

**Cenário de risco:** usuário com janelas pessoais do Chrome abertas (não relacionadas à automação) tem tudo fechado à força sem aviso, com risco de perda de dados não salvos (ex.: e-mail sendo redigido, formulário preenchido).

**Correção proposta:** localizar apenas os processos cujo `CommandLine` contenha o diretório de perfil de depuração da automação (`browser_debug_profile_dir`) via PowerShell (`Get-CimInstance Win32_Process`), encerrando somente esses PIDs. Quando `use_system_browser_profile=True`, não forçar encerramento algum — apenas registrar aviso, pois não é seguro distinguir processos da automação dos pessoais nesse modo.

**Esforço estimado:** médio (requer testar a filtragem por linha de comando em Chrome e Edge).

**Status:** ✅ Aplicado (Sonnet 5, esforço `high`) — `src/utils/browser.py`, nova função `_find_automation_browser_pids` e `terminate_browser_processes` reescrita. **Pendente:** validar a filtragem de `CommandLine` em uma máquina real com Chrome e com Edge (não foi possível testar contra um navegador real neste ambiente).

---

## Fase 2 — Alto (robustez/segurança, sem risco imediato de perda de dado do usuário externo)

**Status:** ✅ Concluída em 2026-07-15. Itens 5, 7 e 10 com Sonnet 5, esforço `high` (`CHANGELOG.md` v1.4.5); itens 6, 8 e 9 com **Opus 4.8**, esforço `high` (`CHANGELOG.md` v1.4.6). Validação real (múltiplos certificados no Windows, GUI durante execução real) ainda pendente — ver notas por item.

> *Nota de correção:* a versão anterior deste plano listava o item 16 junto com 6, 8 e 9 nesta recomendação, mas o item 16 pertence à Fase 3 — a nota de modelo/esforço dele foi movida para lá.

### 5. Política de certificado do Windows nunca é removida automaticamente
**Local:** `src/main.py:415-434`

**Problema:** `configure_auto_certificate_selection` grava a política `AutoSelectCertificateForUrls` em `HKCU` no início da execução, mas não há `finally`/limpeza chamando `clear_auto_certificate_selection` ao final do processo.

**Cenário de risco:** a política permanece ativa permanentemente no navegador normal do usuário (fora da automação) para os domínios do SIGA, selecionando certificado automaticamente sem prompt até o usuário rodar `--clear-certificate-policy` manualmente.

**Correção proposta:** aplicar a política dentro de um bloco `try/finally` em `main()`, chamando `clear_auto_certificate_selection` ao final da execução (sucesso ou erro), preservando a opção de mantê-la ativa apenas se explicitamente solicitado por uma nova flag (a definir, ex. `--keep-certificate-policy`).

**Esforço estimado:** médio (requer decidir e validar o comportamento padrão desejado com o usuário).

**Status:** ✅ Aplicado (Sonnet 5, esforço `high`) — `src/main.py`: novo bloco `try/finally` em `main()` e nova flag `--keep-certificate-policy` (default: remove a política ao final). Comportamento padrão mudou — quem dependia da política permanecer ativa após a execução deve passar essa flag explicitamente.

---

### 6. Seleção automática do certificado escolhe "o de validade mais longa" sem confirmação
**Local:** `src/utils/certificate_policy.py:104-125`

**Problema:** o script PowerShell ordena certificados por `NotAfter -Descending` e pega o primeiro, sem qualquer validação com o operador.

**Cenário de risco:** usuário com mais de um certificado de autenticação (ex.: e-CNPJ de empresas diferentes) pode ter o certificado errado aplicado silenciosamente como política do navegador.

**Correção proposta:** quando houver mais de um certificado elegível, não aplicar automaticamente — listar as opções (assunto/CN e validade) e pedir confirmação explícita do operador (CLI) ou exibir seleção na GUI, aplicando automaticamente apenas quando houver exatamente um certificado válido.

**Esforço estimado:** médio-alto (requer novo fluxo de interação, tanto CLI quanto GUI).

**Status:** ✅ Aplicado (Opus 4.8, esforço `high`) — `src/utils/certificate_policy.py`: `_find_client_auth_certificate_cn` virou `_list_client_auth_certificates` (lista todos os elegíveis via `ConvertTo-Json`); `configure_auto_certificate_selection` aceita um `selector` opcional e só aplica automaticamente com um único certificado. `src/main.py`: `_prompt_certificate_choice` faz a seleção no terminal (mostra CN + validade). Interação apenas no fluxo CLI, pois a GUI já força `--skip-certificate-policy`. Sem terminal/cancelamento → política não aplicada (prompt nativo do navegador). Lógica de listagem/seleção coberta por 7 cenários de teste com mocks (sem depender de Windows/PowerShell reais).

---

### 7. Escrita de status na planilha reabre e regrava o arquivo inteiro a cada célula
**Local:** `src/extraction/spreadsheet.py:151-193`

**Problema:** cada chamada de `write_status_to_spreadsheet_cell` (potencialmente dezenas/centenas por lote) faz `load_workbook` + varredura completa do cabeçalho + `save()` do arquivo inteiro.

**Cenário de risco:** além do custo de performance O(n) por escrita, aumenta o risco de corrupção do arquivo se o processo for interrompido no meio de um `save()`, e cada reabertura aumenta a chance de colidir com o Excel aberto pelo usuário (item 2).

**Correção proposta:** manter o workbook aberto em memória durante todo o processamento do lote (um único `load_workbook`/`save` por execução, ou salvamentos periódicos em vez de por célula), fechando/salvando definitivamente ao final ou em pontos de checkpoint espaçados.

**Esforço estimado:** médio (requer repensar o ciclo de vida do objeto `Workbook` compartilhado entre extrator e camada de planilha).

**Status:** ✅ Aplicado (Sonnet 5, esforço `high`) — `src/extraction/spreadsheet.py`: workbook de status agora fica em cache por caminho de planilha (`_STATUS_WORKBOOK_CACHE`), evitando reabrir e reescanear o cabeçalho a cada célula; nova função `close_status_workbook` é chamada ao final de `run_batch_from_spreadsheet_in_context` (`src/extraction/siga_extractor.py`). A gravação em tempo real (salvamento a cada atualização) foi preservada — só a reabertura/reescaneamento repetidos foram eliminados. Efeito colateral: coluna de aba não encontrada agora gera aviso explícito no log em vez de falhar silenciosamente.

---

### 8. GUI bloqueia a thread principal do Tkinter ao iniciar o navegador
**Local:** `src/gui.py:942-961` (`_start_browser_if_needed`)

**Problema:** `launch_debug_browser` (incluindo `wait_for_cdp`, que pode aguardar até `browser_start_timeout_ms`, 15s por padrão) é chamado diretamente no callback do botão, na thread principal do Tkinter.

**Cenário de risco:** durante esse tempo a janela fica "Não responde", passando a impressão de travamento ao usuário.

**Correção proposta:** mover a chamada para uma thread de trabalho (seguindo o padrão já usado para a extração em si), atualizando a UI via `root.after(...)` ao concluir.

**Esforço estimado:** médio.

**Status:** ✅ Aplicado (Opus 4.8, esforço `high`) — `src/gui.py`: `_start_browser_if_needed` agora dispara `launch_debug_browser` em thread, desabilitando o botão e mostrando "Iniciando o navegador..." imediatamente; sucesso/falha atualizam a UI via `_on_browser_start_succeeded`/`_on_browser_start_failed` na thread principal (`_ui_after`). Guarda contra cliques repetidos enquanto a thread está viva.

---

### 9. Fechar a GUI durante uma extração não cancela nem aguarda a thread de trabalho
**Local:** `src/gui.py:116-117`, `1202-1204` (`_on_close`)

**Problema:** `_stop_requested` é definido mas nunca lido; `_on_close` apenas remove o handler de log e destrói a janela, sem checar se `_worker_thread` está viva nem sinalizar cancelamento.

**Cenário de risco:** fechar a janela durante uma extração em andamento deixa uma thread em segundo plano dirigindo o Selenium; se essa thread tentar chamar `root.after(...)` após o `destroy()`, gera exceção Tk não tratada.

**Correção proposta:** em `_on_close`, verificar se há thread de trabalho ativa; se houver, sinalizar `_stop_requested`, exibir aviso/confirmação ao usuário, aguardar encerramento gracioso (com timeout) e só então fechar a `BrowserSession` e destruir a janela.

**Esforço estimado:** médio.

**Status:** ✅ Aplicado (Opus 4.8, esforço `high`) — `src/gui.py`: `_on_close` detecta execução em andamento, pede confirmação, sinaliza `_closing`/`_stop_requested`, chama `shutdown_debug_browser` (faz o Selenium falhar rápido e a thread sair do bloco `with BrowserSession`), aguarda a thread com `join(timeout=10)` e só então destrói a janela. Novo agendador `_ui_after` (usado no worker de extração e na abertura do navegador) descarta atualizações de UI após o fechamento, eliminando `TclError`. **Observação:** o cancelamento é forçado (encerrando o navegador), não cooperativo — a interrupção cooperativa por linha exigiria mudanças no extrator (`siga_extractor.py`), fora do escopo deste item.

---

### 10. Funções de matching/download mortas (código não referenciado)
**Local:** `src/extraction/siga_extractor.py` — `_extract_download_match_fragments`, `_download_row_matches_taxpayer`, `_find_latest_download_row`, `_click_xlsx_detail_download_button`/`_find_xlsx_detail_download_button`, `_return_from_detail_to_fiscal_menu`, `_is_zero_cnpj_base_row`/`_row_cnpj_base_key`

**Problema:** nenhuma dessas funções é chamada em nenhum outro ponto do arquivo — indício de refatoração incompleta.

**Cenário de risco:** não é um bug em produção, mas um risco de manutenção: alguém pode "corrigir um bug" nessas funções pensando que afetam o comportamento real, quando o fluxo em produção usa outras funções equivalentes.

**Correção proposta:** confirmar (via busca de referências) que são realmente mortas e removê-las, ou, se alguma ainda for necessária como fallback futuro, documentar isso explicitamente no docstring.

**Esforço estimado:** baixo, mas requer confirmação cuidadosa antes de remover.

**Status:** ✅ Aplicado (Sonnet 5, esforço `high`) — confirmado por busca de referências em todo o repositório (não só no arquivo) que as 8 funções listadas estavam realmente mortas; removidas de `src/extraction/siga_extractor.py`. `_document_key` também foi removida por ter ficado órfã (era chamada só por `_download_row_matches_taxpayer`). Compilação, parsing AST e importação dos módulos alterados foram verificados após a remoção.

---

## Fase 3 — Médio

**Status:** ✅ Concluída em 2026-07-15. Itens 11–15 e 18 com Sonnet 5, esforço `high` (`CHANGELOG.md` v1.4.7); item 16 com **Opus 4.8**, esforço `high` (`CHANGELOG.md` v1.4.8); item 17 investigado e considerado não-bug (nenhuma alteração). Todas as correções foram validadas com testes unitários isolados (mocks), sem acesso a um SIGA real.

### 11. Matching de documento por `startswith` pode confundir CNPJs
**Local:** `src/extraction/siga_extractor.py:3332-3341` (`_row_matches_taxpayer_document`)

**Problema:** usa correspondência por prefixo (`startswith`) entre os dígitos da célula e o CNPJ-alvo.

**Cenário de risco:** um número mais longo que por coincidência começa com os mesmos dígitos do CNPJ-alvo (ex.: número de processo interno da SEFAZ) pode ser aceito como pertencente ao contribuinte errado, misturando downloads entre CNPJs.

**Correção proposta:** exigir igualdade exata dos dígitos normalizados (ou verificação de limite de token/separador), em vez de prefixo.

**Esforço estimado:** baixo-médio (checar se há casos legítimos de truncamento que dependem do `startswith` atual).

**Status:** ✅ Aplicado (Sonnet 5, esforço `high`) — `src/extraction/siga_extractor.py`, `_row_matches_taxpayer_document` agora exige `cell_digits == taxpayer_base_key`. Testado com mock isolado (linha exata casa; linha com sufixo extra não casa mais).

---

### 12. `BrowserSession.__enter__` pode vazar o processo do navegador
**Local:** `src/utils/browser.py:230-256`

**Problema:** se qualquer etapa após a criação do driver falhar antes do `return self.context`, o `__exit__` nunca é chamado (protocolo padrão de context manager), então o processo do navegador/driver não é fechado.

**Correção proposta:** envolver o corpo de `__enter__` em `try/except`, fechando explicitamente qualquer recurso já criado antes de relançar a exceção.

**Esforço estimado:** baixo-médio.

**Status:** ✅ Aplicado (Sonnet 5, esforço `high`) — `src/utils/browser.py`, `BrowserSession.__enter__` agora fecha `self.context` (ou o `driver` bruto, se o contexto ainda não foi criado) num `except Exception` antes de relançar. Testado com mock forçando falha em `BrowserContext.__init__`: `driver.quit()` é chamado como esperado.

---

### 13. `resolve_browser_executable` só verifica dois caminhos fixos
**Local:** `src/utils/browser.py:70-78`

**Problema:** não usa `shutil.which` nem consulta o registro do Windows para localizar instalações não padrão.

**Correção proposta:** adicionar fallback via `shutil.which("chrome"/"msedge")` e, se necessário, leitura da chave de registro `App Paths` do Windows antes de falhar.

**Esforço estimado:** baixo.

**Status:** ✅ Aplicado (Sonnet 5, esforço `high`) — `src/utils/browser.py`, `resolve_browser_executable` agora tenta `shutil.which(image_name)` antes de levantar `BrowserLauncherError`. Não foi implementada a leitura da chave de registro `App Paths` (fora do escopo mínimo necessário); `shutil.which` já cobre o caso descrito no problema (instalação fora do Program Files, mas presente no `PATH`). Testado com mocks para os dois desfechos (encontrado via `which` / não encontrado em lugar nenhum).

---

### 14. Entrada manual de CNPJ na GUI nunca grava planilha de resultados
**Local:** `src/gui.py:1021-1033`, `spreadsheet.py:158-159`

**Problema:** quando `output_spreadsheet_path=None` (fluxo de entrada manual), `write_status_to_spreadsheet_cell` é um no-op silencioso.

**Cenário de risco:** para CNPJs digitados manualmente, não existe nenhum rastro persistido de status além do log em tela, que se perde ao fechar a aplicação.

**Correção proposta:** gerar uma planilha de resultados temporária/nomeada mesmo para a entrada manual (ex. `resultados_manual_<timestamp>.xlsx`) para manter rastreabilidade, alinhado ao requisito de auditoria do PRD.

**Esforço estimado:** médio.

**Status:** ✅ Aplicado (Sonnet 5, esforço `high`) — nova função `build_manual_entry_workbook` em `src/extraction/spreadsheet.py`, usada em `src/gui.py` no modo manual para gerar `resultados_manual_<timestamp>.xlsx` na pasta de saída selecionada. Como pré-requisito, a numeração de linha da entrada manual (`load_cnpjs_from_text`) passou a começar em 2 em vez de 1, reservando a linha 1 para o cabeçalho da nova planilha (sem isso, um CNPJ colado na primeira linha colidiria com o cabeçalho). Testado ponta a ponta: geração da planilha, gravação de status via `write_status_to_spreadsheet_cell` e conferência de que CNPJ e status caem na mesma linha.

---

### 15. Mesma linha da Central de Downloads pode ser atribuída a duas solicitações diferentes
**Local:** `src/extraction/siga_extractor.py:2480-2545`

**Problema:** não há controle de "linha já reivindicada por outro `request_key`" durante o matching.

**Cenário de risco:** dois `PendingDetailRequest` com títulos parecidos (mesmo mês/ano/aba) podem casar com a mesma linha, fazendo o mesmo arquivo ser salvo em duas pastas diferentes.

**Correção proposta:** manter um conjunto de linhas/identificadores já atribuídos durante a varredura e excluí-los de novas correspondências na mesma passada.

**Esforço estimado:** médio.

**Status:** ✅ Aplicado (Sonnet 5, esforço `high`) — `src/extraction/siga_extractor.py`: `_scan_downloads_table_once`/`_scan_downloads_current_page_for_targets` agora recebem um `claimed_rows: dict[(page_number, index), request_key]`; uma linha só pode ser avaliada por um `request_key` diferente do que já a reivindicou nesta passada completa. **Trade-off assumido:** a exclusividade é "primeiro a reivindicar leva", não uma otimização de alocação global (ex. Hungarian assignment) — suficiente para eliminar a duplicação identificada, sem reescrever o algoritmo de pontuação. Validado por compilação/import; não foi possível testar com uma tabela real da Central de Downloads.

---

### 16. Espera por downloads reraspa todas as páginas a cada ciclo
**Local:** `src/extraction/siga_extractor.py:2426-2453` (`_find_pending_download_matches`)

**Problema:** a cada iteração do laço de espera, `page.reload()` é seguido de nova varredura de **todas** as páginas paginadas desde o início, mesmo que a maioria dos itens já tenha sido encontrada.

**Cenário de risco:** em lotes grandes (muitas linhas × muitas abas), o tempo total de espera degrada de forma aproximadamente quadrática.

**Correção proposta:** manter o conjunto de solicitações já resolvidas fora do laço e pular diretamente para as páginas ainda não visitadas na iteração atual, ou parar a varredura assim que todas as pendências restantes forem encontradas.

**Esforço estimado:** médio-alto (requer cuidado para não quebrar a lógica de paginação existente).

**Status:** ✅ Aplicado (Opus 4.8, esforço `high`) — `src/extraction/siga_extractor.py`: `_scan_downloads_table_once` para de paginar assim que todas as solicitações são localizadas (`located_keys >= target_keys`) nas varreduras intermediárias. **Fundamento de segurança:** como todas as solicitações são feitas antes de abrir a tela, a paginação é estável durante a espera — nenhuma linha nova aparece e cada solicitação ocupa uma única linha, cujo status apenas muda de "processando" para "concluído" no lugar. **Salvaguarda contra regressão de duplicatas:** a parada antecipada só vale nas varreduras intermediárias (onde só importa saber se algo ainda processa); antes de retornar o resultado final, é feita uma varredura completa (`full_scan=True`) que lê todas as páginas, tornando o resultado idêntico ao comportamento original independentemente da ordenação da tela. Validado com 3 cenários de teste (mocks): parada antecipada na varredura intermediária, leitura completa no `full_scan`, e o fluxo completo espera→reload→varredura final.

---

### 17. Entrada manual de CNPJ não aceita CGF de 9 dígitos
**Local:** `src/extraction/spreadsheet.py:132-148` (`_extract_documents_from_text`)

**Problema:** só aceita tokens de exatamente 14 caracteres, diferente da leitura via planilha (que aceita coluna `cgf`).

**Cenário de risco:** um CGF colado manualmente na GUI é descartado silenciosamente, sem nenhuma linha criada nem aviso indicando qual token foi ignorado.

**Correção proposta:** alinhar a função ao mesmo suporte de CGF (9 dígitos) já existente no carregamento por planilha, e emitir aviso explícito para tokens descartados.

**Esforço estimado:** baixo-médio.

**Status:** ⚠️ **Investigado e considerado não-bug** — teste direto contra o código real mostrou que `_normalize_document` já faz zero-padding de qualquer token alfanumérico de até 14 caracteres antes da checagem `len(digits) == 14`. Um CGF de 9 dígitos colado manualmente (`'123456789'`) já é normalizado para `'00000123456789'` e aceito, exatamente como acontece na leitura via planilha (que usa a mesma função de normalização para a coluna `cgf`). Este item da revisão original estava incorreto — nenhuma alteração de código foi feita. Validado com `load_cnpjs_from_text('123456789')` → `SpreadsheetRow(cnpj='00000123456789', ...)`.

---

### 18. `input()` bloqueante pressupõe terminal interativo
**Local:** `src/auth/siga_login.py:61-66` (`wait_for_manual_login`)

**Problema:** hoje só é evitado porque a GUI passa `allow_manual_login_prompt=False`, mas é um acoplamento frágil entre módulos.

**Cenário de risco:** se algum fluxo futuro (ex. execução sem console anexado) alcançar esse caminho, trava ou lança exceção sem mensagem clara.

**Correção proposta:** adicionar uma verificação explícita de `sys.stdin.isatty()` antes de chamar `input()`, com mensagem de erro clara caso não haja terminal interativo disponível.

**Esforço estimado:** baixo.

**Status:** ✅ Aplicado (Sonnet 5, esforço `high`) — `src/auth/siga_login.py`, `wait_for_manual_login` verifica `sys.stdin.isatty()` antes do `input()` e levanta `RuntimeError` com mensagem explícita (sugerindo `--gui` ou `--disable-attach`) quando não há terminal interativo.

---

## Fase 4 — Baixo / Melhoria

**Status:** ✅ Concluída em 2026-07-15. Itens 19–24 com **Claude Sonnet 4.6 (Thinking)**, esforço `low`, registrado em `CHANGELOG.md` v1.4.9. Item 25 (refatoração transversal de exceções genéricas) tratado como iniciativa contínua conforme o plano — não foi executado como tarefa única.

### 19. `_find_row_by_digits` limita a varredura a 80 candidatos
**Local:** `src/extraction/siga_extractor.py:3863-3888`

**Correção proposta:** tornar o limite configurável ou, no mínimo, registrar um aviso explícito no log quando o limite for atingido sem encontrar correspondência, para facilitar diagnóstico.

**Esforço estimado:** baixo.

---

### 20. Sem validação de formato/checksum de CNPJ antes da busca no SIGA
**Local:** `src/extraction/siga_extractor.py:3724-3739`

**Correção proposta:** validar formato básico (comprimento/checksum quando numérico) na leitura da planilha (`spreadsheet.py`), reportando erro imediato em vez de gastar um ciclo completo de timeouts no SIGA para CNPJs obviamente malformados.

**Esforço estimado:** baixo-médio.

---

### 21. Botão "Ajuda" resolve o manual via CWD em vez do helper de assets
**Local:** `src/gui.py:741-758` vs. `154-157`

**Problema:** inconsistente com o padrão já usado para ícones/logo (`_resolve_asset_path`).

**Correção proposta:** usar `_resolve_asset_path` também para localizar `manual_instrucoes.html`.

**Esforço estimado:** baixo.

---

### 22. Lógica de detecção de cabeçalho da planilha duplicada
**Local:** `src/extraction/spreadsheet.py:33-40` vs. `171-177`

**Problema:** a mesma varredura de cabeçalho é reimplementada duas vezes (leitura e escrita); qualquer ajuste futuro nos aliases de cabeçalho precisa ser replicado manualmente nos dois lugares, sob risco de a escrita de status parar de funcionar silenciosamente (`col_index is None` → não escreve nada, sem aviso).

**Correção proposta:** extrair a detecção de cabeçalho para uma função compartilhada única, usada tanto na leitura quanto na escrita; adicionar log de aviso quando `col_index` não for encontrado.

**Esforço estimado:** baixo-médio.

---

### 23. XPath extremamente posicional para o toggle do menu lateral
**Local:** `src/extraction/siga_extractor.py:3785-3789`

**Problema:** seletor depende da estrutura DOM exata (`//*[@id='main-structure-header-id']/div/div[1]/...`); qualquer mudança pequena no front-end do SIGA quebra silenciosamente, caindo em fallback de texto sem indicar a causa raiz no log.

**Correção proposta:** priorizar seletores por atributo/texto/role já usados em outras partes do arquivo, mantendo o XPath posicional apenas como último fallback, com log explícito indicando quando o fallback foi necessário (sinal de possível mudança de layout do SIGA).

**Esforço estimado:** baixo-médio.

---

### 24. Encerramento do navegador só verifica se a porta CDP fechou
**Local:** `src/utils/browser.py:150-155`, `199-205`

**Problema:** não confirma se o processo do navegador realmente terminou, apenas se a porta de depuração parou de responder.

**Correção proposta:** após o `taskkill`, verificar explicitamente (via PID) se o processo ainda existe antes de considerar o encerramento bem-sucedido.

**Esforço estimado:** baixo.

---

### 25. Uso extensivo de `except Exception` genérico sem categorização
**Local:** recorrente em `siga_extractor.py`, `gui.py`, `main.py`

**Problema:** captura ampla com apenas log, sem diferenciar erro recuperável (ex.: timeout de rede) de erro fatal (ex.: bug de seletor, dado inesperado).

**Cenário de risco:** dado o tamanho do módulo principal (~3900 linhas) e a criticidade do fluxo fiscal, a falta de categorização dificulta a triagem em produção e amplia o impacto dos itens 2 e 3.

**Correção proposta:** não é uma correção pontual — é um padrão a ser adotado gradualmente: introduzir exceções específicas do domínio (ex. `DownloadTimeoutError`, `UnexpectedPageStateError`) nos pontos mais críticos (matching de downloads, abertura de contribuinte) para permitir tratamento diferenciado, mantendo `except Exception` apenas como rede de segurança externa.

**Esforço estimado:** alto (mudança transversal, melhor tratada como iniciativa contínua, não como item único).

---

## Resumo por fase

| Fase | Itens | Severidade | Status | Modelo | Esforço |
|---|---|---|---|---|---|
| 1 | 1–4 | Crítico | ✅ Concluída (v1.4.4) | Sonnet 5 | `high` |
| 2 | 5–10 | Alto | ✅ Concluída (v1.4.5 + v1.4.6) | Sonnet 5 + Opus 4.8 | `high` |
| 3 | 11–18 | Médio | ✅ Concluída (v1.4.7 + v1.4.8) | Sonnet 5 + Opus 4.8 | `high` |
| 4 | 19–25 | Baixo/Melhoria | ✅ Concluída (v1.4.9, itens 19–24) | Claude Sonnet 4.6 (Thinking) | `low` (item 25: `high`, iniciativa contínua) |

**Notas:**
- **Item 17** (Fase 3): investigado e considerado não-bug — nenhuma ação necessária.

---

## Pós-plano — Achados de execução real (fora dos 25 itens originais)

Itens descobertos após a conclusão das Fases 1–4, a partir da análise de logs de execuções reais (`logs/run.log`, `logs/errors.log`), não fazem parte da revisão estática original de 25 pontos.

### 26. Falha de paginação na Central de Downloads aborta o lote inteiro sem tratamento
**Local:** `src/extraction/siga_extractor.py` (`_download_found_pending_requests`)

**Problema:** quando `_go_to_next_downloads_page` falha no meio do lote (não consegue avançar para a próxima página da Central de Downloads), o código levantava `TimeoutError` sem tratamento, propagando até a GUI e abortando toda a extração — mesmo com downloads já concluídos com sucesso em páginas anteriores.

**Como foi descoberto:** diagnóstico de um erro real relatado pelo usuário (`logs/run.log`, 2026-07-15 16:27:19), correlacionado com uma sequência de falhas de re-localização de linha na "página 2" nos minutos anteriores, sugerindo instabilidade pontual da Central de Downloads no meio de um lote longo.

**Correção aplicada:** nova função `_advance_to_next_downloads_page_with_retry` tenta uma recuperação (reload + reavanço até a posição esperada) antes de desistir; se a recuperação falhar, `_mark_unreached_download_pages_as_unavailable` marca os itens das páginas não alcançadas como "Erro: Falha ao navegar na Central de Downloads" (aviso `.txt` + status na planilha) e o lote termina de forma graciosa, preservando os downloads já concluídos.

**Status:** ✅ Aplicado (Sonnet 5, esforço `high`, `CHANGELOG.md` v1.5.3). Validado com 3 cenários de teste (mocks): avanço direto sem retry, recuperação via reload, falha total tratada sem exceção — incluindo o fluxo completo (`_download_found_pending_requests`) com resultado parcial preservado. **Pendente:** validação contra uma Central de Downloads real, já que a causa raiz da instabilidade da paginação (overlay do SIGA, mudança na lista, etc.) não pôde ser reproduzida neste ambiente.

---

### 27. Varredura da Central de Downloads não usa o maior tamanho de página disponível
**Local:** `src/extraction/siga_extractor.py` (`_download_pending_detail_requests`, `_find_pending_download_matches`, `_advance_to_next_downloads_page_with_retry`)

**Problema:** a automação nunca ajustava o "linhas por página" do paginador PrimeNG da Central de Downloads, deixando-o no padrão da tela (normalmente baixo, ex. 10). Para um histórico acumulado de solicitações (às vezes 100+ páginas), isso obriga a varredura a navegar página por página um número desnecessariamente alto de vezes, mesmo para lotes pequenos (ex.: 1 único contribuinte).

**Como foi descoberto:** relatado pelo usuário durante uso real ("as vezes 100 páginas ou mais, e perde muito tempo"); o usuário inspecionou o elemento no DevTools do navegador e forneceu o HTML do dropdown (`p-dropdown` do PrimeNG, `aria-label="Rows per page"`), permitindo escrever um seletor preciso sem acesso direto ao SIGA neste ambiente.

**Correção aplicada:** nova função `_select_max_downloads_page_size` localiza o dropdown (via `[aria-label='Rows per page']`, com fallback por classe `.p-paginator-rpp-options`), lê o texto de todas as opções da lista, identifica a de maior valor numérico (sem fixar um número no código) e a seleciona. Chamada uma vez ao entrar na tela de Downloads e reaplicada após cada `page.reload()` do fluxo (que reseta a preferência de volta ao padrão). Se o dropdown ou as opções não forem encontrados, registra aviso e mantém o comportamento anterior — sem regressão funcional.

**Status:** ✅ Aplicado (Sonnet 5, esforço `high`, `CHANGELOG.md` v1.5.4). Validado com 3 cenários de teste (mocks): seleção correta do maior valor (inclusive fora de ordem), ausência do seletor tratada sem exceção, opções sem texto numérico tratadas com `Escape` para fechar o dropdown sem selecionar nada. **Pendente:** confirmar no SIGA real quais valores de "linhas por página" estão realmente disponíveis (o usuário viu "10" como valor atual, mas as opções da lista aberta ainda não foram confirmadas) e o ganho de tempo efetivo em um lote real com histórico grande. **Efeito colateral encontrado em uso real:** esta mudança expôs o bug descrito no item 28 abaixo (já corrigido).

**Achado colateral (não corrigido, fora de escopo):** durante a investigação, `_download_requested_file`/`_find_download_row_by_screen_name` (por volta da linha 3063 e 3159 do arquivo) foram encontradas sem nenhuma chamada em todo o repositório — parecem ser código morto remanescente de uma versão anterior do fluxo de download (antes do lote via `_download_pending_detail_requests`), na mesma linha do item 10. Não removidas agora para não ampliar o escopo desta correção; candidatas a uma limpeza futura.

---

### 28. `_find_elements` podia devolver `None` e escapar dos tratamentos de erro existentes
**Local:** `src/utils/selenium_compat.py` (`Page._find_elements`, `Page._descendants`)

**Problema:** em casos raros, quando o elemento raiz consultado está no meio de uma re-renderização do DOM (comum na SPA Angular do SIGA), o Selenium pode devolver `None` em vez de uma lista vazia. Como `Error` (usado em quase todo `except` do projeto, inclusive em `_row_cell_texts`) é apenas um apelido para `WebDriverException`, e `TypeError` não é uma subclasse dele, o `TypeError: 'NoneType' object is not iterable` resultante escapava de **todos** os pontos do código que tentavam se proteger com `except Error:` — não só na Central de Downloads.

**Como foi descoberto:** relatado pelo usuário em uso real, logo após a mudança do item 27 entrar em produção. A seleção de 100 linhas por página causa uma re-renderização grande da tabela (10 → 100 linhas de uma vez), o que tornou muito mais provável bater nessa condição de corrida do Selenium durante a varredura subsequente. O bug em si é anterior ao item 27 e podia (mais raramente) afetar qualquer leitura de linha/célula em qualquer parte do extrator.

**Correção aplicada:** `_find_elements` e `_descendants` normalizam qualquer retorno `None` para lista vazia (`result if result is not None else []`), fazendo esse tipo de falha ser tratado pelos `except Error:` já existentes em todo o código, em vez de escapar como exceção não tratada. Reforço complementar em `_select_max_downloads_page_size` (item 27): espera pós-seleção aumentada de 500ms para 1.500ms, dando mais tempo ao Angular para terminar de renderizar a tabela maior antes da varredura começar.

**Status:** ✅ Aplicado (Sonnet 5, esforço `high`, `CHANGELOG.md` v1.5.5). Validado com teste de ponta a ponta reproduzindo a cadeia exata do crash relatado (`row.locator("td")` com `find_elements` retornando `None`): antes da correção, levantava `TypeError`; depois, resulta em `0` células encontradas (tratado normalmente pelo código existente). Testado também o caminho normal (lista real de elementos) para garantir que não houve regressão.

---

### 29. Varredura em lote silenciosa por minutos após a correção do item 27, sem log de progresso
**Local:** `src/extraction/siga_extractor.py` (`_scan_downloads_table_once`, `_scan_downloads_current_page_for_targets`, `_row_cell_texts`)

**Problema:** mesmo depois do item 28 (que impede o crash), a varredura em lote da Central de Downloads não registrava nenhum log durante seu andamento — nenhuma linha aparecia até a página inteira ser processada. Combinado com o timeout padrão de 2000ms por célula em `_row_cell_texts`, uma linha obsoleta logo após o re-render grande causado pela mudança de linhas por página (item 27) podia fazer cada célula dela esperar o timeout inteiro antes de desistir; numa tabela de dezenas de linhas, isso somava minutos de silêncio total no log.

**Como foi descoberto:** relatado pelo usuário em uso real — após aplicar corretamente o novo tamanho de página (50 linhas), o processo ficou ~11 minutos sem gravar nenhuma linha nova no log. Sem forma de diferenciar "ainda trabalhando, só que devagar" de "travado", o usuário encerrou o processo manualmente pelo Gerenciador de Tarefas, interrompendo a extração antes de chegar aos downloads.

**Correção aplicada:** (1) `_scan_downloads_table_once` agora registra uma linha de log a cada página varrida (com a contagem de solicitações já localizadas) e um resumo ao final — silêncio total no log nunca mais deve durar mais que o tempo de uma única página. (2) `_row_cell_texts` ganhou o parâmetro `cell_timeout_ms`, usado pela varredura em lote com um valor bem menor (400ms em vez do padrão de 2000ms) — reduz em até 5x o custo de cada célula obsoleta, sem alterar o timeout dos demais pontos do código que leem células de linha (mantidos em 2000ms).

**Status:** ✅ Aplicado (Sonnet 5, esforço `high`, `CHANGELOG.md` v1.5.6). Validado com mocks: log de progresso disparado a cada página varrida e resumo final; timeout de 400ms confirmado na varredura em lote e timeout padrão de 2000ms confirmado inalterado nos demais call sites de `_row_cell_texts`. **Limite de honestidade:** não foi possível confirmar contra o SIGA real qual é o mecanismo exato por trás do silêncio de 11 minutos (hipótese: acúmulo de timeouts de 2s em células obsoleto após o re-render da tabela) — a correção ataca o sintoma observável (silêncio + timeout longo) mesmo sem certeza absoluta da causa raiz exata; o log de progresso, por si só, já resolve o problema de "parecer travado" independentemente da causa.

---

*As Fases 1 (itens 1–4), 2 (itens 5–10), 3 (itens 11–18) e 4 (itens 19–24) já foram implementadas — código alterado em `src/extraction/siga_extractor.py`, `src/extraction/spreadsheet.py`, `src/utils/browser.py`, `src/utils/certificate_policy.py`, `src/utils/selenium_compat.py`, `src/auth/siga_login.py`, `src/main.py` e `src/gui.py`, registrado em `CHANGELOG.md` nas versões v1.4.4 a v1.4.9 e v1.5.3 a v1.5.6. O item 25 (refatoração transversal de `except Exception`) é tratado como iniciativa contínua a ser aplicada gradualmente. Os itens 26–29 (pós-plano) foram implementados a partir da análise de erros e comportamentos reais de execução.*
