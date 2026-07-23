---
name: SIGA Automação
colors:
  surface: '#f7f9ff'
  surface-dim: '#cbdcee'
  surface-bright: '#f7f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#ecf4ff'
  surface-container: '#e2efff'
  surface-container-high: '#d9eafc'
  surface-container-highest: '#d4e4f6'
  on-surface: '#0d1d2a'
  on-surface-variant: '#3f493e'
  inverse-surface: '#223240'
  inverse-on-surface: '#e7f2ff'
  outline: '#6f7a6d'
  outline-variant: '#bfcaba'
  surface-tint: '#006e25'
  primary: '#00531a'
  on-primary: '#ffffff'
  primary-container: '#006e25'
  on-primary-container: '#90ee94'
  inverse-primary: '#7edb83'
  secondary: '#4e5f7e'
  on-secondary: '#ffffff'
  secondary-container: '#cadaff'
  on-secondary-container: '#4f5f7f'
  tertiary: '#474746'
  on-tertiary: '#ffffff'
  tertiary-container: '#5f5e5e'
  on-tertiary-container: '#dad8d7'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#99f89d'
  primary-fixed-dim: '#7edb83'
  on-primary-fixed: '#002106'
  on-primary-fixed-variant: '#00531a'
  secondary-fixed: '#d7e3ff'
  secondary-fixed-dim: '#b6c7eb'
  on-secondary-fixed: '#081b37'
  on-secondary-fixed-variant: '#364765'
  tertiary-fixed: '#e5e2e1'
  tertiary-fixed-dim: '#c8c6c5'
  on-tertiary-fixed: '#1b1b1c'
  on-tertiary-fixed-variant: '#474746'
  background: '#f7f9ff'
  on-background: '#0d1d2a'
  surface-variant: '#d4e4f6'
typography:
  display-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  title-sm:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '500'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  label-caps:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.05em
  code-sm:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
  headline-lg-mobile:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 8px
  container-max-width: 1440px
  gutter: 24px
  sidebar-width: 260px
  margin-mobile: 16px
  margin-desktop: 32px
---

## Brand & Style
The design system is engineered for high-stakes tax automation, where precision and efficiency are paramount. The brand personality is authoritative yet invisible—a tool that empowers backoffice professionals to manage complex financial data with absolute confidence. 

The aesthetic leans into **Modern Professionalism** with a heavy influence from **Minimalism**. It prioritizes data density without sacrificing clarity. The interface utilizes a structured, high-contrast layout to ensure that critical tax discrepancies are immediately visible. Visual flourishes are stripped away in favor of functional clarity, creating a "command center" atmosphere that feels secure, robust, and technologically advanced.

## Colors
The palette is anchored by **Dark Navy Blue (#031632)**, used exclusively for primary navigation and sidebars to establish a foundation of stability and depth. **Forest Green (#006e25)** serves as the high-visibility primary action color, signaling growth, correctness, and successful automation. 

**Dark Charcoal (#1e1e1e)** is reserved for "Console Areas"—specialized zones for logs, code snippets, or raw data feeds where technical focus is required. The **Light Gray (#f8f9fa)** background provides a clean, low-strain canvas for long-form data review. Neutral accents use **Slate Gray** to handle secondary information and decorative borders without competing for attention.

## Typography
This design system employs a systematic typographic hierarchy designed for legibility in data-dense environments. **Inter** is the workhorse for the entire UI, chosen for its exceptional tall x-height and clarity in small-scale tabular data. 

For technical outputs, automation logs, and tax calculation strings, **JetBrains Mono** is used to ensure character distinction (e.g., distinguishing between '0' and 'O'). Headlines are kept tight and professional with slight negative letter-spacing, while functional labels use an uppercase style to create clear section headers within complex forms.

## Layout & Spacing
The layout follows a **Fixed-Fluid Hybrid** model. The sidebar remains a fixed 260px width, while the main content area utilizes a fluid 12-column grid to maximize the visibility of wide data tables. 

A strict **8px spacing scale** governs all margins and paddings, ensuring mathematical harmony across the platform. On desktop, the main workspace uses a 32px outer margin to provide visual breathing room. On mobile and tablet, the grid collapses to 4 and 8 columns respectively, with the sidebar transitioning to a hidden drawer. Content density is high, with tight 16px gutters between data cards to allow more information "above the fold."

## Elevation & Depth
This design system avoids heavy shadows to maintain a clean, professional "SaaS" look. Depth is primarily communicated through **Tonal Layering**. 

1. **Surface (L0):** The main background in Light Gray.
2. **Cards (L1):** White surfaces with a 1px Slate Gray border (opacity 10%) and a very subtle, diffused 4px blur shadow.
3. **Overlays (L2):** Modals and dropdowns use a slightly more pronounced shadow (12px blur, 5% opacity) to float above the workspace.

Navigation elements (sidebar) use no shadow, instead relying on the strong color contrast of Dark Navy Blue against the Light Gray background to define the layout structure.

## Shapes
A consistent **8px corner radius (Rounded)** is applied to all primary UI elements, including cards, input fields, and buttons. This radius provides a modern, approachable feel while remaining structured enough for a financial tool. Large containers like main dashboard areas may use `rounded-xl` (24px) for a softer outer frame, while small utility components like tags and badges use a 4px radius to maintain sharpness.

## Components

### Buttons
Primary buttons are **Forest Green (#006e25)** with white text, featuring a completely flat design (no gradients). Secondary buttons use a Slate Gray outline. Ghost buttons are reserved for tertiary actions to keep the focus on the "Run" and "Submit" workflows.

### Data Tables
Tables are the heart of the design system. They feature high-contrast headers with a subtle Light Gray background. Rows use a 1px bottom border in Slate Gray. Interactive rows should feature a Forest Green left-border highlight on hover.

### Console Areas
A specialized component for logs: a **Dark Charcoal (#1e1e1e)** container with **JetBrains Mono** text in light gray or green. These areas should have internal padding of 16px and a "Copy" utility button fixed to the top right.

### Input Fields
Inputs use white backgrounds with a 1px Slate Gray border. On focus, the border transitions to Forest Green with a subtle 2px outer glow in the same color. Labels are positioned above the field using the `label-caps` typography style.

### Minimalist Cards
Cards have no heavy borders. They use white backgrounds and 8px rounded corners. Header sections within cards are separated by a subtle 1px horizontal line, ensuring the summary data and detailed data are clearly partitioned.