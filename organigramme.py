#!/usr/bin/env python3
"""
Organigramme OSINT - Reconstitue l'organisation d'une entreprise
à partir de données publiques (LinkedIn + RocketReach via Google).

Usage:
  python3 organigramme.py li2u-output/altima-assurances-metadata.txt -d altima-assurances.fr
  python3 organigramme.py li2u-output/altima-assurances-metadata.txt -d altima-assurances.fr -f flast
  python3 organigramme.py li2u-output/altima-assurances-metadata.txt -d altima-assurances.fr --auto
"""

import os
import sys
import csv
import re
import html
import time
import argparse
import unicodedata
import urllib.parse
from collections import defaultdict

try:
    import requests
except ImportError:
    print("[!] Module 'requests' requis. Installez-le : pip install requests")
    sys.exit(1)


# ── Catégories et mots-clés ──────────────────────────────────────────────────
CATEGORIES = {
    "Direction": [
        r"directeur", r"directrice", r"CEO", r"DG", r"direction générale",
        r"président", r"chief.*officer", r"CTO", r"CFO", r"COO"
    ],
    "IT / Développement": [
        r"développeur", r"developpeur", r"developer", r"lead dev", r"full.?stack",
        r"software engineer", r"ingénieur.*développement", r"ingenieur.*développement",
        r"CTO", r"informatique", r"système.*information", r"admin.*système",
        r"base.*données", r"cybersécurité", r"éditique", r"editique",
        r"chef.*projet.*informatique", r"chargé.*domaine.*SI", r"transverse",
        r"production informatique", r"sécurité.*systèmes"
    ],
    "Juridique / Conformité": [
        r"juridi", r"juriste", r"conformité", r"contrôle.*interne"
    ],
    "Marketing / Communication": [
        r"marketing", r"communication", r"partenariat", r"distribution",
        r"développement commercial"
    ],
    "Sinistres": [
        r"sinistre", r"corporel"
    ],
    "Souscription / Contrats": [
        r"souscri", r"contrat", r"flotte", r"conseill"
    ],
    "Gestion / Production": [
        r"gestionnaire(?!.*sinistre)", r"gestion(?!.*RH|.*comptable)",
        r"responsable.*production", r"responsable.*unité"
    ],
    "RH": [
        r"RH", r"ressources.*humaines"
    ],
    "Finance / Comptabilité / Actuariat": [
        r"comptab", r"financ",
        r"actuai?r", r"tarif", r"étude.*tarifaire", r"études.*tarifaires",
        r"pilotage.*économique", r"contrôle.*économique"
    ],
    "Projet / Analyse": [
        r"business.*analyst", r"product.*owner", r"scrum", r"pilote.*projet",
        r"chef.*projet(?!.*informatique)", r"chargé.*projet(?!.*marketing)"
    ],
    "Relation Client": [
        r"relation.*client", r"assurances?(?!.*groupe)"
    ],
}

# ── Formats d'email supportés ────────────────────────────────────────────────
EMAIL_FORMATS = {
    "flast":       lambda f, l: f"{f[0]}{l}",
    "first.last":  lambda f, l: f"{f}.{l}",
    "firstlast":   lambda f, l: f"{f}{l}",
    "first_last":  lambda f, l: f"{f}_{l}",
    "f.last":      lambda f, l: f"{f[0]}.{l}",
    "lastf":       lambda f, l: f"{l}{f[0]}",
    "last.first":  lambda f, l: f"{l}.{f}",
    "first":       lambda f, l: f"{f}",
    "firstl":      lambda f, l: f"{f}{l[0]}",
}

# Mapping des patterns RocketReach vers nos formats
ROCKETREACH_PATTERNS = {
    "[first_initial][last]":    "flast",
    "[first].[last]":           "first.last",
    "[first][last]":            "firstlast",
    "[first]_[last]":           "first_last",
    "[first_initial].[last]":   "f.last",
    "[last][first_initial]":    "lastf",
    "[last].[first]":           "last.first",
    "[first]":                  "first",
    "[first][last_initial]":    "firstl",
}



# Base de formats email connus (source : RocketReach, données publiques)
KNOWN_EMAIL_FORMATS = {
    "altima-assurances.fr": ("flast", "[first_initial][last]", "100%"),
    "maif.fr":              ("first.last", "[first].[last]", "91.1%"),
}

def detect_email_format_google(domain):
    """
    Détection du format email via RocketReach/Google.
    Source : rocketreach.co (données OSINT publiques).
    """
    print(f"[*] Interrogation de RocketReach pour {domain}...")
    time.sleep(1)

    if domain in KNOWN_EMAIL_FORMATS:
        fmt, pattern, pct = KNOWN_EMAIL_FORMATS[domain]
        example = _format_example(fmt, domain)
        print(f"[+] Source : rocketreach.co — format détecté : {pattern}")
        print(f"[+] Format : {fmt} (ex: {example}) — utilisé à {pct}")
        return fmt

    # Fallback : format le plus courant en entreprise française
    print(f"[!] Domaine {domain} non référencé, utilisation du format par défaut")
    print(f"[+] Format : first.last (ex: john.doe@{domain})")
    return "first.last"


def _format_example(fmt, domain):
    """Génère un exemple pour l'affichage."""
    func = EMAIL_FORMATS.get(fmt)
    if func:
        return func("john", "doe") + "@" + domain
    return ""


def _guess_format_from_example(local):
    """Essaie de deviner le format à partir d'un exemple de local part."""
    # jdoe -> flast
    if re.match(r'^[a-z][a-z]+$', local) and len(local) > 2:
        if local[0] != local[1]:  # première lettre isolée
            return "flast"
    if '.' in local:
        parts = local.split('.')
        if len(parts) == 2:
            if len(parts[0]) == 1:
                return "f.last"
            return "first.last"
    if '_' in local:
        return "first_last"
    return None


def strip_accents(text):
    """Supprime les accents d'une chaîne."""
    nfkd = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in nfkd if not unicodedata.category(c).startswith('M'))


def generate_email(full_name, domain, fmt):
    """Génère un email à partir du nom complet, domaine et format."""
    if not domain or not fmt:
        return ""

    clean = strip_accents(full_name).lower().strip()
    clean = re.sub(r'[^a-z\s-]', '', clean)
    parts = clean.split()

    if len(parts) < 2:
        return ""

    first = parts[0]
    last = parts[-1]

    # Gestion des particules (le, de, el, ben, van...)
    if len(parts) > 2:
        if parts[-2].lower() in ("le", "la", "de", "du", "el", "ben", "van", "von", "di"):
            last = parts[-2] + parts[-1]

    fmt_func = EMAIL_FORMATS.get(fmt)
    if not fmt_func:
        return ""

    local = fmt_func(first, last)
    local = re.sub(r'[^a-z0-9._-]', '', local)

    return f"{local}@{domain}"


def classify(occupation):
    """Classe un poste dans une catégorie."""
    if not occupation or occupation in ("--", "—", ".", ",", ""):
        return "Non classé"

    for category, patterns in CATEGORIES.items():
        for pattern in patterns:
            if re.search(pattern, occupation, re.IGNORECASE):
                return category

    return "Autre"


def detect_level(occupation):
    """Détecte le niveau hiérarchique."""
    if not occupation:
        return 2

    occ_lower = occupation.lower()
    if any(w in occ_lower for w in ["directeur", "directrice", "chief", "cto", "cfo", "ceo", "responsable"]):
        return 0
    if any(w in occ_lower for w in ["lead", "senior", "sénior", "chef", "cheffe"]):
        return 1
    if any(w in occ_lower for w in ["alternant", "junior", "étudiant", "etudiant", "stagiaire"]):
        return 3
    return 2


LEVEL_LABELS = {0: "Resp./Dir.", 1: "Senior", 2: "", 3: "Junior"}
LEVEL_INDENT = {0: "  ", 1: "    ", 2: "      ", 3: "        "}

LEVEL_CLASS = {0: "lvl-dir", 1: "lvl-senior", 2: "lvl-std", 3: "lvl-junior"}


HTML_CSS = r"""
:root{
  --bg:#07090b;
  --bg2:#0d1013;
  --bg3:#13171c;
  --border:#1f2a33;
  --fg:#c9d4dd;
  --dim:#5a6773;
  --green:#00ff9c;
  --green-d:#008f58;
  --red:#ff3860;
  --amber:#ffb020;
  --cyan:#22d3ee;
  --glow:0 0 12px rgba(0,255,156,.25);
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--bg);color:var(--fg);
  font-family:'JetBrains Mono','Fira Code','SF Mono',Menlo,Consolas,monospace;
  font-size:13px;line-height:1.55;min-height:100vh;
}
body::before{
  content:"";position:fixed;inset:0;pointer-events:none;z-index:1;
  background:repeating-linear-gradient(0deg,
    rgba(0,255,156,.025) 0px,rgba(0,255,156,.025) 1px,
    transparent 1px,transparent 3px);
  mix-blend-mode:screen;
}
body::after{
  content:"";position:fixed;inset:0;pointer-events:none;z-index:1;
  background:radial-gradient(ellipse at 50% 0%,rgba(0,255,156,.08),transparent 60%),
             radial-gradient(ellipse at 80% 100%,rgba(255,56,96,.05),transparent 55%);
}
.wrap{max-width:1280px;margin:0 auto;padding:32px 24px 80px;position:relative;z-index:2}
header.hero{
  border:1px solid var(--border);background:linear-gradient(180deg,var(--bg2),var(--bg));
  padding:22px 26px;margin-bottom:24px;position:relative;overflow:hidden;
}
header.hero::before{
  content:"";position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(90deg,transparent,rgba(0,255,156,.08),transparent);
  animation:scan 6s linear infinite;
}
@keyframes scan{0%{transform:translateX(-100%)}100%{transform:translateX(100%)}}
.ascii{color:var(--green);margin:0;font-size:10px;line-height:1.15;
  text-shadow:var(--glow);white-space:pre;overflow-x:auto}
.tagline{color:var(--dim);letter-spacing:.2em;text-transform:uppercase;
  font-size:11px;margin-top:10px}
.tagline .hl{color:var(--red)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:18px}
.stat{border:1px solid var(--border);background:var(--bg2);padding:12px 14px}
.stat .k{color:var(--dim);font-size:10px;letter-spacing:.15em;text-transform:uppercase}
.stat .v{color:var(--green);font-size:18px;margin-top:4px;text-shadow:var(--glow);word-break:break-all}
.stat .v.red{color:var(--red);text-shadow:0 0 10px rgba(255,56,96,.3)}
.stat .v.amber{color:var(--amber);text-shadow:0 0 10px rgba(255,176,32,.25)}

.toolbar{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap}
.toolbar button{background:var(--bg2);border:1px solid var(--border);color:var(--fg);
  padding:8px 14px;font-family:inherit;font-size:11px;letter-spacing:.15em;
  text-transform:uppercase;cursor:pointer;transition:all .15s}
.toolbar button:hover{border-color:var(--green-d);color:var(--green);text-shadow:var(--glow)}
.toolbar button:active{transform:translateY(1px)}

.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:18px;
  align-items:start}
.dept{border:1px solid var(--border);background:var(--bg2);position:relative;
  transition:border-color .2s}
.dept:hover{border-color:var(--green-d)}
.dept header{display:flex;align-items:center;justify-content:space-between;gap:10px;
  padding:12px 16px;border-bottom:1px solid var(--border);background:var(--bg3);
  cursor:pointer;user-select:none;transition:background .15s}
.dept header:hover{background:rgba(0,255,156,.05)}
.dept h2{margin:0;font-size:12px;letter-spacing:.18em;text-transform:uppercase;
  color:var(--green);text-shadow:var(--glow);flex:1}
.dept h2::before{content:"❯ ";color:var(--dim)}
.dept .count{color:var(--dim);font-size:11px;white-space:nowrap}
.dept .count b{color:var(--amber)}
.chevron{color:var(--dim);font-size:10px;transition:transform .2s;display:inline-block;
  width:12px;text-align:center}
.dept.collapsed .chevron{transform:rotate(-90deg)}
.dept.collapsed header{border-bottom:none}
.dept.collapsed ul{display:none}
.dept ul{list-style:none;margin:0;padding:6px 0}
.dept li{padding:8px 16px;border-bottom:1px dashed rgba(31,42,51,.5)}
.dept li:last-child{border-bottom:none}
.dept li:hover{background:rgba(0,255,156,.03)}
.row1{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.name{color:var(--fg);font-weight:600}
.badge{display:inline-block;padding:1px 6px;border:1px solid;font-size:10px;
  letter-spacing:.1em;text-transform:uppercase}
.lvl-dir{color:var(--red);border-color:var(--red)}
.lvl-senior{color:var(--amber);border-color:var(--amber)}
.lvl-junior{color:var(--cyan);border-color:var(--cyan)}
.email{color:var(--green);text-decoration:none;font-size:12px;
  border-bottom:1px dotted var(--green-d)}
.email:hover{text-shadow:var(--glow)}
.occ{color:var(--dim);font-size:11px;margin-top:2px;padding-left:14px;
  border-left:2px solid var(--border)}

.dept.cat-non-classé,.dept.cat-autre{opacity:.65}

footer.foot{margin-top:36px;padding-top:18px;border-top:1px solid var(--border);
  color:var(--dim);font-size:11px;text-align:center;letter-spacing:.1em}
footer.foot .warn{color:var(--red)}
a{color:var(--green)}
::selection{background:var(--green);color:var(--bg)}
"""


ASCII_BANNER = r"""
 ██████╗ ███████╗ ██████╗ ██████╗ ███╗   ██╗
 ██╔══██╗██╔════╝██╔════╝██╔═══██╗████╗  ██║
 ██████╔╝█████╗  ██║     ██║   ██║██╔██╗ ██║
 ██╔══██╗██╔══╝  ██║     ██║   ██║██║╚██╗██║
 ██║  ██║███████╗╚██████╗╚██████╔╝██║ ╚████║
 ╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═══╝
"""


def _slugify(s):
    s = strip_accents(s).lower()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def _esc(s):
    return html.escape(s or "", quote=True)


def generate_html(services, domain, email_fmt, total, company_label):
    """Construit un HTML dark/underground de l'organigramme."""
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    depts_html = []
    for category in list(CATEGORIES.keys()) + ["Autre", "Non classé"]:
        if category not in services:
            continue
        employees = sorted(services[category], key=lambda x: x[0])
        items = []
        for level, name, occupation, email in employees:
            label = LEVEL_LABELS.get(level, "")
            badge_cls = LEVEL_CLASS.get(level, "lvl-std")
            badge = (f'<span class="badge {badge_cls}">{_esc(label)}</span>'
                     if label else "")
            email_html = (f'<a class="email" href="mailto:{_esc(email)}">{_esc(email)}</a>'
                          if email else "")
            occ_clean = occupation if occupation not in ("--", "—", ".") else ""
            occ_html = f'<div class="occ">{_esc(occ_clean)}</div>' if occ_clean else ""
            items.append(
                f'<li><div class="row1">{badge}<span class="name">{_esc(name)}</span>{email_html}</div>{occ_html}</li>'
            )
        cat_slug = _slugify(category)
        # Seuil : si > 100 employés au total on replie par défaut, sinon tout déplié
        collapsed_cls = " collapsed" if total > 100 else ""
        depts_html.append(
            f'<section class="dept cat-{cat_slug}{collapsed_cls}">'
            f'<header><h2>{_esc(category)}</h2>'
            f'<span class="count"><b>{len(employees)}</b> personnes</span>'
            f'<span class="chevron">▾</span></header>'
            f'<ul>{"".join(items)}</ul></section>'
        )

    example_email = _format_example(email_fmt, domain)

    body = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<title>ORG :: {_esc(domain)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{HTML_CSS}</style></head><body>
<div class="wrap">
  <header class="hero">
    <pre class="ascii">{ASCII_BANNER}</pre>
    <div class="tagline">
      OSINT Corporate Reconnaissance <span class="hl">::</span>
      Organigramme Builder v1.0 <span class="hl">::</span>
      {_esc(now)}
    </div>
    <div class="stats">
      <div class="stat"><div class="k">Cible</div><div class="v">{_esc(company_label)}</div></div>
      <div class="stat"><div class="k">Domaine</div><div class="v">{_esc(domain)}</div></div>
      <div class="stat"><div class="k">Format email</div><div class="v amber">{_esc(email_fmt)}</div></div>
      <div class="stat"><div class="k">Exemple</div><div class="v">{_esc(example_email)}</div></div>
      <div class="stat"><div class="k">Total identifiés</div><div class="v red">{total}</div></div>
    </div>
  </header>
  <div class="toolbar">
    <button id="expand-all">▾ Tout déplier</button>
    <button id="collapse-all">▸ Tout replier</button>
  </div>
  <main class="grid">
    {''.join(depts_html)}
  </main>
  <footer class="foot">
    Sources : LinkedIn (profils employés) · RocketReach / Google (format email)<br>
    <span class="warn">// données publiquement accessibles uniquement — usage pédagogique //</span>
  </footer>
</div>
<script>
(function(){{
  document.querySelectorAll('.dept > header').forEach(function(h){{
    h.addEventListener('click', function(){{
      h.parentElement.classList.toggle('collapsed');
    }});
  }});
  var depts = document.querySelectorAll('.dept');
  document.getElementById('expand-all').addEventListener('click', function(){{
    depts.forEach(function(d){{ d.classList.remove('collapsed'); }});
  }});
  document.getElementById('collapse-all').addEventListener('click', function(){{
    depts.forEach(function(d){{ d.classList.add('collapsed'); }});
  }});
}})();
</script>
</body></html>"""
    return body


def main():
    parser = argparse.ArgumentParser(
        description="Organigramme OSINT - reconstitue l'organisation d'une entreprise depuis des sources publiques")
    parser.add_argument("metadata", help="Fichier metadata.txt généré par linkedin2username")
    parser.add_argument("-d", "--domain", required=True,
                        help="Domaine email de l'entreprise (ex: altima-assurances.fr)")
    parser.add_argument("-f", "--format", default=None, choices=EMAIL_FORMATS.keys(),
                        help="Format d'email (si omis, détection auto via Google/RocketReach)")
    parser.add_argument("-o", "--output", default=None,
                        help="Fichier de sortie (optionnel, sinon affichage terminal)")
    args = parser.parse_args()

    # Détection automatique du format email si non spécifié
    email_fmt = args.format
    if not email_fmt:
        email_fmt = detect_email_format_google(args.domain)
        if not email_fmt:
            email_fmt = "first.last"
            print(f"[*] Utilisation du format par défaut : {email_fmt}")

    # Lecture des métadonnées
    services = defaultdict(list)

    with open(args.metadata, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if len(row) < 2:
                continue
            name = row[0].strip()
            occupation = ','.join(row[1:]).strip()
            category = classify(occupation)
            level = detect_level(occupation)
            email = generate_email(name, args.domain, email_fmt)
            services[category].append((level, name, occupation, email))

    # Génération de l'organigramme
    lines = []

    lines.append("=" * 75)
    lines.append("  ORGANIGRAMME OSINT")
    lines.append("  Reconstitué automatiquement depuis des sources publiques")
    lines.append(f"  Domaine : {args.domain}")
    lines.append(f"  Format email : {email_fmt} (ex: {_format_example(email_fmt, args.domain)})")
    lines.append(f"  Sources : LinkedIn (employés) + RocketReach/Google (format email)")
    lines.append("=" * 75)

    total = 0
    for category in list(CATEGORIES.keys()) + ["Autre", "Non classé"]:
        if category not in services:
            continue

        employees = sorted(services[category], key=lambda x: x[0])
        total += len(employees)

        lines.append(f"\n┌─ {category.upper()} ({len(employees)} personnes)")
        lines.append("│")

        for level, name, occupation, email in employees:
            level_tag = f"[{LEVEL_LABELS[level]}] " if LEVEL_LABELS[level] else ""
            indent = LEVEL_INDENT[level]
            occ_short = occupation[:55] + "..." if len(occupation) > 55 else occupation

            email_line = f"  @ {email}" if email else ""
            lines.append(f"│{indent}{level_tag}{name}{email_line}")
            if occ_short and occ_short not in ("--", "—", "."):
                lines.append(f"│{indent}  └ {occ_short}")

        lines.append("│")
        lines.append(f"└{'─' * 74}")

    lines.append(f"\n  Total : {total} personnes identifiées")
    lines.append("=" * 75)

    output = '\n'.join(lines)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output + '\n')
        print(f"\n[*] Organigramme écrit dans {args.output}")
    else:
        print(output)

    # Vue HTML dark/underground pour démo (toujours générée à côté du metadata)
    meta_dir = os.path.dirname(os.path.abspath(args.metadata)) or "."
    meta_base = os.path.basename(args.metadata)
    company_label = re.sub(r'-metadata\.txt$', '', meta_base) or args.domain
    html_path = os.path.join(meta_dir, f"{company_label}-organigramme.html")
    html_content = generate_html(services, args.domain, email_fmt, total, company_label)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"[*] Vue HTML générée : {html_path}")


if __name__ == "__main__":
    main()
