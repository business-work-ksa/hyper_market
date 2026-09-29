#!/usr/bin/env bash
#
# Construction pour une plateforme sans serveur.
#
# Pourquoi un script et non une suite de commandes dans `vercel.json` :
#
#   * le champ est **limité à 256 caractères**, et la suite les dépassait ;
#   * une suite enchaînée à la main ne se commente pas, et chacune des étapes
#     ci-dessous a une raison qui n'est pas évidente ;
#   * `set -e` rend l'arrêt à la première erreur explicite plutôt que dépendant
#     de la bonne écriture de chaque `&&`.
#
# C'est le même raisonnement que pour `entree.sh`, l'entrée de production : on ne
# confie pas à un champ de formulaire ce qui décide si une instance sert des
# données isolées ou non.
set -euo pipefail

: "${DJANGO_SETTINGS_MODULE:=config.settings}"
export DJANGO_SETTINGS_MODULE

# La plateforme exige un répertoire de sortie, et il doit exister. Sans lui, elle
# cherche `public/`, ne le trouve pas, et **se replie sur la racine du dépôt** :
# `manage.py` et `requirements.txt` deviennent alors des fichiers publics servis
# par le CDN — et un fichier servi par le CDN passe **avant** la réécriture vers
# l'application. Ce répertoire est donc vide exprès.
mkdir -p sortie_vide
: > sortie_vide/.vide

# WhiteNoise sert ces fichiers depuis la fonction ; le manifeste produit ici est
# ce qui permet les noms versionnés et le cache immuable.
python3 manage.py collectstatic --noinput

# Il n'y a pas de démarrage où poser les migrations : une fonction sans serveur
# n'a pas de hook d'entrée. Elles tournent donc ici, et une construction qui
# échoue n'est pas déployée.
python3 manage.py migrate --noinput

# Critère bloquant : si une table scopée n'est pas protégée par la sécurité au
# niveau ligne, on ne met rien en ligne. C'est la barrière 3, celle que le code
# applicatif ne peut pas contourner.
python3 manage.py verifier_rls

# Compte administrateur, seulement s'il n'existe pas encore. Numéro, nom et mot
# de passe viennent des variables d'environnement — jamais du dépôt.
#
# L'échec est toléré par un `||` et non par un `;` : si le compte existe déjà, on
# continue en le disant ; toute autre erreur reste visible dans le journal.
if [ -n "${DJANGO_SUPERUSER_TELEPHONE:-}" ]; then
    python3 manage.py createsuperuser --noinput \
        || echo "Compte administrateur : déjà présent, rien à faire."
fi

# Garnissage de la démonstration, seulement si `JOURS_DEMO` est posé.
#
# **Il n'est pas là par défaut**, et c'est une leçon payée trois quarts d'heure : vingt
# jours de ventes simulées représentent plus de neuf mille requêtes — une écriture à la
# fois, à travers les vrais services, pour que le journal comptable soit cohérent — et
# contre une base gratuite au CPU bridé, cela dépasse le délai maximal d'une
# construction. Le volume est donc un paramètre, et le garnissage une décision.
#
# `charger_demo` est transactionnel : interrompu, il n'abîme rien, il n'a simplement pas
# eu lieu. C'est ce qui rend une nouvelle tentative sans risque.
if [ -n "${JOURS_DEMO:-}" ]; then
    python3 manage.py preparer_demo --jours "$JOURS_DEMO"
fi

# Les trois niveaux d'administration. Idempotent : posés une fois, vérifiés à chaque mise
# en ligne.
#
# Trois personnages et non un (ADR-012) : le superadministrateur qui administre tout et
# n'existe que pour le jour où quelque chose est cassé ; l'administrateur du marché qui
# valide, suspend et vend des emplacements, sans jamais voir la marge d'un commerçant ; et
# le compte de commerçant avec lequel cette même personne vend, s'il y en a un.
#
# Le groupe de permissions est synchronisé à chaque passage : c'est lui qui rend la
# distinction opérante, puisqu'un compte `is_staff` sans permission voit une administration
# vide.
python3 manage.py preparer_administrateur \
    --superadmin "${DJANGO_SUPERUSER_TELEPHONE:-}" \
    --administrateur "${ADMIN_MARCHE_TELEPHONE:-}" \
    --commercant "${ADMIN_COMMERCANT_TELEPHONE:-}" \
    --boutique "${ADMIN_BOUTIQUE:-}"

echo "Construction terminée."
