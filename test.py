import time
import unittest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

class TestSoleilBleuAPI(unittest.TestCase):

    def test_calc_simulation(self):
        # Path to the local file
        file_path = "data_exemple.csv"

        # Prepare the query parameters
        params = {
            "id": "0",
            "prix_achat": "340",
            "type_centrale": "toiture",
            "montant_pret": "50000",
            "taux_pret": "0.23",
            "duree_pret": "10",
            "devis_installation": "false",
            "localisation": "localisation",
            "annee": "2022",
            "puissance_min": "10",
            "puissance_max": "1000",
        }

        # Test the simulation endpoint
        with open(file_path, "rb") as file:
            files = {"file": ("data_exemple.csv", file, "text/csv")}
            response = client.post("/calc_simulation", params=params, files=files)

        # Debugging: Print the initial POST response
        print("Initial POST response:", response.status_code, response.json())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "Processing")
        self.assertIn("request_id", response.json())
        request_id = response.json()["request_id"]

        # Retry logic to check the status until it is completed
        max_retries = 30
        sleep_interval = 4  # seconds
        for attempt in range(max_retries):
            result_response = client.get(f"/simulation_result/{request_id}")
            # Debugging: Print each retry response
            print(f"Attempt {attempt + 1}: GET /simulation_result/{request_id} response:", result_response.status_code, result_response.json())

            if result_response.status_code == 200 and result_response.json()["status"] == "Completed":
                self.assertIn("results", result_response.json())
                break
            elif result_response.status_code == 500:
                self.fail(f"Simulation failed with 500 status: {result_response.json()}")
            else:
                print(f"Simulation not complete, retrying in {sleep_interval} seconds...")
                time.sleep(sleep_interval)
        else:
            self.fail(f"Simulation did not complete within {max_retries * sleep_interval} seconds")

    def test_result_not_found(self):
        # Test retrieving results for a non-existent request
        response = client.get("/simulation_result/9999")
        # Debugging: Print the GET response for non-existent request
        print("GET /simulation_result/9999 response:", response.status_code, response.json())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Result not found")

if __name__ == "__main__":
    unittest.main()
