---
title: ShortMaker
emoji: 🎬
colorFrom: yellow
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# 🎬 ShortMaker

Transforme une vidéo longue (lien YouTube ou fichier) en shorts verticaux 9:16 avec sous-titres animés, en ligne ou sur ton ordinateur.

> **App Mac prête à l'emploi :** rubrique **Releases** de ce dépôt → `ShortMaker-Mac.zip`, puis suis `LISEZMOI-MAC.txt`.
> **Version en ligne :** voir `EN-LIGNE.md`.

**Comment ça marche :** tu colles un lien → l'app télécharge la vidéo → Whisper la transcrit mot par mot → l'IA (Claude) te propose les moments forts → tu ajustes → l'app génère les shorts en MP4.

---

## 1. Installation (une seule fois)

### a) Python 3.10 ou plus récent
- **Windows** : télécharge-le sur [python.org](https://www.python.org/downloads/) et **coche « Add Python to PATH »** pendant l'installation.
- **Mac** : `brew install python` (ou l'installeur de python.org).

### b) FFmpeg (le moteur vidéo)
- **Windows** : ouvre un terminal et tape `winget install Gyan.FFmpeg`, puis redémarre le terminal.
- **Mac** : `brew install ffmpeg`
- **Linux** : `sudo apt install ffmpeg`

Pour vérifier : `ffmpeg -version` doit afficher quelque chose.

### c) Clé API Claude (pour les suggestions IA)
Crée une clé sur [console.anthropic.com](https://console.anthropic.com), puis colle-la dans **⚙️ Réglages** dans l'app. Une analyse coûte généralement quelques centimes. Sans clé, tout le reste fonctionne : tu choisis simplement les moments toi-même.

## 2. Lancer l'app

- **Windows** : double-clic sur `lancer-windows.bat`
- **Mac / Linux** : dans un terminal, dans le dossier : `chmod +x lancer-mac-linux.sh` (une fois), puis `./lancer-mac-linux.sh`

Le premier lancement installe les dépendances (quelques minutes). Ensuite le navigateur s'ouvre sur **http://127.0.0.1:5050**.

> La toute première transcription télécharge aussi le modèle Whisper (≈ 500 Mo pour « small »).

## 3. Utilisation

1. **Importer** : colle un lien YouTube, ou clique sur 📁 Fichier.
2. **Attendre la transcription** : compte en gros 0,3 à 1 fois la durée de la vidéo sur un PC sans carte graphique avec le modèle « small ». Choisis « base » dans les Réglages pour aller plus vite.
3. **Choisir les moments** :
   - ✨ *Trouver les moments forts* : l'IA propose des passages, avec une note et une accroche ;
   - ou **sélectionne du texte** dans la transcription → ✂️ *Créer un clip* ;
   - ou *+ Ajouter*, puis ajuste le début et la fin avec ⏱ (ça prend la position actuelle de la vidéo).
   - ▶ *Écouter* joue uniquement le passage.
4. **Style** : karaoké, Hormozi, néon ou sobre, couleur d'accent, position, recadrage (suivi du visage, centre fixe ou fond flou), majuscules, accroche, barre de progression.
5. **Générer** : coche les clips voulus (ou aucun pour tout générer) → les MP4 apparaissent dans *Shorts générés* → ⬇ Télécharger.

Les fichiers sont aussi dans `data/<projet>/clips/`.

## Problèmes fréquents

| Problème | Solution |
|---|---|
| « Téléchargement impossible » | YouTube change souvent : `pip install -U yt-dlp` (dans le venv), ou importe le fichier directement. |
| « ffmpeg est introuvable » | Installe FFmpeg (étape 1b) puis relance. |
| Transcription très lente | Réglages → modèle « base » ou « tiny ». Avec une carte NVIDIA + CUDA, Whisper l'utilise automatiquement. |
| Le recadrage ne suit pas bien | Choisis « Vidéo entière + fond flou » ou « Centre fixe ». Le suivi marche mieux avec un visage de face. |
| Erreur API Claude 404 sur le modèle | Lance l'app avec la variable `CLAUDE_MODEL` réglée sur un modèle disponible pour ton compte. |

## Structure

```
app.py                 serveur local + API
static/index.html      interface
pipeline/
  download.py          téléchargement (yt-dlp)
  transcribe.py        transcription mot par mot (faster-whisper)
  suggest.py           suggestions de moments forts (API Claude)
  reframe.py           suivi du visage → recadrage 9:16
  subtitles.py         sous-titres animés (format ASS)
  render.py            assemblage final avec FFmpeg
fonts/                 police des sous-titres
data/                  tes projets (vidéos, transcriptions, shorts)
```

⚠️ N'utilise que des vidéos dont tu as les droits (les tiennes, ou avec l'accord du créateur). Télécharger des vidéos YouTube est contraire à leurs conditions d'utilisation, sauf autorisation.
