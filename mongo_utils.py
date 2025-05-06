import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB = os.getenv("MONGO_DB", "yt_scrap")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "logs")

client = MongoClient(MONGO_URI)
db = client[MONGO_DB]
collection = db[MONGO_COLLECTION]

def insert_log(log_data):
    """Insère un log dans la collection MongoDB."""
    try:
        result = collection.insert_one(log_data)
        return result.inserted_id
    except Exception as e:
        print(f"Erreur insertion MongoDB: {e}")
        return None

# Nouvelle fonction pour insérer les métadonnées des vidéos dans une collection dédiée
video_meta_collection = db[os.getenv("MONGO_VIDEO_COLLECTION", "videos")]

def insert_video_metadata(video_data):
    """Insère les métadonnées d'une vidéo téléchargée dans la collection MongoDB dédiée."""
    try:
        result = video_meta_collection.insert_one(video_data)
        return result.inserted_id
    except Exception as e:
        print(f"Erreur insertion métadonnées vidéo MongoDB: {e}")
        return None

def video_exists_in_metadata(video_id):
    """Vérifie si une vidéo existe déjà dans la collection des métadonnées."""
    try:
        return video_meta_collection.find_one({"video_id": video_id}) is not None
    except Exception as e:
        print(f"Erreur lors de la vérification de l'existence de la vidéo dans MongoDB: {e}")
        return False