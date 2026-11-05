"""BQR4: the four billing addresses of the client EGG (FR, BE, CH, MEA), as the owner wrote them in the comment of the annotated draft PDF
(26.10.2026), split into the separate fields of the QR-bill ONLY where the split is unambiguous. Nothing here is ever stored by itself: the mandate screen
shows these values as a proposal marked « à confirmer », and they are saved only when the owner presses « Enregistrer » (and they count for the QR-bill only
once « adresse vérifiée » is ticked).

`lines` are the printed lines of the address (the key to recognise it in a mandate's free-text address); `fields` is the split, or None when the text does not
allow one without guessing (EGG MEA: no postal code, no street number: left empty on purpose).
"""
PRESETS = (
    {"label": "EGG FR", "lines": ("55 avenue Victor Hugo", "75116 Paris"),
     "fields": {"client_street": "avenue Victor Hugo", "client_house_num": "55", "client_pcode": "75116", "client_city": "Paris", "client_country": "FR"}},
    {"label": "EGG BE", "lines": ("Avenue du Bourgmestre", "Etienne Demunter 5, boîte 10", "1090 JETTE"),
     # the street name runs over two lines of the text; « 5, boîte 10 » is kept whole in the number field
     "fields": {"client_street": "Avenue du Bourgmestre Etienne Demunter", "client_house_num": "5, boîte 10", "client_pcode": "1090", "client_city": "JETTE", "client_country": "BE"}},
    {"label": "EGG CH", "lines": ("Route de Saint Julien 63", "1212 Lancy"),
     "fields": {"client_street": "Route de Saint Julien", "client_house_num": "63", "client_pcode": "1212", "client_city": "Lancy", "client_country": "CH"}},
    {"label": "EGG MEA", "lines": ("Office 28 - Floor 23", "The One Tower - TECOM", "Dubai"), "fields": None},
)


def _norm(s):
    return " ".join(str(s or "").casefold().split())


def match_text(billing_address):
    """The preset whose printed lines all appear in the free-text address of the mandate, or None (also None when several match: ambiguous)."""
    have = {_norm(l) for l in str(billing_address or "").splitlines() if l.strip()}
    hits = [p for p in PRESETS if all(_norm(l) in have for l in p["lines"])]
    return hits[0] if len(hits) == 1 else None
