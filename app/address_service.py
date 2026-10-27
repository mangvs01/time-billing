"""Reusable billing addresses (rc37, P2): the table, the choice of an invoice's address, the instantané copied into the draft.

Decision D4: addresses are grouped by the client's LEGAL identity (projects.client_legal_id, normalised by rules.legal_key), with the short client name as
fallback key; there is no `clients` table. Decision D8: a draft keeps reading the mandate's address until an explicit choice is saved; the choice COPIES the
address text into the invoice (bill_label / bill_contact / bill_address), so the invoice never moves when the address of the client is edited afterwards; an
explicit « actualiser » re-copies it. An issued invoice only ever reads its snapshot (nothing here changes it).
"""
import re

from app import billing_rules as rules

DDL = """CREATE TABLE IF NOT EXISTS billing_addresses(id INTEGER PRIMARY KEY AUTOINCREMENT, client_key TEXT NOT NULL CHECK(length(client_key)>0),
  label TEXT NOT NULL CHECK(length(trim(label))>0), contact TEXT NOT NULL DEFAULT '', address TEXT NOT NULL CHECK(length(trim(address))>0),
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), sort_order INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT, UNIQUE(client_key,label))"""
MAX_LABEL = 60; MAX_CONTACT = 120; MAX_LINES = 6; MAX_LINE = 80
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁠﻿]")


def client_key(project):
    """Grouping key of a mandate's client: its normalised legal identifier, else its normalised short name (prefixed so the two never collide)."""
    legal = rules.legal_key(project["client_legal_id"] if "client_legal_id" in project.keys() else "")
    if legal: return legal
    name = " ".join(((project["client"] if "client" in project.keys() else "") or "").casefold().split())
    return "NOM:" + name if name else ""


def clean_text(value, label, maxlen):
    v = _CTRL.sub("", (value or "").replace("\r\n", "\n").replace("\r", "\n")).strip()
    if len(v) > maxlen: raise ValueError(f"{label} trop long ({maxlen} caractères au maximum)")
    return v


def validate(label, contact, address):
    """(label, contact, address) cleaned, or ValueError. The printed block is `contact` then `address`, one line per line, in a column 164 pt wide."""
    label = " ".join(clean_text(label, "libellé", MAX_LABEL).split())
    contact = " ".join(clean_text(contact, "destinataire", MAX_CONTACT).split())
    lines = [" ".join(l.split()) for l in clean_text(address, "adresse", MAX_LINES * MAX_LINE).split("\n") if l.strip()]
    if not label: raise ValueError("libellé obligatoire")
    if not lines: raise ValueError("adresse obligatoire")
    if len(lines) + bool(contact) > MAX_LINES: raise ValueError(f"adresse trop longue : {MAX_LINES} lignes imprimées au maximum (destinataire compris)")
    if any(len(l) > MAX_LINE for l in lines): raise ValueError(f"une ligne de l'adresse dépasse {MAX_LINE} caractères")
    return label, contact, "\n".join(lines)


def from_lines(lines):
    """Seed form: the first printed line is the addressee (billing_contact), the others the address."""
    lines = [l for l in lines if l.strip()]
    return lines[0], "\n".join(lines[1:])


GLOBAL_KEY = "*"     # rc40 (owner's annotated PDF, 27.10.2026): « créer une liste déroulante avec les clients suivants : EGG FR / BE / CH / MEA » = one list offered on EVERY mandate


def listing(c, key, include_inactive=False):
    """The addresses offered to a mandate of client `key`: its own, plus the global list (client_key '*'), whatever the mandate's client (even none)."""
    return [dict(r) for r in c.execute("SELECT * FROM billing_addresses WHERE client_key IN (?, ?)" + ("" if include_inactive else " AND active=1") + " ORDER BY (client_key=?) DESC, sort_order,label,id", (key or "", GLOBAL_KEY, GLOBAL_KEY))]


def make_global(c):
    """Idempotent: the four addresses seeded for the first client (rc37) become the global list. Only exact seeded labels, never anything else."""
    c.execute("UPDATE billing_addresses SET client_key=? WHERE client_key='NOM:bsci' AND label IN ('EGG FR','EGG BE','EGG CH','EGG MEA') AND NOT EXISTS (SELECT 1 FROM billing_addresses g WHERE g.client_key=? AND g.label=billing_addresses.label)", (GLOBAL_KEY, GLOBAL_KEY))


def get(c, aid):
    r = c.execute("SELECT * FROM billing_addresses WHERE id=?", (aid,)).fetchone()
    return dict(r) if r else None


def choose(c, invoice, project, choice):
    """Fields of the invoice row for the address `choice` ('' = the mandate's own address again; else an id of billing_addresses of this client). ValueError when refused."""
    if choice in (None, ""): return {"billing_address_id": None, "bill_label": None, "bill_contact": None, "bill_address": None}
    if not str(choice).isdigit(): raise ValueError("adresse de facturation inconnue")
    a = get(c, int(choice))
    if not a or a["client_key"] not in (client_key(project), GLOBAL_KEY): raise ValueError("cette adresse n'appartient pas au client de ce mandat")
    if not a["active"] and int(choice) != (invoice["billing_address_id"] if "billing_address_id" in invoice.keys() else None):
        raise ValueError("cette adresse est désactivée")        # a draft may keep a deactivated address it already carries, never take one
    return {"billing_address_id": a["id"], "bill_label": a["label"], "bill_contact": a["contact"], "bill_address": a["address"]}


def effective(invoice, project):
    """What the invoice prints: (label, contact, address, source) — the copy chosen on the invoice, else the mandate's own address (drafts and invoices created before rc37)."""
    keys = invoice.keys()
    if "billing_address_id" in keys and invoice["billing_address_id"] is not None and (invoice["bill_address"] or "").strip():
        return invoice["bill_label"] or "", invoice["bill_contact"] or "", invoice["bill_address"], "choix"
    return "", project["billing_contact"] or "", project["billing_address"] or "", "mandat"
