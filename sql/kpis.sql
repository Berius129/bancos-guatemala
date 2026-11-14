-- Indicadores financieros por banco y fecha de corte (DuckDB).
-- Uso:  .venv/bin/python src/kpis.py   (carga el CSV limpio y corre este archivo)
--
-- Notas de método:
-- * Cifras en miles de quetzales.
-- * El estado de resultados de la SIB es ACUMULADO en el año (enero a la fecha de corte),
--   por eso la utilidad se anualiza: utilidad * 12 / mes. En diciembre no cambia nada.
-- * ROA y ROE usan el promedio entre el saldo actual y el del corte anterior del mismo banco.
--   Si el banco no existía en el corte anterior, se usa el saldo actual.

CREATE OR REPLACE TABLE balances AS
SELECT * FROM read_csv_auto('data/processed/balances.csv');

-- Pasamos de formato largo a una fila por banco y fecha con las cuentas que usamos.
CREATE OR REPLACE VIEW cuentas AS
SELECT
    fecha,
    banco,
    SUM(valor_miles_q) FILTER (WHERE cuenta = 'ACTIVO')                         AS activo,
    SUM(valor_miles_q) FILTER (WHERE cuenta = 'CAPITAL CONTABLE')               AS capital,
    SUM(valor_miles_q) FILTER (WHERE cuenta = 'OBLIGACIONES DEPOSITARIAS')      AS depositos,
    SUM(valor_miles_q) FILTER (WHERE cuenta = 'DISPONIBILIDADES')               AS disponibilidades,
    SUM(valor_miles_q) FILTER (WHERE cuenta = 'CARTERA DE CRÉDITOS - SUMA')     AS cartera_bruta,
    SUM(valor_miles_q) FILTER (WHERE cuenta = 'Vencidos')                       AS cartera_vencida,
    SUM(valor_miles_q) FILTER (WHERE cuenta = '(-) Estimaciones Por Valuación') AS estimaciones_cartera,
    SUM(valor_miles_q) FILTER (WHERE cuenta = 'PRODUCTOS FINANCIEROS')          AS productos_financieros,
    SUM(valor_miles_q) FILTER (WHERE cuenta = 'GASTOS FINANCIEROS')             AS gastos_financieros,
    SUM(valor_miles_q) FILTER (WHERE cuenta = 'MARGEN OPERACIONAL BRUTO')       AS margen_operacional_bruto,
    SUM(valor_miles_q) FILTER (WHERE cuenta = 'GASTOS DE ADMINISTRACIÓN')       AS gastos_administracion,
    SUM(valor_miles_q) FILTER (WHERE cuenta = 'GANANCIA (PÉRDIDA) NETA')        AS utilidad_neta_acum
FROM balances
GROUP BY fecha, banco;

CREATE OR REPLACE VIEW cuentas_promedio AS
SELECT
    *,
    (activo  + COALESCE(LAG(activo)  OVER w, activo))  / 2 AS activo_promedio,
    (capital + COALESCE(LAG(capital) OVER w, capital)) / 2 AS capital_promedio
FROM cuentas
WINDOW w AS (PARTITION BY banco ORDER BY fecha);

CREATE OR REPLACE VIEW kpis AS
SELECT
    fecha,
    banco,
    activo,
    capital,
    cartera_bruta,
    depositos,
    utilidad_neta_acum * 12.0 / month(fecha)                              AS utilidad_anualizada,
    -- Rentabilidad
    utilidad_neta_acum * 12.0 / month(fecha) / NULLIF(activo_promedio, 0)  AS roa,
    utilidad_neta_acum * 12.0 / month(fecha) / NULLIF(capital_promedio, 0) AS roe,
    -- Eficiencia: cuánto del margen bruto se va en gastos de administración (menor es mejor)
    gastos_administracion / NULLIF(margen_operacional_bruto, 0)           AS eficiencia,
    -- Calidad de cartera
    cartera_vencida / NULLIF(cartera_bruta, 0)                            AS morosidad,
    estimaciones_cartera / NULLIF(cartera_vencida, 0)                     AS cobertura,
    -- Estructura y liquidez
    capital / NULLIF(activo, 0)                                           AS capital_sobre_activo,
    cartera_bruta / NULLIF(depositos, 0)                                  AS cartera_sobre_depositos,
    disponibilidades / NULLIF(depositos, 0)                               AS liquidez_inmediata,
    -- Tamaño relativo
    activo / SUM(activo) OVER (PARTITION BY fecha)                        AS participacion_activos,
    depositos / SUM(depositos) OVER (PARTITION BY fecha)                  AS participacion_depositos
FROM cuentas_promedio;

-- Concentración del mercado: índice Herfindahl-Hirschman sobre activos.
-- Referencia usual: < 1,500 poco concentrado; 1,500-2,500 moderado; > 2,500 alto.
CREATE OR REPLACE VIEW concentracion AS
SELECT
    fecha,
    ROUND(SUM(POWER(participacion_activos * 100, 2)))                     AS hhi_activos,
    SUM(participacion_activos) FILTER (WHERE rk <= 3)                     AS cr3,
    SUM(participacion_activos) FILTER (WHERE rk <= 5)                     AS cr5,
    COUNT(*)                                                              AS bancos
FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY fecha ORDER BY activo DESC) AS rk
    FROM kpis
)
GROUP BY fecha;

-- Totales del sistema (todas las cuentas sumadas, luego los cocientes).
CREATE OR REPLACE VIEW sistema AS
SELECT
    fecha,
    SUM(activo)                                         AS activo,
    SUM(utilidad_neta_acum) * 12.0 / month(fecha) / SUM(activo_promedio)  AS roa,
    SUM(utilidad_neta_acum) * 12.0 / month(fecha) / SUM(capital_promedio) AS roe,
    SUM(gastos_administracion) / SUM(margen_operacional_bruto)            AS eficiencia,
    SUM(cartera_vencida) / SUM(cartera_bruta)                             AS morosidad,
    SUM(estimaciones_cartera) / SUM(cartera_vencida)                      AS cobertura,
    SUM(cartera_bruta) / SUM(depositos)                                   AS cartera_sobre_depositos,
    COUNT(*)                                                              AS bancos
FROM cuentas_promedio
GROUP BY fecha;
