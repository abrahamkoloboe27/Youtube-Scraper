import os
import csv
import random
import isodate
import logging
import time
import re
import subprocess
import concurrent.futures
from datetime import timedelta
from googleapiclient.discovery import build
import requests
from tqdm import tqdm
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
from mongo_utils import insert_log, insert_video_metadata, video_exists_in_metadata
from minio_utils import upload_audio, minio_est_disponible, client as minio_client, MINIO_BUCKET

load_dotenv()

API_KEY = os.getenv("GOOGLE_API")
AUDIO_DIR = "audios/"
MAX_DOWNLOAD_RETRIES = 5
MAX_WORKERS = 10
DELAY_BETWEEN_DOWNLOADS = (3, 10)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.81 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:94.0) Gecko/20100101 Firefox/94.0"
]

# Chargement dynamique des playlists depuis un fichier texte

def extraire_playlist_id(url_ou_id):
    """
    Extrait l'identifiant de playlist à partir d'une URL complète ou retourne l'ID si déjà fourni.
    """
    # Si la ligne ressemble déjà à un ID (pas d'URL), retourne tel quel
    if url_ou_id.startswith("PL") and "http" not in url_ou_id:
        return url_ou_id.strip()
    # Recherche dans l'URL
    import urllib.parse
    parsed = urllib.parse.urlparse(url_ou_id)
    query = urllib.parse.parse_qs(parsed.query)
    # playlist?list= ou &list= dans l'URL
    if "list" in query:
        return query["list"][0]
    # Cas où l'ID est à la fin de l'URL sans paramètre
    if "playlist/" in url_ou_id:
        return url_ou_id.split("playlist/")[-1].split("?")[0].split("&")[0]
    # Fallback: retourne la ligne brute
    return url_ou_id.strip()

with open(os.path.join(os.path.dirname(__file__), "playlist.txt"), "r") as f:
    PLAYLISTS = [extraire_playlist_id(line.strip()) for line in f if line.strip() and not line.startswith("#") and ("list=" in line or (line.startswith("PL") and "http" not in line))]
if not os.path.exists(AUDIO_DIR):
    os.makedirs(AUDIO_DIR)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("youtube_download.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()

def nettoyer_nom_fichier(titre):
    titre = re.sub(r'[\\/*?:"<>|]', "", titre)
    return titre.strip()[:150]

def telecharger_fichier(url, nom_fichier):
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            total = int(r.headers.get('content-length', 0))
            with open(nom_fichier, 'wb') as f, tqdm(
                desc=os.path.basename(nom_fichier),
                total=total,
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
                leave=False
            ) as bar:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        bar.update(len(chunk))
            return True
    except Exception as e:
        logger.error(f"Téléchargement échoué pour {nom_fichier}: {str(e)}")
        return False

def audio_exists_in_minio(object_name):
    try:
        return minio_client.stat_object(MINIO_BUCKET, object_name) is not None
    except Exception:
        return False

def telecharger_avec_ytdlp(video_info):
    """Méthode de secours utilisant yt-dlp pour contourner les limitations de SaveTube"""
    video_id = video_info['video_id']
    try:
        subprocess.run([
            'yt-dlp',
            '-x',
            '--audio-format', 'mp3',
            '-o', f'{AUDIO_DIR}/%(id)s.%(ext)s',
            video_info['url']
        ], check=True)
        mp3_path = os.path.join(AUDIO_DIR, f"{video_id}.mp3")
        
        if os.path.exists(mp3_path):
            if upload_audio(mp3_path):
                if verify_and_cleanup(mp3_path, f"{video_id}.mp3"):
                    logger.info(f"Fichier {mp3_path} supprimé après vérification MinIO")
                else:
                    logger.error("Échec de la vérification MinIO, fichier conservé")
            # Insertion métadonnées vidéo
            insert_video_metadata({
                'video_id': video_id,
                'url': video_info['url'],
                'title': video_info.get('title', ''),
                'audio_path': mp3_path,
                'status': 'success',
                'timestamp': time.time()
            })
            return {**video_info, 'status': 'success', 'audio_path': mp3_path}
    except Exception as e:
        logger.error(f"Échec du téléchargement alternatif pour {video_id}: {str(e)}")
    return {**video_info, 'status': 'failed'}


def telecharger_video_savetube(video_info):
    video_id = video_info['video_id']
    url_video = video_info['url']
    mp3_path = os.path.join(AUDIO_DIR, f"{video_id}.mp3")
    object_name = f"{video_id}.mp3"
    # Vérification MongoDB
    if video_exists_in_metadata(video_id):
        # Vérification MinIO
        if audio_exists_in_minio(object_name):
            logger.info(f"Vidéo déjà présente dans MongoDB et MinIO: {video_id}, on saute.")
            video_info['audio_path'] = mp3_path
            video_info['status'] = 'success'
            return video_info
        else:
            logger.info(f"Vidéo déjà dans MongoDB mais pas dans MinIO: {video_id}, upload MinIO.")
            if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
                upload_audio(mp3_path)
                return video_info
            else:
                logger.warning(f"Fichier local manquant pour {video_id}, impossible d'uploader dans MinIO.")
                video_info['status'] = 'missing_local_audio'
                return video_info
    # Sinon, on continue le téléchargement normal
    if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
        logger.info(f"Existant: {video_id}")
        video_info['audio_path'] = mp3_path
        video_info['status'] = 'success'
        # Upload Minio
        upload_audio(mp3_path)
        # Insertion métadonnées vidéo
        insert_video_metadata({
            'video_id': video_id,
            'url': url_video,
            'title': video_info.get('title', ''),
            'duration': video_info.get('duration', None),
            'audio_path': mp3_path,
            'minio_path': mp3_path,  # À adapter si le chemin MinIO diffère
            'status': 'success',
            'timestamp': time.time()
        })
        return video_info
    logger.info(f"Début téléchargement: {video_id}")
    for tentative in range(MAX_DOWNLOAD_RETRIES):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    viewport={'width': 1280, 'height': 720}
                )
                page = context.new_page()
                def block_ads(route, request):
                    ads_domains = ["doubleclick.net", "googlesyndication.com", "adservice.google.com"]
                    if any(d in request.url for d in ads_domains):
                        route.abort()
                    else:
                        route.continue_()
                page.route("**/*", block_ads)
                # Vérification disponibilité SaveTube avant d'aller plus loin
                try:
                    response = page.goto("https://yt.savetube.me/1kejjj1", timeout=15000)
                    if not response or response.status != 200:
                        logger.error(f"SaveTube indisponible ou erreur HTTP: {getattr(response, 'status', 'no response')}")
                        raise Exception("SaveTube non disponible")
                except Exception as e:
                    logger.error(f"Impossible d'accéder à SaveTube: {e}")
                    raise
                try:
                    page.wait_for_selector("div.fc-consent-root", timeout=5000)
                    page.click("button.fc-cta-consent")
                    logger.info("Consent dialog dismissed")
                except Exception:
                    logger.debug("No consent dialog found")
                try:
                    page.wait_for_selector("input.search-input", timeout=10000)
                    page.fill("input.search-input", url_video)
                    page.click("button:text('Get Video')")
                    # Nouvelle logique pour détecter la section de téléchargement
                    try:
                        selectors = [
                            "#resultSection",
                            "#downloadSection",
                            ".download-area",
                            ".result-area",
                            "#result-section",
                            "#download-section",
                            ".result-section",
                            ".download-section"
                        ]
                        found = False
                        for sel in selectors:
                            try:
                                page.wait_for_selector(sel, timeout=7000)
                                found = True
                                logger.info(f"Section de téléchargement détectée avec le sélecteur: {sel}")
                                break
                            except Exception:
                                continue
                        if not found:
                            html = page.content()
                            # Recherche de message d'erreur ou page d'accueil générique
                            if 'No video found' in html or 'not found' in html.lower() or 'youtube shorts video download' in html.lower() or '<title>Download YouTube Shorts Video - YouTube Shorts Downloader</title>' in html:
                                logger.error(f"Redirection vers la page d'accueil de SaveTube détectée pour {video_id}")
                                logger.error(f"Extrait HTML: {html[:2000]}")
                                logger.warning("Tentative de téléchargement alternatif avec yt-dlp...")
                                return telecharger_avec_ytdlp(video_info)
                            logger.error(f"Timeout ou erreur lors de l'attente de la section de téléchargement pour {video_id}. Extrait HTML: {html[:3000]}")
                            raise Exception("Section de téléchargement non trouvée")
                    except Exception as e:
                        html = page.content()
                        logger.error(f"Timeout ou erreur lors de l'attente de la section de téléchargement pour {video_id}: {e}\nContenu page: {html[:3000]}")
                        raise
                except Exception as e:
                    # Logguer le HTML de la page pour analyse
                    html = page.content()
                    logger.error(f"Timeout ou erreur lors de l'attente du downloadSection pour {video_id}: {e}\nContenu page: {html[:2000]}")
                    raise
                titre_raw = page.query_selector("h3.text-left").inner_text()
                titre_video = nettoyer_nom_fichier(titre_raw)
                page.select_option("select#quality", label="MP3 320kbps")
                page.click("button:has-text('Get Link')")
                page.wait_for_url("**/start-download**", timeout=30000)
                page.wait_for_selector("a.text-white:has-text('Download')", timeout=20000)
                btn = page.query_selector("a.text-white:has-text('Download')")
                download_link = btn.get_attribute("href")
                browser.close()
                if telecharger_fichier(download_link, mp3_path):
                    logger.info(f"Succès: {video_id}")
                    video_info['audio_path'] = mp3_path
                    video_info['status'] = 'success'
                    # Upload Minio
                    upload_audio(mp3_path)
                    # Insertion métadonnées vidéo
                    insert_video_metadata({
                        'video_id': video_id,
                        'url': url_video,
                        'title': titre_video,
                        'duration': video_info.get('duration', None),
                        'audio_path': mp3_path,
                        'minio_path': mp3_path,  # À adapter si le chemin MinIO diffère
                        'status': 'success',
                        'timestamp': time.time()
                    })
                    return video_info
        except Exception as e:
            details = f"Erreur pour {video_id} (tentative {tentative+1}/{MAX_DOWNLOAD_RETRIES}): {str(e)}"
            logger.error(details)
            if tentative < MAX_DOWNLOAD_RETRIES - 1:
                time.sleep(random.uniform(2, 5))
    video_info['audio_path'] = None
    video_info['status'] = 'failed'
    insert_log({
        'video_id': video_id,
        'url': url_video,
        'title': video_info.get('title', ''),
        'audio_path': None,
        'status': 'failed',
        'timestamp': time.time()
    })
    return video_info

def get_video_details(youtube, video_id):
    try:
        response = youtube.videos().list(
            part='snippet,contentDetails',
            id=video_id
        ).execute()
        if not response['items']:
            return None
        item = response['items'][0]
        title = item['snippet']['title']
        duration_iso = item['contentDetails']['duration']
        duration_minutes = isodate.parse_duration(duration_iso).total_seconds() / 60
        captions = "yes" if item['contentDetails'].get('caption') == "true" else "no"
        return title, duration_minutes, captions
    except Exception as e:
        logger.error(f"Erreur récupération détails vidéo: {e}")
        return None

def get_videos_from_playlist(youtube, playlist_id):
    videos = []
    nextPageToken = None
    while True:
        pl_request = youtube.playlistItems().list(
            part="snippet",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=nextPageToken
        )
        pl_response = pl_request.execute()
        for item in pl_response['items']:
            video_id = item['snippet']['resourceId']['videoId']
            details = get_video_details(youtube, video_id)
            if details:
                title, duration, captions = details
                videos.append({
                    'video_id': video_id,
                    'url': f"https://www.youtube.com/watch?v={video_id}",
                    'title': title,
                    'duration': duration,
                    'captions': captions
                })
        nextPageToken = pl_response.get('nextPageToken')
        if not nextPageToken:
            break
    return videos

def afficher_stats(videos):
    total = len(videos)
    success = sum(1 for v in videos if v.get('status') == 'success')
    failed = sum(1 for v in videos if v.get('status') == 'failed')
    print(f"Succès: {success}/{total} | Échecs: {failed}")

def main():
    print("🚀 DÉBUT DU TÉLÉCHARGEMENT MASSIF YOUTUBE")
    start_time = time.time()
    youtube = build('youtube', 'v3', developerKey=API_KEY)
    youtube_2 = build('youtube', 'v3', developerKey=os.getenv("GOOGLE_API_2"))
    
    all_videos = []
    for playlist_id in PLAYLISTS:
        logger.info(f"Traitement playlist: {playlist_id}")
        try: 
            vids = get_videos_from_playlist(youtube, playlist_id)
        except Exception as e:
            logger.error(f"Erreur récupération vidéos de la playlist {playlist_id}: {e}")
            vids = get_videos_from_playlist(youtube_2, playlist_id)
        if not vids:
            logger.error(f"Aucune vidéo trouvée pour la playlist {playlist_id}")
            continue
        all_videos.extend(vids)
    videos_unique = list({video['video_id']: video for video in all_videos}.values())
    print(f"Nombre total de vidéos à télécharger: {len(videos_unique)}")
    total_estimated_duration = sum(video['duration'] for video in videos_unique)
    hours = int(total_estimated_duration // 60)
    minutes = int(total_estimated_duration % 60)
    print(f"Durée totale estimée du dataset: {hours}h {minutes}m ({total_estimated_duration:.1f} minutes)")
    for video in videos_unique:
        video['status'] = 'pending'
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_video = {executor.submit(telecharger_video_savetube, video): video for video in videos_unique}
        completed = 0
        for future in concurrent.futures.as_completed(future_to_video):
            video = future_to_video[future]
            try:
                result = future.result()
                if result['status'] == 'success':
                    video_index = videos_unique.index(video)
                    videos_unique[video_index] = result
                completed += 1
                if completed % 5 == 0 or completed == len(videos_unique):
                    afficher_stats(videos_unique)
            except Exception as e:
                logger.error(f"Exception dans le worker pour {video['video_id']}: {str(e)}")
                video['status'] = 'failed'
    end_time = time.time()
    elapsed_time = end_time - start_time
    elapsed_str = str(timedelta(seconds=int(elapsed_time)))
    successful_downloads = sum(1 for v in videos_unique if v.get('status') == 'success')
    failed_downloads = sum(1 for v in videos_unique if v.get('status') == 'failed')
    print("\n" + "="*60)
    print("RÉSUMÉ FINAL")
    print(f"Téléchargements réussis: {successful_downloads}/{len(videos_unique)} ({successful_downloads/len(videos_unique)*100:.1f}%)")
    print(f"Téléchargements échoués: {failed_downloads}")
    total_duration = sum(v.get('duration', 0) for v in videos_unique if v.get('status') == 'success')
    hours = int(total_duration // 60)
    minutes = int(total_duration % 60)
    print(f"Durée totale du dataset: {hours}h {minutes}m ({total_duration:.1f} minutes)")
    if successful_downloads > 0:
        avg_time_per_video = elapsed_time / successful_downloads
        print(f"Vitesse moyenne: {avg_time_per_video:.2f} secondes par vidéo")
    print(f"Temps total d'exécution: {elapsed_str}")
    print("="*60)
    print("\n🏁 TÉLÉCHARGEMENT TERMINÉ\n")

if __name__ == "__main__":
    main()
