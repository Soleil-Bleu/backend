import pandas as pd
import math
from numerize import numerize
import datetime

# Définition des constantes
DATA_PATH = "https://raw.githubusercontent.com/Smehlish/excel_to_python/main/"
IRRADIATION_URL =  "https://raw.githubusercontent.com/Smehlish/excel_to_python/main/Irradiation.csv" #TODO prendre l'irradiation de la localisation et la convertir dans le bon pas de temps
COLUMNS_TO_DROP = ['PRM', 'Type de données', 'Date de début', 'Date de fin', 'Grandeur métier', 'Grandeur physique', 'Statut demandé', 'Unité', 'Pas en minutes', 'Statut de la mesure']

# Charger les données d'irradiation
def import_data(filename, annee):
    """
    Charge les données d'ENEDIS et les données d'irradiation, effectue des manipulations sur le DataFrame,
    puis retourne le DataFrame résultant et les constantes ENEDIS.

    Args:
        ENEDIS_filename (str): Nom du fichier d'ENEDIS.
        annee (int): Année à filtrer dans le DataFrame.

    Returns:
        pd.DataFrame: DataFrame résultant après les manipulations.
        Liste des données de consommation.
        Erreurs si il y a
    """
    df = pd.read_csv(DATA_PATH + filename, sep=';', encoding='ISO-8859-1', dtype='unicode')
    df_irrad = pd.read_csv(IRRADIATION_URL, sep=';', encoding='ISO-8859-1', dtype='unicode')

    # Récupération des constantes (1ère ligne) | TODO mettre ça dans import_data()
    PRM = df['PRM'].iloc[0]
    type_de_donnees = df['Type de données'].iloc[0]
    date_de_debut = df['Date de début'].iloc[0]
    date_de_fin = df['Date de fin'].iloc[0]
    grandeur_metier = df['Grandeur métier'].iloc[0]
    grandeur_physique = df['Grandeur physique'].iloc[0]
    statut_demande = df['Statut demandé'].iloc[0]
    unite = df['Unité'].iloc[0]
    pas_en_minutes = int(df['Pas en minutes'].iloc[0])
    df.drop(columns=COLUMNS_TO_DROP, inplace=True) # suppression des colonnes inutiles

    # Conversion du timestamp
    df['Timestamp'] = pd.to_datetime(df['Date de la mesure'] + ' ' + df['Heure de la mesure'], format='%d-%m-%Y %H:%M')
    df.drop(columns=['Date de la mesure', 'Heure de la mesure'], inplace=True)

    # Filtre sur l'année
    df = df[df['Timestamp'].dt.year == annee].copy(deep=True) #TODO prendre année 2023 si copmlète, sinon 2022, sinon 2021 ...

    df['Irradiation']=''
    ### copie-colle l'irradiation en fonction du pas de temps | TODO mettre ça dans import_data() TODO irradiation la ou on est et le convertir dans le bon pas de temps
    if pas_en_minutes == 5 :
        df['Irradiation'].iloc[0:] = df_irrad['Irradiation 5min'].iloc[0:]
    elif pas_en_minutes == 10 :
        donnees_irradiation_10min = df_irrad['Irradiation 10min'].iloc[0:]
        df['Irradiation'].iloc[0:] = donnees_irradiation_10min
    elif pas_en_minutes == 30 :
        donnees_irradiation_30min = df_irrad['Irradiation 30min'].iloc[0:]
        df['Irradiation'].iloc[0:] = donnees_irradiation_30min
    else :
        print("Une erreur s'est produite : impossible d'accéder au pas de temps (il doit figurer sur la cellule M2 du fichier CSV d'ENEDIS)")

    df['Irradiation'] = pd.to_numeric(df['Irradiation'], errors='coerce') #conversion de la colonne "Iradiation" en float

    ### Division de la colonne puissance par 1000 pour passer en kWh
    df['Valeur'] = df['Valeur'].astype(float) / 1000

    tot_consommation = df['Valeur'].sum() / (60000/pas_en_minutes)


    ### Création colonne "production_théorique" et "energie surplus"
    efficacite_intensite_lumineuse_basse = 0.005
    efficacite_intensite_lumineuse_haute = 0.21  # A changer en fonction de la region si on a pas l'irradiation de l'endroit
    ratio_surface_puissance = 222
    df['production_theorique'] = df.apply(lambda row: (efficacite_intensite_lumineuse_basse * row['Irradiation'] if row['Irradiation'] < 5 else efficacite_intensite_lumineuse_haute * row['Irradiation']) / ratio_surface_puissance * 1, axis=1)
    production_unitaire = df['production_theorique'].sum() / (60000/pas_en_minutes)

    constantes_ENEDIS = [tot_consommation, production_unitaire, PRM, type_de_donnees, date_de_debut, date_de_fin, grandeur_metier, grandeur_physique, statut_demande, unite, pas_en_minutes]
    return df, constantes_ENEDIS



def simulation(puissance, id, df_ENEDIS, constantes_ENEDIS, annee, devis_installation, prix_achat, type_centrale, localisation, montant_pret_bancaire, taux_pret_bancaire, duree_pret_bancaire) -> dict:
    '''   Effectue une simulation en fonction de différents paramètres pour une puissance et append le résultat dans le tableau results.

    Args:
        puissance (float): Puissance pour la simulation.
        id (int)

        df_ENEDIS (pd.DataFrame): DataFrame des données ENEDIS.
        constantes_ENEDIS (list): Liste des constantes ENEDIS.
        annee (int): Année pour la simulation.
        devis_installation (bool): Indique si un devis d'installation est disponible.
        prix_achat (float): Prix d'achat de l'électricité.
        type_centrale (str): Type de centrale ('toiture' ou 'ombriere').
        localisation (str): Coordonnées GPS ou emplacement.
        montant_pret_bancaire (float): Montant du prêt bancaire.
        taux_pret_bancaire (float): Taux du prêt bancaire.
        duree_pret_bancaire (int): Durée du prêt bancaire en années.

    Returns:
        Le dict puissance '''
    # Charger les données de consommation ENEDIS
    tot_consommation, production_unitaire, PRM, type_de_donnees, date_de_debut, date_de_fin, grandeur_metier, grandeur_physique, statut_demande, unite, pas_en_minutes = constantes_ENEDIS
    df = df_ENEDIS.copy(deep=True)


    # Définir le prix vente en fonction de puissance ### sites qui publient les données https://terresolaire.com/Blog/rentabilite-photovoltaique/tarif-rachat-photovoltaique/ ; https://soleriel.fr/guide-solaire/aide-photovoltaique/tarifs-achat-photovoltaique/
    prix_vente = (
             133.9 if puissance <= 36.
        else  80.3 if puissance <= 99.9
        else 131.2)

    # Prime en €/kWc installé                        ### sites qui publient les données https://terresolaire.com/Blog/rentabilite-photovoltaique/tarif-rachat-photovoltaique/ ; https://soleriel.fr/guide-solaire/aide-photovoltaique/tarifs-achat-photovoltaique/
    prime_installation = (
             510 if puissance <=   3
        else 380 if puissance <=   9
        else 210 if puissance <=  36
        else 110 if puissance <= 100
        else   0)

    df['production_theorique'] *= puissance
    df['energie_surplus'] = df.apply(lambda row: 0 if row['production_theorique'] < row['Valeur'] else (row['production_theorique'] - row['Valeur']) / (60/pas_en_minutes), axis=1)

    #TODO à changer avec la localisation
    productible = 1.23 #MWh générés pour chaque kWc installé par an

    ### Calcul de la consommation, production et energie en surplus en MWh
    tot_production = production_unitaire * puissance
    tot_energie_surplus = df['energie_surplus'].sum() / (1000)

    ### Calcul des taux Auto-Cons et Auto-Prod en %
    taux_AC = 1-(tot_energie_surplus/tot_production)
    taux_AP = (taux_AC*tot_production)/tot_consommation

    ### Calcul coûts installation,
    courbe_tendence_toiture_inf_100_A = -315.45047
    courbe_tendence_toiture_inf_100_B = 2645.9
    courbe_tendence_toiture_sup_100_A = -0.483
    courbe_tendence_toiture_sup_100_B = 1241.49
    courbe_tendence_ombriere_inf_100_A = -211.59148
    courbe_tendence_ombriere_inf_100_B = 2570.567
    courbe_tendence_ombriere_sup_100_A = -0.3654
    courbe_tendence_ombriere_sup_100_B = 1633
    prix_onduleur = 50.025 # prix remplacement des onduleur par an par kWc
    nettoyage = 500 # prix nettoyage, assurance, gestion
    print(devis_installation, type(devis_installation))
    if devis_installation == False : #cas pas de devis
        if type_centrale == 'toiture' :
            if puissance <= 100 :
                cout_installation = (courbe_tendence_toiture_inf_100_A * math.log(puissance) + courbe_tendence_toiture_inf_100_B) * puissance
            else :
                cout_installation = (courbe_tendence_toiture_sup_100_A * puissance + courbe_tendence_toiture_sup_100_B) * puissance
        else: # cas ombriere
            if puissance <= 100 :
                cout_installation = (courbe_tendence_ombriere_inf_100_A * math.log(puissance) + courbe_tendence_ombriere_inf_100_B) * puissance
            else :
                cout_installation = (courbe_tendence_ombriere_sup_100_A * puissance + courbe_tendence_ombriere_sup_100_B) * puissance
    else :  # cas devis
        cout_installation = devis_installation
    ### calcul de la maintenance par an, bénéfices par an, amortissement et bilan à 20 ans
    cout_maintenance = puissance*prix_onduleur + nettoyage
    benefices_an_brut = (productible*puissance*prix_achat*taux_AC + productible*puissance*prix_vente*(1-taux_AC) - cout_maintenance)
    benefices_an_pret = (productible*puissance*prix_achat*taux_AC + productible*puissance*prix_vente*(1-taux_AC) - cout_maintenance - montant_pret_bancaire*taux_pret_bancaire)
    amortissement = cout_installation/benefices_an_pret
    bilan_20_ans = benefices_an_brut*20 - cout_installation - montant_pret_bancaire*taux_pret_bancaire*duree_pret_bancaire


    results =  {
        "puissance" : puissance,
        "id" : id,
        "amortissement" : numerize.numerize(amortissement),
        "autoconso" : round(taux_AC*100,1),
        "autoprod" : round(taux_AP*100,1),
        "benef_20_ans" : numerize.numerize(bilan_20_ans),
        "tri" : None, # TODO
        # "created_at" : datetime.datetime.now(),
        
    }

    return results


### MAIN ###

### Definition de la puissance
def choisir_puissance(choix_puissance, puissance_choisie = 100):
    if choix_puissance == 'puissance precise':
        return [puissance_choisie]
    elif choix_puissance == 'puissance potentielle':
        return [i*puissance_choisie/10 for i in range (1,12)]
    else:
        return [3, 9, 15, 25, 36, 50, 75, 100, 125, 150, 175, 200, 300, 400, 500]


### TEST ###
"""
puissances = choisir_puissance('jsp')  # par défaut "jsp", sinon "puissance precise" ou "puissance potentielle"
id = 1
filename = "data_exemple.csv"
annee = 2022
devis_installation = False              # False si il a pas de devis et prix exact si il en a un
prix_achat = 338
type_centrale = 'ombriere'               # choisir 'toiture' ou 'ombriere'
localisation = "localisation"           # coordonnées GPS ?
montant_pret_bancaire = 50000           # faire attention qu'il ne soit pas plus élevé que le cout installation
taux_pret_bancaire = 0.00                  # % du remboursement  TODO dans l'amortisement (si 2%, mettre 0.02)
duree_pret_bancaire = 10                # durée en année

df_ENEDIS, constantes_ENEDIS = import_data(filename, annee)
for puissance in puissances:
    results = simulation(puissance, id, df_ENEDIS, constantes_ENEDIS, annee, devis_installation, prix_achat, type_centrale, localisation, montant_pret_bancaire, taux_pret_bancaire, duree_pret_bancaire)
    print(results)
"""