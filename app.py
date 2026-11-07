import os
import tempfile
import re
from flask import Flask, render_template, request, redirect, url_for
import pdfplumber

app = Flask(__name__)

ERREUR = "Format PDF incorrect ou non conforme au relevé MVola."

class FormatIncorrect(Exception):
    pass

def trouver_entetes(words):
    pos = {}
    for w in words:
        t = w["text"].upper()
        if t == "DESTINATAIRE":
            pos["init_x1"] = w["x1"]
        elif t == "DESCRIPTION":
            pos["desc_x0"], pos["desc_x1"] = w["x0"], w["x1"]
        elif t == "MONTANT":
            pos["montant_x0"] = w["x0"]
    if not {"init_x1", "desc_x0", "desc_x1", "montant_x0"} <= pos.keys():
        raise FormatIncorrect
    return pos

def lire_montants_transfert(page, pos):
    words = page.extract_words(keep_blank_chars=False)
    resultats = []
    for w in words:
        if not (pos["init_x1"] < w["x0"] < pos["desc_x0"]):
            continue
        if w["text"] != "Transfert":
            continue
        ligne = [
            m for m in words
            if abs(m["top"] - w["top"]) < 3 and m["x0"] >= pos["desc_x1"]
        ]
        ligne.sort(key=lambda m: m["x0"])
        brut = "".join(m["text"] for m in ligne)
        mt = re.fullmatch(r"([+-])(\d+)", brut)
        if not mt:
            raise FormatIncorrect
        valeur = int(mt.group(2))
        resultats.append(-valeur if mt.group(1) == "-" else valeur)
    return resultats

def traiter_pdf(chemin):
    try:
        with pdfplumber.open(chemin) as pdf:
            if not pdf.pages:
                raise FormatIncorrect
            texte = "\n".join((p.extract_text() or "") for p in pdf.pages)

            if "RELEVE DE TRANSACTIONS MVOLA" not in texte.upper():
                raise FormatIncorrect

            compte = re.search(r"COMPTE\s*:\s*(\d+)", texte)
            periode = re.search(
                r"PERIODE\s*:\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})", texte)
            initial = re.search(r"SOLDE INITIAL\s*:\s*([\d ]+?)\s*Ar", texte)
            final = re.search(r"SOLDE FINAL\s*:\s*([\d ]+?)\s*Ar", texte)
            if not (compte and periode and initial and final):
                raise FormatIncorrect

            montants = []
            for page in pdf.pages:
                words = page.extract_words()
                try:
                    pos = trouver_entetes(words)
                except FormatIncorrect:
                    continue
                montants += lire_montants_transfert(page, pos)
                
        return {
            "succes": True,
            "compte": compte.group(1),
            "periode": f"{periode.group(1)} au {periode.group(2)}",
            "initial": initial.group(1).strip(),
            "final": final.group(1).strip(),
            "montants": montants,
            "total": sum(montants)
        }
    except Exception:
        return {"succes": False, "erreur": ERREUR}

@app.route("/", methods=["GET", "POST"])
def index():
    resultat = None
    if request.method == "POST":
        if "pdf_file" not in request.files:
            return redirect(request.url)
        fichier = request.files["pdf_file"]
        if fichier.filename == "":
            return redirect(request.url)
        if fichier:
            # Enregistrement temporaire du fichier uploadé
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                fichier.save(tmp.name)
                tmp_path = tmp.name
            try:
                resultat = traiter_pdf(tmp_path)
            finally:
                os.unlink(tmp_path)
    return render_template("index.html", resultat=resultat)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)