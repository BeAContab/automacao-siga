/**
 * Tokens de design do SIGA Automacao.
 *
 * Copiados dos blocos <script id="tailwind-config"> dos mockups gerados no Stitch
 * (design/extra_o_siga, design/extra_o_nfc_e_atualizada, design/extra_o_nf_e_atualizada),
 * que por sua vez batem com design/accounting_automation_suite/DESIGN.md e com as
 * constantes BRAND_* que a GUI Tkinter usava. Os tres mockups compartilham o mesmo
 * dicionario base; as cores "status-*" so aparecem no mockup de NF-e, entao aqui elas
 * ficam unificadas para os tres.
 *
 * Nao reescrever estes valores "de memoria": eles sao a fonte de verdade visual do
 * produto e devem ser alterados junto com o DESIGN.md.
 */
module.exports = {
  darkMode: 'class',
  // Inclui os parciais HTML e todo o JS que monta markup, para o purge do Tailwind
  // enxergar as classes usadas. Classes montadas dinamicamente NAO sao detectadas -
  // por isso o codigo JS sempre usa classes completas e estaticas (ver safelist abaixo).
  content: ['./src/**/*.html', './src/**/*.js'],
  // Classes que so existem em tabelas de lookup no JS (mapa de status -> cor). Sao
  // strings completas, mas ficam explicitas aqui como rede de seguranca, ja que sao o
  // unico ponto onde uma classe pode nao aparecer literalmente no markup estatico.
  safelist: [
    'text-status-green',
    'text-status-amber',
    'text-status-orange',
    'text-error',
    'text-on-surface-variant',
    'animate-spin',
  ],
  theme: {
    extend: {
      colors: {
        'outline-variant': '#d5c4b1',
        'on-surface-variant': '#504536',
        'primary-fixed': '#ffddb3',
        'tertiary-fixed-dim': '#b9c9d2',
        'surface-bright': '#f8fafb',
        'tertiary-container': '#abbbc3',
        primary: '#825500',
        secondary: '#496172',
        'on-background': '#191c1d',
        'secondary-fixed-dim': '#b1cadd',
        'on-secondary-fixed': '#031e2c',
        'on-secondary-fixed-variant': '#324a59',
        'on-tertiary-container': '#3c4b52',
        surface: '#f8fafb',
        'inverse-on-surface': '#eff1f2',
        'surface-container-high': '#e6e8e9',
        'on-tertiary': '#ffffff',
        'on-primary-container': '#654100',
        'on-primary-fixed': '#291800',
        'surface-container': '#eceeef',
        'on-surface': '#191c1d',
        'primary-fixed-dim': '#fcba59',
        'on-primary': '#ffffff',
        background: '#f8fafb',
        error: '#ba1a1a',
        'on-error-container': '#93000a',
        'on-tertiary-fixed': '#0e1e24',
        'primary-container': '#ecac4c',
        'surface-variant': '#e1e3e4',
        'surface-dim': '#d8dadb',
        'inverse-primary': '#fcba59',
        'surface-container-highest': '#e1e3e4',
        'on-tertiary-fixed-variant': '#3a4950',
        tertiary: '#516168',
        'surface-tint': '#825500',
        'on-primary-fixed-variant': '#633f00',
        'error-container': '#ffdad6',
        outline: '#837564',
        'on-secondary': '#ffffff',
        'inverse-surface': '#2e3132',
        'secondary-fixed': '#cce6f9',
        'surface-container-low': '#f2f4f5',
        'tertiary-fixed': '#d5e5ee',
        'on-error': '#ffffff',
        'on-secondary-container': '#4e6676',
        'surface-container-lowest': '#ffffff',
        'secondary-container': '#cae3f7',
        // Paleta de marca "Barreira & Associados" (extraida do logo)
        'siga-gold': '#ECAC4C',
        'siga-gold-text': '#2F4A55',
        'siga-petrol': '#3C5464',
        'siga-slate': '#84949C',
        'siga-terminal': '#1C2C34',
        // Cores semanticas de status (originalmente so no mockup de NF-e)
        'status-green': '#2E7D32',
        'status-amber': '#F57F17',
        'status-orange': '#EF6C00',
      },
      borderRadius: {
        DEFAULT: '0.125rem',
        lg: '0.25rem',
        xl: '0.5rem',
        full: '0.75rem',
      },
      spacing: {
        'sidebar-width': '280px',
        'execution-panel-width': '320px',
        base: '4px',
        xs: '4px',
        sm: '8px',
        md: '16px',
        lg: '24px',
        xl: '32px',
        gutter: '16px',
      },
      fontFamily: {
        'console-text': ['JetBrains Mono', 'Consolas', 'monospace'],
        'label-bold': ['Inter', 'Segoe UI', 'sans-serif'],
        'body-md': ['Inter', 'Segoe UI', 'sans-serif'],
        'body-sm': ['Inter', 'Segoe UI', 'sans-serif'],
        'headline-lg': ['Inter', 'Segoe UI', 'sans-serif'],
        'headline-md': ['Inter', 'Segoe UI', 'sans-serif'],
      },
      fontSize: {
        'console-text': ['13px', { lineHeight: '18px', fontWeight: '400' }],
        'label-bold': ['12px', { lineHeight: '16px', fontWeight: '600' }],
        'body-md': ['14px', { lineHeight: '20px', fontWeight: '400' }],
        'body-sm': ['12px', { lineHeight: '16px', fontWeight: '400' }],
        'headline-lg': ['24px', { lineHeight: '32px', letterSpacing: '-0.02em', fontWeight: '700' }],
        'headline-md': ['18px', { lineHeight: '24px', fontWeight: '600' }],
      },
    },
  },
  // O mockup do Stitch carregava o Tailwind com "?plugins=forms" - os checkboxes da
  // grade de empresas dependem desse plugin para aceitar cor via "text-siga-petrol".
  plugins: [require('@tailwindcss/forms')],
};
