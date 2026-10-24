"""Tableau de bord : ventes autour des fêtes au Sénégal, alignées sur le jour de la fête (J0).
Données fictives, à visée pédagogique (TP4 Python avancé, ISM)."""
from pathlib import Path
import unicodedata

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st

DOSSIER_RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
PERIODE = ("2016-01-01", "2025-12-31")

st.set_page_config(page_title="Fêtes et consommation au Sénégal", layout="wide")


def normaliser_categorie(texte):
    """Même règle que la partie 1 : sans accents, minuscules, sans espaces autour."""
    texte = unicodedata.normalize("NFKD", str(texte)).encode("ascii", "ignore").decode("ascii")
    return texte.strip().lower().replace(" ", "_").replace("-", "_")


@st.cache_data(show_spinner="Chargement des données...")
def charger_donnees():
    ventes = pd.read_csv(DOSSIER_RAW / "ventes_journalieres.csv", parse_dates=["date"],
                         dtype={"magasin_id": "category", "categorie": "category"})
    corr = {lib: normaliser_categorie(lib) for lib in ventes["categorie"].cat.categories}
    ventes["categorie"] = ventes["categorie"].map(corr).astype("category")
    ventes = ventes.drop_duplicates()
    # Quantités négatives ou aberrantes (> 10 x p99 du magasin et de la catégorie) : ignorées
    p99 = (ventes.groupby(["magasin_id", "categorie"], observed=True)["quantite"]
           .transform(lambda s: s.quantile(0.99)))
    ventes.loc[(ventes["quantite"] < 0) | (ventes["quantite"] > 10 * p99), "quantite"] = np.nan
    calendrier = pd.read_csv(DOSSIER_RAW / "calendrier_evenements.csv", parse_dates=["date_debut", "date_fin"])
    magasins = pd.read_csv(DOSSIER_RAW / "magasins.csv", parse_dates=["date_ouverture"])
    return ventes, calendrier, magasins


@st.cache_data
def courbes_alignees(fete, magasins_sel, categorie, avant, apres):
    """Ventes quotidiennes (somme des magasins choisis) de J-avant à J+apres, pour chaque année de la fête."""
    ventes, calendrier, _ = charger_donnees()
    occurrences = calendrier.loc[(calendrier["evenement"] == fete)
                                 & calendrier["date_debut"].between(*PERIODE), "date_debut"]
    v = ventes[(ventes["categorie"] == categorie) & ventes["magasin_id"].isin(magasins_sel)]
    quotidien = v.groupby("date")["quantite"].sum(min_count=1)
    morceaux = []
    for j0 in occurrences:
        jours = pd.date_range(j0 - pd.Timedelta(days=avant), j0 + pd.Timedelta(days=apres), freq="D")
        morceaux.append(pd.DataFrame({"jour_relatif": np.arange(-avant, apres + 1),
                                      "quantite": quotidien.reindex(jours).to_numpy(),
                                      "annee": j0.year}))
    return pd.concat(morceaux, ignore_index=True)


ventes, calendrier, magasins = charger_donnees()

# ---- Barre latérale : les trois choix demandés ----
st.sidebar.header("Choix")
fetes = sorted(calendrier["evenement"].unique())
fete = st.sidebar.selectbox("Fête", fetes, index=fetes.index("Tabaski"))
options_villes = {"Tout le réseau (10 magasins)": list(magasins["magasin_id"]),
                  "Dakar (3 magasins)": list(magasins.loc[magasins["region"] == "Dakar", "magasin_id"])}
options_villes.update({f"{r.ville} ({r.magasin_id})": [r.magasin_id] for r in magasins.itertuples()})
ville = st.sidebar.selectbox("Ville", list(options_villes))
categories = sorted(ventes["categorie"].cat.categories)
categorie = st.sidebar.selectbox("Catégorie", categories, index=categories.index("betail_mouton"))
avant = st.sidebar.slider("Jours avant J0", 7, 60, 30)
apres = st.sidebar.slider("Jours après J0", 0, 30, 7)
st.sidebar.caption("Fenêtre d'achat : J-7 à J-1. Référence : J-60 à J-31. Pour le Ramadan, J0 = premier jour du jeûne.")

# ---- Calculs ----
donnees = courbes_alignees(fete, tuple(options_villes[ville]), categorie, max(avant, 60), apres)
uplift_annee = (donnees.assign(periode=np.select([donnees["jour_relatif"].between(-7, -1),
                                                  donnees["jour_relatif"].between(-60, -31)],
                                                 ["fenetre", "reference"], default="autre"))
                .query("periode != 'autre'")
                .pivot_table(index="annee", columns="periode", values="quantite", aggfunc="mean"))
uplift_annee["uplift"] = uplift_annee["fenetre"] / uplift_annee["reference"]
uplift_moyen = uplift_annee["fenetre"].sum() / uplift_annee["reference"].sum()
donnees = donnees[donnees["jour_relatif"] >= -avant]

# ---- Affichage ----
st.title("Fêtes et consommation au Sénégal")
st.caption("Ventes journalières alignées sur le jour de la fête (J0), 2016-2025. **Données fictives**, à visée pédagogique.")

prochaine = calendrier.loc[(calendrier["evenement"] == fete) & (calendrier["annee"] == 2026), "date_debut"]
c1, c2, c3 = st.columns(3)
c1.metric("Uplift moyen (J-7 à J-1 / J-60 à J-31)", f"x{uplift_moyen:.2f}")
c2.metric("Années disponibles", int(donnees["annee"].nunique()))
c3.metric("Date en 2026", prochaine.iloc[0].strftime("%d/%m/%Y") if len(prochaine) else "non prévue")

fig, ax = plt.subplots(figsize=(11, 4.5))
for annee, d in donnees.groupby("annee"):
    ax.plot(d["jour_relatif"], d["quantite"], linewidth=0.8, alpha=0.45, label=str(annee))
moyenne = donnees.groupby("jour_relatif")["quantite"].mean()
ax.plot(moyenne.index, moyenne.values, color="black", linewidth=2.5, label="Moyenne")
ax.axvspan(-7, -1, color="tab:orange", alpha=0.12, label="Fenêtre J-7 à J-1")
ax.axvline(0, color="grey", linestyle="--", linewidth=1)
ax.set_title(f"{categorie} : {ville}, autour de : {fete}")
ax.set_xlabel("Jours par rapport à la fête (0 = J0)")
ax.set_ylabel("Quantité vendue par jour")
ax.legend(ncol=6, fontsize=7, loc="upper left")
st.pyplot(fig)

st.subheader("Uplift par année")
st.dataframe(uplift_annee.rename(columns={"fenetre": "moyenne J-7 à J-1", "reference": "moyenne J-60 à J-31"})
            .round(2), width="stretch")

with st.expander("Méthode"):
    st.markdown(
        "- Nettoyage identique au notebook : catégories normalisées, doublons supprimés, "
        "quantités négatives ou supérieures à 10 fois le 99e percentile ignorées.\n"
        "- Uplift = vente moyenne par jour de J-7 à J-1 divisée par la vente moyenne par jour de J-60 à J-31.\n"
        "- Attention aux chevauchements : par exemple, Pâques tombe pendant le Ramadan en 2022-2024, "
        "et la référence de la Tamkharit contient les achats de la Tabaski.")