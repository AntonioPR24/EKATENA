"""Sección 2: censurar textos en un PDF y guardar la copia en la carpeta de censurados.

Cada página se convierte en imagen y se pintan rectángulos negros SOBRE LOS PÍXELES.
El texto censurado no queda debajo: no se puede copiar, seleccionar ni recuperar.
"""
import os

from .pdf_ocr import localizar_texto, palabras_por_pagina, normalizar


def censurar_pdf(ruta_pdf, textos, ruta_salida, tesseract_cmd="", dpi=200, margen=2):
    """Censura `textos` en `ruta_pdf` y guarda el resultado en `ruta_salida`.

    Devuelve un diccionario {texto: número de apariciones censuradas}.
    """
    import pypdfium2 as pdfium
    from PIL import ImageDraw

    paginas = palabras_por_pagina(ruta_pdf, tesseract_cmd)
    cajas, conteo = {}, {}
    for t in textos:
        encontrados = localizar_texto(paginas, t)
        conteo[t] = len(encontrados)
        for r in encontrados:
            cajas.setdefault(r["pagina"], []).append(r)

    escala = dpi / 72
    pdf = pdfium.PdfDocument(ruta_pdf)
    imagenes = []
    for n in range(len(pdf)):
        imagen = pdf[n].render(scale=escala).to_pil().convert("RGB")
        dibujo = ImageDraw.Draw(imagen)
        for r in cajas.get(n + 1, []):
            dibujo.rectangle(
                [(r["x0"] - margen) * escala, (r["top"] - margen) * escala,
                 (r["x1"] + margen) * escala, (r["bottom"] + margen) * escala],
                fill="black",
            )
        imagenes.append(imagen)

    os.makedirs(os.path.dirname(os.path.abspath(ruta_salida)), exist_ok=True)
    imagenes[0].save(ruta_salida, save_all=True, append_images=imagenes[1:], resolution=dpi)
    return conteo


def verificar_censura(ruta_censurado, textos, tesseract_cmd=""):
    """Vuelve a leer el PDF censurado con OCR y devuelve los textos que TODAVÍA aparecen."""
    paginas = palabras_por_pagina(ruta_censurado, tesseract_cmd, mostrar_progreso=False)
    return [t for t in textos if normalizar(t) and localizar_texto(paginas, t)]
