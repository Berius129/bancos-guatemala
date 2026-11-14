"""Genera las gráficas del reporte en reports/figuras/.

Uso:  .venv/bin/python src/graficas.py   (después de kpis.py y clusters.py)
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
from matplotlib.ticker import MultipleLocator, PercentFormatter

RAIZ = Path(__file__).resolve().parents[1]
PROC = RAIZ / "data" / "processed"
FIG = RAIZ / "reports" / "figuras"

# Paleta (validada para daltonismo en orden de slots; ver README)
SUPERFICIE = "#fcfcfb"
TEXTO = "#0b0b0b"
TEXTO_2 = "#52514e"
GRID = "#e4e3df"
GRIS = "#9a9893"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
DIVERGENTE = LinearSegmentedColormap.from_list("div", ["#e34948", "#f0efec", "#2a78d6"])
FUENTE = "Fuente: Superintendencia de Bancos (SIB), balances a diciembre. Elaboración propia."

plt.rcParams.update({
    "figure.facecolor": SUPERFICIE, "axes.facecolor": SUPERFICIE, "savefig.facecolor": SUPERFICIE,
    "font.family": "sans-serif", "font.size": 10, "text.color": TEXTO,
    "axes.edgecolor": GRID, "axes.labelcolor": TEXTO_2, "axes.titlecolor": TEXTO,
    "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.8,
    "xtick.color": TEXTO_2, "ytick.color": TEXTO_2, "xtick.major.size": 0, "ytick.major.size": 0,
    "lines.linewidth": 2, "legend.frameon": False,
})


def titulo(fig, texto: str, subtitulo: str) -> None:
    fig.text(0.02, 0.97, texto, fontsize=14, fontweight="bold", va="top")
    fig.text(0.02, 0.915, subtitulo, fontsize=10, color=TEXTO_2, va="top")
    fig.text(0.02, 0.015, FUENTE, fontsize=8, color=TEXTO_2)


def guardar(fig, nombre: str) -> None:
    fig.savefig(FIG / nombre, dpi=200)
    plt.close(fig)
    print("  ", nombre)


def participacion(k: pd.DataFrame) -> None:
    grandes = ["Industrial", "Banrural", "G&T Continental"]
    k = k.assign(grupo=k["banco"].where(k["banco"].isin(grandes), "Resto de bancos"))
    s = k.groupby(["fecha", "grupo"])["participacion_activos"].sum().unstack()
    s.index = s.index.year

    fig, ax = plt.subplots(figsize=(9, 5.2))
    fig.subplots_adjust(top=0.82, bottom=0.1, left=0.07, right=0.8)
    for color, nombre in zip(SERIES[:3] + [GRIS], grandes + ["Resto de bancos"]):
        ax.plot(s.index, s[nombre], color=color, label=nombre)
        ax.annotate(f"{nombre}  {s[nombre].iloc[-1]:.0%}", (s.index[-1], s[nombre].iloc[-1]),
                    xytext=(8, 0), textcoords="offset points", va="center", fontsize=9.5, color=TEXTO)
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.set_ylim(0, 0.45)
    ax.set_xticks(s.index)
    ax.legend(loc="upper left", ncol=4, fontsize=9, bbox_to_anchor=(0, 1.06))
    titulo(fig, "Tres bancos concentran casi dos tercios del sistema",
           "Participación en los activos totales del sistema bancario, 2015-2025")
    guardar(fig, "01_participacion.png")


def sistema(s: pd.DataFrame) -> None:
    s = s.set_index(s["fecha"].dt.year)
    paneles = [
        ("roe", "Rentabilidad sobre patrimonio (ROE)", "más alto = más rentable", 0.02),
        ("eficiencia", "Eficiencia (gastos adm. / margen bruto)", "más bajo = más eficiente", 0.04),
        ("morosidad", "Morosidad (cartera vencida / cartera total)", "más bajo = mejor", 0.005),
        ("cobertura", "Cobertura (reservas / cartera vencida)", "más alto = más colchón", 0.5),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(10, 6.8), sharex=True)
    fig.subplots_adjust(top=0.82, bottom=0.08, left=0.07, right=0.97, hspace=0.5, wspace=0.22)
    for ax, (col, nombre, ayuda, paso) in zip(axes.flat, paneles):
        ax.axvspan(2019.6, 2021.4, color=GRID, alpha=0.6, lw=0)
        ax.plot(s.index, s[col], color=SERIES[0], marker="o", markersize=4)
        ax.set_title(nombre, fontsize=10, pad=20)
        ax.text(0, 1.03, ayuda, transform=ax.transAxes, fontsize=8.5, color=TEXTO_2, va="bottom")
        ax.yaxis.set_major_locator(MultipleLocator(paso))
        ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0 if col != "morosidad" else 1))
        maxi, mini = s[col].idxmax(), s[col].idxmin()
        for anio in {maxi, mini, s.index[-1]}:
            ax.annotate(f"{s.loc[anio, col]:.1%}" if col == "morosidad" else f"{s.loc[anio, col]:.0%}",
                        (anio, s.loc[anio, col]), xytext=(0, 7), textcoords="offset points",
                        ha="center", fontsize=8.5, color=TEXTO)
        lo, hi = s[col].min(), s[col].max()
        ax.set_ylim(lo - (hi - lo) * 0.25, hi + (hi - lo) * 0.3)
        ax.set_xticks(s.index[::2])
    axes[0, 0].text(2020.5, axes[0, 0].get_ylim()[0], "pandemia", ha="center", va="bottom",
                    fontsize=8, color=TEXTO_2)
    titulo(fig, "Tras la pandemia, más reservas y más ganancias; desde 2023, más morosidad",
           "Indicadores del sistema bancario en conjunto, cifras a diciembre de cada año")
    guardar(fig, "02_indicadores_sistema.png")


def heatmap_roe(k: pd.DataFrame) -> None:
    ultima = k["fecha"].max()
    vigentes = k[k["fecha"] == ultima].sort_values("activo", ascending=False)["banco"]
    m = k[k["banco"].isin(vigentes)].pivot_table(index="banco", columns=k["fecha"].dt.year, values="roe")
    m = m.loc[vigentes]

    fig, ax = plt.subplots(figsize=(10, 7.4))
    fig.subplots_adjust(top=0.86, bottom=0.07, left=0.15, right=0.99)
    norm = TwoSlopeNorm(vmin=-0.3, vcenter=0, vmax=0.3)
    ax.imshow(m.clip(-0.3, 0.3), cmap=DIVERGENTE, norm=norm, aspect="auto")
    ax.grid(False)
    ax.set_xticks(range(m.shape[1]), m.columns)
    ax.set_yticks(range(m.shape[0]), m.index)
    ax.xaxis.tick_top()
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            v = m.iat[i, j]
            if np.isnan(v):
                continue
            fuerte = abs(v) > 0.2
            ax.text(j, i, f"{v:.0%}", ha="center", va="center", fontsize=8,
                    color="white" if fuerte else TEXTO)
    for x in np.arange(-0.5, m.shape[1]):
        ax.axvline(x, color=SUPERFICIE, lw=2)
    for y in np.arange(-0.5, m.shape[0]):
        ax.axhline(y, color=SUPERFICIE, lw=2)
    titulo(fig, "ROE por banco: los grandes ganan de forma estable; los pequeños, a saltos",
           "Rentabilidad sobre patrimonio por año. Azul = ganancia, rojo = pérdida. Ordenado por tamaño (activos 2025)")
    guardar(fig, "03_roe_por_banco.png")


def grupos(c: pd.DataFrame) -> None:
    orden = ["Reservas altas", "Reservas ajustadas", "Nuevos, muy capitalizados"]
    # Desplazamiento de etiquetas (puntos) para que no se encimen.
    ajuste = {"Industrial": (10, -14), "Bantrab": (-8, -14), "BAM": (8, 6), "BAC": (8, -10),
              "Promerica": (8, 2), "Cuscatlán": (8, 4), "Antigua": (8, 4), "Ficohsa": (-46, -12),
              "CHN": (-30, 6), "Azteca": (-44, 2), "Vivibanco": (8, 2), "Citibank": (-22, 10),
              "INV": (-26, 2), "G&T Continental": (10, -12), "Credicorp": (10, -2),
              "Interbanco": (-14, 12), "Banrural": (14, 4)}

    fig, ax = plt.subplots(figsize=(9.5, 6.4))
    fig.subplots_adjust(top=0.84, bottom=0.12, left=0.09, right=0.97)
    ax.grid(True, axis="both")
    ax.axvline(1, color=GRIS, lw=1, ls=(0, (3, 3)))
    ax.text(1.01, 0.012, "reservas = 100 % de la cartera vencida", fontsize=8, color=TEXTO_2, va="bottom")
    tam = 40 + 1500 * c["activo"] / c["activo"].max()
    for color, g in zip(SERIES[:3], orden):
        d = c[c["nombre_grupo"] == g]
        ax.scatter(d["cobertura"], d["capital_sobre_activo"], s=tam[d.index], color=color, alpha=0.85,
                   edgecolor=SUPERFICIE, linewidth=2, zorder=3)
        ax.scatter([], [], s=80, color=color, label=g)  # marcador de leyenda de tamaño fijo
    for banco, f in c.iterrows():
        ax.annotate(banco, (f["cobertura"], f["capital_sobre_activo"]), xytext=ajuste.get(banco, (8, 4)),
                    textcoords="offset points", fontsize=8.5, color=TEXTO, zorder=4)
    ax.set_xlim(0.7, 3.15)
    ax.set_ylim(0, 0.42)
    ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.set_xlabel("Cobertura: reservas / cartera vencida (Citibank sin cartera vencida, tope 300 %)")
    ax.set_ylabel("Capital / activos")
    leg = ax.legend(loc="upper right", fontsize=9, title="Grupo (k-means, 7 indicadores)", title_fontsize=9)
    leg._legend_box.align = "left"
    titulo(fig, "Lo que más separa a los bancos es cuánto guardan para préstamos malos",
           "Promedio 2023-2025 por banco. Tamaño del círculo = activos 2025")
    guardar(fig, "04_grupos_bancos.png")


def main() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    # Las gráficas del reporte comparan cierres anuales; los cortes parciales van al dashboard.
    k = pd.read_csv(PROC / "kpis.csv", parse_dates=["fecha"])
    s = pd.read_csv(PROC / "sistema.csv", parse_dates=["fecha"])
    k, s = k[k["fecha"].dt.month == 12], s[s["fecha"].dt.month == 12]
    c = pd.read_csv(PROC / "clusters.csv", index_col="banco")
    participacion(k)
    sistema(s)
    heatmap_roe(k)
    grupos(c)


if __name__ == "__main__":
    main()
