import os
import logging
from typing import List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError
from calculs import simulation, choisir_puissance, import_data, calculate_scenarios
from fastapi.encoders import jsonable_encoder
import json
import concurrent.futures

# Import Supabase client
from supabase import create_client, Client

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

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

# Initialize Supabase client
url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url, key)

class SimulationRequest(BaseModel):
    id: int
    email: str = Field(..., description="The email of the user")
    prix_achat: int = Field(..., gt=0, description="The purchase price must be positive")
    type_centrale: str = Field(..., description="The type of power plant")
    localisation: int = Field(..., description="The location of the installation")
    surface: float = Field(..., gt=0, description="The surface area of the installation must be positive")
    orientation: float = Field(..., gt=0, description="The orientation of the installation")
    inclinaison: float = Field(..., gt=0, description="The inclination of the installation")
    montant_pret: Optional[int] = Field(0, ge=0, description="The loan amount must be positive")
    taux_pret: Optional[float] = Field(0, ge=0, le=100, description="The loan interest rate must be between 0 and 100")
    duree_pret: Optional[int] = Field(0, ge=0, description="The loan duration in years must be positive")

def calculate_simulation_task(request: SimulationRequest, file_path: str):
    """
    Function to perform the long-running simulation task.
    """
    try:
        logger.info(f"Starting calculation task for request ID {request.id}")

        # Update the status to 'Processing'
        supabase.table("simulations").update({"status": "Processing"}).eq("form_id", request.id).execute()

        puissances = choisir_puissance(request.surface)
        df_ENEDIS, constantes_ENEDIS = import_data(
            file_path, 
            localisation=request.localisation,
            orientation=request.orientation, 
            inclinaison=request.inclinaison,
        )

        """with concurrent.futures.ProcessPoolExecutor() as executor:
            futures = {
                executor.submit(simulation, puissance, df_ENEDIS, constantes_ENEDIS, request.prix_achat, request.type_centrale, request.montant_pret, request.taux_pret, request.duree_pret): puissance
                for puissance in puissances
            }

            points_simu = []
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                    points_simu.append(result)
                except Exception as e:
                    logger.error(f"Simulation failed for power {futures[future]}: {e}") """
        points_simu = []
        for puissance in puissances:
            points_simu.append(simulation(puissance, df_ENEDIS, constantes_ENEDIS, request.prix_achat, request.type_centrale, request.montant_pret, request.taux_pret, request.duree_pret))

        points_simu.sort(key=lambda x: x['puissance'])
        logger.info("All simulations completed :", points_simu)

        scenarios = calculate_scenarios(
            data=points_simu, 
            conso_totale=constantes_ENEDIS['total_consumption'], 
        )

        logger.info(f"Scenarios calculated: {scenarios}")

        # Update the status to 'Completed' and save the results
        supabase.table("simulations").update({
            "results": {"points_simu": points_simu, "scenarios": scenarios}
        }).eq("form_id", request.id).execute()

        supabase.table("simulations").update({"status": "Completed"}).eq("form_id", request.id).execute()

    except Exception as e:
        logger.error(f"Error in calculate_simulation_task !", exc_info=True)
        # Update the status to 'Error' and save the error message
        supabase.table("simulations").update({
            "status": "Error",
            "results": {"error": str(e)}
        }).eq("form_id", request.id).execute()

def upload_file_and_insert_data_task(file_path: str, simulation_request: SimulationRequest):
    """
    Function to upload the file to Supabase storage and insert data into the database.
    """
    try:
        
        # Insert the data into the database
        insert_data = {
            "form_id": simulation_request.id,
            "email": simulation_request.email,
            "prix_achat": simulation_request.prix_achat,
            "type_centrale": simulation_request.type_centrale,
            "localisation": simulation_request.localisation,
            "surface": simulation_request.surface,
            "orientation": simulation_request.orientation,
            "inclinaison": simulation_request.inclinaison,
            "montant_pret": simulation_request.montant_pret,
            "taux_pret": simulation_request.taux_pret,
            "duree_pret": simulation_request.duree_pret,
            "file_path": str(simulation_request.id),
            "status": "Received",
            "results": {}
        }
        supabase.table("simulations").insert(insert_data).execute()
        logger.info(f"Data inserted into database for request ID {simulation_request.id}")

        # Upload the file to Supabase storage
        with open(file_path, "rb") as f:
            res = supabase.storage.from_("Enedis").upload(file=f, path=str(simulation_request.id), file_options={"content-type": "text/csv"})

        # Add the simulation task to background tasks
        calculate_simulation_task(simulation_request, file_path)
        
    except Exception as e:
        logger.error(f"Error in upload_file_and_insert_data_task: {str(e)}")
        # Update the status to 'Error' and save the error message
        supabase.table("simulations").update({
            "status": "Error",
            "results": {"error": str(e)}
        }).eq("form_id", simulation_request.id).execute()
    
    finally:
        os.remove(file_path)  # Clean up the uploaded file after processing
        logger.info(f"File {simulation_request.id} removed after processing")

@app.post("/calc_simulation", response_model=dict)
async def calc_simulation(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    id: int = Form(...),
    email: str = Form(...),
    prix_achat: int = Form(...),
    type_centrale: str = Form(...),
    localisation: int = Form(...),
    surface: float = Form(...),
    orientation: float = Form(...),
    inclinaison: float = Form(...),
    montant_pret: Optional[int] = Form(...),
    taux_pret: Optional[float] = Form(...),
    duree_pret: Optional[int] = Form(...),
):
    """
    Endpoint to calculate simulation based on provided parameters and uploaded file.
    """
    os.makedirs("files", exist_ok=True)  # Ensure the directory exists

    file_location = os.path.join("files", f"{id}.csv")
    with open(file_location, "wb") as f:
        f.write(file.file.read())

    try:
        # Construct SimulationRequest object
        simulation_request = SimulationRequest(
            id=id,
            email=email,
            prix_achat=prix_achat,
            type_centrale=type_centrale,
            localisation=localisation,
            surface=surface,
            orientation=orientation,
            inclinaison=inclinaison,
            montant_pret=montant_pret,
            taux_pret=taux_pret,
            duree_pret=duree_pret,
        )

        logger.info(f"Received simulation request: {jsonable_encoder(simulation_request)}")

        # Add the upload file and insert data task to background tasks
        background_tasks.add_task(upload_file_and_insert_data_task, file_location, simulation_request)

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

@app.get("/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
