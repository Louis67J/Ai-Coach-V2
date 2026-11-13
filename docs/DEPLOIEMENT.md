# Plan de déploiement

Objectif : l'app web tourne en permanence sur un serveur, en HTTPS, ouverte à
d'autres athlètes qui apportent leurs propres clés (voir README, « Ouvrir
l'app à d'autres athlètes »). Le bot Discord tourne sur le même serveur pour
toi seul, ce qui règle au passage le brief qui ne part que si ton PC est
allumé.

Les prix et besoins de ressources ci-dessous sont des estimations à vérifier
au moment de commander.

## 0. Avant tout : le dépôt est public

Le dépôt GitHub est **public**, et `data/profile.json` / `data/sessions.json`
(date de naissance, poids, FC, toutes tes séances) sont dans son historique.
Les retirer de la branche principale ne les retire pas de l'historique.

1. Passer le dépôt en privé : GitHub → Settings → General → Danger Zone →
   Change visibility. Immédiat et réversible.
2. Si le dépôt doit redevenir public un jour : réécrire l'historique pour en
   effacer ces deux fichiers (`git filter-repo --path data/profile.json
   --path data/sessions.json --invert-paths`, puis push forcé). Irréversible,
   à faire seulement quand plus aucune branche en cours n'en dépend.

## 1. Ranger tes données (sur ton PC)

1. Récupérer la branche, restaurer tes deux fichiers si le pull les a
   retirés (commande dans le README, « Tes données »).
2. Générer une `APP_SECRET_KEY` et l'ajouter à `.env`.
3. `python -m ai_coach.main claim-data louis`, puis `OWNER_ATHLETE=louis`
   dans `.env`.
4. Vérifier que tout marche comme avant : `python -m ai_coach.main check`,
   `start-web.bat`, `start-bot.bat`.

## 2. Choisir l'hébergement

Besoins : Python 3.12, un disque persistant pour `data/`, et environ 2 Go de
RAM (le modèle d'embedding de la mémoire du coach charge PyTorch).

| Option | Coût estimé | Pour | Contre |
|---|---|---|---|
| **VPS (Hetzner CX22, 4 Go)** — recommandé | ~5 €/mois | Disque persistant, RAM suffisante, prix fixe, serveurs en UE (RGPD) | Tu gères les mises à jour système |
| Railway / Render / Fly.io | 10–25 €/mois avec 2 Go de RAM | Déploiement depuis GitHub, peu d'admin | Volume persistant à configurer, prix qui monte avec la RAM |
| Streamlit Community Cloud | Gratuit | Zéro admin | Pas de disque persistant ni de bot : inadapté |

Recommandation : un VPS Hetzner en Allemagne ou en Finlande, avec Docker.

## 3. Conteneuriser (fait, dans le dépôt)

- `Dockerfile` : Python 3.12 slim, PyTorch en version CPU (pas de CUDA
  inutile), modèle d'embedding téléchargé au build. L'app tourne avec un
  utilisateur non-root.
- `docker-compose.yml`, trois services qui partagent `data/` et `outputs/`
  (dossiers du serveur, à côté du fichier, jamais dans l'image) :
  - `web` : le dashboard Streamlit, joignable seulement via Caddy ;
  - `bot` : le bot Discord, dans le profil `bot` (démarré seulement si on le
    demande, pour ne pas avoir deux bots tant que celui du PC tourne) ;
  - `caddy` : HTTPS automatique pour `DOMAIN`, configuré dans
    `deploy/Caddyfile`.
- `.env` sur le serveur uniquement : `MULTI_USER=1`, `APP_SECRET_KEY`,
  `OWNER_ATHLETE=louis`, `DOMAIN`, `TZ=Europe/Paris`, tes clés et celles de
  Discord.
- Le brief suit `TZ` : `BRIEF_HOUR=7` part à 7 h heure de Paris, heure d'été
  comprise, même si le serveur est en UTC.

Essai en local (Docker Desktop), sans HTTPS ni domaine :

```sh
docker compose build
docker compose run --rm -p 8501:8501 web   # puis http://localhost:8501
```

## 4. Mettre en ligne

1. Acheter un nom de domaine (~10 €/an) et le pointer vers l'IP du VPS
   (enregistrement A). Caddy en a besoin pour obtenir le certificat.
2. Sur le VPS : créer un utilisateur non-root, n'autoriser que la connexion
   SSH par clé, activer le pare-feu (ports 22, 80, 443) et les mises à jour
   de sécurité automatiques.
3. Installer Docker, cloner le dépôt (privé : clé de déploiement GitHub),
   déposer `.env` (copie de `.env.example`, remplie).
4. Copier ton dossier `data/` depuis ton PC (`scp -r data/ serveur:…`), puis
   le donner à l'utilisateur du conteneur : `sudo chown -R 1000:1000 data
   outputs`.
5. `docker compose up -d --build`, puis vérifier : `https://DOMAIN`,
   connexion avec le compte `louis`, tes données visibles.
6. Arrêter le bot sur ton PC, puis `docker compose --profile bot up -d` et
   `!brief` sur Discord.

## 5. Tenir dans la durée

- **Sauvegardes** : `deploy/backup.sh` archive `data/` dans `backups/` et
  garde 7 jours ; à lancer chaque nuit par cron (ligne prête dans le
  script), puis à copier vers un stockage externe (Hetzner Storage Box ou
  autre). Garder
  `APP_SECRET_KEY` à part : sans elle, les clés des utilisateurs sont
  illisibles.
- **Mises à jour** : `git pull && docker compose --profile bot up -d --build`. Plus tard,
  une GitHub Action peut le faire à chaque merge sur `main`.
- **Surveillance** : un check de disponibilité gratuit (UptimeRobot) sur
  l'URL, et `docker compose logs` en cas de souci.

## 6. Avant d'inviter d'autres athlètes

- **Session qui survit au rechargement de la page** : aujourd'hui, recharger
  l'onglet déconnecte. À corriger avec un cookie de session signé.
- **Limiter les tentatives de connexion** (anti force brute).
- **RGPD** : poids, FC et séances sont des données de santé. Il faut une
  politique de confidentialité, le consentement explicite à l'inscription,
  et un bouton pour supprimer son compte et ses données.
- **Conditions d'Intervals.icu** : vérifier qu'une app tierce peut utiliser
  les clés API de ses utilisateurs. Intervals.icu propose aussi un accès
  OAuth, plus propre pour une app publique.
- **Paiement (2 €/mois)** : Stripe Checkout ou Lemon Squeezy (qui gère la
  TVA européenne à ta place), avec un statut d'abonnement vérifié à la
  connexion. À brancher une fois les premiers testeurs contents.

## Ordre proposé

1. Dépôt en privé (toi, 1 minute).
2. Ranger tes données (toi, sur ton PC, étape 1).
3. ~~Dockerfile et compose (dans le dépôt).~~ Fait.
4. Mise en ligne sur le VPS, pour toi seul.
5. Session persistante, limite de connexion, RGPD.
6. Premiers testeurs gratuits, puis paiement.
