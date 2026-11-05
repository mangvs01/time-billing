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
_CTRL_MORE = re.compile("[\\x80-\\x84\\x86-\\x9f\\u00ad\\u061c\\u2066-\\u2069]")       # review rc40: C1 controls, soft hyphen, Arabic letter mark and direction isolates (the class above stops at the embeddings / overrides)


# BQR5: structured form of each address of the list (the five fields of the QR-bill + « vérifiée »), additive columns of billing_addresses. Copied into the invoice with the text.
STRUCT_FIELDS = ("street", "house_num", "pcode", "city", "country")
STRUCT_COLS = tuple("addr_" + f for f in STRUCT_FIELDS)        # billing_addresses.addr_street … addr_country ; addr_verified is the 6th
INVOICE_COLS = {"addr_street": "bill_street", "addr_house_num": "bill_house_num", "addr_pcode": "bill_pcode", "addr_city": "bill_city", "addr_country": "bill_country", "addr_verified": "bill_addr_verified"}


def migrate(c):
    """BQR5, idempotent and additive: the six structured columns of billing_addresses, then the EGG FR/BE/CH split of app/address_presets.py for the global addresses that carry
    none yet (EGG MEA: the text gives neither postal code nor number, left empty on purpose). Filled addresses are NEVER overwritten and nothing is marked « vérifiée »: the owner confirms."""
    have = {r[1] for r in c.execute("PRAGMA table_info(billing_addresses)")}
    for col in STRUCT_COLS:
        if col not in have: c.execute(f"ALTER TABLE billing_addresses ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
    if "addr_verified" not in have: c.execute("ALTER TABLE billing_addresses ADD COLUMN addr_verified INTEGER NOT NULL DEFAULT 0")
    from app import address_presets
    for pr in address_presets.PRESETS:
        f = pr["fields"]
        if not f: continue
        want = {" ".join(l.casefold().split()) for l in pr["lines"]}
        for r in c.execute("SELECT id,address FROM billing_addresses WHERE label=? AND addr_verified=0 AND addr_street='' AND addr_house_num='' AND addr_pcode='' AND addr_city='' AND addr_country=''", (pr["label"],)).fetchall():
            if want <= {" ".join(l.casefold().split()) for l in (r[1] or "").splitlines()}:      # only when the stored text is the owner's text of that address
                c.execute("UPDATE billing_addresses SET addr_street=?,addr_house_num=?,addr_pcode=?,addr_city=?,addr_country=? WHERE id=?",
                          (f["client_street"], f["client_house_num"], f["client_pcode"], f["client_city"], f["client_country"], r[0]))


def unmigrate(c):
    """Rollback of migrate (SQLite >= 3.35 DROP COLUMN): the structured data of the list is lost, the texts stay."""
    have = {r[1] for r in c.execute("PRAGMA table_info(billing_addresses)")}
    for col in (*STRUCT_COLS, "addr_verified"):
        if col in have: c.execute(f"ALTER TABLE billing_addresses DROP COLUMN {col}")


def clean_struct(form):
    """(street, house_num, pcode, city, country, verified) of a form, normalised, or ValueError naming the faulty field (the rules of the QR-bill module). Empty = not structured."""
    from app import qr_bill
    v = [" ".join(clean_text(form.get(k), k, 200).split()) for k in ("addr_street", "addr_house_num", "addr_pcode", "addr_city", "addr_country")]
    v[4] = v[4].upper()
    if any(v):
        bad = qr_bill.address_problems(*v, who="Adresse structurée")
        if bad: raise ValueError(" ".join(bad))
    return (*v, 1 if form.get("addr_verified") == "1" and any(v) else 0)


def client_key(project):
    """Grouping key of a mandate's client: its normalised legal identifier, else its normalised short name (prefixed so the two never collide)."""
    legal = rules.legal_key(project["client_legal_id"] if "client_legal_id" in project.keys() else "")
    if legal: return legal
    name = " ".join(((project["client"] if "client" in project.keys() else "") or "").casefold().split())
    return "NOM:" + name if name else ""


def clean_text(value, label, maxlen):
    v = _CTRL_MORE.sub("", _CTRL.sub("", (value or "").replace("\r\n", "\n").replace("\r", "\n"))).strip()
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
    if choice in (None, ""): return {"billing_address_id": None, "bill_label": None, "bill_contact": None, "bill_address": None, **{c: None for c in INVOICE_COLS.values()}}
    if not str(choice).isdigit(): raise ValueError("adresse de facturation inconnue")
    a = get(c, int(choice))
    if not a or a["client_key"] not in (client_key(project), GLOBAL_KEY): raise ValueError("cette adresse n'appartient pas au client de ce mandat")
    if not a["active"] and int(choice) != (invoice["billing_address_id"] if "billing_address_id" in invoice.keys() else None):
        raise ValueError("cette adresse est désactivée")        # a draft may keep a deactivated address it already carries, never take one
    return {"billing_address_id": a["id"], "bill_label": a["label"], "bill_contact": a["contact"], "bill_address": a["address"],
            **{INVOICE_COLS[k]: (a.get(k) if k != "addr_verified" else int(a.get(k) or 0)) for k in INVOICE_COLS}}      # BQR5: the structured copy follows the text


def effective(invoice, project):
    """What the invoice prints: (label, contact, address, source) — the copy chosen on the invoice, else the mandate's own address (drafts and invoices created before rc37)."""
    keys = invoice.keys()
    if "billing_address_id" in keys and invoice["billing_address_id"] is not None and (invoice["bill_address"] or "").strip():
        return invoice["bill_label"] or "", invoice["bill_contact"] or "", invoice["bill_address"], "choix"
    return "", project["billing_contact"] or "", project["billing_address"] or "", "mandat"
