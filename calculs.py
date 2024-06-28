import pandas as pd
import math
import logging
from numerize import numerize
import datetime

# Constants
IRRADIATION_URL = "https://raw.githubusercontent.com/Smehlish/excel_to_python/main/Irradiation.csv"
COLUMNS_TO_DROP = [
    'PRM', 'Type de données', 'Date de début', 'Date de fin', 
    'Grandeur métier', 'Grandeur physique', 'Statut demandé', 'Unité', 
    'Pas en minutes', 'Statut de la mesure'
]

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

def import_data(file_path, annee):
    try:
        df = pd.read_csv(file_path, sep=';', encoding='ISO-8859-1', dtype='unicode')
        df_irrad = pd.read_csv(IRRADIATION_URL, sep=';', encoding='ISO-8859-1', dtype='unicode')

        # Extract constants
        constants = {
            'PRM': df['PRM'].iloc[0],
            'type_de_donnees': df['Type de données'].iloc[0],
            'date_de_debut': df['Date de début'].iloc[0],
            'date_de_fin': df['Date de fin'].iloc[0],
            'grandeur_metier': df['Grandeur métier'].iloc[0],
            'grandeur_physique': df['Grandeur physique'].iloc[0],
            'statut_demande': df['Statut demandé'].iloc[0],
            'unite': df['Unité'].iloc[0],
            'pas_en_minutes': int(df['Pas en minutes'].iloc[0])
        }

        # Drop unnecessary columns
        df.drop(columns=COLUMNS_TO_DROP, inplace=True)

        # Convert timestamp
        df['Timestamp'] = pd.to_datetime(df['Date de la mesure'] + ' ' + df['Heure de la mesure'], format='%d-%m-%Y %H:%M')
        df.drop(columns=['Date de la mesure', 'Heure de la mesure'], inplace=True)

        # Filter by year
        df = df[df['Timestamp'].dt.year == annee].copy(deep=True)

        # Add and populate Irradiation column based on the time step
        df['Irradiation'] = ''
        if constants['pas_en_minutes'] == 5:
            df['Irradiation'] = df_irrad['Irradiation 5min'].iloc[:len(df)].values
        elif constants['pas_en_minutes'] == 10:
            df['Irradiation'] = df_irrad['Irradiation 10min'].iloc[:len(df)].values
        elif constants['pas_en_minutes'] == 30:
            df['Irradiation'] = df_irrad['Irradiation 30min'].iloc[:len(df)].values
        else:
            raise ValueError("Invalid time step in CSV file")

        df['Irradiation'] = pd.to_numeric(df['Irradiation'], errors='coerce')

        # Convert power to kWh
        df['Valeur'] = df['Valeur'].astype(float) / 1000

        total_consumption = df['Valeur'].sum() / (60000 / constants['pas_en_minutes'])

        # Calculate theoretical production and unit production
        efficacite_lumineuse = {'basse': 0.005, 'haute': 0.21}
        ratio_surface_puissance = 222
        df['production_theorique'] = df.apply(
            lambda row: (efficacite_lumineuse['basse'] if row['Irradiation'] < 5 else efficacite_lumineuse['haute']) * row['Irradiation'] / ratio_surface_puissance, axis=1
        )
        production_unitaire = df['production_theorique'].sum() / (60000 / constants['pas_en_minutes'])

        return df, {'total_consumption': total_consumption, 'production_unitaire': production_unitaire, **constants}
    except Exception as e:
        logging.error(f"Error in import_data: {str(e)}")
        raise

def simulation(puissance, id, df_ENEDIS, constantes_ENEDIS, annee, prix_achat, type_centrale, localisation, montant_pret_bancaire, taux_pret_bancaire, duree_pret_bancaire) -> dict:
    try:
        total_consumption = constantes_ENEDIS['total_consumption']
        production_unitaire = constantes_ENEDIS['production_unitaire']
        pas_en_minutes = constantes_ENEDIS['pas_en_minutes']

        df = df_ENEDIS.copy(deep=True)

        # Define the sale price based on power
        prix_vente = (
            133.9 if puissance <= 36 else
            80.3 if puissance <= 99.9 else
            131.2
        )

        # Installation prime in €/kWc installed
        prime_installation = (
            510 if puissance <= 3 else
            380 if puissance <= 9 else
            210 if puissance <= 36 else
            110 if puissance <= 100 else
            0
        )

        df['production_theorique'] *= puissance
        df['energie_surplus'] = df.apply(
            lambda row: 0 if row['production_theorique'] < row['Valeur'] else (row['production_theorique'] - row['Valeur']) / (60 / pas_en_minutes),
            axis=1
        )

        # Change based on location
        productible = 1.23 # MWh generated for each kWc installed per year

        # Calculate consumption, production and surplus energy in MWh
        tot_production = production_unitaire * puissance
        tot_energie_surplus = df['energie_surplus'].sum() / 1000

        # Log the relevant variables
        logging.debug(f"Total Production: {tot_production}")
        logging.debug(f"Total Energy Surplus: {tot_energie_surplus}")

        # Safeguard against division by zero
        if tot_production == 0:
            logging.warning("Total production is zero, setting autoconso and autoprod to zero.")
            taux_AC = 0
            taux_AP = 0
        else:
            taux_AC = 1 - (tot_energie_surplus / tot_production)
            taux_AP = (taux_AC * tot_production) / total_consumption if total_consumption != 0 else 0

        # Calculate installation costs
        courbe_tendence = {
            'toiture': {
                'inf_100': {'A': -315.45047, 'B': 2645.9},
                'sup_100': {'A': -0.483, 'B': 1241.49}
            },
            'ombriere': {
                'inf_100': {'A': -211.59148, 'B': 2570.567},
                'sup_100': {'A': -0.3654, 'B': 1633}
            }
        }

        prix_onduleur = 50.025 # inverter replacement cost per year per kWc
        nettoyage = 500 # cleaning, insurance, management cost

        # if not devis_installation: # if quote = 0€ (default)
        courbe = courbe_tendence[type_centrale]
        if puissance <= 100:
            cout_installation = (courbe['inf_100']['A'] * math.log(puissance) + courbe['inf_100']['B']) * puissance
        else:
            cout_installation = (courbe['sup_100']['A'] * puissance + courbe['sup_100']['B']) * puissance
        # else: cout_installation = devis_installation

        # Calculate maintenance cost per year, annual profits, amortization and 20-year balance
        cout_maintenance = puissance * prix_onduleur + nettoyage
        benefices_an_brut = (
            productible * puissance * prix_achat*100 * taux_AC + 
            productible * puissance * prix_vente * (1 - taux_AC) - 
            cout_maintenance
        )
        benefices_an_pret = (
            benefices_an_brut - 
            montant_pret_bancaire * taux_pret_bancaire
        )
        amortissement = cout_installation / benefices_an_pret if benefices_an_pret != 0 else float('inf')
        bilan_20_ans = benefices_an_brut * 20 - cout_installation - montant_pret_bancaire * taux_pret_bancaire*0.01 * duree_pret_bancaire

        return {
            "puissance": puissance,
            "amortissement": round(amortissement, 3 - int(math.floor(math.log10(abs(amortissement)))) - 1),
            "autoconso": round(taux_AC * 100, 1),
            "autoprod": round(taux_AP * 100, 1),
            "bilan_20_ans": round(bilan_20_ans, 3 - int(math.floor(math.log10(abs(bilan_20_ans)))) - 1),
            "tri": 1, # TODO
        }
    except Exception as e:
        logging.error(f"Error in simulation: {str(e)}")
        return {"error": str(e)}


# Choose power function
def choisir_puissance(puissance_min, puissance_max):
    """
    Choose 12 evenly distributed integer power values between a given minimum and maximum.

    Args:
        puissance_min (float): Minimum power value.
        puissance_max (float): Maximum power value.

    Returns:
        List[int]: List of 12 evenly distributed integer power values between min and max.
    """
    try:
        step = (puissance_max - puissance_min) / 11
        return [int(puissance_min + step * i) for i in range(12)]
    except Exception as e:
        logging.error(f"Error in choisir_puissance: {str(e)}")
        raise

