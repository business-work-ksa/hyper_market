VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: installer migrer referentiels demo servir tester verifier propre

installer:            ## Crée l'environnement virtuel et installe les dépendances
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

migrer:               ## Applique les migrations
	$(PY) manage.py migrate

referentiels:         ## Charge rôles, rayons, offres, prestataires et plan comptable
	$(PY) manage.py initialiser_referentiels

demo: referentiels    ## Charge un jeu de démonstration (2 boutiques de Douala/Yaoundé)
	$(PY) manage.py charger_demo

servir:               ## Lance le serveur de développement
	$(PY) manage.py runserver

tester:               ## Exécute la suite de tests
	$(PY) manage.py test tests

verifier:             ## Contrôles de cohérence Django + migrations manquantes
	$(PY) manage.py check
	$(PY) manage.py makemigrations --check --dry-run

propre:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -f db.sqlite3
