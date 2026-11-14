"""Agrupa los bancos por perfil financiero con k-means.

Usa el promedio de los últimos tres cierres anuales (diciembre) para suavizar años atípicos,
y solo los bancos que siguen operando. Los cortes parciales (p. ej. septiembre) se excluyen:
mezclarlos con cierres anuales cambia el resultado del agrupamiento.

Uso:  .venv/bin/python src/clusters.py   (después de src/kpis.py)
"""
from pathlib import Path

import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

RAIZ = Path(__file__).resolve().parents[1]
PROC = RAIZ / "data" / "processed"

VARIABLES = ["roa", "eficiencia", "morosidad", "cobertura", "capital_sobre_activo",
             "cartera_sobre_depositos", "liquidez_inmediata"]


def preparar() -> pd.DataFrame:
    k = pd.read_csv(PROC / "kpis.csv", parse_dates=["fecha"])
    k = k[k["fecha"].dt.month == 12]
    ultima = k["fecha"].max()
    vigentes = k.loc[k["fecha"] == ultima, "banco"]
    k = k[k["banco"].isin(vigentes) & (k["fecha"].dt.year >= ultima.year - 2)].copy()

    # Casos límite que romperían la escala:
    # * eficiencia con margen bruto ~0 o negativo (Ficohsa 2025) -> tope 150 %
    # * cobertura sin cartera vencida (Citibank) -> se toma como el tope, 300 %
    k["eficiencia"] = k["eficiencia"].clip(0, 1.5).where(k["eficiencia"] >= 0, 1.5)
    k["cobertura"] = k["cobertura"].fillna(3.0).clip(upper=3.0)

    perfil = k.groupby("banco")[VARIABLES].mean()
    perfil["activo"] = k[k["fecha"] == ultima].set_index("banco")["activo"]
    return perfil


def main() -> None:
    perfil = preparar()
    X = StandardScaler().fit_transform(perfil[VARIABLES])

    print("Silhouette por número de grupos (más alto = grupos mejor separados):")
    puntajes = {}
    for n in range(2, 7):
        etiquetas = KMeans(n_clusters=n, n_init=50, random_state=0).fit_predict(X)
        puntajes[n] = silhouette_score(X, etiquetas)
        print(f"  k={n}: {puntajes[n]:.3f}")

    # Nos quedamos con 3 grupos aunque otro k puntúe parecido: es lo que se puede
    # explicar en una entrevista y lo que permite colores distinguibles en la gráfica.
    km = KMeans(n_clusters=3, n_init=50, random_state=0).fit(X)
    perfil["grupo"] = km.labels_

    # Nombre de cada grupo según su perfil (el número que asigna k-means es arbitrario).
    medias = perfil.groupby("grupo")[["capital_sobre_activo", "cobertura"]].mean()
    nuevos = medias["capital_sobre_activo"].idxmax()
    resto = medias.drop(nuevos)
    nombres = {
        nuevos: "Nuevos, muy capitalizados",
        resto["cobertura"].idxmax(): "Reservas altas",
        resto["cobertura"].idxmin(): "Reservas ajustadas",
    }
    perfil["nombre_grupo"] = perfil["grupo"].map(nombres)

    pca = PCA(n_components=2).fit(X)
    comp = pca.transform(X)
    perfil["pc1"], perfil["pc2"] = comp[:, 0], comp[:, 1]
    print(f"\nVarianza explicada por PC1+PC2: {pca.explained_variance_ratio_.sum():.0%}")
    cargas = pd.DataFrame(pca.components_.T, index=VARIABLES, columns=["pc1", "pc2"])
    print(cargas.round(2).to_string())

    resumen = perfil.groupby("nombre_grupo")[VARIABLES].mean()
    resumen["bancos"] = (perfil.sort_values("activo", ascending=False).reset_index()
                         .groupby("nombre_grupo")["banco"].agg(", ".join))
    pd.set_option("display.width", 250, "display.max_colwidth", 120)
    print("\nPerfil promedio por grupo:\n", resumen.round(3).to_string())

    perfil.to_csv(PROC / "clusters.csv")


if __name__ == "__main__":
    main()
