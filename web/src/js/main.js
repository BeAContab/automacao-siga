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
 *   window.sigaOnExecutionFinished({status})      - fim da execucao (sucesso ou falha)
 *   window.sigaSetProgress(percent)               - barra de progresso
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

  /* ---------------------------- troca de modo ---------------------------- */

  function setMode(mode) {
    if (!S.MODES.includes(mode)) return;
    S.state.mode = mode;

    document.querySelectorAll('[data-screen]').forEach((section) => {
      section.hidden = section.dataset.screen !== mode;
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

    refreshExecuteButton();
    if (mode !== 'nfe') R.renderGrid(mode);
  }

  /**
   * Habilita o botao Executar. No modo NF-e ele nao depende do navegador (que nem
   * existe ali); nos outros, exige o navegador iniciado - mesma regra da versao
   * Tkinter, onde o botao so era liberado por _on_browser_start_succeeded.
   */
  function refreshExecuteButton() {
    const btn = document.getElementById('btn-execute');
    const browserBtn = document.getElementById('btn-start-browser');
    if (!btn) return;
    if (S.state.running) {
      btn.disabled = true;
    } else if (S.state.mode === 'nfe') {
      btn.disabled = false;
    } else {
      btn.disabled = !S.state.browserStarted;
    }
    if (browserBtn) browserBtn.disabled = S.state.running || S.state.browserStarted;
  }

  /** Bloqueia/libera os controles durante a execucao (equivale a _set_controls_state). */
  function setRunning(running) {
    S.state.running = running;
    document.querySelectorAll('#workspace button, #workspace input, #workspace select, #workspace textarea')
      .forEach((node) => { node.disabled = running; });
    refreshExecuteButton();
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
    'pick-nfce-spreadsheet': ['file', 'spreadsheet', 'nfce-spreadsheet'],
    'pick-nfce-base': ['file', 'spreadsheet', 'nfce-base-spreadsheet'],
    'pick-nfe-chrome': ['file', 'chrome', 'nfe-chrome-path'],
    'pick-siga-output': ['dir', 'siga_output', 'siga-output-dir'],
    'pick-nfce-keys': ['dir', 'nfce_keys', 'nfce-keys-folder'],
    'pick-nfce-output': ['dir', 'nfce_output', 'nfce-output-dir'],
    'pick-nfe-input': ['dir', 'nfe_input', 'nfe-input-folder'],
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
          case 'load-nfce-spreadsheet': return void await loadSpreadsheet('nfce');
          case 'load-manual': return void await loadManual(mode);
          case 'clear-manual':
            document.getElementById(mode + '-manual-cnpjs').value = '';
            return;
          case 'select-all-docs': return void setAllDocs(true);
          case 'clear-all-docs': return void setAllDocs(false);
          case 'select-all-incluir': return void setAllIncluir(true);
          case 'clear-all-incluir': return void setAllIncluir(false);
          case 'clear-rows': return void await clearRows(mode);
          case 'validate-rows': return void await validateRows(mode);
          case 'copy-log': return void copyLog();
          case 'start-browser': return void await startBrowser();
          case 'execute': return void await execute();
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
    const result = await Api.startBrowser();
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
    R.setStatus('Navegador iniciado. Faça o login manualmente e, depois, clique em Executar.');
  };

  window.sigaOnBrowserFailed = function (payload) {
    S.state.browserStarted = false;
    refreshExecuteButton();
    R.setStatus('Não foi possível abrir o navegador automaticamente: ' + payload.message);
  };

  window.sigaOnExecutionFinished = function (payload) {
    setRunning(false);
    R.setProgress(100);
    R.setStatus((payload && payload.status) || 'Execução finalizada.');
  };

  window.sigaSetProgress = function (percent) { R.setProgress(percent); };
  window.sigaSetStatus = function (text) { R.setStatus(text); };
  window.sigaShowMessage = function (payload) {
    Modal.alert(payload.message, payload.level || 'error');
  };

  /* ------------------------------- inicio -------------------------------- */

  async function boot() {
    wireEvents();
    setInputTab('siga', 'import');
    setInputTab('nfce', 'import');

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
    document.getElementById('siga-output-dir').value = initial.output_dir;
    document.getElementById('nfe-max-workers').value = initial.nfe_max_workers;
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
