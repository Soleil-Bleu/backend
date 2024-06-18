import os
import logging
from typing import List, Optional, Annotated
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import pandas as pd
from calculs import simulation, choisir_puissance, import_data

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="SoleilBleuAPI"
)

origins = [
    "http://localhost:3000",
    "http://localhost:5174",
    "*" #TODO enlever quand on sait l'adresse du front
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SimulationRequest(BaseModel):
    id: int
    prix_achat: int = Field(..., gt=0, description="The purchase price must be positive")
    type_centrale: str = Field(..., description="The type of power plant")
    montant_pret: int = Field(..., gt=0, description="The loan amount must be positive")
    taux_pret: float = Field(..., gt=0, le=1, description="The loan interest rate must be between 0 and 1")
    duree_pret: int = Field(..., gt=0, description="The loan duration in years must be positive")
    devis_installation: bool = Field(False, description="Whether to include installation costs in the quote")
    localisation: str = Field("localisation", description="The location of the installation")
    annee: int = Field(2022, ge=2000, le=2100, description="The year of the simulation must be between 2000 and 2100")
    puissances: Optional[List[Annotated[float, Field(gt=0)]]] = Field(None, description="List of power values to simulate")

# A dictionary to store results, in a real application this should be a database
results_store = {}

def calculate_simulation_task(request_id: int, request: SimulationRequest, file_path: str):
    """
    Function to perform the long-running simulation task.
    """
    try:
        logger.debug("Starting calculation task for request ID %d", request_id)

        if request.puissances is None or not request.puissances:
            request.puissances = choisir_puissance('jsp')

        df_ENEDIS, constantes_ENEDIS = import_data(file_path, request.annee)

        logger.debug("Data imported successfully for request ID %d", request_id)

        results = []
        for puissance in request.puissances:
            result = simulation(
                puissance, request.id, df_ENEDIS, constantes_ENEDIS, request.annee,
                request.devis_installation, request.prix_achat, request.type_centrale,
                request.localisation, request.montant_pret, request.taux_pret, request.duree_pret
            )
            results.append(result)
        results_store[request_id] = results
    except Exception as e:
        logger.error("Error in calculate_simulation_task: %s", str(e))
        results_store[request_id] = {"error": str(e)}
    finally:
        os.remove(file_path)  # Clean up the uploaded file after processing
        logger.debug("File %s removed after processing", file_path)

@app.post("/calc_simulation", response_model=dict)
async def calc_simulation(
    background_tasks: BackgroundTasks,
    id: int = Form(...),
    prix_achat: int = Form(..., gt=0, description="The purchase price must be positive"),
    type_centrale: str = Form(...),
    montant_pret: int = Form(..., gt=0, description="The loan amount must be positive"),
    taux_pret: float = Form(..., gt=0, le=1, description="The loan interest rate must be between 0 and 1"),
    duree_pret: int = Form(..., gt=0, description="The loan duration in years must be positive"),
    devis_installation: bool = Form(False, description="Whether to include installation costs in the quote"),
    localisation: str = Form("localisation", description="The location of the installation"),
    annee: int = Form(2022, ge=2000, le=2100, description="The year of the simulation must be between 2000 and 2100"),
    puissances: Optional[List[float]] = Form(None, description="List of power values to simulate"),
    file: UploadFile = File(...)
):
    """
    Endpoint to calculate simulation based on provided parameters and uploaded file.
    """
    os.makedirs("files", exist_ok=True)  # Ensure the directory exists

    file_location = f"files/{file.filename}"
    with open(file_location, "wb") as f:
        f.write(file.file.read())

    request_data = SimulationRequest(
        id=id,
        prix_achat=prix_achat,
        type_centrale=type_centrale,
        montant_pret=montant_pret,
        taux_pret=taux_pret,
        duree_pret=duree_pret,
        devis_installation=devis_installation,
        localisation=localisation,
        annee=annee,
        puissances=puissances
    )

    logger.info("Received simulation request: %s", request_data)

    # Add the simulation task to background tasks
    background_tasks.add_task(calculate_simulation_task, id, request_data, file_location)

    return {"status": "Processing", "request_id": id}

@app.get("/simulation_result/{request_id}", response_model=dict)
async def get_simulation_result(request_id: int):
    """
    Endpoint to retrieve the results of a simulation.
    """
    result = results_store.get(request_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Result not found")
    return {"status": "Completed", "results": result}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
