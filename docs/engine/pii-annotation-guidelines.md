# PII-Annotationsrichtlinie (Gold-Standard)

> Zweck: eine **konsistente Wahrheit** für den Benchmark. Für jede Textstelle beantwortest du drei
> Fragen — **Ist es PII? Welcher Typ? Wo genau (Rand)?** Diese Richtlinie legt die Antworten fest,
> damit zwei Durchgänge (oder zwei Personen) dieselbe Gold-GT ergeben.
>
> Gilt für das Profil `review-heavy` (die Typen unten). Annotiert wird in der **Dev-Ansicht** der App.

## Die goldene Regel

Markiere **genau den Wert, der pseudonymisiert werden müsste** — als *eine* logische Einheit,
**ohne** Feld-Label, **ohne** angrenzende Felder, **ohne** Rand-Satzzeichen.

> Faustregel für den Rand: Es ist der Teil, den man **ersetzen** würde, damit die Person/Sache nicht
> mehr identifizierbar ist, der Satz aber sonst intakt bleibt.

## Span-Konventionen (die Ränder) — das Wichtigste

1. **Nur der Wert, nicht das Label.** `E-Mail: max@x.at` → markiere nur `max@x.at`.
   `Name: Max Muster` → nur `Max Muster`. `IBAN: AT61…` → nur `AT61…`.
2. **Ganze logische Einheit.** Eine Adresse = Straße + Nr + PLZ + Ort als **ein** Span. Ein Name =
   Vor- + Nachname als **ein** `PERSON`-Span.
3. **Kein Übergreifen in Nachbarfelder.** `Musterstrasse 12, 1010 Wien. E-Mail` → das `. E-Mail`
   gehört zum nächsten Feld → **nicht** mitmarkieren.
4. **Keine Rand-Satzzeichen/Leerzeichen.** Ein `.`, `,`, `)` oder Leerzeichen am Anfang/Ende gehört
   nicht dazu.
5. **Eine Entity pro Wert.** Zwei getrennte Werte nie zu einem Span zusammenfassen (auch nicht, wenn
   sie nebeneinander stehen).

## Deine Frage: Was ist eine ADDRESS?

Die **vollständige Postanschrift als ein Span**: Straße + Hausnummer + PLZ + Ort — weil genau das
zusammen die Person verortet und zusammen pseudonymisiert werden muss.

| Fall | Span |
| --- | --- |
| **Richtig** — vollständig | `Musterstrasse 12, 1010 Wien` |
| **Falsch** — zu kurz (PLZ+Ort weggelassen, obwohl vorhanden) | `Musterstrasse 12` |
| **Falsch** — Nachbarfeld mitgegriffen (dein Screenshot, Offset 28–63) | `Musterstrasse 12, 1010 Wien. E-Mail` |

**Sonderfälle:**
- Steht **nur** die Straße oder **nur** `PLZ Ort` da → markiere das Vorhandene.
- Stehen Straße und Ort auf **verschiedenen Zeilen** weit auseinander und ein zusammenhängender Span
  ist nicht möglich → markiere den **zusammenhängenden Adressblock** (ein Span kann keinen fremden
  Text überspringen).

## Typen im Detail (Profil `review-heavy`)

### Namen & Organisationen
| Typ | Definition | Rand-Konvention | Beispiel |
| --- | --- | --- | --- |
| `PERSON` | Eine natürliche Person | Vor+Nachname als ein Span; **Titel/Anrede weglassen** | richtig `Max Mustermann`; falsch `Mag. Max Mustermann`, `Herr Max Mustermann` |
| `ORGANIZATION` | Firma/Behörde/Kanzlei | Voller Name **inkl. Rechtsform** (GmbH/AG) | z. B. `Sachverständigenbüro Müller GmbH` |

> **Wichtig:** Ein Firmenname im **Briefkopf** oder in einer Section-Überschrift ist **PII** — *nicht*
> als „Überschrift" verwerfen. (Das ist genau der Fall, der die Struktur-Stufe defensiv macht.)

### Adresse & Kontakt (Zeilen-Typen)
| Typ | Definition | Rand-Konvention |
| --- | --- | --- |
| `ADDRESS` | Postanschrift | Straße + Nr + PLZ + Ort als ein Span (siehe oben) |
| `CONTACT_LINE` | Eine kombinierte Kontaktzeile (Tel/Fax/E-Mail als Zeile) | Nur wenn als Zeile erkannt; sonst die Einzelwerte einzeln |
| `CUSTOMER_LINE` | Kundenkennzeile (Name/Nr kombiniert) | Die erkannte Zeile ohne führendes Label |

### Strukturierte Identifikatoren
| Typ | Beispiel-Wert (nur der Wert markieren) |
| --- | --- |
| `EMAIL_ADDRESS` | `max.mustermann@example.at` (kein `mailto:`, kein Label) |
| `PHONE_NUMBER` | `+43 664 1234567` (Vorwahl + interne Leerzeichen/Bindestriche gehören dazu) |
| `IBAN_CODE` | `AT61 1904 3002 3457 3201` (mit/ohne Leerzeichen, wie im Text) |
| `CREDIT_CARD` | die Kartennummer exakt |
| `IP_ADDRESS` | `192.168.0.10` |
| `URL` | `https://example.at/pfad` exakt |

### Österreich / Domain-Identifikatoren — **P3, Leak-kritisch: hier besonders genau**
| Typ | Was |
| --- | --- |
| `SVNR_AT` | Sozialversicherungsnummer (10-stellig) |
| `UID_AT` | UID (`ATU12345678`) |
| `FN_AT` | Firmenbuchnummer (`FN 123456 a`) |
| `TAX_ID_AT` | Steuernummer |
| `BIC` | Bank-BIC (`BKAUATWW`) |
| `LICENSE_PLATE_AT` | Kfz-Kennzeichen |
| `PASSPORT_NUMBER` / `ID_CARD_NUMBER` | Reisepass- / Personalausweisnummer |
| `POLICY_NUMBER`, `CLAIM_NUMBER`, `CONTRACT_NUMBER`, `CASE_NUMBER`, `INVOICE_NUMBER`, `OFFER_NUMBER`, `CUSTOMER_NUMBER`, `FILE_REFERENCE`, `REPORT_NUMBER`, `ASSESSMENT_NUMBER`, `PROJECT_ID`, `TRANSACTION_ID`, `USER_ID` | der jeweilige Nummern-/ID-Wert (z. B. `POL-2024-998877`), **ohne** Label |

### Datum & Kontext
| Typ | Hinweis |
| --- | --- |
| `DATE_TIME` | Ein Datum/eine Zeit (`13.07.2026`). Generisch = schwaches PII; trotzdem markieren. |
| `BIRTH_DATE` | Geburtsdatum — **sensibler** als DATE_TIME. Kein Recognizer → **manuell hinzufügen**. |
| `BIRTH_PLACE` | Geburtsort — kein Recognizer → **manuell hinzufügen**. |

> Vier Typen haben **keinen** Detektor und erscheinen daher nie automatisch — nur über *Manuell
> hinzufügen*: `BIRTH_DATE`, `BIRTH_PLACE`, `GIVEN_NAME`, `FAMILY_NAME`. Standard: einen Namen als
> **`PERSON`** annotieren (nicht in Vor-/Nachname splitten), außer du willst diese Typen gezielt
> aufbauen.

## Was NICHT PII ist (→ `false_positive`)
- **Feld-Labels/Überschriften selbst**: `Rechnungsnummer`, `Leistungen und Positionen` (das Label,
  nicht der Wert).
- Generische Wörter, Produktnamen, reine Beträge/Preise, Prozentangaben.
- Allgemeine Datumsangaben ohne Personenbezug (Ermessen).
- **Aber:** ein Firmen-/Personenname bleibt PII, auch wenn er wie eine Überschrift aussieht.

## Über-Erfassung (falscher Rand) behandeln — wichtig für die Struktur-Messung

Wenn der Detektor **zu viel** gegriffen hat (dein Screenshot):

1. **`false_positive`** auf die erkannte Entity setzen (sie hat den falschen Rand), **und**
2. **Manuell hinzufügen** des sauberen Spans (`Musterstrasse 12, 1010 Wien`).

> Nur „keep" würde den *falschen* Rand als Wahrheit festschreiben — dann sähe später ein korrekter
> Clip fälschlich wie ein Fehler aus. Alternativ/zusätzlich das dev-Feedback nutzen:
> „Problem auswählen" → `span_too_long_right`.

## Entscheidungs-Spickzettel
| Situation | Aktion |
| --- | --- |
| Echtes PII, Rand korrekt | Bindende Entscheidung: **Pseudonymisieren** (oder **Keep**) |
| Kein PII | Bindende Entscheidung: **false_positive** |
| Rand zu lang/falsch | **false_positive** + **Manuell hinzufügen** (korrekter Span) |
| Übersehenes PII | **Manuell hinzufügen** |
| Unsicher | Dev-Feedback „Problem auswählen" + Kommentar (**kein** Rohtext); im Zweifel **als PII behalten** — bei Datenschutz zählt Recall vor Precision |

## Zwei Prinzipien zum Merken
1. **Rand = nur der Wert, die ganze Einheit, nichts Fremdes.**
2. **Im Zweifel schützen:** lieber eine Entity zu viel bestätigen als eine echte übersehen — ein Miss
   ist ein Leak.
