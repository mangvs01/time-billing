"""BILL-RC48-FIX (G): what the user reads when the DATABASE itself refuses a write (a trigger, a constraint). The SQL guards raise short English sentences (they are written for the
logs and for tests); an English or technical text must never reach the screen, so the two screens that used to print `str(e)` (restoring a JSON backup, creating a credit note) go
through `french(e)`. The mapping is by the exact text of the guard: an unknown text is NOT shown, the generic sentence is (the detail stays in the service log, written by the caller)."""
import sqlite3

GUARDS = {
    "The credits of an invoice line cannot exceed its amount": "le total des avoirs d'une ligne de facture dépasse le montant de cette ligne",
    "The operations of a credit note cannot exceed its amount": "les remboursements et imputations d'une note de crédit dépassent son montant",
    "The line totals of a credit note must equal the sum of its credited lines": "les totaux des lignes d'une note de crédit ne correspondent pas à la somme de ses lignes",
    "A credited line belongs to the invoice of the credit note": "une ligne créditée doit appartenir à la facture de la note de crédit",
    "A credited line keeps the VAT regime of the invoice line": "une ligne créditée garde le régime de TVA de la ligne de facture",
    "Lines of an issued invoice are immutable": "les lignes d'une facture émise ne peuvent plus être modifiées",
    "Lines of an issued invoice cannot be deleted": "les lignes d'une facture émise ne peuvent pas être supprimées",
    "Lines of an issued credit note are immutable": "les lignes d'une note de crédit émise ne peuvent plus être modifiées",
    "Lines of an issued credit note cannot be deleted": "les lignes d'une note de crédit émise ne peuvent pas être supprimées",
    "Issued invoices are immutable": "une facture émise ne peut plus être modifiée",
    "Issued invoices cannot be deleted": "une facture émise ne peut pas être supprimée",
    "Issued credit notes are immutable": "une note de crédit émise ne peut plus être modifiée",
    "Issued credit notes cannot be deleted": "une note de crédit émise ne peut pas être supprimée",
    "Frozen invoice snapshots are immutable": "la copie figée d'une facture ne peut pas être modifiée",
    "Frozen invoice snapshots cannot be deleted": "la copie figée d'une facture ne peut pas être supprimée",
    "Frozen credit notes are immutable": "la copie figée d'une note de crédit ne peut pas être modifiée",
    "Frozen credit notes cannot be deleted": "la copie figée d'une note de crédit ne peut pas être supprimée",
    "Frozen invoice annex is immutable": "l'annexe figée d'une facture ne peut pas être modifiée",
    "Frozen invoice annex cannot be deleted": "l'annexe figée d'une facture ne peut pas être supprimée",
    "The audit log is append-only": "le journal d'audit ne peut qu'être complété",
    "Credit operations are append-only": "les opérations d'une note de crédit ne peuvent qu'être ajoutées",
    "Credit note cancellations are immutable": "l'annulation d'une note de crédit ne peut pas être modifiée",
    "Invoice number history is append-only": "l'historique des numéros de facture ne peut qu'être complété",
    "Invoice date history is append-only": "l'historique des dates de facture ne peut qu'être complété",
    "Time entry history is append-only": "l'historique des saisies de temps ne peut qu'être complété",
    "Variance decisions are append-only": "les décisions sur les écarts ne peuvent qu'être ajoutées",
    "Invoice number already used by a historical invoice": "ce numéro de facture est déjà utilisé par une facture historique",
    "An issued invoice needs a number": "une facture émise doit avoir un numéro",
    "An issued invoice needs its real issuance timestamp": "une facture émise doit porter sa date et heure d'émission réelles",
    "The date of an issued invoice cannot change": "la date d'une facture émise ne peut pas changer",
    "Credit notes require an issued invoice": "une note de crédit ne peut porter que sur une facture émise",
    "Credit treatment required before issuance": "le traitement du crédit (remboursement, imputation…) doit être choisi avant l'émission",
    "Only an issued credit note can be cancelled": "seule une note de crédit émise peut être annulée",
    "Cancelled credit note": "cette note de crédit est annulée",
    "A credit note decision needs an issued credit note of the same invoice": "la décision doit désigner une note de crédit émise de la même facture",
    "A historical invoice keeps the values read from its source; only its status can change": "une facture historique garde les valeurs lues dans sa source ; seul son statut peut changer",
    "A reversal must cancel one operation of the same note, kind and amount": "une contre-passation doit annuler une opération de la même note, du même type et du même montant",
    "A variance decision concerns an issued invoice": "une décision sur un écart concerne une facture émise",
    "An entry id that ever existed is never given again": "le numéro d'une saisie qui a existé n'est jamais réattribué",
    "Historical invoices are never deleted (reject them instead)": "une facture historique ne se supprime pas (la refuser à la place)",
    "Operation kind does not match the credit treatment": "le type d'opération ne correspond pas au traitement choisi pour la note de crédit",
    "Operations require an issued credit note": "les remboursements et imputations exigent une note de crédit émise",
    "Unknown credit treatment": "traitement de la note de crédit inconnu",
    "issued_at is set only when the invoice is issued": "la date d'émission n'est renseignée qu'à l'émission de la facture",
}
GENERIC = "la base de données a refusé cette écriture (le détail technique est dans le journal du service)"


def french(e):
    """French sentence (no capital, no final full stop, to be inserted after « : ») for a database error `e`: a guard of GUARDS, a duplicate, else GENERIC. Never the raw text."""
    msg = str(e)
    for en, fr in GUARDS.items():
        if en in msg: return fr
    if "UNIQUE constraint failed" in msg:
        if "billing_addresses" in msg: return "deux adresses d'un même client portent le même nom (aux majuscules et minuscules près)"
        return "un élément identique existe déjà (doublon refusé par la base)"
    if "FOREIGN KEY constraint failed" in msg: return "un élément fait référence à une donnée absente"
    if "CHECK constraint failed" in msg or "NOT NULL constraint failed" in msg: return "une valeur est absente ou hors limites"
    if "database is locked" in msg: return "la base est occupée, réessayer dans un instant"
    return GENERIC


def is_database_error(e):
    return isinstance(e, sqlite3.DatabaseError)
