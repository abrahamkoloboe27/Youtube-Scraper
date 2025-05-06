"""
Utilitaires MinIO pour le projet Youtube-Fon-Scrapping.

Ce module fournit des fonctions pour :
- Vérifier la disponibilité du service MinIO
- Uploader des fichiers audio dans le bucket MinIO
- Vérifier la présence d'un fichier dans MinIO et supprimer le fichier local si besoin

Variables d'environnement utilisées :
- MINIO_ENDPOINT : Adresse du service MinIO
- MINIO_ACCESS_KEY : Clé d'accès MinIO
- MINIO_SECRET_KEY : Clé secrète MinIO
- MINIO_BUCKET : Nom du bucket MinIO
"""
import os
from minio import Minio
from minio.error import S3Error
from dotenv import load_dotenv
import socket

load_dotenv()

MINIO_ENDPOINT ="minio:9000"
MINIO_ACCESS_KEY ="minioadmin"
MINIO_SECRET_KEY ="minioadmin"
MINIO_BUCKET ="audios"

client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)

def minio_est_disponible(timeout=3):
    """
    Vérifie si le service MinIO est disponible.
    Args:
        timeout (int): Durée maximale d'attente en secondes pour la connexion.
    Returns:
        bool: True si MinIO est accessible, False sinon.
    """
    try:
        host, port = MINIO_ENDPOINT.split(":")
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception as e:
        print(f"MinIO non disponible: {e}")
        return False


def upload_audio(file_path, object_name=None):
    """
    Upload un fichier audio dans le bucket MinIO.
    Args:
        file_path (str): Chemin local du fichier à uploader.
        object_name (str, optionnel): Nom de l'objet dans MinIO. Si None, utilise le nom du fichier.
    Returns:
        str ou bool: Nom de l'objet uploadé ou False en cas d'échec.
    """
    if not minio_est_disponible():
        print("Erreur: Impossible de se connecter à MinIO. Vérifiez que le service est démarré et accessible.")
        #return False
    if object_name is None:
        object_name = os.path.basename(file_path)
    try:
        # Créer le bucket s'il n'existe pas
        if not client.bucket_exists(MINIO_BUCKET):
            client.make_bucket(MINIO_BUCKET)
        client.fput_object(MINIO_BUCKET, object_name, file_path)
        return object_name
    except S3Error as conn_err:
        print(f"Erreur de connexion à MinIO: {conn_err}")
        return False
    except Exception as e:
        print(f"Erreur upload Minio (autre): {e}")
        return False

def verify_and_cleanup(file_path, object_name):
    """
    Vérifie la présence du fichier dans MinIO et supprime le fichier local si l'upload a réussi.
    Args:
        file_path (str): Chemin local du fichier à supprimer.
        object_name (str): Nom de l'objet dans MinIO à vérifier.
    Returns:
        bool: True si le fichier a été trouvé dans MinIO et supprimé localement, False sinon.
    """
    try:
        client.stat_object(MINIO_BUCKET, object_name)
        os.remove(file_path)
        return True
    except S3Error as e:
        print(f"Erreur vérification MinIO: {e}")
        return False
    except Exception as e:
        print(f"Erreur suppression fichier {file_path}: {e}")
        return False