/*
 * Logica especifica de cada modo: validar o formulario, montar o payload e disparar a
 * execucao no Python.
 *
 * As validacoes daqui sao as mesmas (mesmo texto) que a versao Tkinter fazia com
 * messagebox antes de iniciar a thread de trabalho. Elas existem para dar resposta
 * imediata ao usuario - o Python revalida tudo de qualquer forma (defesa em
 * profundidade), porque esta camada e so a interface.
 */
(function () {
  'use strict';

  const S = window.SigaState;
  const Api = window.SigaApi;
  const Modal = window.SigaModal;

  function val(id) {
    const node = document.getElementById(id);
    return node ? node.value.trim() : '';
  }

  /** Traduz {ok:false, error, level} devolvido pelo Python num modal, e devolve false. */
  async function handleBackendResult(result) {
    if (result && result.ok) return true;
    const message = (result && result.error) || 'Não foi possível iniciar a execução.';
    await Modal.alert(message, (result && result.level) || 'error');
    return false;
  }

  /* -------------------------------- SIGA -------------------------------- */

  async function runSiga() {
    if (!S.state.browserStarted) {
      await Modal.alert("Clique em 'Iniciar Navegador' e faça o login antes de executar.", 'warning');
      return false;
    }
    const outputDir = val('siga-output-dir');
    if (!outputDir) {
      await Modal.alert('Informe uma pasta de saída válida.', 'warning');
      return false;
    }
    const selection = S.collectSigaSelection();
    if (!selection.length) {
      await Modal.alert('Selecione pelo menos um CNPJ e uma aba fiscal.', 'warning');
      return false;
    }
    const month = val('siga-month');
    if (!month) {
      await Modal.alert('Informe o mês de referência.', 'warning');
      return false;
    }
    const year = val('siga-year');
    if (!/^\d{4}$/.test(year)) {
      await Modal.alert('Informe um ano válido com 4 dígitos.', 'warning');
      return false;
    }

    return handleBackendResult(await Api.startSiga({
      rows: selection,
      month: month,
      year: year,
      output_dir: outputDir,
      // O Python usa isso para decidir entre copiar a planilha de origem ou gerar uma
      // planilha de resultados nova (o equivalente ao is_manual_mode da versao Tkinter).
      manual_mode: S.state.inputTab.siga === 'manual',
      spreadsheet_path: val('siga-spreadsheet'),
    }));
  }

  /* -------------------------------- NFC-e ------------------------------- */

  async function runNfce() {
    if (!S.state.browserStarted) {
      await Modal.alert("Clique em 'Iniciar Navegador' antes de executar o modo NFC-e.", 'warning');
      return false;
    }
    const cpf = val('nfce-cpf');
    const senha = document.getElementById('nfce-senha').value;
    if (!cpf || !senha) {
      await Modal.alert('Informe o CPF e a senha do contador antes de usar o modo NFC-e.', 'error');
      return false;
    }
    const outputDir = val('nfce-output-dir');
    if (!outputDir) {
      await Modal.alert('Selecione a pasta de saída dos XMLs de NFC-e.', 'warning');
      return false;
    }
    const keysFolder = val('nfce-keys-folder');
    if (!keysFolder) {
      await Modal.alert('Selecione a pasta com as planilhas de chaves por empresa.', 'warning');
      return false;
    }
    const selection = S.collectNfceSelection();
    if (!selection.length) {
      await Modal.alert('Carregue pelo menos uma empresa (planilha ou entrada manual) antes de executar.', 'warning');
      return false;
    }

    return handleBackendResult(await Api.startNfce({
      rows: selection,
      output_dir: outputDir,
      keys_folder: keysFolder,
      base_spreadsheet: val('nfce-base-spreadsheet'),
      // CPF/senha trafegam so nesta chamada e vivem em memoria do lado Python pelo
      // tempo da execucao - nunca sao gravados em .env, planilha ou log.
      cpf: cpf,
      senha: senha,
    }));
  }

  /* --------------------------------- NF-e ------------------------------- */

  async function runNfe() {
    const inputFolder = val('nfe-input-folder');
    if (!inputFolder) {
      await Modal.alert('Selecione a pasta com as planilhas NF-e.', 'warning');
      return false;
    }
    const workers = parseInt(val('nfe-max-workers'), 10);
    if (!Number.isInteger(workers) || workers < 1 || workers > 4) {
      await Modal.alert('Informe uma quantidade de Chromes entre 1 e 4.', 'warning');
      return false;
    }

    // Zera a tabela para nao misturar contagens com a execucao anterior.
    S.resetNfeResults();
    window.SigaRender.clearNfeResults();

    return handleBackendResult(await Api.startNfe({
      input_folder: inputFolder,
      max_workers: workers,
      chrome_path: val('nfe-chrome-path'),
    }));
  }

  window.SigaScreens = {
    run: function (mode) {
      if (mode === 'nfce') return runNfce();
      if (mode === 'nfe') return runNfe();
      return runSiga();
    },
  };
})();
