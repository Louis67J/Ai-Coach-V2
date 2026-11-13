# Image unique pour l'app web et le bot Discord (voir docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Cache du modèle d'embedding, rempli au build (hors du volume data/)
    HF_HOME=/opt/hf-cache \
    # L'image slim contient déjà tzdata : TZ règle l'heure du brief
    TZ=Europe/Paris

WORKDIR /app

# PyTorch en version CPU : le serveur n'a pas de GPU, et la version par
# défaut embarque CUDA (plusieurs Go pour rien).
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install -r requirements.txt

# Le modèle d'embedding de la mémoire du coach, téléchargé une fois au build
# plutôt qu'à chaque démarrage de conteneur.
RUN python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"

COPY pyproject.toml README.md ./
COPY src ./src
# Installation éditable : le code cherche data/ et outputs/ à côté de
# pyproject.toml, donc dans /app (montés en volumes par compose).
RUN pip install --no-deps -e . \
    && mkdir -p /app/data /app/outputs \
    && useradd --create-home --uid 1000 coach \
    && chown -R coach:coach /app/data /app/outputs

USER coach

EXPOSE 8501

CMD ["streamlit", "run", "src/ai_coach/web/app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", \
     "--server.headless=true", "--browser.gatherUsageStats=false"]
