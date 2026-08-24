from __future__ import annotations

"""Compila a interface web para `src/web_dist/`, que é o que o app carrega em runtime.

Faz duas coisas:

1. Roda o Tailwind CLI (`npx tailwindcss`) para gerar o `styles.css` já com purge e
   minificação — nenhuma dependência de CDN sobra no resultado.
2. Copia os arquivos estáticos (HTML, JS, fontes vendorizadas, logo) para a pasta de
   distribuição.

Node é dependência **de build**, nunca de execução: o `.exe` empacotado leva apenas o
conteúdo já gerado em `src/web_dist/`.

Uso:
    python web/build.py            # build de produção (minificado)
    python web/build.py --watch    # recompila o CSS a cada alteração, para desenvolver
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent
SRC_DIR = WEB_DIR / "src"
DIST_DIR = WEB_DIR.parent / "src" / "web_dist"
LOGO_SOURCE = WEB_DIR.parent / "images" / "logo" / "logo.png"


def run_tailwind(watch: bool) -> None:
    """Compila o CSS. `npx` resolve o binário instalado em web/node_modules."""
    command = [
        "npx",
        "tailwindcss",
        "-i",
        str(SRC_DIR / "styles" / "tailwind.css"),
        "-o",
        str(DIST_DIR / "styles.css"),
    ]
    command.append("--watch" if watch else "--minify")
    # shell=True no Windows porque `npx` é um .cmd, não um executável nativo.
    subprocess.run(command, check=True, cwd=WEB_DIR, shell=(sys.platform == "win32"))


def copy_static() -> None:
    """Espelha HTML/JS/fontes/logo na pasta de distribuição."""
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    shutil.copy2(SRC_DIR / "index.html", DIST_DIR / "index.html")

    js_dest = DIST_DIR / "js"
    if js_dest.exists():
        shutil.rmtree(js_dest)
    shutil.copytree(SRC_DIR / "js", js_dest)

    fonts_dest = DIST_DIR / "fonts"
    if fonts_dest.exists():
        shutil.rmtree(fonts_dest)
    shutil.copytree(SRC_DIR / "styles" / "fonts", fonts_dest)

    if LOGO_SOURCE.exists():
        shutil.copy2(LOGO_SOURCE, DIST_DIR / "logo.png")
    else:
        print(f"AVISO: logo não encontrada em {LOGO_SOURCE}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compila a interface web do SIGA Automação.")
    parser.add_argument("--watch", action="store_true", help="Recompila o CSS continuamente.")
    args = parser.parse_args()

    copy_static()
    print(f"Estáticos copiados para {DIST_DIR}")
    run_tailwind(watch=args.watch)
    if not args.watch:
        css = DIST_DIR / "styles.css"
        print(f"CSS compilado: {css} ({css.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
