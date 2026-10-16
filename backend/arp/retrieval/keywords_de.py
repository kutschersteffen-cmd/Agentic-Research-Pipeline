"""German search terms for English seed keywords, so a German report's passages are found.

BM25 matches words, and a field's seed keywords are English: on a German annual report ("Geschäftsbericht")
or sustainability report they hit nothing, and with hybrid retrieval off a low-risk field then finds no
evidence at all. Expanding at search time covers every field (presets and user-built schemas) without
changing a field's definition, so nothing is re-versioned or re-extracted.

Keys are matched as whole words inside a keyword (case-insensitive); every matching key adds its terms."""

from __future__ import annotations

import re

GLOSSARY: dict[str, list[str]] = {
    # emissions and targets
    "emission": ["Emissionen", "THG-Emissionen", "Treibhausgasemissionen", "CO2-Emissionen"],
    "emissions": ["Emissionen", "THG-Emissionen", "Treibhausgasemissionen", "CO2-Emissionen"],
    "greenhouse gas": ["Treibhausgas", "Treibhausgasemissionen", "THG"],
    "ghg": ["THG", "Treibhausgas"],
    "carbon": ["CO2", "Kohlenstoff"],
    "intensity": ["Intensität", "Emissionsintensität"],
    "target": ["Ziel", "Zielsetzung", "Reduktionsziel"],
    "targets": ["Ziele", "Zielsetzungen", "Reduktionsziele"],
    "reduction": ["Reduktion", "Reduzierung", "Minderung"],
    "reduce": ["reduzieren", "senken", "verringern"],
    "net zero": ["Netto-Null", "Netto-Null-Emissionen", "Klimaneutralität", "klimaneutral"],
    "net-zero": ["Netto-Null", "Klimaneutralität"],
    "carbon neutral": ["klimaneutral", "CO2-neutral", "Klimaneutralität"],
    "interim": ["Zwischenziel", "Zwischenziele"],
    "pathway": ["Pfad", "Reduktionspfad"],
    "value chain": ["Wertschöpfungskette", "Lieferkette"],
    "purchased electricity": ["eingekaufter Strom", "Strombezug"],
    "offsets": ["Kompensation", "CO2-Kompensation", "Ausgleichszertifikate"],
    "carbon credits": ["CO2-Zertifikate", "Emissionszertifikate", "Kompensationszertifikate"],
    "renewable": ["erneuerbar", "erneuerbare Energien", "Ökostrom"],
    "energy": ["Energie", "Energieverbrauch"],
    "decarbonisation": ["Dekarbonisierung"],
    "decarbonization": ["Dekarbonisierung"],
    "climate": ["Klima", "Klimaschutz"],
    "transition plan": ["Transitionsplan", "Übergangsplan", "Klimatransitionsplan"],
    "just transition": ["gerechter Übergang", "sozial gerechter Übergang"],
    "scenario": ["Szenario", "Szenarioanalyse"],
    "fossil": ["fossil", "fossile Brennstoffe"],
    "coal": ["Kohle", "Kohleausstieg"],
    "oil and gas": ["Öl und Gas"],
    "deforestation": ["Entwaldung", "entwaldungsfrei"],
    "biodiversity": ["Biodiversität", "biologische Vielfalt"],
    "water": ["Wasser", "Wasserentnahme", "Wasserverbrauch"],
    "waste": ["Abfall", "Abfälle"],
    "supplier": ["Lieferanten", "Zulieferer"],
    "suppliers": ["Lieferanten", "Zulieferer"],
    "lobbying": ["Lobbyarbeit", "Interessenvertretung"],
    "trade association": ["Verband", "Branchenverband", "Wirtschaftsverband"],
    "board": ["Aufsichtsrat", "Vorstand"],
    "governance": ["Unternehmensführung", "Governance"],
    "sustainability": ["Nachhaltigkeit", "nachhaltig"],
    "assurance": ["Prüfung", "Prüfungsurteil", "Bestätigungsvermerk"],
    # money and the EU Taxonomy
    "revenue": ["Umsatzerlöse", "Umsatz", "Erlöse"],
    "revenues": ["Umsatzerlöse", "Umsätze", "Erlöse"],
    "turnover": ["Umsatzerlöse", "Umsatz"],
    "capex": ["Investitionsausgaben", "Investitionen", "CapEx"],
    "capital expenditure": ["Investitionsausgaben", "Investitionen"],
    "opex": ["Betriebsausgaben", "OpEx"],
    "operating expenditure": ["Betriebsausgaben"],
    "taxonomy": ["Taxonomie", "EU-Taxonomie"],
    "aligned": ["taxonomiekonform"],
    "taxonomy-aligned": ["taxonomiekonform"],
    "eligible": ["taxonomiefähig"],
    "taxonomy-eligible": ["taxonomiefähig"],
    "not eligible": ["nicht taxonomiefähig"],
    "non-eligible": ["nicht taxonomiefähig"],
    "enabling": ["ermöglichende Tätigkeiten"],
    "transitional": ["Übergangstätigkeiten"],
    "nuclear": ["Kernenergie"],
    "fossil gas": ["fossiles Gas", "Erdgas"],
    "green": ["grün", "grüne", "nachhaltige"],
    "low-carbon": ["CO2-arm", "kohlenstoffarm"],
    "denominator": ["Nenner", "Gesamtumsatz"],
    "fiscal year": ["Geschäftsjahr"],
    "reporting year": ["Berichtsjahr", "Geschäftsjahr"],
    # pay
    "remuneration": ["Vergütung", "Vorstandsvergütung"],
    "remuneration report": ["Vergütungsbericht"],
    "compensation": ["Vergütung"],
    "short-term incentive": ["kurzfristige variable Vergütung", "Jahresbonus", "STI"],
    "long-term incentive": ["langfristige variable Vergütung", "LTI"],
    "annual bonus": ["Jahresbonus", "Tantieme"],
    "performance share": ["Performance Share", "Aktientantieme"],
    "modifier": ["Modifikator", "Korrekturfaktor"],
    "multiplier": ["Multiplikator"],
    "esg": ["ESG", "Nachhaltigkeitsziele", "ESG-Ziele"],
}

_PATTERNS = [(re.compile(rf"(?<![\w-]){re.escape(k)}(?![\w-])", re.IGNORECASE), terms) for k, terms in GLOSSARY.items()]


def with_german(keywords: list[str]) -> list[str]:
    """`keywords` followed by the German terms of every glossary key they contain, each once."""
    out = dict.fromkeys(keywords)
    for kw in keywords:
        for pattern, terms in _PATTERNS:
            if pattern.search(kw):
                out.update(dict.fromkeys(terms))
    return list(out)
