"""Sección 1: base de datos SQLite con los documentos escaneados.

Cada PDF recibe un ID propio (DOC-000001, DOC-000002, ...) y se guarda su estado:
    registrado -> censurado -> extraido
o "revisar" si algo necesita que una persona lo mire.
"""
import hashlib
import json
import os
import sqlite3
from datetime import datetime

ESQUEMA = """
CREATE TABLE IF NOT EXISTS documentos (
    num               INTEGER PRIMARY KEY AUTOINCREMENT,
    id                TEXT UNIQUE,              -- DOC-000001
    nombre_archivo    TEXT NOT NULL,            -- nombre original del escaneado
    ruta_original     TEXT NOT NULL,
    hash_sha256       TEXT UNIQUE NOT NULL,     -- evita registrar dos veces el mismo PDF
    paginas           INTEGER,
    fecha_registro    TEXT NOT NULL,
    estado            TEXT NOT NULL DEFAULT 'registrado',
    ruta_censurado    TEXT,
    zonas_censuradas  INTEGER,
    fecha_censura     TEXT,
    fecha_extraccion  TEXT,
    datos_json        TEXT,                     -- todo lo que extrajo Claude, en JSON
    notas             TEXT
);

CREATE TABLE IF NOT EXISTS datos_extraidos (
    documento_id  TEXT NOT NULL REFERENCES documentos(id),
    campo         TEXT NOT NULL,
    valor         TEXT,
    PRIMARY KEY (documento_id, campo)
);
"""


def _ahora():
    return datetime.now().isoformat(timespec="seconds")


def conectar(ruta_db):
    con = sqlite3.connect(ruta_db)
    con.row_factory = sqlite3.Row
    con.executescript(ESQUEMA)
    return con


def hash_archivo(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def registrar_documento(con, ruta_pdf, paginas=None):
    """Registra un PDF y devuelve (id, es_nuevo). Si ya estaba registrado, devuelve su ID."""
    h = hash_archivo(ruta_pdf)
    fila = con.execute("SELECT id FROM documentos WHERE hash_sha256 = ?", (h,)).fetchone()
    if fila:
        return fila["id"], False

    cur = con.execute(
        "INSERT INTO documentos (nombre_archivo, ruta_original, hash_sha256, paginas, fecha_registro) "
        "VALUES (?, ?, ?, ?, ?)",
        (os.path.basename(ruta_pdf), os.path.abspath(ruta_pdf), h, paginas, _ahora()),
    )
    doc_id = f"DOC-{cur.lastrowid:06d}"
    con.execute("UPDATE documentos SET id = ? WHERE num = ?", (doc_id, cur.lastrowid))
    con.commit()
    return doc_id, True


def documentos_en_estado(con, estado):
    return con.execute(
        "SELECT * FROM documentos WHERE estado = ? ORDER BY num", (estado,)
    ).fetchall()


def marcar_censurado(con, doc_id, ruta_censurado, zonas):
    con.execute(
        "UPDATE documentos SET estado='censurado', ruta_censurado=?, zonas_censuradas=?, "
        "fecha_censura=?, notas=NULL WHERE id=?",
        (os.path.abspath(ruta_censurado), zonas, _ahora(), doc_id),
    )
    con.commit()


def marcar_revisar(con, doc_id, motivo, ruta_censurado=None, zonas=None):
    con.execute(
        "UPDATE documentos SET estado='revisar', notas=?, "
        "ruta_censurado=COALESCE(?, ruta_censurado), zonas_censuradas=COALESCE(?, zonas_censuradas) "
        "WHERE id=?",
        (motivo, os.path.abspath(ruta_censurado) if ruta_censurado else None, zonas, doc_id),
    )
    con.commit()


def aprobar_censura(con, doc_id):
    """Después de revisar a mano un PDF censurado marcado como 'revisar', lo deja listo para Claude."""
    fila = con.execute("SELECT ruta_censurado FROM documentos WHERE id=?", (doc_id,)).fetchone()
    if not fila or not fila["ruta_censurado"]:
        raise ValueError(f"{doc_id} no tiene un PDF censurado todavía.")
    con.execute(
        "UPDATE documentos SET estado='censurado', fecha_censura=?, notas='aprobado manualmente' "
        "WHERE id=?",
        (_ahora(), doc_id),
    )
    con.commit()


def reiniciar(con, doc_id):
    """Vuelve a poner un documento como 'registrado' para repetir la censura."""
    con.execute("UPDATE documentos SET estado='registrado', notas=NULL WHERE id=?", (doc_id,))
    con.commit()


def guardar_extraccion(con, doc_id, datos):
    con.execute(
        "UPDATE documentos SET estado='extraido', fecha_extraccion=?, datos_json=?, notas=NULL "
        "WHERE id=?",
        (_ahora(), json.dumps(datos, ensure_ascii=False), doc_id),
    )
    con.executemany(
        "INSERT OR REPLACE INTO datos_extraidos (documento_id, campo, valor) VALUES (?, ?, ?)",
        [(doc_id, k, None if v is None else str(v)) for k, v in datos.items()],
    )
    con.commit()


def tabla_documentos(con):
    """Lista resumida de todos los documentos (para mostrar en el notebook)."""
    return con.execute(
        "SELECT id, nombre_archivo, estado, paginas, zonas_censuradas, fecha_registro, notas "
        "FROM documentos ORDER BY num"
    ).fetchall()
