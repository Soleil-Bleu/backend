import os
import logging
from typing import List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError
from calculs import simulation, choisir_puissance, import_data, calculate_scenarios
from fastapi.encoders import jsonable_encoder
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="SoleilBleuAPI")

origins = [
    "http://localhost:3000",
    "http://localhost:5174",
    "*"  # TODO: remove when the frontend address is known
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
    montant_pret: Optional[int] = Field(0, ge=0, description="The loan amount must be positive")
    taux_pret: Optional[float] = Field(0, ge=0, le=100, description="The loan interest rate must be between 0 and 100")
    duree_pret: Optional[int] = Field(0, ge=0, description="The loan duration in years must be positive")
    localisation: str = Field(..., description="The location of the installation")
    annee: int = Field(..., ge=2000, le=2100, description="The year of the simulation must be between 2000 and 2100")
    puissances: List[int] = Field(..., description="The minimum and maximum power value to simulate")

results_store = {}

def calculate_simulation_task(request_id: int, request: SimulationRequest, file_path: str):
    """
    Function to perform the long-running simulation task.
    """
    try:
        logger.info(f"Starting calculation task for request ID {request_id}")
        results_store[request_id] = {"status": "Processing"}

        puissance_min, puissance_max = request.puissances[0], request.puissances[-1]
        puissances = choisir_puissance(puissance_min, puissance_max)

        df_ENEDIS, constantes_ENEDIS = import_data(file_path, request.annee)

        points_simu = []
        for puissance in puissances:
            result = simulation(
                puissance, request.id, df_ENEDIS, constantes_ENEDIS, request.annee, 
                request.prix_achat, request.type_centrale,
                request.localisation, request.montant_pret, request.taux_pret, request.duree_pret
            )
            points_simu.append(result)
        scenarios = calculate_scenarios(points_simu, 500, 1000) #TODO
        results_store[request_id] = {"status": "Completed", "results": {"points_simu":points_simu,"scenarios":scenarios}}

    except Exception as e:
        logger.error(f"Error in calculate_simulation_task: {str(e)}")
        results_store[request_id] = {"status": "Error", "error": str(e)}
    finally:
        os.remove(file_path)  # Clean up the uploaded file after processing
        logger.info(f"File {file_path} removed after processing")

@app.post("/calc_simulation", response_model=dict)
async def calc_simulation(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    id: int = Form(...),
    prix_achat: int = Form(...),
    type_centrale: str = Form(...),
    montant_pret: Optional[int] = Form(...),
    taux_pret: Optional[float] = Form(...),
    duree_pret: Optional[int] = Form(...),
    localisation: str = Form(...),
    annee: int = Form(...),
    puissances: str = Form(...),  # Expecting a JSON string
):
    """
    Endpoint to calculate simulation based on provided parameters and uploaded file.
    """
    os.makedirs("files", exist_ok=True)  # Ensure the directory exists

    file_location = f"files/{file.filename}"
    with open(file_location, "wb") as f:
        f.write(file.file.read())

    try:
        logger.info("Received raw puissances: %s", puissances)
        
        # Convert puissances JSON string to list
        puissances_list = json.loads(puissances)
        logger.info("Parsed puissances: %s", puissances_list)

        # Construct SimulationRequest object
        simulation_request = SimulationRequest(
            id=id,
            prix_achat=prix_achat,
            type_centrale=type_centrale,
            montant_pret=montant_pret,
            taux_pret=taux_pret,
            duree_pret=duree_pret,
            localisation=localisation,
            annee=annee,
            puissances=puissances_list,
        )

        logger.info(f"Received simulation request: {jsonable_encoder(simulation_request)}")

        # Add the simulation task to background tasks
        background_tasks.add_task(calculate_simulation_task, simulation_request.id, simulation_request, file_location)

        return {"status": "Processing", "request_id": simulation_request.id}

    except ValidationError as ve:
        logger.error(f"Validation error: {ve.errors()}")
        raise HTTPException(status_code=422, detail={"validation_error": ve.errors()})
    except json.JSONDecodeError as je:
        logger.error(f"JSON decode error: {je}")
        raise HTTPException(status_code=422, detail={"json_error": str(je)})
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail={"unexpected_error": str(e)})

@app.get("/simulation_result/{request_id}", response_model=dict)
async def get_simulation_result(request_id: int):
    """
    Endpoint to retrieve the results of a simulation.
    """
    result = results_store.get(request_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Result not found")
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
