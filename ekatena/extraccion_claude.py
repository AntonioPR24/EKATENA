"""Sección 3: enviar el PDF YA CENSURADO a Claude y extraer los campos predeterminados.

Requiere una API key de Anthropic en la variable de entorno ANTHROPIC_API_KEY
(o un perfil creado con `ant auth login`). Nunca escribas la key en el notebook.
"""
import base64
import json
import os

import anthropic

MODELO = "claude-opus-5-5"
LIMITE_MB = 23  # la petición admite 32 MB; el PDF crece ~33 % al codificarlo en base64

INSTRUCCIONES = """Eres un asistente que extrae datos de reportes escaneados en español.

Reglas:
- Devuelve únicamente los campos solicitados, con el valor tal como aparece en el documento.
- Si un dato no aparece o no se puede leer con seguridad, devuelve null. No lo inventes ni lo deduzcas.
- Algunas zonas del documento están tapadas con rectángulos negros porque fueron censuradas.
  No intentes adivinar lo que hay debajo; trata esos datos como no disponibles (null).
- Respeta el formato original de fechas y números (por ejemplo "15/06/2026", "100.00%")."""


def construir_esquema(campos):
    """Convierte {"campo": "descripción"} en un JSON Schema donde cada campo es texto o null."""
    return {
        "type": "object",
        "properties": {
            nombre: {"anyOf": [{"type": "string"}, {"type": "null"}], "description": descripcion}
            for nombre, descripcion in campos.items()
        },
        "required": list(campos),
        "additionalProperties": False,
    }


def extraer_datos(ruta_pdf_censurado, campos, client=None, effort="medium"):
    """Envía el PDF censurado a Claude y devuelve un diccionario {campo: valor}."""
    tamano_mb = os.path.getsize(ruta_pdf_censurado) / (1024 * 1024)
    if tamano_mb > LIMITE_MB:
        raise ValueError(
            f"El PDF censurado pesa {tamano_mb:.1f} MB (máximo ~{LIMITE_MB} MB). "
            "Baja DPI_SALIDA en la configuración y vuelve a censurarlo."
        )

    with open(ruta_pdf_censurado, "rb") as f:
        pdf_b64 = base64.standard_b64encode(f.read()).decode("ascii")

    lista_campos = "\n".join(f"- {k}: {v}" for k, v in campos.items())
    client = client or anthropic.Anthropic()
    respuesta = client.beta.messages.create(
        model=MODELO,
        max_tokens=16000,
        # Si el modelo rechaza la petición por seguridad, el servidor la reintenta con otro modelo
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={
            "effort": effort,
            "format": {"type": "json_schema", "schema": construir_esquema(campos)},
        },
        system=INSTRUCCIONES,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64},
                },
                {"type": "text", "text": f"Extrae estos campos del documento:\n{lista_campos}"},
            ],
        }],
    )

    if respuesta.stop_reason == "refusal":
        raise RuntimeError("Claude rechazó procesar este documento.")
    if respuesta.stop_reason == "max_tokens":
        raise RuntimeError("La respuesta quedó cortada (max_tokens).")

    texto = next(b.text for b in respuesta.content if b.type == "text")
    return json.loads(texto)
