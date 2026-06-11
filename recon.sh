#!/bin/bash
# ============================================================================
#  OSINT Corporate Recon - Organigramme Builder
#  Reconstitue l'organigramme d'une entreprise depuis des sources publiques
# ============================================================================

set -e

# ── Couleurs & Styles ───────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

# ── Fonctions d'affichage ───────────────────────────────────────────────────
banner() {
    echo ""
    echo -e "${PURPLE}${BOLD}"
    echo "    ╔═══════════════════════════════════════════════════════════╗"
    echo "    ║                                                           ║"
    echo "    ║     ██████╗ ███████╗ ██████╗ ██████╗ ███╗   ██╗           ║"
    echo "    ║     ██╔══██╗██╔════╝██╔════╝██╔═══██╗████╗  ██║           ║"
    echo "    ║     ██████╔╝█████╗  ██║     ██║   ██║██╔██╗ ██║           ║"
    echo "    ║     ██╔══██╗██╔══╝  ██║     ██║   ██║██║╚██╗██║           ║"
    echo "    ║     ██║  ██║███████╗╚██████╗╚██████╔╝██║ ╚████║           ║"
    echo "    ║     ╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═══╝           ║"
    echo "    ║                                                           ║"
    echo "    ║         OSINT Corporate Reconnaissance Tool               ║"
    echo "    ║         Organigramme Builder v1.0                         ║"
    echo "    ║                                                           ║"
    echo "    ╚═══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

step() {
    echo ""
    echo -e "  ${CYAN}${BOLD}[$1/5]${NC} ${WHITE}${BOLD}$2${NC}"
    echo -e "  ${DIM}$(printf '%.0s─' {1..60})${NC}"
}

info() {
    echo -e "  ${BLUE}    ►${NC} $1"
}

success() {
    echo -e "  ${GREEN}    ✔${NC} $1"
}

warn() {
    echo -e "  ${YELLOW}    ⚠${NC} $1"
}

fail() {
    echo -e "  ${RED}    ✘${NC} $1"
    exit 1
}

spinner() {
    local pid=$1
    local msg=$2
    local spin='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    local i=0
    while kill -0 "$pid" 2>/dev/null; do
        printf "\r  ${BLUE}    ${spin:i++%${#spin}:1}${NC} ${DIM}${msg}${NC}"
        sleep 0.1
    done
    printf "\r  ${GREEN}    ✔${NC} ${msg}                    \n"
}

# ── Arguments ────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPANY=""
DOMAIN=""
EMAIL_FORMAT=""
OUTPUT_DIR="li2u-output"
OUTPUT_FILE=""

usage() {
    echo -e "${WHITE}Usage:${NC}"
    echo "  ./recon.sh -c <company-slug> -d <domain>"
    echo ""
    echo -e "${WHITE}Options:${NC}"
    echo "  -c    LinkedIn company slug (ex: altima-assurances)"
    echo "  -d    Domaine email (ex: altima-assurances.fr)"
    echo "  -f    Format email, optionnel (ex: flast, first.last)"
    echo "  -o    Fichier de sortie, optionnel"
    echo ""
    echo -e "${WHITE}Exemple:${NC}"
    echo "  ./recon.sh -c altima-assurances -d altima-assurances.fr"
    echo ""
    exit 0
}

while getopts "c:d:f:o:h" opt; do
    case $opt in
        c) COMPANY="$OPTARG" ;;
        d) DOMAIN="$OPTARG" ;;
        f) EMAIL_FORMAT="$OPTARG" ;;
        o) OUTPUT_FILE="$OPTARG" ;;
        h) usage ;;
        *) usage ;;
    esac
done

if [ -z "$COMPANY" ] || [ -z "$DOMAIN" ]; then
    banner
    echo -e "  ${RED}Erreur: les paramètres -c et -d sont obligatoires.${NC}"
    echo ""
    usage
fi

# ── Go ───────────────────────────────────────────────────────────────────────
banner

echo -e "  ${DIM}Cible    :${NC} ${WHITE}${BOLD}$COMPANY${NC}"
echo -e "  ${DIM}Domaine  :${NC} ${WHITE}${BOLD}$DOMAIN${NC}"
echo -e "  ${DIM}Date     :${NC} ${WHITE}$(date '+%Y-%m-%d %H:%M:%S')${NC}"

# ── STEP 1 : Environnement ──────────────────────────────────────────────────
step 1 "Préparation de l'environnement"

# Créer le venv hors ProtonDrive (qui casse les symlinks et permissions)
VENV_DIR="$HOME/.cache/linkedin-recon-venv"

if [ ! -d "$VENV_DIR" ] || [ ! -x "$VENV_DIR/bin/python3" ]; then
    info "Création du virtualenv dans $VENV_DIR..."
    rm -rf "$VENV_DIR"
    python3 -m venv "$VENV_DIR"
    success "Virtualenv créé"
else
    success "Virtualenv existant détecté"
fi

source "$VENV_DIR/bin/activate"

info "Installation des dépendances..."
python3 -m pip install -q requests selenium 2>/dev/null &
spinner $! "Installation de requests + selenium"

# Vérification des drivers Selenium
if command -v geckodriver &>/dev/null; then
    success "geckodriver trouvé : $(which geckodriver)"
elif command -v chromedriver &>/dev/null; then
    success "chromedriver trouvé : $(which chromedriver)"
else
    warn "Aucun driver Selenium trouvé (geckodriver/chromedriver)"
    warn "Tentative d'installation via brew..."
    if command -v brew &>/dev/null; then
        brew install geckodriver 2>/dev/null || warn "Installation geckodriver échouée, essayez manuellement"
    else
        fail "Installez geckodriver ou chromedriver manuellement"
    fi
fi

# ── STEP 2 : Scraping LinkedIn ──────────────────────────────────────────────
step 2 "Extraction des employés via LinkedIn"

info "Lancement de linkedin2username sur ${BOLD}$COMPANY${NC}"
info "Un navigateur va s'ouvrir pour l'authentification LinkedIn"
echo ""
echo -e "  ${YELLOW}${BOLD}    ⏳ En attente de votre connexion LinkedIn...${NC}"
echo -e "  ${DIM}    (connectez-vous puis appuyez sur Entrée dans le terminal)${NC}"
echo ""

python3 "$SCRIPT_DIR/linkedin2username.py" -c "$COMPANY" -o "$SCRIPT_DIR/$OUTPUT_DIR"

METADATA="$SCRIPT_DIR/$OUTPUT_DIR/${COMPANY}-metadata.txt"

if [ ! -f "$METADATA" ]; then
    fail "Fichier metadata introuvable : $METADATA"
fi

NB_EMPLOYEES=$(( $(wc -l < "$METADATA") - 1 ))
success "${BOLD}$NB_EMPLOYEES${NC}${GREEN} employés extraits de LinkedIn${NC}"

# ── STEP 3 : Détection du format email ──────────────────────────────────────
step 3 "Détection du format email via Google/RocketReach"

if [ -n "$EMAIL_FORMAT" ]; then
    success "Format imposé : ${BOLD}$EMAIL_FORMAT${NC}"
else
    info "Recherche automatique du format pour ${BOLD}$DOMAIN${NC}..."
    # On laisse organigramme.py s'en occuper, il affichera le résultat
fi

# ── STEP 4 : Génération de l'organigramme ───────────────────────────────────
step 4 "Construction de l'organigramme"

info "Classification des employés par service..."
info "Détection des niveaux hiérarchiques..."

ORGCMD="python3 $SCRIPT_DIR/organigramme.py $METADATA -d $DOMAIN"

if [ -n "$EMAIL_FORMAT" ]; then
    ORGCMD="$ORGCMD -f $EMAIL_FORMAT"
fi

if [ -n "$OUTPUT_FILE" ]; then
    ORGCMD="$ORGCMD -o $OUTPUT_FILE"
fi

echo ""
eval "$ORGCMD"

# ── STEP 5 : Résumé ────────────────────────────────────────────────────────
step 5 "Récapitulatif"

echo ""
echo -e "  ${GREEN}${BOLD}  Reconnaissance terminée avec succès.${NC}"
echo ""
echo -e "  ${DIM}  Fichiers générés dans ${NC}${WHITE}$OUTPUT_DIR/${NC}${DIM} :${NC}"
echo ""

for f in "$SCRIPT_DIR/$OUTPUT_DIR/${COMPANY}"*; do
    fname=$(basename "$f")
    fsize=$(du -h "$f" | cut -f1 | xargs)
    echo -e "    ${CYAN}├─${NC} $fname ${DIM}($fsize)${NC}"
done

if [ -n "$OUTPUT_FILE" ]; then
    echo ""
    echo -e "  ${DIM}  Organigramme :${NC} ${WHITE}$OUTPUT_FILE${NC}"
fi

echo ""
echo -e "  ${PURPLE}${DIM}──────────────────────────────────────────────────────────${NC}"
echo -e "  ${DIM}  Sources utilisées :${NC}"
echo -e "  ${DIM}    • LinkedIn (profils employés)${NC}"
echo -e "  ${DIM}    • Google/RocketReach (format email)${NC}"
echo -e "  ${DIM}  Disclaimer : données publiquement accessibles uniquement${NC}"
echo -e "  ${PURPLE}${DIM}──────────────────────────────────────────────────────────${NC}"
echo ""
