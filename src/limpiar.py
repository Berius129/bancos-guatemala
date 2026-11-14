"""Limpia los archivos de la SIB (Consulta dinámica: Balance General y Estado de Resultados
de Instituciones Bancarias) y los convierte a una tabla en formato largo.

La SIB entrega un "Consulta.xls" que en realidad es HTML (latin-1). Cada archivo tiene una
fecha de corte, una columna de cuentas y una columna por banco. Las cifras vienen en miles
de quetzales.

Uso:  .venv/bin/python src/limpiar.py
Lee todos los .xls/.html de data/raw/ y escribe data/processed/balances.csv
"""
from __future__ import annotations

import re
import sys
from io import StringIO
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
RAW = RAIZ / "data" / "raw"
SALIDA = RAIZ / "data" / "processed" / "balances.csv"

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

# Filas que son subtotales o títulos repetidos: se les antepone la sección para que la
# clave de cuenta sea única dentro del archivo.
AMBIGUAS = {"SUMA", "Productos", "Gastos"}

# Subtotales cuya sección "real" no es la última que apareció en el archivo.
RENOMBRAR = {"CRÉDITOS DIFERIDOS - SUMA": "PASIVO - SUMA"}

# Nombres cortos para gráficas. La SIB omite la palabra "Banco" en el encabezado.
NOMBRES_CORTOS = {
    "EL CRÉDITO HIPOTECARIO NACIONAL DE GUATEMALA": "CHN",
    "CUSCATLÁN GUATEMALA": "Cuscatlán",
    "DE LOS TRABAJADORES": "Bantrab",
    "INDUSTRIAL": "Industrial",
    "DE DESARROLLO RURAL": "Banrural",
    "INTERNACIONAL": "Interbanco",
    "CITIBANK, N.A., SUCURSAL GUATEMALA": "Citibank",
    "VIVIBANCO": "Vivibanco",
    "FICOHSA GUATEMALA": "Ficohsa",
    "PROMERICA": "Promerica",
    "PROMERICA DE GUATEMALA": "Promerica de Guatemala",  # se fusiona con Promerica en 2018
    "DE CRÉDITO": "Banco de Crédito",                   # deja de reportar en 2019
    "DE ANTIGUA": "Antigua",
    "DE AMÉRICA CENTRAL": "BAC",
    "AGROMERCANTIL DE GUATEMALA": "BAM",
    "G&T CONTINENTAL": "G&T Continental",
    "AZTECA DE GUATEMALA": "Azteca",
    "INV": "INV",
    "CREDICORP": "Credicorp",
    "NEXA": "Nexa",
    "MULTIMONEY": "Multimoney",
}

# Primera fila de cada bloque grande, para saber si una cuenta es de balance o de resultados.
INICIO_RESULTADOS = "ESTADO DE RESULTADOS"


def fecha_de_corte(texto: str) -> pd.Timestamp:
    m = re.search(r"(\d{1,2}) de (\w+) de (\d{4})", texto, flags=re.IGNORECASE)
    if not m:
        raise ValueError(f"No encontré la fecha de corte en: {texto[:200]!r}")
    dia, mes, anio = int(m.group(1)), MESES[m.group(2).lower()], int(m.group(3))
    return pd.Timestamp(anio, mes, dia)


def nombre_banco(texto: str) -> tuple[str, str]:
    """Devuelve (nombre oficial, nombre corto). Avisa si aparece un banco nuevo."""
    oficial = re.sub(r"\s+", " ", str(texto)).strip()
    clave = re.sub(r",? S\. ?A\.$", "", oficial).strip()
    corto = NOMBRES_CORTOS.get(clave)
    if corto is None:
        print(f"AVISO: banco sin nombre corto, agrégalo a NOMBRES_CORTOS: {oficial!r}", file=sys.stderr)
        corto = clave.title()
    return oficial, corto


def leer_archivo(ruta: Path) -> pd.DataFrame:
    html = ruta.read_bytes().decode("latin-1")
    tablas = pd.read_html(StringIO(html))
    datos = max(tablas, key=lambda t: t.shape[0] * t.shape[1])
    fecha = fecha_de_corte(str(datos.iat[0, 0]))

    nombres = [nombre_banco(b) for b in datos.iloc[0, 1:]]
    oficiales = {corto: oficial for oficial, corto in nombres}
    bancos = [corto for _, corto in nombres]
    cuerpo = datos.iloc[1:].copy()
    cuerpo.columns = ["cuenta"] + bancos

    filas = []
    bloque, seccion = "balance", None
    for orden, fila in enumerate(cuerpo.itertuples(index=False), start=1):
        cuenta = str(fila[0]).strip() if pd.notna(fila[0]) else ""
        if not cuenta:
            continue
        if cuenta.upper() == INICIO_RESULTADOS:
            bloque, seccion = "resultados", None
            continue
        clave = f"{seccion} - {cuenta}" if cuenta in AMBIGUAS and seccion else cuenta
        clave = RENOMBRAR.get(clave, clave)
        # Las cuentas en mayúsculas abren una sección; las que tienen minúsculas son detalle.
        if cuenta.isupper() and cuenta not in AMBIGUAS:
            seccion = cuenta
        for banco, valor in zip(bancos, fila[1:]):
            filas.append((fecha, banco, bloque, orden, clave, valor))

    df = pd.DataFrame(filas, columns=["fecha", "banco", "estado", "orden", "cuenta", "valor_miles_q"])
    df["valor_miles_q"] = pd.to_numeric(df["valor_miles_q"], errors="coerce")
    # Títulos sin valor (p. ej. "OTROS PRODUCTOS Y GASTOS DE OPERACIÓN") no aportan nada.
    df = df.dropna(subset=["valor_miles_q"])
    df["banco_nombre_oficial"] = df["banco"].map(oficiales)
    df["archivo"] = ruta.name
    return df


def validar(df: pd.DataFrame) -> None:
    """Chequeos contables básicos: si fallan, el archivo se leyó mal."""
    piv = df.pivot_table(index=["fecha", "banco"], columns="cuenta", values="valor_miles_q", aggfunc="sum")
    dif = (piv["ACTIVO"] - piv["TOTAL IGUAL A LA SUMA DEL ACTIVO"]).abs()
    malos = dif[dif > 1]
    if not malos.empty:
        print("AVISO: activo distinto de pasivo + capital en:\n", malos, file=sys.stderr)
    dif = (piv["GANANCIA (PÉRDIDA) NETA"] - piv["RESULTADOS DEL EJERCICIO"]).abs()
    malos = dif[dif > 1]
    if not malos.empty:
        print("AVISO: utilidad del estado de resultados distinta a la del balance en:\n", malos, file=sys.stderr)


def main() -> None:
    rutas = sorted(p for p in RAW.iterdir() if p.suffix.lower() in {".xls", ".html", ".htm"})
    if not rutas:
        sys.exit(f"No hay archivos en {RAW}")
    partes = [leer_archivo(r) for r in rutas]
    df = pd.concat(partes, ignore_index=True)

    repetidas = df.duplicated(["fecha", "banco", "cuenta"], keep=False)
    if repetidas.any():
        # El mismo mes descargado dos veces: nos quedamos con una copia.
        df = df.drop_duplicates(["fecha", "banco", "cuenta"], keep="last")

    validar(df)
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(SALIDA, index=False)
    print(f"{len(rutas)} archivos -> {len(df):,} filas, {df['banco'].nunique()} bancos, "
          f"fechas {df['fecha'].min():%Y-%m} a {df['fecha'].max():%Y-%m} -> {SALIDA.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
