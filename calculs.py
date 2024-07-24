import pandas as pd
import math
import logging
from numerize import numerize
import datetime
import numpy as np

# Constants
IRRADIATION_URL = "https://raw.githubusercontent.com/Smehlish/excel_to_python/main/Irradiation.csv"
COLUMNS_TO_DROP = [
    'PRM', 'Type de données', 'Date de début', 'Date de fin', 
    'Grandeur métier', 'Grandeur physique', 'Statut demandé', 'Unité', 
    'Pas en minutes', 'Statut de la mesure'
]

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def get_coef_by_postal_code(postal_code):
    df_loc = pd.read_csv('ensoleillement.csv', delimiter=';', encoding='latin1')
    df_loc['Coef'] = df_loc['Coef'].str.replace(',', '.').astype(float)
    postal_code = str(postal_code)[:2]

    coef = df_loc.loc[df_loc['Num dép'] == postal_code, 'Coef']
    print(df_loc.loc[df_loc['Num dép'] == postal_code, 'Nom'])
    if not coef.empty:
        return coef.values[0]
    else:
        return 1


def import_data(file_path, localisation, orientation, inclinaison):
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

        # Trouver les années complètes disponibles
        df['Year'] = df['Timestamp'].dt.year
        periods_per_year = {
            5: 105120,   # 5 minutes intervals in a year
            10: 52560,   # 10 minutes intervals in a year
            30: 17520    # 30 minutes intervals in a year
        }
        periods_required = periods_per_year[constants['pas_en_minutes']]

        # Vérifier que chaque année a le bon nombre de périodes et toutes les valeurs présentes
        complete_years = df.groupby('Year').filter(lambda x: len(x) == periods_required and x['Valeur'].notna().all())['Year'].unique()
        
        if len(complete_years) == 0:
            raise ValueError("Aucune année complète trouvée dans les données avec toutes les valeurs présentes. Vérifiez que le fichier CSV transmis par ENEDIS soit complet sur au moins une année, sinon vous pouvez essayer d'approximer ces données manquantes en copiant celles d'autres périodes. Si les périodes sont trop longues, contactez nous ! ")
        else:
            # Select the most recent complete year
            annee = complete_years.max()
        
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

        # Convert consumption to kWh
        df['Valeur'] = df['Valeur'].astype(float) / 1000

        total_consumption = df['Valeur'].sum() / (60000 / constants['pas_en_minutes'])

        # Calculate theoretical production and unit production
        efficacite_lumineuse = {'basse': 0.005, 'haute': 0.21* efficiency_modelization(orientation, inclinaison) * get_coef_by_postal_code(localisation)}
        ratio_surface_puissance = 222
        df['production_theorique'] = df.apply(
            lambda row: (efficacite_lumineuse['basse'] if row['Irradiation'] < 5 else efficacite_lumineuse['haute']) * row['Irradiation'] / ratio_surface_puissance, axis=1
        )
        production_unitaire = df['production_theorique'].sum() / (60000 / constants['pas_en_minutes'])

        return df, {'total_consumption': total_consumption, 'production_unitaire': production_unitaire, **constants}
    except Exception as e:
        logging.error(f"Error in import_data: {str(e)}")
        raise


def choisir_puissance(surface_max):
    try:
        puissance_max = math.floor(surface_max / 5)
        step = puissance_max  / 30
        puissances = [int(step * i) for i in range(1, 31)]
        logging.info(f"Puissances considérées : {puissances}")
        return puissances
    except Exception as e:
        logging.error(f"Erreur dans choisir_puissance: {str(e)}")
        raise


# Représentation du tableau d'efficacité
"""
tableau_efficacite = {
    'est': {0: 88, 15: 87, 25: 85, 35: 83, 50: 77, 70: 65, 90: 50},
    'sud-est': {0: 88, 15: 93, 25: 95, 35: 95, 50: 92, 70: 81, 90: 64},
    'sud': {0: 88, 15: 96, 25: 99, 35: 100, 50: 98, 70: 87, 90: 68},
    'sud-ouest': {0: 88, 15: 93, 25: 95, 35: 95, 50: 92, 70: 81, 90: 64},
    'ouest': {0: 88, 15: 87, 25: 85, 35: 82, 50: 76, 70: 65, 90: 50},
}
"""

def efficiency_modelization(orientation, inclination):
    orientation = orientation % 360
    if orientation > 180:
        orientation = 360 - orientation  # symmetrie

    intercept = 67.31
    coefs = {
        'x0': 0.2523,
        'x1': -0.3414,
        'x0^2': -0.000623,
        'x0 x1': 0.008771,
        'x1^2': -0.007267,
        'x0^3': -2.613e-07,
        'x0^2 x1': -2.48e-05,
        'x0 x1^2': 1.695e-06,
        'x1^3': -3.317e-06
    }

    efficiency = (intercept +
                  coefs['x0'] * orientation +
                  coefs['x1'] * inclination +
                  coefs['x0^2'] * orientation**2 +
                  coefs['x0 x1'] * orientation * inclination +
                  coefs['x1^2'] * inclination**2 +
                  coefs['x0^3'] * orientation**3 +
                  coefs['x0^2 x1'] * orientation**2 * inclination +
                  coefs['x0 x1^2'] * orientation * inclination**2 +
                  coefs['x1^3'] * inclination**3)

    return efficiency/100

def simulation(
        puissance, 
        df_ENEDIS, 
        constantes_ENEDIS, 
        prix_achat, 
        type_centrale,
        montant_pret_bancaire, 
        taux_pret_bancaire, 
        duree_pret_bancaire) -> dict:
    try:
        total_consumption = constantes_ENEDIS['total_consumption']
        production_unitaire = constantes_ENEDIS['production_unitaire']
        pas_en_minutes = constantes_ENEDIS['pas_en_minutes']

        df = df_ENEDIS.copy(deep=True)

        # Define the sale price based on power sites qui publient les données https://terresolaire.com/Blog/rentabilite-photovoltaique/tarif-rachat-photovoltaique/ ; https://soleriel.fr/guide-solaire/aide-photovoltaique/tarifs-achat-photovoltaique/
        prix_vente = (
            130.1 if puissance <= 36 else
            78.1 if puissance <= 99.9 else
            114.1
        )

        # Installation prime in €/kWc installed
        prime_installation = (
            300 if puissance <= 3 else
            230 if puissance <= 9 else
            200 if puissance <= 36 else
            100 if puissance <= 100 else
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
            tot_production * prix_achat*10 * taux_AC + 
            tot_production * prix_vente * (1 - taux_AC) - 
            cout_maintenance
        )
        
        benefices_an_pret = (
            benefices_an_brut - 
            montant_pret_bancaire * taux_pret_bancaire
        )
        amortissement = cout_installation / benefices_an_pret if benefices_an_pret != 0 else float('inf')
        baisse_facture = benefices_an_pret/(total_consumption*1000*prix_achat/100) # on passe la conso en kWh et le prix en euros
       
        bilan_20_ans = benefices_an_brut * 20 - cout_installation - montant_pret_bancaire * taux_pret_bancaire*0.01 * duree_pret_bancaire
        return {
            "puissance": puissance,
            "cout_installation": round(cout_installation, 3 - int(math.floor(math.log10(abs(cout_installation)))) - 1),
            "surface": puissance*5,
            "baisse_facture": round(baisse_facture * 100, 1),
            "amortissement": round(amortissement, 3 - int(math.floor(math.log10(abs(amortissement)))) - 1),
            "autoconso": round(taux_AC * 100, 1),
            "autoprod": round(taux_AP * 100, 1),
            "bilan_20_ans": round(bilan_20_ans, 3 - int(math.floor(math.log10(abs(bilan_20_ans)))) - 1),
            "tri": 1, # TODO
        }
    except Exception as e:
        logging.error(f"Error in simulation: {str(e)}")
        return {"error": str(e)}

def calculate_scenarios(data, conso_totale):
    logging.info("Calculating scenarios for data : %s", data)
    scenarios = {}
    
    # Puissance maximale
    puissance_max = max(data, key=lambda x: x['puissance'])
    scenarios['puissance_max'] = puissance_max['puissance']
    
    # Amortissement le plus rapide
    amortissement_rapide = min(data, key=lambda x: x['amortissement'])
    scenarios['amortissement_rapide'] = amortissement_rapide['puissance']
    
    # 100% autoconsommation
    autoconso_100 = [d for d in data if d['autoconso'] > 99]
    if autoconso_100:
        scenarios['autoconso_100'] = autoconso_100[-1]['puissance']
    else:
        scenarios['autoconso_100'] = None
    
    # BEPOS
    bepos = None
    for d in data:
        if d['autoprod'] >= conso_totale:
            bepos = d
            break
    if bepos:
        scenarios['bepos'] = bepos['puissance']
    else:
        scenarios['bepos'] = None
    
    # Bénéfices les plus importants
    benefices_max = max(data, key=lambda x: x['bilan_20_ans'])
    scenarios['benefices_max'] = benefices_max['puissance']
    
    # Le plus rentable
    rentable = max(data, key=lambda x: x['tri'])
    scenarios['rentable'] = rentable['puissance']
    
    return scenarios