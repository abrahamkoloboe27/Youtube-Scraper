"""
Gestionnaire de retry pour les téléchargements échoués dans Youtube-Fon-Scrapping.

Ce script autonome permet de :
- Récupérer les entrées ayant échoué dans MongoDB
- Relancer automatiquement le téléchargement de l'audio pour ces vidéos
- Mettre à jour le statut et le nombre de tentatives dans MongoDB

Variables d'environnement utilisées :
- MONGO_URI : URI de connexion MongoDB
- MONGO_DB : Nom de la base de données
- MONGO_COLLECTION : Nom de la collection des logs
"""
import os
import time
from dotenv import load_dotenv
from pymongo import MongoClient
from mongo_utils import insert_log, video_exists_in_metadata
from scraper import telecharger_video_savetube
import logging
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("youtube_retry_download.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()
# Configuration MongoDB
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB = os.getenv("MONGO_DB", "yt_scrap")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "logs")

client = MongoClient(MONGO_URI)
db = client[MONGO_DB]
collection = db[MONGO_COLLECTION]

def retry_failed_downloads():
    """
    Récupère les échecs de téléchargement depuis MongoDB et relance le processus.
    Parcourt les entrées ayant le statut 'failed', tente un nouveau téléchargement,
    puis met à jour le statut et le nombre de tentatives dans la base.
    Returns:
        None
    """
    failed_entries = collection.find({
        "status": "failed",
    })
    logger.info(f"Nombre d'échecs à réessayer : {failed_entries}")
    for entry in failed_entries:
        video_info = {
            "video_id": entry["video_id"],
            "url": entry["url"],
            "title": entry.get("title", "")
        }

        logger.info(f"Tentative de réessai pour {video_info['video_id']}")
        
        # Réessayer le téléchargement
        result = telecharger_video_savetube(video_info)
        
        # Mettre à jour le statut dans MongoDB
        update_data = {
            "$set": {
                "status": result["status"],
                "last_retry": time.time()
            },
            "$inc": {"retry_attempts": 1}
        }
        collection.update_one({"_id": entry["_id"]}, update_data)

        if result["status"] == "success":
            logger.info(f"Réussite du réessai pour {video_info['video_id']}")
        else:
            logger.warning(f"Nouvel échec pour {video_info['video_id']}")


if __name__ == "__main__":
    while True:
        retry_failed_downloads()
        logging.info("Attente de 10 minutes avant le prochain scan...")
        time.sleep(6)