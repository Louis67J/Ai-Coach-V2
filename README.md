# AI Coach v2

Coach IA personnel pour le cyclisme, connecté à Intervals.icu et Discord.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
pip install -r requirements.txt
cp .env.example .env
# Puis édite .env avec tes vraies clés
```

## Usage

```powershell
python -m ai_coach.main
```