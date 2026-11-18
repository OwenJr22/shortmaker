# Mettre ShortMaker en ligne (Hugging Face Spaces, gratuit)

## 1. Créer le Space
1. Crée un compte sur [huggingface.co](https://huggingface.co).
2. En haut à droite : **New → Space**.
3. Remplis :
   - **Space name** : `shortmaker`
   - **SDK** : **Docker** → modèle **Blank**
   - **Hardware** : *CPU basic · Free*
   - **Visibility** : **Public**. Le site reste protégé par ton mot de passe, et tes clés ne sont jamais visibles. Seul le code l'est.
4. Clique sur **Create Space**.

## 2. Ajouter tes secrets
Dans le Space : **Settings → Variables and secrets → New secret** :

| Nom | Valeur |
|---|---|
| `APP_PASSWORD` | le mot de passe pour entrer sur ton site (obligatoire) |
| `ANTHROPIC_API_KEY` | ta clé API Claude (facultatif, pour les suggestions IA) |

## 3. Envoyer les fichiers
Onglet **Files → Add file → Upload files**, puis glisse **tout le contenu** du dossier `shortmaker` (pas le dossier lui-même) et clique sur **Commit changes to main**.

Le Space se construit tout seul (« Building », 5 à 10 minutes), puis passe en **Running**.

## 4. Utiliser ton site
- L'adresse directe est **https://TON-PSEUDO-shortmaker.hf.space**. Mets-la en favori : c'est plus fiable que la page huggingface.co.
- Entre ton mot de passe, et c'est parti.

## À savoir (version gratuite)
- **Ça se met en veille** après environ 48 h sans visite. Le réveil prend une minute.
- **Les fichiers ne sont pas conservés** quand le Space redémarre ou se met en veille. Télécharge tes shorts dès qu'ils sont prêts.
- **C'est plus lent qu'un bon PC.** La transcription utilise le modèle « base ». Compte en gros la durée de la vidéo pour la transcrire.
- **YouTube bloque souvent** les téléchargements depuis ces serveurs (« Sign in to confirm you're not a bot »). Dans ce cas :
  - le plus simple : télécharge la vidéo sur ton ordi, puis importe le fichier avec 📁 ;
  - ou ⚙️ Réglages → *Envoyer cookies.txt*, exporté depuis youtube.com avec l'extension « Get cookies.txt LOCALLY ». Utilise de préférence un compte Google secondaire : ces cookies donnent accès à ce compte.

## Aller plus loin (payant)
- **Plus rapide** : Settings → Hardware → *CPU upgrade* (≈ 0,03 $/h).
- **Garder les fichiers** : Settings → *Persistent storage*, puis ajoute la variable `DATA_DIR` = `/data`.
- **Autre hébergeur** (Railway, Render, un VPS…) : le même `Dockerfile` fonctionne. Définis les variables `APP_PASSWORD` et `ANTHROPIC_API_KEY`, et le port 7860.
