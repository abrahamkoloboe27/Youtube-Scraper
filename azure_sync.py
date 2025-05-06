import os
import logging
from datetime import datetime
from minio import Minio
from azure.storage.blob import BlobServiceClient
import argparse
from dotenv import load_dotenv

load_dotenv()

# Configuration du logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("azure_sync.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()

# Configuration MinIO
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
MINIO_BUCKET = os.getenv("MINIO_BUCKET")

# Configuration Azure
AZURE_ACCOUNT_URL = os.getenv("AZURE_ACCOUNT_URL")
AZURE_SAS_TOKEN = os.getenv("AZURE_SAS_TOKEN")
AZURE_CONTAINER = os.getenv("AZURE_CONTAINER")


def sync_to_azure():
    """
    Synchronise tous les fichiers depuis MinIO vers Azure Blob Storage
    """
    try:
        # Clients init
        minio_client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=False
        )
        
        blob_service = BlobServiceClient(
            account_url=AZURE_ACCOUNT_URL,
            credential=AZURE_SAS_TOKEN
        )
        container_client = blob_service.get_container_client(AZURE_CONTAINER)

        # Liste des objets MinIO
        objects = minio_client.list_objects(MINIO_BUCKET)
        
        for obj in objects:
            try:
                # Téléchargement depuis MinIO
                data = minio_client.get_object(MINIO_BUCKET, obj.object_name)
                
                # Upload vers Azure
                blob_client = container_client.get_blob_client(obj.object_name)
                blob_client.upload_blob(
                    data.data,
                    overwrite=True,
                    metadata={
                        "minio_etag": obj.etag,
                        "original_size": str(obj.size),
                        "last_modified": obj.last_modified.isoformat()
                    }
                )
                
                logger.info(f"Fichier {obj.object_name} synchronisé avec succès")
                
            except Exception as e:
                logger.error(f"Erreur sur {obj.object_name}: {str(e)}")
                continue
            
    except Exception as e:
        logger.error(f"Erreur de synchronisation globale: {str(e)}")
        raise


def list_azure_blobs(verbose=True):
    """
    Liste tous les blobs présents dans le conteneur Azure
    """
    try:
        blob_service = BlobServiceClient(
            account_url=AZURE_ACCOUNT_URL,
            credential=AZURE_SAS_TOKEN
        )
        container_client = blob_service.get_container_client(AZURE_CONTAINER)

        blobs = container_client.list_blobs()
        total_count = 0
        total_size = 0
        logger.info("\nListe des objets dans Azure Blob Storage:")
        
        for blob in blobs:
            total_count += 1
            total_size += blob.size
            if verbose:
                logger.info(f"- {blob.name} ({blob.size} bytes)")
                logger.info(f"  Dernière modification: {blob.last_modified}")
                logger.info(f"  Métadonnées: {blob.metadata}")

        total_size_gb = total_size / (1024 ** 3)
        logger.info(f"\nRésumé statistique:")
        logger.info(f"Nombre total d'objets: {total_count}")
        logger.info(f"Taille totale occupée: {total_size_gb:.2f} Go")

    except Exception as e:
        logger.error(f"Erreur lors du listing: {str(e)}")
        raise

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Synchronisation MinIO vers Azure')
    parser.add_argument('--list', action='store_true', help='Lister les blobs Azure au lieu de synchroniser')
    parser.add_argument('--stats', action='store_true', help='Afficher les statistiques de stockage')
    args = parser.parse_args()

    if args.list:
        logger.info("Démarrage du listing Azure")
        list_azure_blobs(verbose=True)
        logger.info("Listing terminé")
    elif args.stats:
        logger.info("Démarrage du calcul des statistiques Azure")
        list_azure_blobs(verbose=False)
        logger.info("Calcul des statistiques terminé")
    else:
        logger.info("Démarrage de la synchronisation Azure")
        sync_to_azure()
        logger.info("Synchronisation terminée")