# Analyse: "Agentisches Thematic-Intelligence-System — Zielarchitektur"

Dieses Dokument bewertet die vorgeschlagene Zielarchitektur (sieben Layer,
Postgres/pgvector, Temporal, L4a/L4b/L5/L6/L7) gegen den tatsächlichen Stand
dieses Repos. Kernbefund vorweg: **der überwiegende Teil der Zielarchitektur
ist bereits gebaut** — nicht als Prototyp, sondern als lauffähiges System
(`backend/arp/`, s. [`README.md`](../README.md),
[`docs/METHODOLOGY.md`](METHODOLOGY.md)) mit CLI, API und Frontend. Die
Analyse ist deshalb kein Bewertung "gut geplant vs. ungeplant", sondern ein
Abgleich: welche Entscheidungen des Vorschlags decken sich mit dem
Ist-Zustand, wo geht die bestehende Implementierung über den Vorschlag
hinaus, und wo benennt der Vorschlag echte, noch offene Lücken.

## 1. Layer-Mapping: Vorschlag → Ist-Zustand

| Vorschlag | Ist-Zustand | Bewertung |
|---|---|---|
| L1 Ingestion (docling/unstructured, EDGAR+XBRL/arelle, S3 versioniert) | `arp/ingestion/edgar.py`, `local_files.py`, `parsing.py`; `arp/discovery/` für IR-Crawling; lokaler/dateibasierter Store, kein S3 | ⚠️ teilweise — s. Abschnitt 3.1 |
| L2 Normalisierung/Chunking/Embedding/Entity-Resolution | `arp/ingestion/parsing.py::chunk_document` (LlamaIndex `SentenceSplitter`); `arp/portfolio/entity_resolution.py` (ISIN exakt + Fuzzy-Fallback, kein LEI-Feld); `arp/retrieval/embeddings.py` (lokales ONNX-Modell, **standardmäßig deaktiviert**) | ⚠️ teilweise — s. 3.2 |
| L3 Retrieval (Hybrid Dense+BM25+Fusion+Rerank) | `arp/retrieval/select_evidence.py`: BM25 (LlamaIndex) ist der Default; RRF-Fusion mit lokalem Embedding-Vektor ist implementiert, aber per Flag (`hybrid_retrieval_enabled`) **opt-in, aus**; kein Reranking-Modell | ⚠️ teilweise — s. 3.2 |
| L4a Theme-Exposure-Engine | `arp/research/` — Themen-Dekomposition (`arp theme decompose`), Advocate/Opposing/Adjudicator-Debatte (`matcher_agents.py`, `match_graph.py`), gradueller `ExposureEstimate` (`pure_play/significant/minor/none`), Revenue/CapEx-Kaskade, Indirect-Exposure-Tier | ✅ vorhanden, geht in mehreren Punkten über den Vorschlag hinaus — s. Abschnitt 2 |
| L4b Datenpunkt-Extraktion | `arp/extraction/` — exakt das vorgeschlagene Schema (`not_disclosed` getrennt von `value: None`, `evidence`-Spans, `confidence`), Extractor+Verifier-Paar (`field_graph.py`) | ✅ vorhanden — Self-Consistency (3 Läufe) ist die einzige Lücke, s. 3.4 |
| L5 Kritiker-Agent (anderes Modell) | `verifier_agent.py`, `financials_verifier_agent.py`, `segment_verifier_agent.py`, `spend_verifier_agent.py` — architektonisch getrennter zweiter Call, der zum Widerspruch instruiert ist | ⚠️ läuft auf **demselben** Modell wie der Extraktor — s. 3.3, wichtigster Einzelbefund dieser Analyse |
| L6 Governance (Confidence-Gating, Review-Queue, Audit-Log, Golden Set, Prompt-Versionierung) | `arp/orchestration/review_queue.py` (Append-only Audit-Trail, nie überschrieben), `confidence_review_threshold` in `config.py`, programmatisches Grounding (`grounding.py`) als deterministische Plausibilitätsprüfung | ⚠️ Confidence-Gating und Audit-Trail vorhanden; **kein Golden Set, keine Prompt-Hash-Versionierung, keine deterministischen Business-Regeln** (Green Capex ≤ Total Capex etc.) — s. 3.5 |
| L7 Web-UI (Split-Screen-Review, Universum-Explorer, Batch-Monitor) | `frontend/src/pages/ReviewQueue.tsx`, `TaxonomyLibrary.tsx`, `InspectorModal.tsx`, Run-Monitoring-Views | ⚠️ Quellenansicht ist ein **Modal**, kein dauerhafter Split-Screen — s. 3.6 |
| Orchestrierung: Temporal/Prefect | `arp/orchestration/batch_runner.py` — eigener `asyncio`+Semaphore-Batch-Runner mit JSONL-Checkpointing, Resume, kooperativem Cancel | ⚠️ funktional äquivalent für den Kernfall, aber ohne Workflow-Engine — s. 3.7 |
| Modell-Auswahl nach Aufgabe (Reasoning/Mittelklasse/Kritiker getrennt) | `arp/llm/factory.py` — **ein** globales `llm_model` für alle Agentenrollen | ❌ nicht umgesetzt — s. 3.3 |

## 2. Wo die bestehende Implementierung über den Vorschlag hinausgeht

Das ist keine Nebensache — für die Bewertung "soll ich diese Zielarchitektur
so bauen" ist relevant, dass mehrere ihrer Kernideen im Ist-Zustand bereits
in einer ausgereifteren Form existieren:

- **Graduelles Exposure ist bereits Kernprinzip, nicht nur Aggregations-
  Output.** Der Vorschlag beschreibt in L4a Schritt 3/4 im Wesentlichen das,
  was hier seit der ersten Implementierung so gebaut ist (`ExposureEstimate`,
  `docs/METHODOLOGY.md` Abschnitt zu MSCI-Bändern) — inklusive der
  Revenue/CapEx-Kaskade (strukturierte Datenquelle → Extraktion →
  qualitatives Debat­ten-Fallback), die im Vorschlag gar nicht vorkommt,
  aber genau das Problem "harte Zahl vs. LLM-Schätzung" sauberer löst als
  ein reines Scoring-Feld.
- **Adversariale Verifikation ist bereits zweistufig für Themenzuordnung
  *und* Extraktion**, nicht nur für Extraktion wie in L5 beschrieben: die
  Advocate/Opposing/Adjudicator-Debatte (`match_graph.py`) ist strukturell
  das, was MSCIs "Opposing Agent"-Ansatz beschreibt, und geht über einen
  einzelnen Scoring-Call (Vorschlag L4a.3) hinaus, weil Gegenargumente
  (Greenwashing-Sprache, Aspirationalformulierungen) explizit gesucht
  werden, nicht nur implizit im Prompt verlangt.
- **Die Taxonomie-Ebene ist im Vorschlag unterspezifiziert.** L4a.1 sagt
  "LLM zerlegt Thema, Output versioniert und freigebbar" — das Repo hat das
  zu einer eigenen Bibliothek mit sieben Ableitungsmethoden ausgebaut
  (`industry_anchored`, `authority_source` mit Grounding-Pflicht pro
  Aktivität, `etf_index_holdings`, `news_transcript_mining`, `empirical`,
  `merged`, `manual`), inklusive Ratifizierungsschritt und
  NACE/NAICS/SIC/GICS-Cross-Referenzierung. Das ist eine deutlich robustere
  Antwort auf "wie kommt die Aktivitäten-Taxonomie überhaupt zustande" als
  ein einzelner Dekompositions-Call.
- **Der Indirect-Exposure-Tier (Leontief-Inverse über OECD-ICIO)** hat kein
  Äquivalent im Vorschlag, schließt aber genau die Lücke, die eine reine
  Text-/Disclosure-basierte Engine strukturell hat: Unternehmen, die
  thematisch relevant sind, es aber nie in eigenen Worten sagen.
- **"not_disclosed" vs. "nicht gefunden"** ist im Ist-Zustand nicht nur
  Schema-Feld, sondern durchgängiges Designprinzip ("Was nicht explizit
  offengelegt ist, wird nie geschätzt oder aus einer Summe zurückgerechnet"
  — `docs/METHODOLOGY.md`, Abschnitt "What's deliberately out of scope").

Kurz: Wer diese Zielarchitektur als Neubau-Blueprint liest, unterschätzt,
was hier an Präzisions-Engineering bereits über das hinausgeht, was L4a/L4b
beschreiben.

## 3. Wo der Vorschlag echte, offene Lücken benennt

### 3.1 L1 — XBRL/strukturierte Filingsdaten werden nicht genutzt

Der Vorschlag formuliert eine harte Regel: *"Was in XBRL/strukturierter
Form vorliegt, wird nie durch ein LLM geschätzt."* Das Repo hält dieses
Prinzip bei **narrativen** Daten strikt ein (s. Abschnitt 2), aber
`arp/ingestion/edgar.py` zieht EDGAR-Filings nur als Dokumente/Text — es
gibt keinen `arelle`- oder sonstigen XBRL-Parser im Code. Finanzkennzahlen,
die als strukturierte EDGAR/ESEF-Fakten vorlägen (Total Capex, Revenue by
segment in vielen 10-Ks), laufen also durch dieselbe
Extractor/Verifier-Pipeline wie unstrukturierter Text, obwohl für US-Filer
oft ein maschinenlesbarer Weg existierte. Das ist der stärkste konkrete
Verbesserungsvorschlag aus dem Dokument: ein XBRL-Fact-Loader vor der
Extraktion, mit Fallback auf die LLM-Pipeline nur für Fälle ohne
strukturierten Tag, würde Kosten senken und Fehlerfläche für genau die
Kennzahlen reduzieren, die `CompanyFinancials` (L4b) ohnehin extrahiert.

### 3.2 L2/L3 — Hybrid-Retrieval existiert, ist aber deaktiviert; kein Reranking

`hybrid_retrieval_enabled` (Default `false`, `config.py:43`) und das lokale
ONNX-Embedding (`bge-small-en-v1.5`, 384-dim, `arp/retrieval/embeddings.py`)
sind vollständig implementiert, aber bewusst dunkel geschaltet, "pending
side-by-side validation". Der Vorschlag hätte hier recht: BM25 allein fängt
exakte Fachbegriffe gut, verwischt aber Vokabularlücken (das eigene
Code-Kommentar nennt das Beispiel "e-mobility transition" vs. Seed-Keyword
"electrification"). Der Unterschied zum Vorschlag ist nicht die Idee
(Hybrid-Retrieval), sondern die Wahl: lokales ONNX-Modell statt
`voyage-3-large`/`text-embedding-3-large`, und **kein** separates
Reranking-Modell überhaupt — Top-K kommt direkt aus RRF, nicht aus einer
Rerank-Stufe. Bei einem mehrsprachigen DE/EN-Bestand ist `bge-small-en-v1.5`
zudem nicht multilingual, was der Vorschlag explizit als Anforderung nennt.
**Empfehlung:** die im Vorschlag geforderte Validierung nachholen (das
Flag existiert schon dafür) und bei dieser Gelegenheit auf ein
multilinguales Embedding-Modell prüfen, bevor DE-Berichte in nennenswertem
Umfang durch die Pipeline laufen.

### 3.3 L5/Modell-Auswahl — der wichtigste Einzelbefund

`arp/llm/factory.py::build_llm_client` liefert **einen** Client mit **einem**
`Settings.llm_model` für jede Agentenrolle — Advocate, Opposing, Adjudicator,
Extractor, Verifier, Kritiker in allen Domänen (Financials, Segments, Spend),
Taxonomie-Dekomposition. `docs/METHODOLOGY.md` beschreibt die
Verifier-Rolle als "independent Verifier agent [that] re-reads the same
evidence" — das stimmt für den Kontext (separater Call, separates
Evidence-Fenster, zum Widerspruch instruiert), aber **nicht** für das
Modell selbst. Der Vorschlag benennt in L5 und Abschnitt 4 explizit den
Grund, warum das ein Problem ist: korrelierte Fehler. Ein Modell, das eine
bestimmte Art von Halluzination oder eine bestimmte Fehlinterpretation
systematisch produziert, wird sie in der Verifier-Rolle mit einiger
Wahrscheinlichkeit wiederholen, nicht aufdecken — der Advocate/Opposing/
Adjudicator-Aufbau mildert das über unterschiedliche *Prompts*, aber nicht
über unterschiedliche *Modelle*. Das ist die Lücke mit dem höchsten
Hebel für die eigentliche Zielgröße des Systems (Präzision): sie kostet
im Kern nur eine zweite Model-Config und einen zweiten `LLMClient` im
Verifier-Pfad, keine strukturelle Änderung.

Ebenso fehlt die im Vorschlag (Abschnitt 4) beschriebene Kostenstaffelung
(stärkstes Modell für die einmalige Themen-Dekomposition, Mittelklasse für
das hochvolumige Scoring/die Extraktion). Bei 4.000 Unternehmen × mehreren
Aktivitäten/Feldern läuft aktuell dieselbe Modellklasse durch den
gesamten hochvolumigen Pfad wie durch die seltene, hochwertige
Dekomposition — ökonomisch nicht falsch, aber ungenutztes
Optimierungspotenzial, und `litellm`/ein Adapter dafür existiert nicht;
`build_llm_client` ist fest an `LangChainAnthropicClient` gebunden.

### 3.4 L4b — Self-Consistency (3 Läufe) ist im Vorschlag, fehlt im Code

`field_graph.py` implementiert Extractor→Verifier als **einen** Durchlauf
mit Reject→Re-Extraktion (bis zu Iterationsgrenze) bei Verifier-Widerspruch
— eine andere, aber vertretbare Antwort auf dasselbe Problem (Divergenz
aufdecken), aber nicht die im Vorschlag beschriebenen drei parallelen
Läufe bei Temperatur > 0 mit Divergenz-Check. Der bestehende Ansatz ist
günstiger (ein Extraktions-, ein Verifikationscall statt drei plus
Vergleich), fängt aber eine andere Fehlerklasse: Verifier-Widerspruch
setzt voraus, dass der Verifier das Problem *erkennt*; Self-Consistency
fängt auch Fälle, in denen Extractor und Verifier beide plausibel, aber
uneinig mit sich selbst über wiederholte Läufe wären (z. B. bei
mehrdeutigen Passagen). Beide Mechanismen sind komplementär, keiner
ersetzt den anderen vollständig — für kritische Kennzahlen könnte
Self-Consistency als optionale zusätzliche Stufe (analog zum bereits
opt-in Indirect-Exposure-/Revenue-Catalogue-Muster) sinnvoll sein, statt
das bestehende Extractor/Verifier-Paar zu ersetzen.

### 3.5 L6 — kein Golden Set, keine deterministischen Plausibilitätsregeln, keine Prompt-Versionierung

Das sind drei konkrete, im Code nicht auffindbare Controls aus dem
Vorschlag:

- **Golden Set als Regressionstest.** Es gibt `backend/tests/`, aber keinen
  Mechanismus, der bei jedem Prompt-/Modellwechsel automatisiert gegen
  100–200 manuell verifizierte Referenzextraktionen prüft. Bei einem
  System, dessen zentrales Qualitätsversprechen Präzision ist, ist das die
  einzige Methode, mit der ein Modell- oder Prompt-Update *vor* dem
  Produktivlauf als Regression statt erst im Review sichtbar wird.
- **Deterministische Business-Regeln** (Green Capex ≤ Total Capex,
  YoY-Sprünge > 300% → Flag) — der Vorschlag hat hier den richtigen
  Instinkt ("die Fehlerklasse, für die LLM-Selbstprüfung strukturell blind
  ist"), und das Repo hat mit `grounding.py` bereits genau dieses Muster
  für Zitate etabliert; es fehlt aber das Äquivalent auf Werte-Ebene. Wäre
  ohne größeren Umbau als zusätzlicher, reiner Python-Check nach der
  Aggregation ergänzbar (`arp/extraction/aggregator.py`,
  `financials_aggregator.py`).
- **Prompt-/Modell-Versionierung pro Output.** Es gibt Response-Caching
  (`arp/llm/cache.py`), aber keinen sichtbaren Prompt-Hash/Modellversion
  im persistierten Ergebnis-Datensatz. Für Auditierbarkeit gegenüber
  Aufsicht — das erklärte Alleinstellungsmerkmal dieses Systems gegenüber
  DTM laut eigenem README — ist das eine nicht-triviale Lücke: "bis zur
  Zeichenposition nachvollziehbar" gilt für die Quelle, nicht für "mit
  welcher Prompt-Version wurde das extrahiert".

### 3.6 L7 — Split-Screen vs. Modal

`InspectorModal.tsx` liefert die Quellenansicht als Modal, nicht als
dauerhaft sichtbaren zweiten Bildschirmbereich. Der Vorschlag benennt den
richtigen Skalierungseffekt: bei 4.000 Unternehmen macht jeder zusätzliche
Klick pro Review-Item den Unterschied zwischen "wird tatsächlich geprüft"
und "wird durchgewunken". Das ist eine reine Frontend-Frage, kein
architektonisches Problem — aber bei einem System, dessen Wert explizit
über Reviewbarkeit an Kunden/Aufsicht verkauft wird (README: "ein
Universum, dessen Zusammensetzung sich bis zur Textstelle begründen lässt,
ist verteidigbar"), ist die UX-Reibung im Review-Flow kein kosmetisches
Detail.

### 3.7 Orchestrierung — Temporal ist kein Fehlbetrag, aber die Begründung des Vorschlags trifft real zu

`batch_runner.py::run_batch` erreicht Checkpointing, Resume und
Fehlerisolation bereits mit reinem `asyncio` + JSONL — für den Kernfall
"4.000-Unternehmen-Lauf innerhalb eines Prozesses" ist das eine adäquate,
deutlich einfachere Lösung als Temporal, und in Produktion nachweislich im
Einsatz (Resume-Support in CLI/API dokumentiert). Was fehlt, ist genau der
Fall, den der Vorschlag mit "darf nicht an einem API-Timeout scheitern"
meint, wenn er über einen einzelnen Prozess/Container hinausgeht: kein
Neustart eines Laufs nach Container-/Prozessverlust ohne manuelles
`arp theme resume`, keine Workflow-Visibility-UI unabhängig vom
Run-Store, keine verteilte Ausführung über mehrere Worker. Für den aktuellen
Maßstab (Datei-basiert, ein Prozess) ist das vertretbar; **erst** wenn
Nebenläufigkeit über mehrere Maschinen oder eine Kubernetes-artige
Neustart-Semantik gebraucht wird, zahlt sich der Umstieg auf Temporal/
Prefect aus — vorher wäre es Overengineering gegenüber dem, was bereits
funktioniert.

## 4. Zur pgvector/Postgres-Empfehlung speziell

Der Vorschlag begründet pgvector mit relationalen Joins
(Unternehmen↔Themen↔Datenpunkte↔Holdings) *und* Vektorsuche in einem
System. Das Repo läuft komplett dateibasiert (`runs/`, `taxonomies/`,
`portfolios/`, SQLite nur als Content-Cache für geparste Dokumente,
`document_store.py`) — bewusst, laut README ("no database"). Das ist bei
der aktuellen Betriebsform (Batch-Runs, Review-Queue pro Run, kein
Live-Multi-User-Concurrent-Write auf dieselben Datensätze) kein Rückstand,
sondern eine bewusste, für den Auditierbarkeits-Anspruch sogar passende
Entscheidung: JSONL-Append-Only-Historien (`review_queue.py`: "Decisions
are appended, never mutated in place") sind einfacher lückenlos zu
auditieren als UPDATE-Statements. Der Punkt im Vorschlag, an dem die
Postgres-Empfehlung real zieht, ist **Portfolio Risk & Exposure Monitoring**
(vorhanden, `arp/portfolio/`) — sobald Holdings über viele Portfolios,
Zeitpunkte und Emittenten hinweg abgefragt werden sollen (die Kernaufgabe
von L6/Analytics dort), sind das genau die relationalen Join-Muster, für
die ein Dateisystem schlecht skaliert. Eine selektive Migration nur dieses
Teilbereichs auf Postgres (Holdings/Positionen/Zeitreihen), ohne die
Run-/Review-Historie der anderen Tools anzufassen, wäre der pragmatischere
Schnitt als der im Vorschlag suggerierte einheitliche Store für alles.

## 5. Priorisierte Empfehlungen

Sortiert nach Verhältnis Hebel (Präzision/Auditierbarkeit) zu Aufwand:

1. **Kritiker-Modell entkoppeln** (3.3): zweite Modell-Config für alle
   `*_verifier_agent.py`-Pfade. Kleinste Änderung mit dem direktesten
   Bezug zum erklärten Präzisionsanspruch des Systems.
2. **Prompt-/Modellversion in jeden persistierten Datensatz schreiben**
   (3.5) — Voraussetzung für ein Golden Set und für den vom README selbst
   beanspruchten Audit-Standard.
3. **Golden Set + Regressionslauf bei Prompt-/Modelländerung** (3.5) —
   ohne das ist jede der beiden vorherigen Maßnahmen nur halb wirksam.
4. **XBRL-Fact-Loader vor L4b für EDGAR-Filer** (3.1) — reduziert Kosten
   und Fehlerfläche genau dort, wo strukturierte Daten bereits vorliegen.
5. **Hybrid-Retrieval-Flag validieren und ggf. auf ein multilinguales
   Embedding-Modell wechseln** (3.2) — Infrastruktur existiert, es fehlt
   nur die Validierung, die das Flag selbst als Voraussetzung nennt.
6. **Split-Screen statt Modal im Review** (3.6) — reine Frontend-Änderung,
   wirkt sich aber direkt auf die tatsächliche Review-Quote bei 4.000
   Unternehmen aus.
7. **Deterministische Plausibilitätsregeln nach der Aggregation** (3.5).
8. **Selektive Postgres-Migration nur für Portfolio/Holdings** (4), nicht
   für Run-/Review-Historie.

Explizit *nicht* empfohlen, jedenfalls nicht vor Erreichen einer
Mehrprozess-/Mehrmaschinen-Skalierung: Umstieg von `asyncio`+JSONL auf
Temporal/Prefect (3.7) und ein einheitlicher Postgres/pgvector-Store für
alle sieben Layer (4) — beides adressiert Probleme, die dieses System bei
seiner heutigen Betriebsform (dateibasierte Runs, ein Prozess pro Batch)
noch nicht hat, und beides würde den "no database" / Datei-basierten
Audit-Trail-Ansatz aufgeben, der aktuell gerade zur Auditierbarkeits-These
des Projekts passt.
