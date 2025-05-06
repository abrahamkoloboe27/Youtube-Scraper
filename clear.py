import os 

audio_folder = "./audios"

for file in os.listdir(audio_folder):
    print(f"Removing {file}")
    file_path = os.path.join(audio_folder, file)
    
    # Vérification des permissions
    if not os.access(file_path, os.W_OK):
        print(f"Permission manquante pour {file} - Fichier ignoré")
        continue
        
    try:
        os.remove(file_path)
        print(f"File : {file} removed sucessfully")
    except PermissionError as pe:
        print(f"Erreur permission pour {file}: {pe}. Verrouillé par un autre processus?")
    except FileNotFoundError:
        print(f"Fichier {file} déjà supprimé")
    except Exception as e:
        print(f"Erreur suppression {file}: {type(e).__name__} - {str(e)}")