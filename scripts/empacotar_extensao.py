"""Gera o pacote .zip da extensão (para a Chrome Web Store "não listada", o Edge Add-ons ou "Carregar sem compactação").

    python scripts/empacotar_extensao.py            # cria dist/searching-extensao-<versão>.zip

O pacote leva só os arquivos da extensão (manifest, scripts e página de opções): nenhum token, URL de servidor ou dado local.
"""
import json
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
EXTENSAO = RAIZ / "extensao"
ARQUIVOS = ("manifest.json", "background.js", "ponte.js", "opcoes.html", "opcoes.js")


def main() -> Path:
    versao = json.loads((EXTENSAO / "manifest.json").read_text(encoding="utf-8"))["version"]
    destino = RAIZ / "dist" / f"searching-extensao-{versao}.zip"
    destino.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for nome in ARQUIVOS:
            z.write(EXTENSAO / nome, nome)
    print(f"Pacote criado: {destino}")
    return destino


if __name__ == "__main__":
    main()
