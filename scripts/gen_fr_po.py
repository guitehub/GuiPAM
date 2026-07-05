#!/usr/bin/env python3
"""Génère app/locale/fr/LC_MESSAGES/messages.po depuis le .pot + dictionnaire ci-dessous.

Usage : pybabel extract -F babel.cfg -o messages.pot . && python scripts/gen_fr_po.py messages.pot
Signale toute chaîne sans traduction (à compléter ici avant de relancer).
"""

import sys
from pathlib import Path

from babel.messages.pofile import read_po, write_po

FR = {
    # --- deps / auth ---
    "Read-only account: action not allowed.": "Compte en lecture seule : action non autorisée.",
    "Invalid or missing CSRF token.": "Jeton CSRF invalide ou manquant.",
    "never": "jamais",
    "Too many attempts. Try again in %d seconds.": "Trop de tentatives. Réessayez dans %d secondes.",
    "Invalid username or password.": "Identifiant ou mot de passe invalide.",
    # --- import/export ---
    "File is too large (5 MB max).": "Fichier trop volumineux (5 Mo max).",
    "The file is empty.": "Le fichier est vide.",
    "No IP address column found in the file.": "Aucune colonne d'adresse IP trouvée dans le fichier.",
    "Line %(line)d: %(error)s": "Ligne %(line)d : %(error)s",
    "%(count)d created": "%(count)d créée(s)",
    "%(count)d VLAN(s) created": "%(count)d VLAN créé(s)",
    "%(count)d skipped (duplicates)": "%(count)d ignorée(s) (doublons)",
    "%(count)d error(s)": "%(count)d erreur(s)",
    "View the result on the dashboard": "Voir le résultat sur le tableau de bord",
    "Import a CSV file": "Importer un fichier CSV",
    "Tolerant import for migrating from an Excel export: common column aliases are recognized (ip, adresse, hostname, nom, mac, statut…), duplicates are skipped, missing VLANs are created from the CIDR column (or a /24 by default).": "Import tolérant pour migrer depuis un export Excel : les alias de colonnes courants sont reconnus (ip, adresse, hostname, nom, mac, statut…), les doublons sont ignorés, les VLAN manquants sont créés depuis la colonne CIDR (ou un /24 par défaut).",
    "Import": "Importer",
    "Read-only account: import is not available.": "Compte en lecture seule : l'import n'est pas disponible.",
    "Export to CSV": "Exporter en CSV",
    "Full export of all addresses, in a format that can be re-imported as is (backup or migration).": "Export complet de toutes les adresses, dans un format réimportable tel quel (sauvegarde ou migration).",
    "Download export.csv": "Télécharger export.csv",
    "Import / Export": "Import / Export",
    # --- ips ---
    "IP address not found.": "Adresse IP introuvable.",
    "VLAN not found.": "VLAN introuvable.",
    "Address %s created.": "Adresse %s créée.",
    "Address %s updated.": "Adresse %s mise à jour.",
    "Address %s deleted.": "Adresse %s supprimée.",
    # --- monitors ---
    "Monitor target not found.": "Cible de suivi introuvable.",
    "A TCP check requires a port between 1 and 65535.": "Un check TCP nécessite un port entre 1 et 65535.",
    "ICMP ping is disabled on this instance (GUIPAM_ENABLE_PING=false).": "Le ping ICMP est désactivé sur cette instance (GUIPAM_ENABLE_PING=false).",
    "Interval must be between %(min)d and %(max)d seconds.": "L'intervalle doit être compris entre %(min)d et %(max)d secondes.",
    "Monitor target added on %s.": "Cible de suivi ajoutée sur %s.",
    "Monitor target updated.": "Cible de suivi mise à jour.",
    "Monitor target deleted.": "Cible de suivi supprimée.",
    # --- reseau ---
    "“%s” is not a valid network prefix.": "« %s » n'est pas un préfixe réseau valide.",
    "Name is required.": "Le nom est requis.",
    "Network settings saved.": "Paramètres du réseau enregistrés.",
    # --- subnets ---
    "VLAN tag must be a number between 1 and 4094.": "Le tag VLAN doit être un nombre entre 1 et 4094.",
    "VLAN “%s” created.": "VLAN « %s » créé.",
    "VLAN “%s” updated.": "VLAN « %s » mis à jour.",
    "VLAN “%s” deleted (with its addresses and targets).": "VLAN « %s » supprimé (avec ses adresses et ses cibles).",
    "Cannot change CIDR: %(count)d addresses would fall outside (e.g. %(example)s).": "Impossible de changer le CIDR : %(count)d adresses en sortiraient (ex. %(example)s).",
    # --- users ---
    "User not found.": "Utilisateur introuvable.",
    "Username is required.": "L'identifiant est requis.",
    "Password must be at least %d characters long.": "Le mot de passe doit contenir au moins %d caractères.",
    "Username “%s” is already taken.": "L'identifiant « %s » est déjà pris.",
    "User “%s” created.": "Utilisateur « %s » créé.",
    "Cannot demote or deactivate the last active manager.": "Impossible de rétrograder ou désactiver le dernier manager actif.",
    "User “%s” updated.": "Utilisateur « %s » mis à jour.",
    "Password of “%s” reset.": "Mot de passe de « %s » réinitialisé.",
    "Cannot delete the last active manager.": "Impossible de supprimer le dernier manager actif.",
    "User “%s” deleted.": "Utilisateur « %s » supprimé.",
    # --- ipam ---
    "Invalid CIDR: “%s” is not a valid IPv4 network.": "CIDR invalide : « %s » n'est pas un réseau IPv4 valide.",
    "Invalid CIDR: “%(value)s” has host bits set (network address is %(network)s).": "CIDR invalide : « %(value)s » a des bits d'hôte non nuls (l'adresse réseau est %(network)s).",
    "Only IPv4 is supported in this version.": "Seul IPv4 est pris en charge dans cette version.",
    "“%s” is not a valid IPv4 address.": "« %s » n'est pas une adresse IPv4 valide.",
    "“%s” is not a valid MAC address.": "« %s » n'est pas une adresse MAC valide.",
    "CIDR %(cidr)s overlaps VLAN “%(name)s” (%(other)s).": "Le CIDR %(cidr)s chevauche le VLAN « %(name)s » (%(other)s).",
    "Gateway %(gateway)s is outside subnet %(cidr)s.": "La passerelle %(gateway)s est hors du subnet %(cidr)s.",
    "Address %(address)s is outside subnet %(cidr)s.": "L'adresse %(address)s est hors du subnet %(cidr)s.",
    "%s is the network address and cannot be assigned.": "%s est l'adresse réseau et ne peut pas être attribuée.",
    "%s is the broadcast address and cannot be assigned.": "%s est l'adresse de broadcast et ne peut pas être attribuée.",
    "Address %(address)s already exists in VLAN “%(name)s”.": "L'adresse %(address)s existe déjà dans le VLAN « %(name)s ».",
    "Subnet %(cidr)s is full (%(capacity)d usable addresses).": "Le subnet %(cidr)s est plein (%(capacity)d adresses utilisables).",
    # --- chrome / base ---
    "Your account cannot modify anything.": "Votre compte ne peut rien modifier.",
    "Read-only": "Lecture seule",
    "Dashboard": "Tableau de bord",
    "Audit log": "Journal d'audit",
    "Users": "Utilisateurs",
    "Toggle light/dark theme": "Basculer le thème clair/sombre",
    "Language": "Langue",
    "Log out": "Se déconnecter",
    "Are you sure?": "Confirmer ?",
    "Cancel": "Annuler",
    "Confirm": "Confirmer",
    "Breadcrumb": "Fil d'Ariane",
    # --- login ---
    "Sign in": "Se connecter",
    "Access to GuiPAM requires an account. No self-registration.": "L'accès à GuiPAM nécessite un compte. Pas d'auto-inscription.",
    "Username": "Identifiant",
    "Password": "Mot de passe",
    # --- dashboard ---
    "Edit": "Modifier",
    "Root prefixes:": "Préfixes racine :",
    "VLANs": "VLAN",
    "New VLAN": "Nouveau VLAN",
    "VLAN tag": "Tag VLAN",
    "Name": "Nom",
    "CIDR": "CIDR",
    "Gateway": "Passerelle",
    "Occupancy": "Occupation",
    "IPs": "IP",
    "No VLAN yet. Create your first VLAN to start tracking addresses.": "Aucun VLAN pour l'instant. Créez votre premier VLAN pour commencer à suivre les adresses.",
    "Ask a manager to create it.": "Demandez à un manager de le créer.",
    "Total IPs": "IP totales",
    "Used": "Utilisées",
    "Free": "Libres",
    "Reserved": "Réservées",
    "To review (red)": "À traiter (rouges)",
    "To review": "À traiter",
    "Addresses whose targets no longer respond, worst first. Fix them or clean up stale entries.": "Adresses dont les cibles ne répondent plus, les pires d'abord. Réparez-les ou nettoyez les entrées obsolètes.",
    "last success:": "dernier succès :",
    # --- subnet page ---
    "Plan view": "Vue plan",
    "Network": "Réseau",
    "Netmask": "Masque",
    "Broadcast": "Broadcast",
    "First usable IP": "Première IP utile",
    "Last usable IP": "Dernière IP utile",
    "Capacity": "Capacité",
    "IP addresses": "Adresses IP",
    "New IP": "Nouvelle IP",
    "Search": "Recherche",
    "IP, hostname, label, MAC…": "IP, hôte, libellé, MAC…",
    "Status": "Statut",
    "Health": "Santé",
    "OK": "OK",
    "Warning": "Vieillissant",
    "Down": "Down",
    "Stale": "Obsolète",
    "Never checked": "Jamais vérifié",
    "No target": "Sans cible",
    "Show free IPs": "Afficher les IP libres",
    "Address": "Adresse",
    "Hostname": "Nom d'hôte",
    "Device": "Appareil",
    "MAC": "MAC",
    "Targets": "Cibles",
    "Last check": "Dernier check",
    "No address matches these filters.": "Aucune adresse ne correspond à ces filtres.",
    "No address recorded in this VLAN yet.": "Aucune adresse enregistrée dans ce VLAN pour l'instant.",
    "Loading…": "Chargement…",
    # --- plan ---
    "Plan": "Plan",
    "usable addresses": "adresses utilisables",
    "recorded": "enregistrées",
    "Back to VLAN": "Retour au VLAN",
    "Large subnet: only the first %(max)d addresses are shown.": "Grand subnet : seules les %(max)d premières adresses sont affichées.",
    "free (not recorded)": "libre (non enregistrée)",
    # --- ip detail / row ---
    "Show details": "Afficher le détail",
    "Check all targets of this IP now": "Vérifier toutes les cibles de cette IP maintenant",
    "Delete address %(address)s and its monitor targets?": "Supprimer l'adresse %(address)s et ses cibles de suivi ?",
    "Delete": "Supprimer",
    "Created": "Créée le",
    "Monitor targets": "Cibles de suivi",
    "Add target": "Ajouter une cible",
    "Check": "Vérifier",
    "Label": "Libellé",
    "Interval": "Intervalle",
    "Last success": "Dernier succès",
    "Latency": "Latence",
    "Failures": "Échecs",
    "No monitor target. Add a TCP port check or an ICMP ping to track this address.": "Aucune cible de suivi. Ajoutez un check de port TCP ou un ping ICMP pour suivre cette adresse.",
    "disabled": "désactivée",
    "unknown": "inconnu",
    "Delete this monitor target?": "Supprimer cette cible de suivi ?",
    # --- forms ---
    "Edit address %(address)s": "Modifier l'adresse %(address)s",
    "New IP in %(name)s": "Nouvelle IP dans %(name)s",
    "MAC address": "Adresse MAC",
    "Device label": "Libellé d'appareil",
    "e.g. NAS, printer, hypervisor…": "ex. NAS, imprimante, hyperviseur…",
    "Save": "Enregistrer",
    "Description": "Description",
    "Notes": "Notes",
    "Edit monitor target": "Modifier la cible de suivi",
    "New monitor target on %(address)s": "Nouvelle cible de suivi sur %(address)s",
    "A TCP port check, or an ICMP ping if no port is relevant.": "Un check de port TCP, ou un ping ICMP si aucun port n'est pertinent.",
    "Protocol": "Protocole",
    "Port": "Port",
    "e.g. HTTPS admin UI": "ex. interface d'admin HTTPS",
    "Interval (seconds)": "Intervalle (secondes)",
    "Enabled": "Activée",
    "Network settings": "Paramètres du réseau",
    "This instance manages a single network. Root prefixes are informative only.": "Cette instance gère un seul réseau. Les préfixes racine sont purement informatifs.",
    "Root prefixes (one per line, informative)": "Préfixes racine (un par ligne, informatif)",
    "Default language": "Langue par défaut",
    "Edit VLAN": "Modifier le VLAN",
    "A VLAN is a named subnet. The 802.1Q tag is optional.": "Un VLAN est un subnet nommé. Le tag 802.1Q est facultatif.",
    "VLAN tag (1–4094, optional)": "Tag VLAN (1–4094, facultatif)",
    "Gateway (optional)": "Passerelle (facultative)",
    "Delete VLAN “%(name)s” and all its addresses and targets?": "Supprimer le VLAN « %(name)s » et toutes ses adresses et cibles ?",
    # --- users screen ---
    "New user": "Nouvel utilisateur",
    "Role": "Rôle",
    "Active": "Actif",
    "Last login": "Dernière connexion",
    "“manager” = read/write. “user” = read-only. The last active manager can be neither demoted nor deleted.": "« manager » = lecture/écriture. « user » = lecture seule. Le dernier manager actif ne peut être ni rétrogradé ni supprimé.",
    "Edit user “%(name)s”": "Modifier l'utilisateur « %(name)s »",
    "Password (8 characters minimum)": "Mot de passe (8 caractères minimum)",
    "user (read-only)": "user (lecture seule)",
    "manager (read/write)": "manager (lecture/écriture)",
    "Create": "Créer",
    "Active account": "Compte actif",
    "Reset password (8 characters minimum)": "Réinitialiser le mot de passe (8 caractères minimum)",
    "Reset password": "Réinitialiser le mot de passe",
    "you": "vous",
    "Delete user “%(name)s”? Their audit entries are kept.": "Supprimer l'utilisateur « %(name)s » ? Ses entrées d'audit sont conservées.",
    # --- audit ---
    "User": "Utilisateur",
    "Action": "Action",
    "All": "Toutes",
    "Entity": "Entité",
    "When": "Quand",
    "Who": "Qui",
    "Changes": "Modifications",
    "Previous": "Précédente",
    "Page %(page)d": "Page %(page)d",
    "Next": "Suivante",
    "field(s)": "champ(s)",
    "No audit entries.": "Aucune entrée d'audit.",
    # --- légende santé ---
    "Health color legend": "Légende du code couleur santé",
    "Up, recent success": "Up, succès récent",
    "Up but aging, or down recently": "Up mais vieillissant, ou down récemment",
    "Down for a while": "Down depuis un moment",
    "Down for a long time: dead service or stale entry to clean up": "Down depuis longtemps : service mort ou entrée obsolète à nettoyer",
    "No monitor target": "Aucune cible de suivi",
    "An IP shows the worst color of its active targets.": "Une IP affiche la pire couleur de ses cibles actives.",
    # --- templating (labels santé non extraits automatiquement) ---
    "Down for a long time (stale?)": "Down depuis longtemps (obsolète ?)",
}

EXTRA_MSGIDS = ["Down for a long time (stale?)"]


def main() -> None:
    pot_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("messages.pot")
    out_path = Path("app/locale/fr/LC_MESSAGES/messages.po")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with pot_path.open() as f:
        catalog = read_po(f)
    catalog.locale = "fr"
    catalog.project = "GuiPAM"
    catalog.fuzzy = False  # sinon pybabel compile ignore le catalogue

    missing = []
    for message in catalog:
        if not message.id:
            continue
        translation = FR.get(message.id)
        if translation is None:
            missing.append(message.id)
        else:
            message.string = translation
    for msgid in EXTRA_MSGIDS:
        if msgid not in catalog:
            catalog.add(msgid, FR[msgid])

    with out_path.open("wb") as f:
        write_po(f, catalog, width=0, sort_output=True)

    if missing:
        print("TRADUCTIONS MANQUANTES :")
        for msgid in missing:
            print(" -", msgid)
        sys.exit(1)
    print(f"OK : {out_path} ({len(FR)} traductions)")


if __name__ == "__main__":
    main()
