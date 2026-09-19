VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: installer migrer referentiels demo servir tester verifier securite \
        image deployer journal arreter propre

installer:            ## Crée l'environnement virtuel et installe les dépendances
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

migrer:               ## Applique les migrations
	$(PY) manage.py migrate

referentiels:         ## Charge rôles, rayons, offres, prestataires et plan comptable
	$(PY) manage.py initialiser_referentiels

demo: referentiels    ## Charge un jeu de démonstration (6 boutiques de Douala/Yaoundé)
	$(PY) manage.py charger_demo

servir:               ## Lance le serveur de développement
	$(PY) manage.py runserver

tester:               ## Exécute la suite de tests
	$(PY) manage.py test tests

verifier:             ## Contrôles de cohérence Django + migrations manquantes
	$(PY) manage.py check
	$(PY) manage.py makemigrations --check --dry-run

securite:             ## Vérifie que l'isolation au niveau ligne est réellement active
	$(PY) manage.py verifier_rls

# ---------------------------------------------------------------------------
# Production — voir docs/20-deploiement.md
# ---------------------------------------------------------------------------
image:                ## Construit l'image de production
	docker build -t hypermarche:local .

deployer:             ## Démarre la pile de production (exige .env.production)
	@test -f .env.production || { \
		echo "Absent : .env.production — copiez .env.production.example et remplissez-le."; \
		exit 1; \
	}
	docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build

journal:              ## Suit les journaux de la pile de production
	docker compose -f docker-compose.prod.yml logs -f web

arreter:              ## Arrête la pile de production, sans toucher aux volumes
	docker compose -f docker-compose.prod.yml down

propre:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -f db.sqlite3
