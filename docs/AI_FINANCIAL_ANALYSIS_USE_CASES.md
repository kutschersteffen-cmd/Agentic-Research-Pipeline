# Analyse: KI-Anwendungsfälle in der Finanzanalyse — Abgleich mit dem Ist-Zustand

Dieses Dokument bewertet fünf häufig genannte KI-Anwendungsfälle im
Investment-Research gegen den tatsächlichen Stand dieses Repos:

1. Automatisierte Zusammenfassungen von Earnings Calls und
   Research-Reports "in Echtzeit"
2. Identifikation von Analysten-Bias und Prognosefehlern
3. Unterstützung bei der Portfoliokonstruktion (Fundamentaldaten,
   Risikomodelle, Szenarioanalysen)
4. Frühzeitige Erkennung von Abweichungen von Investmentthesen
5. Automatisierte Alerts, wenn sich die Faktenlage verändert

Methodisch dasselbe Vorgehen wie in
[`THEMATIC_INTELLIGENCE_ARCHITECTURE_REVIEW.md`](THEMATIC_INTELLIGENCE_ARCHITECTURE_REVIEW.md):
kein Feature-Wunschzettel, sondern ein Abgleich — was ist bereits gebaut,
was fehlt wirklich, und was klingt nach einem LLM-Problem, ist aber in
Wahrheit ein Daten-, Lizenz- oder Rechenproblem.

**Kernbefund vorweg:** Die fünf Themen sind *keine* fünf Features. Vier von
fünf hängen an denselben **zwei fehlenden Primitiven** — einer
Point-in-Time-Werteachse pro `(company, field, period)` und einem
maschinenlesbaren Thesen-/Claim-Objekt — plus einer dünnen
Materialitätsschicht davor. Use Case 2 (Analysten-Bias) fällt aus der
Reihe: er ist zu ~90 % ein Datenbeschaffungs-/Lizenzproblem und sollte
ohne Point-in-Time-Schätzungshistorie gar nicht erst begonnen werden.

## 0. Kurzbewertung

| Use Case | Bereits vorhanden | Echte Lücke | Aufwand | Empfehlung |
|---|---|---|---|---|
| 1 Earnings-Call-/Report-Zusammenfassung | Transkript-DocType, Retrieval, Extractor/Verifier, Grounding | Delta-Vergleich zum Vorquartal; "Echtzeit" im Wortsinn; Lizenz für Sell-Side-Research | mittel | ✅ ja — aber als **Delta**-Zusammenfassung, nicht als generische Summary |
| 2 Analysten-Bias & Prognosefehler | XBRL-Actuals (`ingestion/xbrl.py`) als Realisierungsseite | Point-in-Time-Schätzungshistorie (I/B/E/S o. ä.) — fehlt vollständig | hoch (extern) | ⛔ nicht starten ohne Datenlizenz |
| 3 Portfoliokonstruktion | Holdings-Aggregation, Analytics, Climate-Metriken, Fundamentaldaten aus Filings | Kovarianz-/Faktormodell, Optimizer, Szenario-Durchreichung | hoch bzw. Fremdsystem | ⚠️ nur die **Constraint-/Signalseite**, nie den Optimizer |
| 4 Abweichung von der Investmentthese | Commitment-/Milestone-Muster, 64 fixe Indikatoren, Review-Queue | Thesen-Objekt mit Falsifikationsprädikat | mittel | ✅ stärkster Fit, größter Eigenwert |
| 5 Alerts bei veränderter Faktenlage | `ChangeDetector` → `DocumentEvent` → JSONL-Feed + Webhook, `DiscoveryScheduler` | Alert auf **Wert-Delta** statt Dokument-Delta; Materialitätsregeln, Dedup | klein–mittel | ✅ zuerst bauen — schaltet 1, 4 und den Rest mit frei |

## 1. Die gemeinsame, unsichtbare Voraussetzung

Alle fünf Formulierungen enthalten implizit eine Zeitachse: "in Echtzeit",
"Prognosefehler", "Szenario", "Abweichung", "wenn sich … verändert". Das
heutige System hat diese Achse nur an zwei Stellen:

- `DataPointObservation` (`backend/arp/schemas/portfolio.py`) trägt
  `period`, `observed_at` und `source` — das ist exakt die richtige Form,
  aber sie existiert nur portfolio-lokal für Klimadatenpunkte, nicht als
  allgemeine Senke der Extraction Engine.
- `ChangeDetector` (`backend/arp/discovery/change_detector.py`) führt ein
  Manifest gesehener Dokument-URLs und Content-Hashes je Unternehmen. Es
  weiß, dass sich ein *Dokument* geändert hat — nie, dass sich eine
  *Aussage* geändert hat.

Alles andere im Repo ist zeitpunktlos: ein Run erzeugt Felder mit
Zitaten, ein zweiter Run erzeugt neue Felder mit Zitaten, und niemand
vergleicht die beiden. Genau dieser Vergleich ist der gesamte
Informationsgehalt der Use Cases 1, 4 und 5.

Die zweite Voraussetzung: Materialität. Ein 10-K ist jedes Jahr neu — ein
Alert darauf ist wertlos. Interessant ist ausschließlich das Delta in den
Feldern, an denen eine These hängt, oberhalb eines Schwellwerts, dedupliziert
gegen bereits gemeldete Deltas. Ohne diese Schicht produziert jede
Alert-Funktion Alert-Fatigue und wird nach drei Wochen stummgeschaltet.

## 2. Use Case 1 — Earnings Calls und Research-Reports "in Echtzeit"

### Was schon da ist

`DocType.EARNINGS_TRANSCRIPT` ist ein erstklassiger Dokumenttyp
(`schemas/common.py`); Discovery lädt Transkripte von IR-Seiten
(`discovery/crawler.py`, `downloader.py`); Parsing, Chunking mit
Seitenspans (`ingestion/chunk_spans.py`) und Hybrid-Retrieval
(`retrieval/select_evidence.py`) laufen darauf ohne Änderung. Die
Zusammenfassung selbst ist im Kern ein Extraction-Schema mit
Extractor/Verifier-Paar auf entkoppelten Modellen plus programmatischem
Grounding-Check (`arp/grounding.py`) — also genau das, was das System
bereits am besten kann.

### Wo es nicht trägt

**"Echtzeit" ist im Wortsinn nicht gemeint und sollte nicht versprochen
werden.** Der begrenzende Faktor ist nicht das Modell, sondern die
Verfügbarkeit des Transkripts: Discovery ist ein APScheduler-Poll auf
IR-Seiten (`discovery/scheduler.py`), kein Push-Feed, und ein IR-Transkript
erscheint typischerweise Stunden bis Tage nach dem Call. Echtzeit im engeren
Sinn hieße Audio-Stream + ASR + Sprecher-Diarisierung — ein anderes System
mit anderen Fehlermodi, das den gesamten Grounding-Ansatz dieses Repos
(Zitat wird gegen das Quelldokument geprüft) untergräbt, weil das
"Quelldokument" dann eine fehlerbehaftete Transkription ist. Ehrliche
Zielgröße: **minutenaktuell ab Transkript-Verfügbarkeit**, nicht
Echtzeit ab Call-Beginn.

**Sell-Side-Research ist primär ein Lizenzthema, kein technisches.**
Broker-Research darf in aller Regel vertraglich nicht in ein externes
Modell gegeben, weiterverteilt oder als Trainingsgrundlage genutzt werden;
unter MiFID II kommt die Frage der Vergütung und Weitergabe dazu. Das ist
vor jeder Implementierung zu klären — nicht danach.

**Generische Zusammenfassungen sind Commodity.** Jeder Anbieter liefert
sie; der Grenznutzen gegenüber dem Transkript selbst ist gering. Der Wert
liegt im Vergleich: *Was sagt das Management diesmal anders als beim
letzten Call?* Welche Guidance wurde stillschweigend kassiert, welche
Formulierung zu einem laufenden Projekt ist von "on track" zu "we continue
to evaluate" gewandert, welche zuvor genannte Kennzahl wird nicht mehr
genannt. Das ist die Form, die dieses System bauen sollte, und sie setzt
Use Case 5 (Wert-Delta über die Zeit) voraus.

### Konkreter Zuschnitt

Ein Extraction-Schema "Earnings Call Delta" mit festen Feldern (Guidance je
Kennzahl, genannte Projekt-Meilensteine, Kapitalallokations-Aussagen,
Risikonennungen), ausgeführt gegen Transkript N und Transkript N−1, und
einem deterministischen Diff über die Feldwerte. Der LLM extrahiert die
Felder mit Zitat — den Vergleich macht Code, nicht das Modell.
**Anti-Pattern:** beide Transkripte in einen Prompt geben und "vergleiche"
sagen. Das erzeugt plausible, unprüfbare Unterschiede.

## 3. Use Case 2 — Analysten-Bias und Prognosefehler

Dies ist der einzige der fünf Fälle, bei dem ich von einem Start abrate,
solange eine Voraussetzung fehlt.

Bias- und Fehlermessung braucht eine **Point-in-Time-Schätzungshistorie**:
wer hat wann welche Schätzung für welche Periode abgegeben, inklusive
Revisionen, mit dem Stand *zum damaligen Zeitpunkt*. Ohne PIT-Snapshots
misst man Look-ahead-Bias im eigenen Datensatz statt Bias beim Analysten —
restatete Actuals und rückwirkend bereinigte Consensus-Werte kippen das
Vorzeichen der Ergebnisse zuverlässig. Diese Daten sind lizenzpflichtig
(I/B/E/S, Visible Alpha, FactSet o. ä.) und im Repo nicht vorhanden; kein
LLM erzeugt sie.

Was das Repo beiträgt, wenn die Daten da sind:

- **Die Realisierungsseite.** `ingestion/xbrl.py` zieht getaggte Facts
  direkt aus SEC companyfacts — Actuals ohne LLM-Pfad, mit der bereits
  implementierten Tag-Fallback-Kaskade für uneinheitlich taggende Filer.
- **Die qualitative Seite.** Divergenz zwischen Tonfall und Zahl (der
  Report bleibt positiv, das Kursziel sinkt; das Management nennt eine
  zuvor betonte Kennzahl nicht mehr) ist ein Textproblem und passt zum
  Grounding-Ansatz.
- **Das Rechenmuster.** Die Bias-Metriken selbst — mittlerer und medianer
  Prognosefehler, Vorzeichenbias, Revisionsdrift, Herding/Boldness nach
  Clement/Tse — sind deterministisch und gehören ausdrücklich **nicht** ins
  Modell. Das ist exakt das Muster aus `portfolio/qa_agent.py` +
  `portfolio/aggregation.py`: der LLM formuliert die Abfrage, die Engine
  rechnet die Zahl. Wird dieses Muster hier verletzt, ist das Ergebnis
  unprüfbar und für jede Compliance-Diskussion wertlos.

**Empfehlung:** zurückstellen, bis eine PIT-Estimates-Quelle vertraglich
steht. Vorher lässt sich der Fall nicht seriös bauen, nur simulieren.

## 4. Use Case 3 — Portfoliokonstruktion

Hier ist die wichtigste Leistung die Abgrenzung: dieses System ist ein
**Evidenz- und Research-System, kein Optimizer und kein Risikomodell**.

### Was realistisch ist

- **Die Constraint- und Signalseite.** Exposure-Schätzungen aus dem
  Theme-Run, Revenue/CapEx-Auflösung
  (`research/revenue_exposure/`), Segment-/CapEx-/R&D-Daten aus
  `extraction/financials_pipeline.py`, Transition-Plan-Scores und die
  indirekte Input-Output-Exposure-Stufe
  (`research/indirect_exposure/`) sind genau die Eingaben, die einer
  klassischen Konstruktion fehlen — jede mit Zitat und Prüfpfad. Das ist
  der eigentliche Beitrag: nicht bessere Gewichte, sondern belegte
  Eingangsgrößen.
- **Deterministische Szenario-Durchreichung.** Ein Schock auf eine
  Kenngröße (Carbon-Preis, Nachfrage-Pfad, Regulierungsschwelle) auf
  Unternehmensebene, propagiert über bestehende Holdings mit
  `portfolio/aggregation.py`, ergibt Portfolio-Effekte ohne einen einzigen
  LLM-Aufruf in der Zahl. NGFS-artige Klimapfade passen strukturell direkt
  auf die vorhandene Climate-Analytics-Schicht
  (`portfolio/climate/`). Der LLM darf hier höchstens die
  Szenario-*Annahmen* aus Quelldokumenten extrahieren — die Wirkung rechnet
  die Engine.

### Was nicht in dieses System gehört

- **Ein Faktor-/Kovarianz-Risikomodell** (Barra-/Axioma-artig) ist ein
  eigenes quantitatives Projekt mit eigener Datenhistorie — kein
  LLM-Projekt und kein sinnvoller Anbau hier. Falls benötigt: Fremdmodell
  anbinden, Exposures als Input liefern.
- **Ein Optimizer** erst recht nicht. Nebenbedingungen aus diesem System
  zu exportieren ist richtig; die Optimierung hier auszuführen wäre eine
  Zuständigkeitsverwechslung.
- **"Szenarioanalyse per LLM"** im Sinne von "lass das Modell die
  Auswirkung schätzen" produziert plausible erfundene Zahlen. Das ist der
  gefährlichste der fünf Use Cases, weil das Ergebnis gut aussieht und
  nicht falsifizierbar ist.

## 5. Use Case 4 — Abweichung von der Investmentthese

Der stärkste Fit, und der Fall mit dem größten Eigenwert, weil ihn
Standardanbieter nicht liefern können: eine Investmentthese ist
hausintern, unstrukturiert und lebt heute in einem Memo.

Das Muster existiert im Repo bereits zweimal:

- `Commitment` (`schemas/engagement.py`) — eine Zusage mit Status,
  Frist und Beleglage, die periodisch gegen die Faktenlage neu bewertet
  wird.
- Die 64 fixen Transition-Plan-Indikatoren (`arp/transition_plan/`) —
  eine feste Liste prüfbarer Aussagen, je mit geerdetem YES/NO/NA-Verdikt.

Eine Investmentthese ist strukturell dasselbe, nur mit dem Investor statt
dem Unternehmen als Urheber. Was fehlt, ist ein **Thesen-Objekt**:

```
Thesis
  thesis_id, company_id, author, created_at, status
  claims: [
    Claim(
      claim_id,
      statement,                  # "Segment X wächst >15% p.a. bis FY2028"
      measurable_field_id,        # Anker in die Extraction/XBRL-Welt
      predicate,                  # deterministisch prüfbar: >, <, trend, presence
      falsification_condition,    # was diese These widerlegt
      check_interval,             # quartalsweise, bei neuem Dokument, ...
      last_evaluated_at, last_verdict, evidence: [Citation]
    )
  ]
```

Drei Eigenschaften machen den Unterschied zu einem Textfeld:

1. **Der Claim ist an ein Feld gebunden**, nicht an Prosa — er ist damit
   automatisch re-evaluierbar, wenn ein neues Dokument ankommt.
2. **Die Falsifikationsbedingung wird beim Anlegen geschrieben, nicht
   danach.** Das ist die eigentliche Disziplinleistung des Formats und der
   wirksamste Schutz gegen nachträgliche Rationalisierung.
3. **Das Prädikat ist deterministisch.** Der LLM liefert den Wert mit
   Zitat, die Regel entscheidet über Verletzung. Ein "der LLM beurteilt,
   ob die These noch trägt" wäre wieder eine unprüfbare Meinung.

Die Aufsetzung kann agentisch sein: Memo hochladen, Agent schlägt Claims,
Felder und Falsifikationsbedingungen vor, Mensch bestätigt — dasselbe
Checkpoint-Muster wie `orchestration/review_queue.py` und die
Engagement-Checkpoints. Der laufende Betrieb ist dann deterministisch.

## 6. Use Case 5 — Alerts bei veränderter Faktenlage

Das Skelett steht: `ChangeDetector` schreibt `DocumentEvent`s in einen
rollierenden JSONL-Feed und POSTet best-effort an einen Webhook;
`DiscoveryScheduler` triggert das Ganze wiederkehrend und persistiert seine
Konfiguration dateibasiert. Das ist die halbe Miete und war offensichtlich
mit dieser Richtung im Hinterkopf gebaut.

Die fehlende Hälfte ist der Sprung von **Dokument-Delta** zu
**Wert-Delta**:

1. **Werte-Historie.** Jeder Extraction-Run schreibt seine Felder als
   zeitgestempelte Beobachtungen — `DataPointObservation` ist das bereits
   passende Format, es muss nur von der Klima-Nische zur allgemeinen Senke
   der Extraction Engine werden. Damit wird "Feld X hat sich von A nach B
   geändert, Beleg vorher, Beleg nachher" überhaupt erst formulierbar.
2. **Materialitätsregeln.** Schwellwert je Feld (absolut/relativ),
   Richtungsrelevanz, Mindestabstand zwischen Alerts zum selben Claim,
   Dedup gegen bereits gemeldete Deltas. Ohne diese Schicht ist die
   Funktion nach drei Wochen abgeschaltet.
3. **Severity aus der Thesenbindung.** Ein Delta ist nicht per se wichtig —
   es ist wichtig, wenn ein Claim daran hängt (Use Case 4). Das ist die
   natürliche Severity-Quelle und macht Alerts ohne Thesen-Objekt
   strukturell schwächer.

Der bestehende Grounding-Check bleibt dabei die Absicherung gegen den
teuersten Fehlerfall eines Alert-Systems: ein Fehlalarm aus einer
halluzinierten Wertänderung. Ein Delta, dessen beide Seiten nicht gegen
das jeweilige Quelldokument verifiziert sind, darf niemanden wecken.

## 7. Der gemeinsame Nenner

Aus den fünf Fällen destillieren sich **drei fehlende Primitive** — nicht
fünf Features:

| # | Primitiv | Schaltet frei |
|---|---|---|
| P1 | Point-in-Time-Werteachse pro `(company, field, period)` als allgemeine Extraktions-Senke | UC 1 (Delta-Summary), UC 4, UC 5 |
| P2 | Thesen-/Claim-Objekt mit deterministischem Falsifikationsprädikat | UC 4, Severity für UC 5 |
| P3 | Materialitäts-/Dedup-Schicht zwischen Event und Mensch | UC 5, Brauchbarkeit von UC 1 und 4 im Alltag |

Use Case 3 braucht keines davon (er braucht Fremdsysteme und eine klare
Abgrenzung), Use Case 2 braucht eine externe Datenlizenz.

Über alle fünf hinweg gilt dieselbe Linie, die dieses Repo bereits
konsequent zieht und die hier nicht aufgeweicht werden darf: **der LLM
extrahiert und formuliert, die Engine rechnet und entscheidet.** Jede der
fünf Ideen hat eine bequeme Variante, in der das Modell die Zahl oder das
Urteil liefert — und jede dieser Varianten ist unprüfbar.

## 8. Priorisierte Reihenfolge

1. **P1 + P3: Wert-Delta-Alerts.** Kleinster Aufwand, größter
   Freischalteffekt, baut auf bestehendem `ChangeDetector`/Scheduler auf.
2. **P2: Thesen-Objekt + Thesen-Monitor.** Höchster Eigenwert, nicht
   zukaufbar, nutzt P1 direkt.
3. **Earnings-Call-Delta-Zusammenfassung.** Als Delta gegen das
   Vorquartal, nicht als generische Summary; setzt P1 voraus.
4. **Deterministische Szenario-Durchreichung** auf
   `portfolio/aggregation.py` — klar abgegrenzt, ohne Optimizer-Ambition.
5. **Analysten-Bias** — erst nach geklärter PIT-Estimates-Lizenz.

## 9. Was bewusst nicht empfohlen wird

- Echtzeit-Audio/ASR für laufende Calls — anderer Fehlermodus, untergräbt
  den Grounding-Ansatz, geringer Grenznutzen gegenüber T+Stunden.
- Ingestion von Sell-Side-Research vor geklärter Lizenzlage.
- Generische Earnings-Summaries ohne Delta-Bezug — Commodity.
- LLM-berechnete Risiko-, Szenario- oder Bias-Kennzahlen.
- Ein eigenes Faktor-Risikomodell oder ein Optimizer in diesem Repo.
