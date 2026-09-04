/*
 * Renderizacao do DOM a partir do estado.
 *
 * Cuidado importante com o Tailwind: as classes usadas aqui sao SEMPRE strings
 * completas e estaticas (nunca `bg-${cor}-500`). O CSS e compilado com purge, entao
 * uma classe montada por concatenacao simplesmente nao existiria no styles.css final
 * e o estilo quebraria so em producao. O mapa STATUS_STYLE abaixo e o unico lookup de
 * classe do app e por isso esta espelhado na safelist do tailwind.config.js.
 */
(function () {
  'use strict';

  const S = window.SigaState;

  /* ----------------------------- utilidades ----------------------------- */

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  /* -------------------------- grade de empresas -------------------------- */

  const CHECKBOX_CLASS = 'rounded border-siga-slate text-siga-petrol focus:ring-siga-petrol w-4 h-4 cursor-pointer';
  const DOC_FIELDS = ['nfe', 'nfce', 'cte', 'malha', 'debitos'];

  function docCheckboxCell(row, field) {
    const td = el('td', 'py-2 px-1 text-center');
    const input = el('input', CHECKBOX_CLASS);
    input.type = 'checkbox';
    input.checked = !!row[field];
    // Mutacao local: nenhuma ida ao Python a cada clique - so quando executar.
    input.addEventListener('change', () => {
      row[field] = input.checked;
    });
    td.appendChild(input);
    return td;
  }

  /**
   * Desenha a grade do modo informado. SIGA usa 5 colunas de documento; NFC-e usa uma
   * coluna "Chaves" (quantas chaves foram encontradas para a empresa) e uma unica
   * coluna "Incluir" (nao existe escolha por tipo de documento nesse fluxo).
   */
  function renderGrid(mode) {
    const body = document.querySelector('[data-grid-body="' + mode + '"]');
    if (!body) return;
    const rows = S.state.rows[mode];
    body.textContent = '';

    if (!rows.length) {
      const tr = el('tr');
      const td = el('td', 'py-lg px-md text-center text-body-sm text-on-surface-variant');
      if (mode === 'siga') {
        td.colSpan = 7;
        td.textContent = 'Nenhuma empresa carregada — importe uma planilha ou use a entrada manual.';
      } else {
        td.colSpan = 4;
        td.textContent = 'Nenhuma empresa carregada — clique em "Login / Carregar Empresas".';
      }
      tr.appendChild(td);
      body.appendChild(tr);
    } else {
      rows.forEach((row) => {
        const tr = el('tr', 'border-b border-outline-variant/20 hover:bg-secondary-container/20');
        const codClass = mode === 'siga'
          ? 'py-2 px-sm text-siga-slate font-console-text'
          : 'py-2 px-md text-center text-siga-slate font-console-text';
        tr.appendChild(el('td', codClass, row.cod));

        const nome = el('td', (mode === 'siga' ? 'py-2 px-sm' : 'py-2 px-md') + ' font-medium', row.empresa);
        nome.title = row.cnpj ? row.empresa + ' — ' + row.cnpj : row.empresa;
        tr.appendChild(nome);

        if (mode === 'siga') {
          DOC_FIELDS.forEach((field) => tr.appendChild(docCheckboxCell(row, field)));
        } else {
          tr.appendChild(el('td', 'py-2 px-md text-center text-siga-slate font-console-text', row.chavesCount));
          tr.appendChild(docCheckboxCell(row, 'incluir'));
        }
        body.appendChild(tr);
      });
    }

    const chip = document.querySelector('[data-count-chip="' + mode + '"]');
    if (chip) chip.textContent = 'Total carregadas: ' + rows.length;

    const label = document.querySelector('[data-source-label="' + mode + '"]');
    if (label) label.textContent = S.state.sourceLabel[mode];
  }

  /* ---------------------- tabela de resultados NF-e ---------------------- */

  // status_code vem pronto do Python (api.py); aqui so escolhemos icone e cor.
  const STATUS_STYLE = {
    concluido: { icon: 'check_circle', cls: 'text-status-green', spin: false },
    andamento: { icon: 'sync', cls: 'text-status-amber', spin: true },
    parcial: { icon: 'warning', cls: 'text-status-orange', spin: false },
    erro: { icon: 'error', cls: 'text-error', spin: false },
    sem_chaves: { icon: 'pending', cls: 'text-on-surface-variant', spin: false },
  };

  function statusCell(result) {
    const style = STATUS_STYLE[result.status_code] || STATUS_STYLE.sem_chaves;
    const td = el('td', 'p-sm font-medium ' + style.cls);
    const wrap = el('div', 'flex items-center gap-xs whitespace-nowrap');
    const icon = el('span', 'material-symbols-outlined text-[16px] shrink-0' + (style.spin ? ' animate-spin' : ''), style.icon);
    wrap.appendChild(icon);
    wrap.appendChild(el('span', null, result.status_label));
    td.appendChild(wrap);
    return td;
  }

  function buildNfeRow(result) {
    const tr = el('tr', 'border-b border-outline-variant/20');
    tr.dataset.planilha = result.caminho;
    // O caminho completo fica no title: o nome da planilha e longo e a coluna trunca.
    const nome = el('td', 'p-sm font-medium truncate', result.nome);
    nome.title = result.caminho;
    tr.appendChild(nome);
    tr.appendChild(el('td', 'p-sm text-center', result.chaves_total));
    tr.appendChild(el('td', 'p-sm text-center', result.chaves_baixadas));
    tr.appendChild(el('td', 'p-sm text-center', result.chaves_puladas));
    tr.appendChild(el('td', 'p-sm text-center' + (result.chaves_com_falha ? ' text-error font-medium' : ''), result.chaves_com_falha));
    tr.appendChild(statusCell(result));
    return tr;
  }

  /** Insere a linha na primeira vez; nas seguintes so troca as celulas (sem flicker). */
  function upsertNfeRow(result) {
    const body = document.getElementById('nfe-results-body');
    const empty = document.getElementById('nfe-empty-state');
    if (!body) return;

    const existing = body.querySelector('tr[data-planilha="' + CSS.escape(result.caminho) + '"]');
    const fresh = buildNfeRow(result);
    if (existing) {
      body.replaceChild(fresh, existing);
    } else {
      body.appendChild(fresh);
    }
    if (empty) empty.hidden = body.children.length > 0;

    const summary = S.nfeSummary();
    const chip = document.getElementById('nfe-summary');
    if (chip) chip.textContent = summary.done + ' de ' + summary.total + ' planilha(s) concluída(s)';
  }

  function clearNfeResults() {
    const body = document.getElementById('nfe-results-body');
    const empty = document.getElementById('nfe-empty-state');
    if (body) body.textContent = '';
    if (empty) empty.hidden = false;
    const chip = document.getElementById('nfe-summary');
    if (chip) chip.textContent = '0 de 0 planilha(s) concluída(s)';
  }

  /* ------------------------------- console ------------------------------- */

  // Mesmas cores por nivel que o tk.Text usava via tags (log_info/success/warning/error).
  const LOG_COLOR = {
    info: 'text-[#d4d4d4]',
    success: 'text-[#34d399]',
    warning: 'text-[#e97000]',
    error: 'text-[#f87171]',
  };

  function appendLogLine(entry) {
    const box = document.getElementById('console-log');
    if (!box) return;
    // Append incremental: nunca redesenha o console inteiro, mesmo com milhares de linhas.
    const line = el('div', LOG_COLOR[entry.level] || LOG_COLOR.info, entry.text);
    box.appendChild(line);
    while (box.children.length > 2000) box.removeChild(box.firstChild);
    box.scrollTop = box.scrollHeight;
  }

  function clearLog() {
    const box = document.getElementById('console-log');
    if (box) box.textContent = '';
  }

  /* ------------------------------ progresso ------------------------------ */

  function setProgress(percent) {
    const value = Math.max(0, Math.min(100, Number(percent) || 0));
    const bar = document.getElementById('progress-bar');
    const label = document.getElementById('progress-label');
    if (bar) bar.style.width = value + '%';
    if (label) label.textContent = Math.round(value) + '%';
  }

  function setStatus(text) {
    const node = document.getElementById('status-text');
    if (node) node.textContent = text;
  }

  window.SigaRender = {
    renderGrid: renderGrid,
    upsertNfeRow: upsertNfeRow,
    clearNfeResults: clearNfeResults,
    appendLogLine: appendLogLine,
    clearLog: clearLog,
    setProgress: setProgress,
    setStatus: setStatus,
  };
})();
