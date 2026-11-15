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
    "Hardware": "Matériel",
    "e.g. Dell R730, Zyxel GS1200…": "ex. Dell R730, Zyxel GS1200…",
    "Location": "Lieu",
    "e.g. server room, office 2…": "ex. salle serveur, bureau 2…",
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
    # --- API, comptes de service, clés ---
    "Missing, invalid, expired or revoked API key.": "Clé d'API absente, invalide, expirée ou révoquée.",
    "This API key is read-only: action not allowed.": "Cette clé d'API est en lecture seule : action non autorisée.",
    "No free address left in subnet %s.": "Plus aucune adresse libre dans le subnet %s.",
    "An allocated address cannot have the status “libre”.": "Une adresse allouée ne peut pas avoir le statut « libre ».",
    "Could not allocate an address (concurrent updates). Try again.": "Impossible d'allouer une adresse (modifications concurrentes). Réessayez.",
    "Service account not found.": "Compte de service introuvable.",
    "A service account named “%s” already exists.": "Un compte de service nommé « %s » existe déjà.",
    "Service account “%s” created. Add a key to use it.": "Compte de service « %s » créé. Ajoutez-lui une clé pour l'utiliser.",
    "Service account “%s” updated.": "Compte de service « %s » mis à jour.",
    "Service account “%s” deleted (its keys no longer work).": "Compte de service « %s » supprimé (ses clés ne fonctionnent plus).",
    "A read/write key requires a service account with the manager role.": "Une clé en lecture-écriture nécessite un compte de service au rôle manager.",
    "Invalid expiry date.": "Date d'expiration invalide.",
    "The expiry date must be in the future.": "La date d'expiration doit être dans le futur.",
    "API key not found.": "Clé d'API introuvable.",
    "Key “%s” revoked.": "Clé « %s » révoquée.",
    "API": "API",
    "Service accounts": "Comptes de service",
    "New service account": "Nouveau compte de service",
    "Service accounts let scripts, playbooks and AI agents use GuiPAM through its JSON API, with an access key.": "Les comptes de service permettent à des scripts, des playbooks et des agents IA d'utiliser GuiPAM via son API JSON, avec une clé d'accès.",
    "API documentation": "Documentation de l'API",
    "OpenAPI specification": "Spécification OpenAPI",
    "read-only": "lecture seule",
    "read/write": "lecture-écriture",
    "disabled": "désactivé",
    "New key": "Nouvelle clé",
    "Delete service account “%(name)s”? All its keys stop working immediately. Audit entries are kept.": "Supprimer le compte de service « %(name)s » ? Toutes ses clés cessent de fonctionner immédiatement. Les entrées d'audit sont conservées.",
    "Key": "Clé",
    "Identifier": "Identifiant",
    "Access": "Accès",
    "State": "État",
    "Expires": "Expire",
    "Last used": "Dernière utilisation",
    "The account no longer has the manager role: this key can only read.": "Le compte n'a plus le rôle manager : cette clé ne peut que lire.",
    "active": "active",
    "expired": "expirée",
    "revoked": "révoquée",
    "Revoke key “%(name)s”? Tools using it lose access immediately. This cannot be undone.": "Révoquer la clé « %(name)s » ? Les outils qui l'utilisent perdent l'accès immédiatement. Action irréversible.",
    "Revoke": "Révoquer",
    "No key yet: this account cannot connect.": "Aucune clé : ce compte ne peut pas se connecter.",
    "No service account yet. Create one, then give it a key.": "Aucun compte de service. Créez-en un, puis donnez-lui une clé.",
    "Least privilege: keys are read-only by default. A read/write key requires an account with the manager role. Every API action is recorded in the audit log with the account and the key used.": "Moindre privilège : les clés sont en lecture seule par défaut. Une clé en lecture-écriture nécessite un compte au rôle manager. Chaque action faite via l'API est tracée dans le journal d'audit avec le compte et la clé utilisés.",
    "Key “%(name)s” created": "Clé « %(name)s » créée",
    "Copy it now: it will never be shown again.": "Copiez-la maintenant : elle ne sera plus jamais affichée.",
    "Copy": "Copier",
    "Copied": "Copié",
    "Quick test:": "Test rapide :",
    "Done, I saved it": "C'est fait, je l'ai enregistrée",
    "New key for “%(name)s”": "Nouvelle clé pour « %(name)s »",
    "Key name": "Nom de la clé",
    "e.g. the tool or host using it": "ex. l'outil ou la machine qui l'utilise",
    "This account is read-only: give it the manager role to create read/write keys.": "Ce compte est en lecture seule : donnez-lui le rôle manager pour créer des clés en lecture-écriture.",
    "Expiry date (optional)": "Date d'expiration (facultative)",
    "Leave empty for a key that never expires.": "Laissez vide pour une clé qui n'expire jamais.",
    "Create key": "Créer la clé",
    "Done through the API with key “%(key)s”": "Fait via l'API avec la clé « %(key)s »",
    "Edit service account “%(name)s”": "Modifier le compte de service « %(name)s »",
    "Only a manager account can hold read/write keys.": "Seul un compte manager peut porter des clés en lecture-écriture.",
    # --- sauvegarde complète ---
    "This file is not a GuiPAM backup.": "Ce fichier n'est pas une sauvegarde GuiPAM.",
    "This backup was made by a newer GuiPAM (format %(found)d, this version reads up to %(max)d). Update GuiPAM first.": "Cette sauvegarde vient d'un GuiPAM plus récent (format %(found)d, cette version lit jusqu'au format %(max)d). Mettez d'abord GuiPAM à jour.",
    "This backup contains no active manager account: restoring it would lock you out.": "Cette sauvegarde ne contient aucun compte manager actif : la restaurer vous enfermerait dehors.",
    "The backup could not be restored (nothing was changed): %s": "La sauvegarde n'a pas pu être restaurée (rien n'a été modifié) : %s",
    "File is too large.": "Fichier trop volumineux.",
    "Full backup": "Sauvegarde complète",
    "Everything in one JSON file: network, VLANs, addresses, monitor targets, users, service accounts and audit log. This is the guaranteed way to move your data to another instance or across a major version.": "Tout dans un seul fichier JSON : réseau, VLAN, adresses, cibles de suivi, utilisateurs, comptes de service et journal d'audit. C'est le moyen garanti de déplacer vos données vers une autre instance ou de franchir une version majeure.",
    "Download a full backup": "Télécharger une sauvegarde complète",
    "Keep this file private: it contains password and API key fingerprints.": "Gardez ce fichier privé : il contient les empreintes des mots de passe et des clés d'API.",
    "Restore this backup? ALL current data (VLANs, addresses, users, keys, audit log) will be replaced by the content of the file. You will have to log in again.": "Restaurer cette sauvegarde ? TOUTES les données actuelles (VLAN, adresses, utilisateurs, clés, journal d'audit) seront remplacées par le contenu du fichier. Vous devrez vous reconnecter.",
    "Restore a backup": "Restaurer une sauvegarde",
    "GuiPAM also keeps automatic snapshots of its database in the “backups” folder of the data volume: one before every schema migration, and one per day.": "GuiPAM conserve aussi des instantanés automatiques de sa base dans le dossier « backups » du volume de données : un avant chaque migration de schéma, et un par jour.",
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
