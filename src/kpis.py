"""Carga el CSV limpio en DuckDB, crea las vistas de sql/kpis.sql y exporta los resultados.

Uso:  .venv/bin/python src/kpis.py
"""
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parents[1]


def main() -> None:
    con = duckdb.connect(str(RAIZ / "bancos.duckdb"))
    con.execute(f"SET file_search_path = '{RAIZ}'")
    con.execute((RAIZ / "sql" / "kpis.sql").read_text())

    salida = RAIZ / "data" / "processed"
    con.sql("SELECT * FROM kpis ORDER BY fecha, activo DESC").write_csv(str(salida / "kpis.csv"))
    con.sql("SELECT * FROM concentracion ORDER BY fecha").write_csv(str(salida / "concentracion.csv"))
    con.sql("SELECT * FROM sistema ORDER BY fecha").write_csv(str(salida / "sistema.csv"))

    ultima = con.sql("SELECT max(fecha) FROM kpis").fetchone()[0]
    print(f"Corte más reciente: {ultima:%Y-%m-%d}\n")
    con.sql(f"""
        SELECT banco,
               round(activo / 1e6, 1)              AS "activo (miles M Q)",
               round(participacion_activos * 100, 1) AS "part. %",
               round(roa * 100, 2)                 AS "ROA %",
               round(roe * 100, 1)                 AS "ROE %",
               round(eficiencia * 100, 1)          AS "efic. %",
               round(morosidad * 100, 2)           AS "moros. %",
               round(cobertura * 100, 0)           AS "cobert. %"
        FROM kpis WHERE fecha = '{ultima}'
        ORDER BY activo DESC
    """).show(max_rows=50)
    con.sql("""
        SELECT c.fecha, c.bancos, c.hhi_activos, round(c.cr3*100,1) AS "CR3 %",
               round(s.activo/1e6,1) AS "activo (miles M Q)", round(s.roa*100,2) AS "ROA %",
               round(s.roe*100,1) AS "ROE %", round(s.eficiencia*100,1) AS "efic. %",
               round(s.morosidad*100,2) AS "moros. %", round(s.cobertura*100,0) AS "cobert. %",
               round(s.cartera_sobre_depositos*100,1) AS "cart/dep %"
        FROM concentracion c JOIN sistema s USING (fecha) ORDER BY fecha
    """).show()


if __name__ == "__main__":
    main()
