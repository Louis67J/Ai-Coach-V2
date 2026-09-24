# AI Coach v2

Coach IA personnel pour le cyclisme, connecté à Intervals.icu.
Trois façons de s'en servir au-dessus d'un même moteur : un **dashboard web**,
un **bot Discord** (le seul canal qui pousse sans qu'on le sollicite), et une **CLI**.

## Setup (une fois par machine)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
pip install -r requirements.txt
copy .env.example .env
# Puis édite .env avec tes vraies clés
```

Les secrets restent locaux : `.env` n'est jamais commité.

## Au quotidien

Le plus rapide : double-cliquer sur **`start-web.bat`** (dashboard) ou
**`start-bot.bat`** (bot Discord). Ils activent le venv et lancent tout seuls.

En ligne de commande, active d'abord le venv dans chaque nouveau terminal :

```powershell
.\.venv\Scripts\Activate.ps1
```

### Dashboard web

```powershell
streamlit run src/ai_coach/web/app.py
```

Ouvre http://localhost:8501. Pages : Dashboard (forme, projection, méthode
d'entraînement), Plan, Coach, Données, Profil, Bien-être, Séances.

Pour y accéder depuis ton téléphone sur le même réseau :

```powershell
streamlit run src/ai_coach/web/app.py --server.address 0.0.0.0
```

### Ouvrir l'app à d'autres athlètes

Dans `.env`, mets `MULTI_USER=1` et une `APP_SECRET_KEY` (commande de
génération dans `.env.example`). L'app web demande alors un compte, puis
guide chaque nouvel utilisateur : ses clés API Claude et Intervals.icu
(chiffrées sur le serveur, sa consommation Claude est facturée sur son propre
compte Anthropic), un profil minimal, puis l'import de ses séances depuis la
page **Données**.

Chaque athlète a ses données dans `data/athletes/<identifiant>/` et ses
graphes dans `outputs/athletes/<identifiant>/`. Les comptes (mots de passe
hachés) sont dans `data/accounts.json`. Le bot Discord et la CLI restent
mono-utilisateur.

### Tes données

Rien de personnel n'est versionné : `data/` (profil, séances, mémoire du
coach, comptes, clés chiffrées) reste sur la machine qui fait tourner l'app.

Pour ranger tes données dans ton propre compte (conseillé avant d'ouvrir
l'app à d'autres) :

```powershell
python -m ai_coach.main claim-data louis
```

La commande crée le compte `louis` (elle demande un mot de passe), déplace
`data/*` dans `data/athletes/louis/` et y chiffre tes clés de `.env` si
`APP_SECRET_KEY` est définie. Ajoute ensuite `OWNER_ATHLETE=louis` dans
`.env` : le bot, la CLI et l'app retrouvent tes données, et tu te connectes
à l'app multi-utilisateur avec ce compte.

`profile.json` et `sessions.json` étaient versionnés avant ; un `git pull`
qui passe ce changement les retire de ton dossier. Pour les récupérer :

```powershell
git restore --source 62d7c3d --worktree -- data/profile.json data/sessions.json
```

### Bot Discord

```powershell
python -m ai_coach.main bot
```

Nécessaire pour recevoir le **brief quotidien** (heure réglée par `BRIEF_HOUR`
dans `.env`) : il ne part que si le bot tourne et que la machine est allumée.
`!brief` en force un, `!help_coach` liste les commandes.

### CLI

```powershell
python -m ai_coach.main check                  # vérifie la config
python -m ai_coach.main refresh --days 90      # fetch Intervals.icu
python -m ai_coach.main enrich --max 50        # enrichit/classifie les séances
python -m ai_coach.main summary                # résumé du cache
python -m ai_coach.main analyze                # analyse + graphes + report.json
python -m ai_coach.main metrics                # métriques avancées
python -m ai_coach.main ask "Comment va ma forme ?"
python -m ai_coach.main plan --days 7
python -m ai_coach.main session last           # graphe d'une séance
python -m ai_coach.main power_curve
```

### Tests

```powershell
python -m pytest
```

## Réglages utiles (`.env`)

| Variable | Rôle |
|---|---|
| `ANTHROPIC_API_KEY` | Accès au coach |
| `INTERVALS_API_KEY`, `INTERVALS_ATHLETE_ID` | Source des données |
| `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID` | Bot + salon du brief |
| `BRIEF_HOUR`, `BRIEF_MINUTE` | Heure du brief quotidien |
| `ANTHROPIC_MODEL` | Modèle utilisé (optionnel) |
| `MULTI_USER`, `APP_SECRET_KEY` | App web multi-utilisateur (optionnel) |
| `OWNER_ATHLETE` | Ton compte, une fois tes données rangées (optionnel) |

Le reste se règle depuis l'app, onglet **Profil** : FTP, poids, lieu actuel
(la météo du coach suit ce lieu) et objectifs A/B/C.

## Organisation

```
src/ai_coach/
├── analysis.py      métriques (CTL/ATL/TSB, zones, durabilité, FTP…)
├── intervals.py     client Intervals.icu, cache, classification des séances
├── coach.py         appels au LLM + outils
├── brief.py         brief proactif (indépendant du canal)
├── profile.py       profil athlète, objectifs, localisation
├── accounts.py      comptes et clés API chiffrées (multi-utilisateur)
├── plan_tracker.py  plans prescrits et adhérence
├── memory.py/rag.py mémoire conversationnelle
├── web/             dashboard Streamlit
├── bot.py           bot Discord
└── main.py          CLI

data/    profils, caches, comptes (local, jamais versionné)
tests/   tests des fonctions de calcul
scripts/ utilitaires manuels
```

Les modules métier n'écrivent jamais sur la console : ils émettent via
`logging`, et chaque point d'entrée décide où ça sort.
