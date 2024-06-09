from datetime import datetime
from typing import Annotated
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from calculs import simulation, choisir_puissance, import_data

app = FastAPI(
    title="SoleilBleuAPI"
)

origins = [
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class User(BaseModel):
    #reponses formulaire
    id: int
    nom_projet: str
    type_projet: str
    region: str
    tarif: float
    surface_max: float
    inclinaison: int
    orientation: str
    #tableau puissance
    puissance:int
    amortissement: float
    ac : float
    ap : float
    tri : float
    benef_20_ans : float
    #scenarios
    scenarios : str



@app.post("/calc_simulation")
async def calc_simulation(
    id : int,
    filename : str,
    prix_achat : int,
    type_centrale : str,
    montant_pret : int,
    taux_pret : float,
    duree_pret : int,
    devis_installation : bool = False,
    localisation = "localisation",
    annee : int = 2022,
    puissances = "jsp",

) :
    puissances = choisir_puissance('jsp')
    df_ENEDIS, constantes_ENEDIS = import_data(filename + ".csv", annee)
    for puissance in puissances:
        results = simulation(puissance, id, df_ENEDIS, constantes_ENEDIS, annee, devis_installation, prix_achat, type_centrale, localisation, montant_pret, taux_pret, duree_pret)
        print(results)
        return "Ok"


