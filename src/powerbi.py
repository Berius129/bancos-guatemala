"""Genera el dashboard de Power BI como proyecto PBIP (texto, versionable en Git).

1. Exporta un modelo estrella a data/processed/powerbi/ (Bancos, Fechas, Cuentas).
2. Escribe powerbi/BancosGuatemala.SemanticModel (TMDL: tablas, relaciones, medidas DAX).
3. Escribe powerbi/BancosGuatemala.Report (PBIR: páginas y visuales).

Power BI lee los CSV desde GitHub (parámetro RutaDatos), así que el .pbip abre en
cualquier computadora con Power BI Desktop sin configurar rutas locales.

Uso:  .venv/bin/python src/powerbi.py   (después de kpis.py y clusters.py)
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import duckdb
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
PROC = RAIZ / "data" / "processed"
DATOS_PBI = PROC / "powerbi"
SALIDA = RAIZ / "powerbi"
NOMBRE = "BancosGuatemala"
URL_DATOS = "https://raw.githubusercontent.com/Berius129/bancos-guatemala/main/data/processed/powerbi/"

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"
V_VISUAL, V_PAGE, V_REPORT = "2.13.0", "2.1.0", "3.3.0"

MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
COLORES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]


def tag(*partes: str) -> str:
    """lineageTag estable: el mismo objeto conserva su id entre regeneraciones."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "bancos-gt/" + "/".join(partes)))


# ---------------------------------------------------------------- datos

def exportar_datos() -> None:
    DATOS_PBI.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(RAIZ / "bancos.duckdb"), read_only=True)
    cuentas = con.sql("""
        SELECT fecha, banco, activo, capital, depositos, disponibilidades, cartera_bruta,
               cartera_vencida, estimaciones_cartera, margen_operacional_bruto,
               gastos_administracion, utilidad_neta_acum,
               utilidad_neta_acum * 12.0 / month(fecha) AS utilidad_anualizada,
               activo_promedio, capital_promedio
        FROM cuentas_promedio ORDER BY fecha, banco
    """).df()
    oficiales = con.sql("""
        SELECT banco, arg_max(banco_nombre_oficial, fecha) AS nombre_oficial,
               min(fecha) AS primer_corte, max(fecha) AS ultimo_corte
        FROM balances GROUP BY banco
    """).df()
    con.close()

    ultima = cuentas["fecha"].max()
    grupos = pd.read_csv(PROC / "clusters.csv", index_col="banco")["nombre_grupo"]
    bancos = oficiales.assign(
        grupo=oficiales["banco"].map(grupos).fillna("Ya no opera"),
        estado=(oficiales["ultimo_corte"] == ultima).map({True: "Opera", False: "Fusionado o cerrado"}),
    ).sort_values("banco")
    bancos.to_csv(DATOS_PBI / "bancos.csv", index=False)

    fechas = pd.DataFrame({"fecha": sorted(cuentas["fecha"].unique())})
    fechas["fecha"] = pd.to_datetime(fechas["fecha"])
    fechas["anio"] = fechas["fecha"].dt.year
    fechas["mes"] = fechas["fecha"].dt.month
    fechas["etiqueta"] = [f"{MESES[m - 1]} {a}" for a, m in zip(fechas["anio"], fechas["mes"])]
    fechas["tipo_corte"] = fechas["mes"].map(lambda m: "Cierre anual" if m == 12 else "Parcial (anualizado)")
    fechas["orden"] = range(1, len(fechas) + 1)
    fechas.to_csv(DATOS_PBI / "fechas.csv", index=False, date_format="%Y-%m-%d")

    cuentas.to_csv(DATOS_PBI / "cuentas.csv", index=False, date_format="%Y-%m-%d")
    print(f"  datos: {len(bancos)} bancos, {len(fechas)} cortes, {len(cuentas)} filas de cuentas")


# ---------------------------------------------------------------- modelo (TMDL)

TABLAS = {
    "Bancos": {
        "archivo": "bancos.csv",
        "columnas": [("banco", "string"), ("nombre_oficial", "string"), ("primer_corte", "dateTime"),
                     ("ultimo_corte", "dateTime"), ("grupo", "string"), ("estado", "string")],
    },
    "Fechas": {
        "archivo": "fechas.csv",
        "columnas": [("fecha", "dateTime"), ("anio", "int64"), ("mes", "int64"), ("etiqueta", "string"),
                     ("tipo_corte", "string"), ("orden", "int64")],
    },
    "Cuentas": {
        "archivo": "cuentas.csv",
        "columnas": [("fecha", "dateTime"), ("banco", "string")] + [
            (c, "double") for c in [
                "activo", "capital", "depositos", "disponibilidades", "cartera_bruta", "cartera_vencida",
                "estimaciones_cartera", "margen_operacional_bruto", "gastos_administracion",
                "utilidad_neta_acum", "utilidad_anualizada", "activo_promedio", "capital_promedio"]],
    },
}

M_TIPOS = {"string": "type text", "dateTime": "type date", "int64": "Int64.Type", "double": "type number"}

# Todas las medidas de saldo se evalúan en el ÚLTIMO corte del contexto. Así una tarjeta sin
# filtro de fecha muestra el corte más reciente (en vez de sumar años), y una gráfica por
# fecha sigue mostrando cada corte.
def al_corte(expr: str) -> str:
    return f"VAR _f = MAX ( Fechas[fecha] ) RETURN CALCULATE ( {expr}, Fechas[fecha] = _f )"


MEDIDAS = [
    # (nombre, DAX, formato, carpeta, descripción)
    ("Último corte", "MAX ( Fechas[fecha] )", "mmm yyyy", "Base", "Fecha del corte más reciente en el contexto."),
    ("Activos (Q millones)", al_corte("SUM ( Cuentas[activo] )") + " / 1000", "#,0", "Base",
     "Activo total en millones de quetzales (la SIB publica en miles)."),
    ("Utilidad anualizada (Q millones)", al_corte("SUM ( Cuentas[utilidad_anualizada] )") + " / 1000", "#,0", "Base",
     "Utilidad neta acumulada en el año x 12 / mes del corte."),
    ("Número de bancos", al_corte("DISTINCTCOUNT ( Cuentas[banco] )"), "0", "Base", "Bancos que reportan en el corte."),
    ("ROA", f"DIVIDE ( {al_corte('SUM ( Cuentas[utilidad_anualizada] )')}, {al_corte('SUM ( Cuentas[activo_promedio] )')} )",
     "0.00%", "Rentabilidad", "Utilidad anualizada / activo promedio (corte actual y anterior)."),
    ("ROE", f"DIVIDE ( {al_corte('SUM ( Cuentas[utilidad_anualizada] )')}, {al_corte('SUM ( Cuentas[capital_promedio] )')} )",
     "0.0%", "Rentabilidad", "Utilidad anualizada / capital contable promedio."),
    ("Eficiencia", f"DIVIDE ( {al_corte('SUM ( Cuentas[gastos_administracion] )')}, {al_corte('SUM ( Cuentas[margen_operacional_bruto] )')} )",
     "0.0%", "Rentabilidad", "Gastos de administración / margen operacional bruto. Más bajo = mejor."),
    ("Morosidad", f"DIVIDE ( {al_corte('SUM ( Cuentas[cartera_vencida] )')}, {al_corte('SUM ( Cuentas[cartera_bruta] )')} )",
     "0.00%", "Riesgo", "Cartera vencida / cartera bruta."),
    ("Cobertura", f"DIVIDE ( {al_corte('SUM ( Cuentas[estimaciones_cartera] )')}, {al_corte('SUM ( Cuentas[cartera_vencida] )')} )",
     "0%", "Riesgo", "Estimaciones por valuación de cartera / cartera vencida."),
    ("Capital / activos", f"DIVIDE ( {al_corte('SUM ( Cuentas[capital] )')}, {al_corte('SUM ( Cuentas[activo] )')} )",
     "0.0%", "Riesgo", "Capital contable / activo total."),
    ("Cartera / depósitos", f"DIVIDE ( {al_corte('SUM ( Cuentas[cartera_bruta] )')}, {al_corte('SUM ( Cuentas[depositos] )')} )",
     "0%", "Riesgo", "Qué proporción de lo captado está prestada."),
    ("Participación en activos", "DIVIDE ( [Activos (Q millones)], CALCULATE ( [Activos (Q millones)], ALL ( Bancos ) ) )",
     "0.0%", "Mercado", "Activos del banco / activos del sistema en el mismo corte."),
    ("HHI", "SUMX ( VALUES ( Bancos[banco] ), ( 100 * CALCULATE ( [Participación en activos] ) ) ^ 2 )",
     "#,0", "Mercado", "Índice Herfindahl-Hirschman sobre activos. <1,500 poco concentrado; 1,500-2,500 moderado."),
    ("Participación top 3", """VAR _top = TOPN ( 3, ALL ( Bancos[banco] ), [Activos (Q millones)], DESC )
		RETURN DIVIDE ( CALCULATE ( [Activos (Q millones)], _top ), CALCULATE ( [Activos (Q millones)], ALL ( Bancos ) ) )""",
     "0.0%", "Mercado", "Participación conjunta de los tres bancos más grandes."),
    ("ROE sistema", "CALCULATE ( [ROE], ALL ( Bancos ) )", "0.0%", "Comparación", "ROE del sistema completo, ignora el filtro de banco."),
    ("Morosidad sistema", "CALCULATE ( [Morosidad], ALL ( Bancos ) )", "0.00%", "Comparación", "Morosidad del sistema completo."),
    ("Eficiencia sistema", "CALCULATE ( [Eficiencia], ALL ( Bancos ) )", "0.0%", "Comparación", "Eficiencia del sistema completo."),
]


def tmdl_tabla(nombre: str, info: dict, medidas: list | None = None) -> str:
    L = [f"table {nombre}", f"\tlineageTag: {tag('t', nombre)}", ""]
    for m_nombre, dax, fmt, carpeta, desc in medidas or []:
        L.append(f"\t/// {desc}")
        if "\n" in dax:
            L.append(f"\tmeasure '{m_nombre}' =")
            for linea in dax.split("\n"):
                L.append("\t\t\t" + linea.strip())
        else:
            L.append(f"\tmeasure '{m_nombre}' = {dax}")
        L += [f"\t\tformatString: {fmt}", f"\t\tdisplayFolder: {carpeta}",
              f"\t\tlineageTag: {tag('m', m_nombre)}", ""]
    for col, tipo in info["columnas"]:
        L += [f"\tcolumn {col}", f"\t\tdataType: {tipo}"]
        if tipo == "dateTime":
            L.append("\t\tformatString: yyyy-mm-dd")
        if tipo in ("double", "int64") and col not in ("anio", "mes", "orden"):
            L.append("\t\tsummarizeBy: sum")
        else:
            L.append("\t\tsummarizeBy: none")
        if nombre == "Fechas" and col == "etiqueta":
            L.append("\t\tsortByColumn: orden")
        if nombre == "Cuentas":
            L.append("\t\tisHidden")
        L += [f"\t\tlineageTag: {tag('c', nombre, col)}", f"\t\tsourceColumn: {col}", ""]
    tipos = ",\n".join(f'\t\t\t\t\t\t{{"{c}", {M_TIPOS[t]}}}' for c, t in info["columnas"])
    L += [
        f"\tpartition {nombre} = m",
        "\t\tmode: import",
        "\t\tsource =",
        "\t\t\t\tlet",
        f'\t\t\t\t\tOrigen = Csv.Document(Web.Contents(RutaDatos & "{info["archivo"]}"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),',
        "\t\t\t\t\tEncabezados = Table.PromoteHeaders(Origen, [PromoteAllScalars = true]),",
        "\t\t\t\t\tTipos = Table.TransformColumnTypes(Encabezados, {",
        tipos,
        '\t\t\t\t\t}, "en-US")',
        "\t\t\t\tin",
        "\t\t\t\t\tTipos",
        "",
    ]
    return "\n".join(L)


def escribir_modelo() -> None:
    sm = SALIDA / f"{NOMBRE}.SemanticModel"
    d = sm / "definition"
    (d / "tables").mkdir(parents=True)
    escribir_json(sm / ".platform", {
        "$schema": f"{SCHEMA}/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "SemanticModel", "displayName": "Bancos Guatemala"},
        "config": {"version": "2.0", "logicalId": tag("semanticmodel")},
    })
    escribir_json(sm / "definition.pbism", {
        "$schema": f"{SCHEMA}/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.0", "settings": {"qnaEnabled": False},
    })
    (d / "database.tmdl").write_text("database BancosGuatemala\n\tcompatibilityLevel: 1567\n")
    (d / "model.tmdl").write_text(
        "model Model\n\tculture: es-ES\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
        "\n" + "".join(f"ref table {t}\n" for t in TABLAS)
    )
    (d / "expressions.tmdl").write_text(
        "/// Carpeta (URL o ruta local terminada en / o \\) donde están bancos.csv, fechas.csv y cuentas.csv.\n"
        f'expression RutaDatos = "{URL_DATOS}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
        f"\tlineageTag: {tag('e', 'RutaDatos')}\n"
    )
    (d / "relationships.tmdl").write_text(
        f"relationship {tag('r', 'banco')}\n\tfromColumn: Cuentas.banco\n\ttoColumn: Bancos.banco\n\n"
        f"relationship {tag('r', 'fecha')}\n\tfromColumn: Cuentas.fecha\n\ttoColumn: Fechas.fecha\n"
    )
    for nombre, info in TABLAS.items():
        texto = tmdl_tabla(nombre, info, MEDIDAS if nombre == "Cuentas" else None)
        (d / "tables" / f"{nombre}.tmdl").write_text(texto)


# ---------------------------------------------------------------- reporte (PBIR)

def lit(v) -> dict:
    if isinstance(v, bool):
        s = "true" if v else "false"
    elif isinstance(v, (int, float)):
        s = f"{v}D"
    else:
        s = "'" + str(v).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": s}}}


def campo(entidad: str, prop: str, medida: bool) -> dict:
    tipo = "Measure" if medida else "Column"
    return {tipo: {"Expression": {"SourceRef": {"Entity": entidad}}, "Property": prop}}


def proy(entidad: str, prop: str, medida: bool = False, nombre: str | None = None) -> dict:
    p = {"field": campo(entidad, prop, medida), "queryRef": f"{entidad}.{prop}", "nativeQueryRef": prop}
    if nombre:
        p["displayName"] = nombre
    return p


def M(prop: str, nombre: str | None = None) -> dict:
    return proy("Cuentas", prop, True, nombre)


def titulo_obj(texto: str) -> dict:
    return {"title": [{"properties": {
        "show": lit(True), "text": lit(texto), "fontSize": lit(11), "bold": lit(True),
        "fontColor": {"solid": {"color": lit("#0b0b0b")}},
    }}]}


class Pagina:
    def __init__(self, nombre: str, titulo: str, subtitulo: str):
        self.nombre, self.titulo = nombre, titulo
        self.visuales: list[dict] = []
        self.interacciones: list[dict] = []
        self.texto("encabezado", 24, 12, 900, 70, titulo, subtitulo)

    def _agregar(self, nombre, x, y, w, h, visual: dict) -> str:
        z = len(self.visuales) * 1000
        self.visuales.append({
            "$schema": f"{SCHEMA}/item/report/definition/visualContainer/{V_VISUAL}/schema.json",
            "name": nombre,
            "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z},
            "visual": visual,
        })
        return nombre

    def texto(self, nombre, x, y, w, h, titulo, subtitulo):
        parrafos = [{"textRuns": [{"value": titulo, "textStyle": {"fontSize": "20pt", "fontWeight": "bold"}}]}]
        if subtitulo:
            parrafos.append({"textRuns": [{"value": subtitulo, "textStyle": {"fontSize": "11pt", "color": "#52514e"}}]})
        return self._agregar(nombre, x, y, w, h, {
            "visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": parrafos}}]},
        })

    def segmentador(self, nombre, x, y, w, h, entidad, prop, encabezado, unico=True):
        objetos = {
            "data": [{"properties": {"mode": lit("Dropdown")}}],
            "header": [{"properties": {"show": lit(True), "text": lit(encabezado)}}],
        }
        if unico:
            objetos["selection"] = [{"properties": {"strictSingleSelect": lit(True)}}]
        return self._agregar(nombre, x, y, w, h, {
            "visualType": "slicer",
            "query": {"queryState": {"Values": {"projections": [proy(entidad, prop)]}}},
            "objects": objetos,
        })

    def tarjeta(self, nombre, x, y, w, h, medida, etiqueta):
        return self._agregar(nombre, x, y, w, h, {
            "visualType": "card",
            "query": {"queryState": {"Values": {"projections": [M(medida, etiqueta)]}}},
            "objects": {
                "labels": [{"properties": {"fontSize": lit(22), "color": {"solid": {"color": lit("#0b0b0b")}}}}],
                "categoryLabels": [{"properties": {"show": lit(True), "fontSize": lit(10)}}],
            },
        })

    def linea(self, nombre, x, y, w, h, medidas: list[tuple[str, str]], titulo, eje=("Fechas", "fecha")):
        return self._agregar(nombre, x, y, w, h, {
            "visualType": "lineChart",
            "query": {"queryState": {
                "Category": {"projections": [proy(*eje)]},
                "Y": {"projections": [M(m, n) for m, n in medidas]},
            }},
            "objects": {
                "categoryAxis": [{"properties": {"axisType": lit("Categorical"), "showAxisTitle": lit(False)}}],
                "valueAxis": [{"properties": {"showAxisTitle": lit(False)}}],
                "legend": [{"properties": {"show": lit(len(medidas) > 1), "position": lit("Top")}}],
                "markers": [{"properties": {"show": lit(True)}}],
            },
            "visualContainerObjects": titulo_obj(titulo),
        })

    def barras(self, nombre, x, y, w, h, categoria, medida, titulo, tipo="clusteredBarChart"):
        return self._agregar(nombre, x, y, w, h, {
            "visualType": tipo,
            "query": {
                "queryState": {
                    "Category": {"projections": [proy(*categoria)]},
                    "Y": {"projections": [M(medida)]},
                },
                "sortDefinition": {"sort": [{"field": campo("Cuentas", medida, True), "direction": "Descending"}],
                                   "isDefaultSort": False},
            },
            "objects": {
                "labels": [{"properties": {"show": lit(True)}}],
                "valueAxis": [{"properties": {"show": lit(False)}}],
                "categoryAxis": [{"properties": {"showAxisTitle": lit(False)}}],
            },
            "visualContainerObjects": titulo_obj(titulo),
        })

    def tabla(self, nombre, x, y, w, h, columnas: list[dict], titulo, orden_medida):
        return self._agregar(nombre, x, y, w, h, {
            "visualType": "tableEx",
            "query": {
                "queryState": {"Values": {"projections": columnas}},
                "sortDefinition": {"sort": [{"field": campo("Cuentas", orden_medida, True), "direction": "Descending"}],
                                   "isDefaultSort": False},
            },
            "visualContainerObjects": titulo_obj(titulo),
        })

    def dispersion(self, nombre, x, y, w, h, titulo):
        return self._agregar(nombre, x, y, w, h, {
            "visualType": "scatterChart",
            "query": {"queryState": {
                "Category": {"projections": [proy("Bancos", "banco")]},
                "Series": {"projections": [proy("Bancos", "grupo")]},
                "X": {"projections": [M("Cobertura")]},
                "Y": {"projections": [M("ROE")]},
                "Size": {"projections": [M("Activos (Q millones)")]},
            }},
            "objects": {
                "categoryLabels": [{"properties": {"show": lit(True)}}],
                "legend": [{"properties": {"show": lit(True), "position": lit("Top")}}],
            },
            "visualContainerObjects": titulo_obj(titulo),
        })

    def sin_filtro(self, origen: str, destinos: list[str]) -> None:
        self.interacciones += [{"source": origen, "target": t, "type": "NoFilter"} for t in destinos]

    def escribir(self, carpeta: Path) -> None:
        p = carpeta / self.nombre
        (p / "visuals").mkdir(parents=True)
        pagina = {
            "$schema": f"{SCHEMA}/item/report/definition/page/{V_PAGE}/schema.json",
            "name": self.nombre, "displayName": self.titulo.split(":")[0],
            "displayOption": "FitToPage", "height": 720, "width": 1280,
        }
        if self.interacciones:
            pagina["visualInteractions"] = self.interacciones
        escribir_json(p / "page.json", pagina)
        for v in self.visuales:
            escribir_json(p / "visuals" / v["name"] / "visual.json", v)


def paginas() -> list[Pagina]:
    # 1. Sistema
    s = Pagina("sistema", "Sistema bancario de Guatemala",
               "Indicadores del sistema al corte elegido. Las tendencias muestran todos los cortes.")
    fecha = s.segmentador("filtro-fecha", 1040, 16, 216, 64, "Fechas", "etiqueta", "Corte")
    tarjetas = []
    for i, (m, et) in enumerate([("Activos (Q millones)", "Activos (Q millones)"), ("ROE", "ROE"),
                                 ("Morosidad", "Morosidad"), ("Cobertura", "Cobertura"),
                                 ("HHI", "Concentración (HHI)"), ("Participación top 3", "Top 3 bancos")]):
        tarjetas.append(s.tarjeta(f"kpi-{i}", 24 + i * 206, 96, 196, 100, m, et))
    barras = s.barras("participacion", 24, 212, 500, 492, ("Bancos", "banco"), "Participación en activos",
                      "Participación en activos por banco")
    roe = s.linea("tendencia-roe", 540, 212, 716, 240, [("ROE", "ROE")], "ROE del sistema por corte",
                  eje=("Fechas", "etiqueta"))
    mor = s.linea("tendencia-morosidad", 540, 464, 716, 240, [("Morosidad", "Morosidad")],
                  "Morosidad del sistema por corte", eje=("Fechas", "etiqueta"))
    s.sin_filtro(fecha, [roe, mor])

    # 2. Comparación de bancos
    b = Pagina("bancos", "Comparación de bancos",
               "Todos los indicadores por banco al corte elegido. Ordenado por tamaño.")
    b.segmentador("filtro-fecha", 1040, 16, 216, 64, "Fechas", "etiqueta", "Corte")
    b.segmentador("filtro-grupo", 816, 16, 216, 64, "Bancos", "grupo", "Grupo", unico=False)
    cols = [proy("Bancos", "banco", nombre="Banco")] + [M(m, n) for m, n in [
        ("Activos (Q millones)", "Activos (Q mill.)"), ("Participación en activos", "Part."), ("ROA", "ROA"),
        ("ROE", "ROE"), ("Eficiencia", "Eficiencia"), ("Morosidad", "Morosidad"), ("Cobertura", "Cobertura"),
        ("Capital / activos", "Capital/activos"), ("Cartera / depósitos", "Cartera/dep.")]]
    b.tabla("tabla-bancos", 24, 96, 700, 608, cols, "Indicadores por banco", "Activos (Q millones)")
    b.dispersion("rentabilidad-cobertura", 740, 96, 516, 608, "ROE contra cobertura (tamaño = activos)")

    # 3. Detalle por banco
    d = Pagina("detalle", "Detalle por banco",
               "Evolución del banco elegido comparada con el sistema completo.")
    d.segmentador("filtro-banco", 1040, 16, 216, 64, "Bancos", "banco", "Banco")
    d.linea("roe-vs-sistema", 24, 96, 612, 300, [("ROE", "Banco"), ("ROE sistema", "Sistema")], "ROE: banco vs. sistema",
            eje=("Fechas", "etiqueta"))
    d.linea("morosidad-vs-sistema", 644, 96, 612, 300, [("Morosidad", "Banco"), ("Morosidad sistema", "Sistema")],
            "Morosidad: banco vs. sistema", eje=("Fechas", "etiqueta"))
    d.linea("eficiencia-vs-sistema", 24, 404, 612, 300, [("Eficiencia", "Banco"), ("Eficiencia sistema", "Sistema")],
            "Eficiencia: banco vs. sistema (más bajo = mejor)", eje=("Fechas", "etiqueta"))
    d.barras("activos-banco", 644, 404, 612, 300, ("Fechas", "etiqueta"), "Activos (Q millones)",
             "Activos (Q millones)", tipo="clusteredColumnChart")
    return [s, b, d]


def escribir_reporte() -> None:
    rp = SALIDA / f"{NOMBRE}.Report"
    d = rp / "definition"
    (d / "pages").mkdir(parents=True)
    (rp / "StaticResources" / "RegisteredResources").mkdir(parents=True)
    escribir_json(rp / ".platform", {
        "$schema": f"{SCHEMA}/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "Report", "displayName": "Bancos Guatemala"},
        "config": {"version": "2.0", "logicalId": tag("report")},
    })
    escribir_json(rp / "definition.pbir", {
        "$schema": f"{SCHEMA}/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0",
        "datasetReference": {"byPath": {"path": f"../{NOMBRE}.SemanticModel"}},
    })
    escribir_json(rp / "StaticResources" / "RegisteredResources" / "BancosGT.json", {
        "name": "BancosGT", "dataColors": COLORES,
        "foreground": "#0b0b0b", "foregroundNeutralSecondary": "#52514e",
        "background": "#fcfcfb", "backgroundLight": "#f0efec", "tableAccent": "#2a78d6",
        "good": "#0ca30c", "neutral": "#fab219", "bad": "#d03b3b",
    })
    escribir_json(d / "version.json", {
        "$schema": f"{SCHEMA}/item/report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0",
    })
    escribir_json(d / "report.json", {
        "$schema": f"{SCHEMA}/item/report/definition/report/{V_REPORT}/schema.json",
        "themeCollection": {"customTheme": {
            "name": "BancosGT.json",
            "reportVersionAtImport": {"visual": V_VISUAL, "page": V_PAGE, "report": V_REPORT},
            "type": "RegisteredResources",
        }},
        "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources",
                              "items": [{"name": "BancosGT.json", "path": "BancosGT.json", "type": "CustomTheme"}]}],
    })
    ps = paginas()
    for p in ps:
        p.escribir(d / "pages")
    escribir_json(d / "pages" / "pages.json", {
        "$schema": f"{SCHEMA}/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": [p.nombre for p in ps], "activePageName": ps[0].nombre,
    })
    escribir_json(SALIDA / f"{NOMBRE}.pbip", {
        "$schema": f"{SCHEMA}/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": f"{NOMBRE}.Report"}}],
        "settings": {"enableAutoRecovery": True},
    })
    (SALIDA / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")


def escribir_json(ruta: Path, obj: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    exportar_datos()
    for p in [SALIDA / f"{NOMBRE}.SemanticModel", SALIDA / f"{NOMBRE}.Report"]:
        if p.exists():
            shutil.rmtree(p)
    escribir_modelo()
    escribir_reporte()
    print(f"  proyecto: {SALIDA.relative_to(RAIZ)}/{NOMBRE}.pbip")


if __name__ == "__main__":
    main()
