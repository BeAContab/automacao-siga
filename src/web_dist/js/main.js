/*
 * Bootstrap da interface: liga os eventos do DOM, troca o modo ativo e expoe o
 * contrato que o Python chama de volta.
 *
 * ============================ CONTRATO Backend -> Frontend ============================
 * O Python (src/webui/bridge.py) chama estas funcoes globais via window.evaluate_js,
 * direto de qualquer thread. Renomear qualquer uma exige mudar o lado Python junto.
 *
 *   window.sigaAppendLog({text, level})           - uma linha no console de execucao
 *   window.sigaUpsertNfeResult({...})             - upsert de uma planilha na tabela NF-e
 *   window.sigaOnBrowserStarted()                 - navegador de depuracao abriu
 *   window.sigaOnBrowserFailed({message})         - falha ao abrir o navegador
 *   window.sigaOnNfceCompaniesLoaded({rows})      - empresas do portal carregadas (modo NFC-e)
 *   window.sigaOnExecutionFinished({status})      - fim da execucao (sucesso ou falha)
 *   window.sigaSetProgress(percent)               - barra de progresso
 *   window.sigaSetStageProgress({stage, percent}) - barra de progresso dedicada de uma etapa (Cadeia Completa)
 *   window.sigaSetStatus(text)                    - texto do rodape
 *   window.sigaShowMessage({message, level})      - erro vindo da thread de trabalho
 * =====================================================================================
 */
(function () {
  'use strict';

  const S = window.SigaState;
  const R = window.SigaRender;
  const Api = window.SigaApi;
  const Modal = window.SigaModal;

  let MODE_LABELS = {};
  let MODE_DESCRIPTIONS = {};

  function val(id) {
    const node = document.getElementById(id);
    return node ? node.value.trim() : '';
  }

  /**
   * Le a fonte de chaves do NFC-e conforme a aba ativa ("Pasta/arquivo" ou "Colar
   * chaves") - devolve so os campos relevantes pro payload da API, deixando a validacao
   * de negocio (obrigatoriedade, formato) pro lado Python, como o resto da interface ja faz.
   */
  function nfceKeysField() {
    const tab = S.state.inputTab['nfce-keys'] || 'file';
    if (tab === 'manual') {
      return {
        manual_keys_text: document.getElementById('nfce-manual-keys').value.trim(),
        manual_direcao: val('nfce-manual-direcao'),
      };
    }
    return { keys_folder: val('nfce-keys-folder') };
  }

  /**
   * O modo 'chain' (cadeia completa) reaproveita a tela e o estado ('rows.siga' etc.)
   * do modo 'siga' inteiros - so acrescenta um bloco de campos extras. Onde o codigo
   * precisa de uma chave de estado/DOM ligada a grade (renderGrid, limpar linhas...),
   * usa-se esta traducao em vez do modo bruto.
   */
  function gridMode(mode) {
    return mode === 'chain' ? 'siga' : mode;
  }

  /* ---------------------------- troca de modo ---------------------------- */

  function setMode(mode) {
    if (!S.MODES.includes(mode)) return;
    S.state.mode = mode;

    document.querySelectorAll('[data-screen]').forEach((section) => {
      section.hidden = section.dataset.screen !== gridMode(mode);
    });

    // Campos extras da cadeia completa (NF-e/NFC-e) só aparecem no modo 'chain'.
    document.querySelectorAll('[data-chain-only]').forEach((node) => {
      node.hidden = mode !== 'chain';
    });

    // Barra de progresso única (demais modos) some no modo 'chain', que usa 3 barras
    // dedicadas (uma por etapa) em vez de uma faixa só dividida entre elas.
    document.querySelectorAll('[data-hide-in-chain]').forEach((node) => {
      node.hidden = mode === 'chain';
    });

    document.querySelectorAll('.nav-item').forEach((btn) => {
      const active = btn.dataset.mode === mode;
      btn.classList.toggle('siga-nav-active', active);
      btn.classList.toggle('border-siga-gold', active);
      btn.classList.toggle('border-transparent', !active);
      btn.classList.toggle('text-siga-petrol', active);
      btn.classList.toggle('font-bold', active);
      btn.classList.toggle('text-on-surface-variant', !active);
    });

    const desc = document.getElementById('mode-description');
    if (desc) desc.textContent = MODE_DESCRIPTIONS[mode] || '';

    const label = document.getElementById('btn-execute-label');
    if (label) label.textContent = MODE_LABELS[mode] || 'Executar';

    // "Iniciar Navegador" so faz sentido em SIGA/NFC-e: o modo NF-e e consulta publica
    // e gerencia os proprios Chromes, sem BrowserSession.
    const browserBtn = document.getElementById('btn-start-browser');
    if (browserBtn) browserBtn.hidden = mode === 'nfe';

    // "Login / Carregar Empresas" e exclusivo do NFC-e (login automatico + raspagem
    // de empresas do portal - substitui a antiga importacao de planilha).
    const nfceLoadBtn = document.getElementById('btn-nfce-load-companies');
    if (nfceLoadBtn) nfceLoadBtn.hidden = mode !== 'nfce';

    refreshExecuteButton();
    if (mode !== 'nfe') R.renderGrid(gridMode(mode));
  }

  /**
   * Habilita o botao Executar. No modo NF-e ele nao depende do navegador (que nem
   * existe ali); nos outros, exige o navegador iniciado - mesma regra da versao
   * Tkinter, onde o botao so era liberado por _on_browser_start_succeeded.
   */
  function refreshExecuteButton() {
    const btn = document.getElementById('btn-execute');
    const browserBtn = document.getElementById('btn-start-browser');
    const nfceLoadBtn = document.getElementById('btn-nfce-load-companies');
    const pauseResumeBtn = document.getElementById('btn-pause-resume');
    const pauseResumeLabel = document.getElementById('btn-pause-resume-label');
    const pauseResumeIcon = document.getElementById('btn-pause-resume-icon');
    const stopBtn = document.getElementById('btn-stop-execution');
    if (!btn) return;
    if (S.state.running) {
      btn.disabled = true;
    } else if (S.state.mode === 'nfe') {
      btn.disabled = false;
    } else {
      btn.disabled = !S.state.browserStarted;
    }
    if (browserBtn) browserBtn.disabled = S.state.running || S.state.browserStarted;
    // So faz sentido logar/carregar empresas depois que o navegador estiver de pe.
    if (nfceLoadBtn) nfceLoadBtn.disabled = S.state.running || !S.state.browserStarted;
    // Pausar/Continuar e Encerrar so fazem sentido com uma execucao de fato em andamento.
    if (pauseResumeBtn) {
      pauseResumeBtn.hidden = !S.state.running;
      pauseResumeBtn.disabled = !S.state.running;
    }
    if (pauseResumeLabel) pauseResumeLabel.textContent = S.state.paused ? 'Continuar' : 'Pausar';
    if (pauseResumeIcon) pauseResumeIcon.textContent = S.state.paused ? 'play_arrow' : 'pause';
    if (stopBtn) {
      stopBtn.hidden = !S.state.running;
      stopBtn.disabled = !S.state.running;
    }
  }

  /** Bloqueia/libera os controles durante a execucao (equivale a _set_controls_state). */
  function setRunning(running) {
    S.state.running = running;
    if (!running) S.state.paused = false; // nunca fica "pausado" fora de uma execucao ativa
    document.querySelectorAll('#workspace button, #workspace input, #workspace select, #workspace textarea')
      .forEach((node) => { node.disabled = running; });
    refreshExecuteButton();
  }

  /** Alterna pausar/continuar a execucao em andamento. */
  async function togglePauseResume() {
    if (!S.state.running) return;
    const result = S.state.paused ? await Api.resumeExtraction() : await Api.pauseExtraction();
    if (result && result.ok) {
      S.state.paused = !S.state.paused;
      refreshExecuteButton();
    } else if (result && result.error) {
      await Modal.alert(result.error, 'error');
    }
  }

  /** Encerra a execucao em andamento por completo, apos confirmacao (acao destrutiva). */
  async function stopExecution() {
    if (!S.state.running) return;
    const confirmed = await Modal.confirm(
      'Encerrar a execução agora? O que já foi solicitado/baixado fica salvo, mas o restante do lote não será processado. Esta ação não pode ser desfeita.',
      { level: 'warning', okLabel: 'Encerrar', cancelLabel: 'Cancelar' }
    );
    if (!confirmed) return;
    const result = await Api.stopExtraction();
    if (result && !result.ok && result.error) {
      await Modal.alert(result.error, 'error');
    }
    // A UI volta ao estado normal via sigaOnExecutionFinished, disparado pelo Python
    // assim que a thread de trabalho efetivamente terminar (nao precisa de setRunning aqui).
  }

  /* ------------------------------- entrada ------------------------------- */

  function setInputTab(mode, tab) {
    S.state.inputTab[mode] = tab;
    document.querySelectorAll('[data-tabs="' + mode + '"] .input-tab').forEach((btn) => {
      const active = btn.dataset.tab === tab;
      btn.classList.toggle('border-siga-gold', active);
      btn.classList.toggle('text-siga-petrol', active);
      btn.classList.toggle('border-transparent', !active);
      btn.classList.toggle('text-on-surface-variant', !active);
    });
    document.querySelectorAll('[data-tab-panel^="' + mode + '-"]').forEach((panel) => {
      panel.hidden = panel.dataset.tabPanel !== mode + '-' + tab;
    });
  }

  function applyLoadedRows(mode, result, sourceLabel) {
    S.state.rows[mode] = (result.rows || []).map(S.makeRow);
    S.state.sourceLabel[mode] = sourceLabel;
    R.renderGrid(mode);
    R.setStatus(sourceLabel);
  }

  async function loadSpreadsheet(mode) {
    const path = document.getElementById(mode + '-spreadsheet').value.trim();
    if (!path) {
      await Modal.alert('Selecione o arquivo .xlsx antes de carregar.', 'warning');
      return;
    }
    const result = await Api.loadSpreadsheet(path);
    if (!result.ok) {
      S.state.rows[mode] = [];
      S.state.sourceLabel[mode] = result.error;
      R.renderGrid(mode);
      await Modal.alert(result.error, 'error');
      return;
    }
    setInputTab(mode, 'import');
    applyLoadedRows(mode, result, 'Planilha carregada com ' + result.rows.length + ' empresa(s).');
  }

  async function loadManual(mode) {
    const text = document.getElementById(mode + '-manual-cnpjs').value.trim();
    if (!text) {
      await Modal.alert('Digite pelo menos um CNPJ no campo manual.', 'warning');
      return;
    }
    const result = await Api.loadManualCnpjs(text);
    if (!result.ok) {
      await Modal.alert(result.error, 'error');
      return;
    }
    setInputTab(mode, 'manual');
    applyLoadedRows(mode, result, 'Entrada manual: ' + result.rows.length + ' CNPJ(s) carregado(s).');
  }

  /* ------------------------------- dialogos ------------------------------ */

  // kind -> [metodo da ponte, id do campo que recebe o caminho escolhido]
  const PICKERS = {
    'pick-siga-spreadsheet': ['file', 'spreadsheet', 'siga-spreadsheet'],
    'pick-nfce-base': ['file', 'spreadsheet', 'nfce-base-spreadsheet'],
    'pick-nfe-chrome': ['file', 'chrome', 'nfe-chrome-path'],
    'pick-siga-output': ['dir', 'siga_output', 'siga-output-dir'],
    'pick-nfce-keys': ['dir', 'nfce_keys', 'nfce-keys-folder'],
    'pick-nfce-keys-file': ['file', 'spreadsheet', 'nfce-keys-folder'],
    'pick-nfce-output': ['dir', 'nfce_output', 'nfce-output-dir'],
    'pick-nfe-input': ['dir', 'nfe_input', 'nfe-input-folder'],
    'pick-nfe-input-file': ['file', 'spreadsheet', 'nfe-input-folder'],
    'pick-nfe-output': ['dir', 'nfe_output', 'nfe-output-dir'],
    'pick-chain-nfce-base': ['file', 'spreadsheet', 'chain-nfce-base-spreadsheet'],
    'pick-chain-nfe-chrome': ['file', 'chrome', 'chain-nfe-chrome-path'],
  };

  async function runPicker(action) {
    const spec = PICKERS[action];
    if (!spec) return;
    const [type, kind, targetId] = spec;
    const chosen = type === 'file' ? await Api.pickFile(kind) : await Api.pickDirectory(kind);
    if (!chosen) return; // usuario cancelou: mantem o valor anterior
    document.getElementById(targetId).value = chosen;
    // Escolher a planilha ja sugere a pasta de saida ao lado dela (comodidade que a
    // versao Tkinter tinha em _browse_spreadsheet).
    if (action === 'pick-siga-spreadsheet') {
      const outputField = document.getElementById('siga-output-dir');
      if (outputField && !outputField.value.trim()) {
        outputField.value = chosen.replace(/[\\/][^\\/]*$/, '');
      }
    }
  }

  /* ---------------------------- acoes da grade --------------------------- */

  function setAllDocs(enabled) {
    S.state.rows.siga.forEach((row) => {
      row.nfe = enabled; row.nfce = enabled; row.cte = enabled; row.malha = enabled; row.debitos = enabled;
    });
    R.renderGrid('siga');
  }

  function toggleDocColumn(field) {
    const rows = S.state.rows.siga;
    if (!rows.length) return;
    const enable = !rows.every((row) => row[field]);
    rows.forEach((row) => { row[field] = enable; });
    R.renderGrid('siga');
  }

  function setAllIncluir(enabled) {
    S.state.rows.nfce.forEach((row) => { row.incluir = enabled; });
    R.renderGrid('nfce');
  }

  async function clearRows(mode) {
    S.state.rows[mode] = [];
    S.state.sourceLabel[mode] = 'Nenhuma planilha carregada ainda.';
    R.renderGrid(mode);
    R.setProgress(0);
    R.setStatus('Lista de empresas limpa.');
  }

  async function validateRows(mode) {
    const count = S.state.rows[mode].length;
    if (!count) {
      await Modal.alert('Carregue pelo menos uma empresa antes de validar.', 'warning');
      return;
    }
    R.setStatus(count + ' empresa(s) prontas para execução.');
    await Modal.alert(count + ' empresa(s) prontas para execução.', 'success');
  }

  /**
   * Substitui a antiga importação de planilha/entrada manual do modo NFC-e: loga no
   * portal SEFAZ-CE e devolve (de forma assíncrona, via window.sigaOnNfceCompaniesLoaded)
   * as empresas elegíveis, já cruzadas com a planilha-base IE/CNPJ e a pasta de chaves.
   */
  async function loadNfceCompanies() {
    const cpf = val('nfce-cpf');
    const senha = document.getElementById('nfce-senha').value;
    if (!cpf || !senha) {
      await Modal.alert('Informe o CPF e a senha do contador antes de usar o modo NFC-e.', 'error');
      return;
    }
    const baseSpreadsheet = val('nfce-base-spreadsheet');
    if (!baseSpreadsheet) {
      await Modal.alert('Selecione a planilha-base IE/CNPJ.', 'warning');
      return;
    }
    const keysField = nfceKeysField();
    if (!keysField.keys_folder && !keysField.manual_keys_text) {
      await Modal.alert('Selecione a pasta/arquivo de chaves, ou cole as chaves manualmente.', 'warning');
      return;
    }

    const btn = document.getElementById('btn-nfce-load-companies');
    if (btn) btn.disabled = true;
    R.setStatus('Carregando empresas do portal SEFAZ-CE... aguarde.');

    const result = await Api.loadNfceCompanies({
      cpf: cpf,
      senha: senha,
      base_spreadsheet: baseSpreadsheet,
      ...keysField,
    });
    if (result && !result.ok) {
      if (btn) btn.disabled = false;
      await Modal.alert(result.error, result.level || 'error');
    }
    // Sucesso real (empresas carregadas ou falha durante o login/raspagem) chega de
    // forma assincrona por window.sigaOnNfceCompaniesLoaded / sigaShowMessage.
  }

  /* ------------------------------- eventos ------------------------------- */

  function wireEvents() {
    document.querySelectorAll('.nav-item').forEach((btn) => {
      btn.addEventListener('click', () => setMode(btn.dataset.mode));
    });

    document.querySelectorAll('[data-tabs]').forEach((group) => {
      const mode = group.dataset.tabs;
      group.querySelectorAll('.input-tab').forEach((btn) => {
        btn.addEventListener('click', () => setInputTab(mode, btn.dataset.tab));
      });
    });

    document.querySelectorAll('[data-doc-col]').forEach((btn) => {
      btn.addEventListener('click', () => toggleDocColumn(btn.dataset.docCol));
    });

    // Delegacao: um unico listener para todos os data-action da pagina.
    document.addEventListener('click', async (event) => {
      const target = event.target.closest('[data-action]');
      if (!target || target.disabled) return;
      const action = target.dataset.action;
      const mode = S.state.mode;

      try {
        if (action.startsWith('pick-')) return void await runPicker(action);

        switch (action) {
          case 'load-siga-spreadsheet': return void await loadSpreadsheet('siga');
          case 'load-manual': return void await loadManual(gridMode(mode));
          case 'clear-manual':
            document.getElementById(gridMode(mode) + '-manual-cnpjs').value = '';
            return;
          case 'select-all-docs': return void setAllDocs(true);
          case 'clear-all-docs': return void setAllDocs(false);
          case 'select-all-incluir': return void setAllIncluir(true);
          case 'clear-all-incluir': return void setAllIncluir(false);
          case 'clear-rows': return void await clearRows(gridMode(mode));
          case 'validate-rows': return void await validateRows(gridMode(mode));
          case 'load-nfce-companies': return void await loadNfceCompanies();
          case 'copy-log': return void copyLog();
          case 'start-browser': return void await startBrowser();
          case 'execute': return void await execute();
          case 'pause-resume': return void await togglePauseResume();
          case 'stop-execution': return void await stopExecution();
          default: return;
        }
      } catch (error) {
        await Modal.alert('Erro inesperado na interface: ' + (error && error.message ? error.message : error), 'error');
      }
    });
  }

  function copyLog() {
    const box = document.getElementById('console-log');
    if (!box) return;
    navigator.clipboard.writeText(box.innerText || '')
      .then(() => R.setStatus('Log copiado para a área de transferência.'))
      .catch(() => R.setStatus('Não foi possível copiar o log.'));
  }

  async function startBrowser() {
    if (S.state.browserStarted) {
      R.setStatus('O navegador já foi iniciado. Faça o login manual e clique em Executar.');
      return;
    }
    const btn = document.getElementById('btn-start-browser');
    if (btn) btn.disabled = true;
    R.setStatus('Iniciando o navegador... aguarde.');
    const result = await Api.startBrowser(S.state.mode);
    if (result && !result.ok) {
      if (btn) btn.disabled = false;
      await Modal.alert(result.error, 'error');
    }
  }

  async function execute() {
    if (S.state.running) {
      await Modal.alert('Uma execução já está em andamento.', 'info');
      return;
    }
    setRunning(true);
    R.setProgress(0);
    const started = await window.SigaScreens.run(S.state.mode);
    if (!started) setRunning(false); // validacao barrou: libera os controles de novo
  }

  /* -------------------- contrato chamado pelo Python --------------------- */

  window.sigaAppendLog = function (entry) {
    S.pushLogLine(entry);
    R.appendLogLine(entry);
  };

  window.sigaUpsertNfeResult = function (result) {
    S.upsertNfeResult(result);
    R.upsertNfeRow(result);
  };

  window.sigaOnBrowserStarted = function () {
    S.state.browserStarted = true;
    refreshExecuteButton();
    R.setStatus(
      S.state.mode === 'nfce'
        ? 'Navegador iniciado. Clique em "Login / Carregar Empresas" para logar automaticamente.'
        : 'Navegador iniciado. Faça o login manualmente e, depois, clique em Executar.'
    );
  };

  window.sigaOnBrowserFailed = function (payload) {
    S.state.browserStarted = false;
    refreshExecuteButton();
    R.setStatus('Não foi possível abrir o navegador automaticamente: ' + payload.message);
  };

  window.sigaOnNfceCompaniesLoaded = function (payload) {
    const btn = document.getElementById('btn-nfce-load-companies');
    if (btn) btn.disabled = false;
    applyLoadedRows('nfce', payload, payload.rows.length + ' empresa(s) encontrada(s) no portal.');
  };

  window.sigaOnExecutionFinished = function (payload) {
    setRunning(false);
    R.setProgress(100);
    if (S.state.mode === 'chain') {
      ['siga', 'nfe', 'nfce'].forEach((stage) => R.setStageProgress(stage, 100));
    }
    R.setStatus((payload && payload.status) || 'Execução finalizada.');
  };

  window.sigaSetProgress = function (percent) { R.setProgress(percent); };
  window.sigaSetStageProgress = function (payload) { R.setStageProgress(payload.stage, payload.percent); };
  window.sigaSetStatus = function (text) { R.setStatus(text); };
  window.sigaShowMessage = function (payload) {
    // Reabilita o botao de carregar empresas do NFC-e caso a falha assincrona tenha
    // vindo dali (login/raspagem do portal falhou dentro da thread de trabalho).
    const nfceLoadBtn = document.getElementById('btn-nfce-load-companies');
    if (nfceLoadBtn) nfceLoadBtn.disabled = false;
    Modal.alert(payload.message, payload.level || 'error');
  };

  /* ------------------------------- inicio -------------------------------- */

  async function boot() {
    wireEvents();
    setInputTab('siga', 'import');
    setInputTab('nfce-keys', 'file');

    const initial = await Api.getInitialState();
    MODE_LABELS = initial.mode_labels;
    MODE_DESCRIPTIONS = initial.mode_descriptions;

    document.getElementById('app-version').textContent = 'v' + initial.version;

    const monthSelect = document.getElementById('siga-month');
    initial.months.forEach((month) => {
      const option = document.createElement('option');
      option.value = month;
      option.textContent = month;
      monthSelect.appendChild(option);
    });
    monthSelect.value = initial.month;
    document.getElementById('siga-year').value = initial.year;
    // "Pasta de saída" fica em branco de propósito - o usuário sempre escolhe na hora,
    // sem sugestão de pasta anterior/padrão (pedido do usuário).
    document.getElementById('nfe-max-workers').value = initial.nfe_max_workers;
    document.getElementById('chain-nfe-max-workers').value = initial.nfe_max_workers;
    // Planilha-base CNPJ/IE do NFC-e: mesmo arquivo de rede do escritório em toda
    // execução, então já vem pré-preenchida (nos dois lugares onde existe o campo:
    // modo NFC-e isolado e a etapa NFC-e da Cadeia Completa) - continua trocável.
    if (initial.nfce_base_spreadsheet) {
      document.getElementById('nfce-base-spreadsheet').value = initial.nfce_base_spreadsheet;
      document.getElementById('chain-nfce-base-spreadsheet').value = initial.nfce_base_spreadsheet;
    }
    if (initial.spreadsheet) document.getElementById('siga-spreadsheet').value = initial.spreadsheet;

    setMode('siga');

    // Avisa o Python que o DOM esta pronto: ele so entao troca o buffer de replay de
    // log por chamadas diretas de evaluate_js (ver bridge.py).
    await Api.onWindowReady();

    if (initial.rows && initial.rows.length) {
      applyLoadedRows('siga', { rows: initial.rows }, 'Planilha carregada com ' + initial.rows.length + ' empresa(s).');
    }
  }

  /** Manda o erro para o log do Python e mostra algo no rodapé, em vez de falhar mudo. */
  function reportError(context, error) {
    const message = context + ': ' + (error && error.message ? error.message : error);
    R.setStatus(message);
    try {
      Api.reportError(message, (error && error.stack) || '');
    } catch (_) {
      /* a ponte pode nem existir ainda; o rodapé já mostrou a mensagem */
    }
  }

  // Rede de segurança: qualquer erro não tratado da interface vira registro no log.
  window.addEventListener('error', (event) => reportError('Erro na interface', event.error || event.message));
  window.addEventListener('unhandledrejection', (event) => reportError('Promessa rejeitada', event.reason));

  document.addEventListener('DOMContentLoaded', () => {
    boot().catch((error) => reportError('Falha ao iniciar a interface', error));
  });
})();
