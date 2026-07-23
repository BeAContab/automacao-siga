# 🎯 Guia de Integração - Ícone SIGA Automação

## Arquivos Gerados

- **siga-automacao.ico** — Arquivo principal para Windows (format ICO, 256x256)
- **siga-automacao-256x256.png** — Resolução alta para documentos/exploradores
- **siga-automacao-128x128.png** — Preview em interfaces gráficas
- **siga-automacao-64x64.png** — Barra de tarefas do Windows
- **siga-automacao-32x32.png** — Ícone pequeno
- **siga-automacao-16x16.png** — Favicon/ícone mínimo

---

## 1. Integração com Tkinter (GUI Python)

Se sua aplicação GUI usa `tkinter`:

```python
import tkinter as tk
from tkinter import Tk
import os

# Criar janela raiz
root = Tk()
root.title("SIGA Automação")

# Definir ícone da janela
icon_path = os.path.join(os.path.dirname(__file__), 'siga-automacao.ico')
try:
    root.iconbitmap(icon_path)
except Exception as e:
    print(f"Aviso: Não foi possível carregar o ícone: {e}")

# Seu código de interface...
root.mainloop()
```

---

## 2. Integração com PyQt5/PySide

Para aplicações Qt:

```python
from PyQt5.QtWidgets import QApplication, QMainWindow
from PyQt5.QtGui import QIcon
import sys
import os

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SIGA Automação")
        
        icon_path = os.path.join(os.path.dirname(__file__), 'siga-automacao.png')
        self.setWindowIcon(QIcon(icon_path))

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
```

---

## 3. Integração com PyInstaller (Compilação .exe)

Para empacotar com PyInstaller:

### Opção A: Via arquivo .spec

No seu `siga-automacao.spec` (ou `siga-automacao-gui.spec`), adicione o ícone na seção `exe`:

```python
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='siga-automacao-gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='siga-automacao.ico',  # ← Adicione esta linha
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
```

### Opção B: Via terminal

```powershell
.\.venv\Scripts\python.exe -m PyInstaller `
  --noconfirm --clean `
  --icon=siga-automacao.ico `
  --windowed `
  siga-automacao-gui.spec
```

---

## 4. Integração com Inno Setup (Instalador)

No arquivo `installer\siga-automacao.iss`, adicione:

```ini
[Setup]
AppName=SIGA Automação
AppVersion=1.0
SetupIconFile=..\siga-automacao.ico

[Files]
Source: "..\dist\siga-automacao-gui.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{commonprograms}\SIGA Automação"; Filename: "{app}\siga-automacao-gui.exe"; IconFilename: "..\siga-automacao.ico"
Name: "{commondesktop}\SIGA Automação"; Filename: "{app}\siga-automacao-gui.exe"; IconFilename: "..\siga-automacao.ico"
```

---

## 5. Organização de Arquivos Recomendada

Coloque o ícone na raiz do seu projeto:

```
siga-automacao/
├── main.py
├── gui/
│   ├── __init__.py
│   └── main_window.py
├── core/
│   └── ... (seu código de automação)
├── siga-automacao.ico          ← Coloque aqui
├── siga-automacao-256x256.png
├── siga-automacao.spec
├── siga-automacao-gui.spec
└── installer/
    └── siga-automacao.iss
```

---

## 6. Teste Rápido

```python
from PIL import Image

# Validar que o ícone está correto
img = Image.open('siga-automacao.ico')
print(f"Ícone carregado com sucesso: {img.size}")
```

---

## 7. Boas Práticas

✅ **Use sempre o caminho relativo** ao arquivo executável  
✅ **Forneça fallback** caso o ícone não seja encontrado  
✅ **Use a resolução 256x256** para qualidade máxima no Windows  
✅ **Teste o ícone** após empacotar com PyInstaller  
✅ **Limpe cache** com `--clean` ao recompilar  

---

## 8. Troubleshooting

| Problema | Solução |
|----------|---------|
| Ícone não aparece no .exe | Verifique caminho absoluto no .spec; use `--noconfirm --clean` |
| Ícone distorcido em alta resolução | Garanta que o ícone é 256x256 pixels |
| Erro ao carregar .ico em Tkinter | Use `.png` em vez de `.ico` como fallback |
| Instalador não mostra ícone | Caminho relativo correto no .iss; recompile |


