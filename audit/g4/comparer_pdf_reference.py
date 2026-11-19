#!/usr/bin/env python3
"""G4-4 — compare the position of the page-1 labels of a generated invoice with the REAL reference invoice (pdftotext -bbox, host tool, read-only).
Usage: comparer_pdf_reference.py <reference.pdf> <generated.pdf>      (both rendered with the same data; prints dx/dy in points per label)"""
import re, subprocess, sys

KEYS = ["FACTURE", "Date", "Facture", "PO:", "Huddl", "Adresse", "Claudia", "DESCRIPTION", "JOUR", "COUT", "MONTANT", "SOUS-TOTAL", "TAUX", "TVA", "AUTRES", "TOTAL",
        "Je", "Paiement", "Titulaire:", "IBAN:", "BIC:", "registre"]


def words(pdf):
    html = subprocess.run(["pdftotext", "-f", "1", "-l", "1", "-bbox", pdf, "-"], capture_output=True, text=True, check=True).stdout
    return [(m.group(5), float(m.group(1)), float(m.group(2))) for m in re.finditer(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>', html)]


ref, new = words(sys.argv[1]), words(sys.argv[2])
worst = 0.0
for k in KEYS:
    a = next((w for w in ref if w[0] == k), None); b = next((w for w in new if w[0] == k), None)
    if a and b:
        dx, dy = b[1] - a[1], b[2] - a[2]; worst = max(worst, abs(dx), abs(dy)); print(f"{k:12} ref=({a[1]:7.1f},{a[2]:6.1f}) app=({b[1]:7.1f},{b[2]:6.1f}) dx={dx:5.1f} dy={dy:5.1f}")
    else: print(f"{k:12} manquant ({'ref' if not a else 'app'})")
print(f"écart maximal : {worst:.1f} pt")
