"""Lectura de PDF: texto seleccionable con pdfplumber o, si es escaneado, OCR con Tesseract.

Todas las posiciones se devuelven en puntos (1/72 de pulgada), con el origen (0, 0)
en la esquina SUPERIOR IZQUIERDA de la página.
"""
import os
import re
import shutil
import unicodedata

CARPETAS_TESSERACT = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe"),
]


def configurar_tesseract(tesseract_cmd=""):
    """Devuelve (modulo_pytesseract, idioma). Lanza RuntimeError si no encuentra Tesseract."""
    import pytesseract

    if tesseract_cmd:
        if not tesseract_cmd.lower().endswith("tesseract.exe") and not tesseract_cmd.endswith("tesseract"):
            raise RuntimeError(
                f"TESSERACT_CMD = {tesseract_cmd!r} no es una ruta a tesseract.exe. "
                "El texto a censurar va en TEXTOS_A_CENSURAR, no en TESSERACT_CMD."
            )
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    else:
        pytesseract.pytesseract.tesseract_cmd = "tesseract"
        if not shutil.which("tesseract"):
            for c in CARPETAS_TESSERACT:
                if os.path.exists(c):
                    pytesseract.pytesseract.tesseract_cmd = c
                    break
    try:
        idiomas = pytesseract.get_languages()
    except Exception:
        raise RuntimeError(
            f"No se encontró Tesseract (se intentó: {pytesseract.pytesseract.tesseract_cmd!r}). "
            "Instálalo o pon la ruta de tesseract.exe en TESSERACT_CMD."
        )
    return pytesseract, ("spa" if "spa" in idiomas else "eng")


def contar_paginas(ruta):
    import pypdfium2 as pdfium
    return len(pdfium.PdfDocument(ruta))


def tiene_texto(ruta):
    import pdfplumber
    with pdfplumber.open(ruta) as pdf:
        return any((p.extract_text() or "").strip() for p in pdf.pages)


def palabras_por_pagina(ruta, tesseract_cmd="", dpi=300, mostrar_progreso=True):
    """Devuelve {num_pagina: {"palabras": [...], "ancho": pt, "alto": pt}}.

    Usa el texto del PDF si lo tiene; si es escaneado, aplica OCR.
    Cada palabra: {"texto", "x0", "top", "x1", "bottom"} en puntos.
    """
    if tiene_texto(ruta):
        import pdfplumber
        resultado = {}
        with pdfplumber.open(ruta) as pdf:
            for n, pagina in enumerate(pdf.pages, 1):
                resultado[n] = {
                    "palabras": [
                        {k: w[k] for k in ("x0", "top", "x1", "bottom")} | {"texto": w["text"]}
                        for w in pagina.extract_words()
                    ],
                    "ancho": float(pagina.width),
                    "alto": float(pagina.height),
                }
        return resultado

    import pypdfium2 as pdfium
    pytesseract, idioma = configurar_tesseract(tesseract_cmd)
    escala = dpi / 72
    pdf = pdfium.PdfDocument(ruta)
    resultado = {}
    for n in range(len(pdf)):
        imagen = pdf[n].render(scale=escala).to_pil()
        datos = pytesseract.image_to_data(imagen, lang=idioma, output_type=pytesseract.Output.DICT)
        palabras = []
        for i, txt in enumerate(datos["text"]):
            if txt.strip():
                x, y, w, h = (datos[k][i] / escala for k in ("left", "top", "width", "height"))
                palabras.append({"texto": txt, "x0": x, "top": y, "x1": x + w, "bottom": y + h})
        resultado[n + 1] = {"palabras": palabras, "ancho": pdf[n].get_width(), "alto": pdf[n].get_height()}
        if mostrar_progreso:
            print(f"    OCR página {n + 1}/{len(pdf)}: {len(palabras)} palabras")
    return resultado


def normalizar(t):
    """Mayúsculas, sin acentos y solo letras/números (para comparar texto de OCR)."""
    t = unicodedata.normalize("NFKD", t.upper())
    return "".join(c for c in t if c.isalnum())


def localizar_texto(paginas, texto):
    """Busca `texto` en las palabras de `paginas` (resultado de palabras_por_pagina).

    No distingue mayúsculas, acentos, signos ni cómo el PDF/OCR haya partido las palabras.
    Devuelve una lista de rectángulos {"pagina", "texto", "x0", "top", "x1", "bottom"}.
    """
    objetivo = normalizar(texto)
    if not objetivo:
        return []
    encontrados = []
    for n, info in paginas.items():
        pals = info["palabras"]
        # Une todas las palabras de la página en una sola cadena normalizada y
        # recuerda a qué palabra pertenece cada letra.
        cadena, dueno = [], []
        for idx, p in enumerate(pals):
            for c in normalizar(p["texto"]):
                cadena.append(c)
                dueno.append(idx)
        cadena = "".join(cadena)

        pos = cadena.find(objetivo)
        while pos != -1:
            i, j = dueno[pos], dueno[pos + len(objetivo) - 1] + 1
            grupo = pals[i:j]
            encontrados.append({
                "pagina": n,
                "texto": " ".join(p["texto"] for p in grupo),
                "x0": min(p["x0"] for p in grupo),
                "top": min(p["top"] for p in grupo),
                "x1": max(p["x1"] for p in grupo),
                "bottom": max(p["bottom"] for p in grupo),
            })
            pos = cadena.find(objetivo, pos + len(objetivo))
    return encontrados
