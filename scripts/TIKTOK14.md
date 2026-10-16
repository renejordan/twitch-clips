# TikTok14: Sicherheitsprüfung und nächste Freigabestufe

Stand: 16. Oktober 2026. Zielkonto: **@ufo3103**.

## Aktueller Status

**Kein betriebsbereiter Auto-Publisher.** Diese Änderung ist eine Sicherheitsstufe,
keine Fertigstellung der gewünschten 14 täglichen Veröffentlichungen. Sie entfernt
den unbestätigten Browser-Uploadpfad vorläufig. `preflight`, `reserve` und `upload`
enden absichtlich mit Exitcode 3, bevor Zugangsdaten, Dateien oder Netzwerkzugriffe
für einen Upload verwendet werden. Auch `TIKTOK14_ENABLED=true` hebt diese Sperre
nicht auf. Der Workflow erhält nur Leserechte und keine TikTok-Secrets.

Die bestehende Datei `.github/workflows/tiktok.yml`, `state/auto20.json`, Releases
und Metricool-Konfiguration werden durch diese Änderung nicht verändert.

Der bisherige Actions-Lauf [#1](https://github.com/renejordan/twitch-clips/actions/runs/38862047466)
prüfte ausschließlich Offline-Selbsttests: `validate` erfolgreich, `auto14`
übersprungen. Er belegt weder eine gültige TikTok-Anmeldung noch ein veröffentlichtes Video.
Im geprüften Hauptstand liegen weder `state/auto14_queue.json` noch
`state/auto14_publish.json`. Nach der Anmeldung als Repository-Eigentümer wurde
`TIKTOK14_ENABLED=false` direkt in den GitHub-Einstellungen bestätigt.
Es sind keine Repository- oder Environment-Secrets hinterlegt. Secret-Werte
wurden weder angefordert noch gelesen. Der Connector verweigerte Schreibzugriffe
mit 403; der getrennte Änderungsvorschlag wird über die angemeldete GitHub-Weboberfläche
eingereicht. Eine zusätzliche App-Installation ist dafür nicht erforderlich.

## Nachgewiesene Probleme des bisherigen Stands

- `tiktok-uploader==1.2.0`: `_set_video` verwendet `range(num_retries)`.
  Mit dem übergebenen Wert `0` wird die Datei nie ausgewählt. Der tatsächliche
  Paketcode wurde ohne Ausführung einer Browseranmeldung untersucht und diese
  Null-Durchlauf-Bedingung isoliert reproduziert.
- Derselbe Paketcode druckt Cookie-Werte in `auth.py`. Die bisherige Umleitung der
  Ausgabekanäle war kein Nachweis für vollständig geschützte Zugangsdaten über den
  gesamten Prozess, Unterprozesse und eventuelle Diagnoseartefakte.
- `account_expected='@ufo3103'` war nur ein Journaleintrag. Eine Prüfung der
  tatsächlich angemeldeten Identität fehlte.
- `reported_success_unverified` erlaubte weitere Versuche. Jetzt stoppen alle
  nicht unabhängig bestätigten Zustände auch nach Ablauf eines Tages.
- Ein fester Produktionsdeckel von 430 reicht für 31 × 14 = 434 nicht aus.
  Die isolierte Produktion berechnet nun 14 × Kalendertage des Monats.
- Der neue Producer las bei alten Clips nur `processed_ids`; ältere Datensätze
  enthalten teilweise ausschließlich `created`-IDs und Quell-URLs. Diese werden
  jetzt ebenfalls ausgeschlossen.
- Der alte Auto20-Producer kennt TikTok14 weiterhin nicht. Die beiden Workflows
  besitzen unterschiedliche Sperren; parallele Auswahl desselben Clips bleibt
  deshalb möglich. Einseitiges Ausschließen und `git pull --rebase` lösen dieses
  Problem nicht. Das ist ein offener Grund für die Uploadsperre.
- Naive Zeitstempel, zukünftige Reservierungen und manipulierte Release-Pfade
  werden in den Offline-Prüfungen nun abgewiesen. Ein künftiger Downloader benötigt
  zusätzlich eine kontrollierte Redirect-Kette, Größen- und Medienprüfung.

## Scheduler und Kosten

`33 * * * *` bietet nominell 24 Startgelegenheiten pro Tag in UTC, jeweils höchstens
eine Produktion bzw. ein Upload im bisherigen Entwurf. GitHub kann geplante Läufe
verzögern oder auslassen. Die jüngsten alten Auto20-Schedule-Läufe kamen deutlich
seltener als stündlich. Offline-Tests beweisen weder Scheduler-Zuverlässigkeit noch
eine Kapazität von 14 gerenderten, freigegebenen Videos pro Tag.

Der Code begrenzt höchstens 14 Versuche pro rollierenden 24 Stunden und Berliner
Kalendertag; er garantiert keine erfolgreichen Posts. Diese Zahl umfasst noch
nicht Veröffentlichungen über Metricool oder manuell. Vor Livebetrieb braucht es
eine gemeinsame Kontierung aller Routen und ein niedrigeres Limit, falls TikTok
es für das Konto vorgibt. Keine Wiederholung bei unbekanntem Ergebnis, CAPTCHA,
Authentifizierungsfehler oder Plattformlimit.

Standardrunner sind für öffentliche Repositorys nach den aktuellen
[GitHub-Abrechnungsregeln](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
kostenlos. Daraus folgt keine Garantie für eine dauerhaft kostenlose Gesamtlösung;
Release-Speicher, Laufzeit, Plattformregeln und externe Dienste bleiben gesondert zu prüfen.

## Voraussetzungen für den nächsten echten Test

1. Eine unterstützte sichere Anmeldemethode festlegen. Eine reguläre interaktive
   Anmeldung erfolgt direkt auf TikTok; keine Passwörter, Session-Cookies oder
   Token in Chat, Repository, öffentliche Logs, Screenshots oder Actions-Artefakte
   übernehmen. Ein zukünftiger Adapter muss die Identität **vor** Dateiübertragung
   zuverlässig als @ufo3103 bestätigen und bei Unklarheit stoppen.
2. Eine atomare gemeinsame Reservierung und eindeutige Clip-Identität für alle
   aktiven Veröffentlichungsrouten entwerfen. Ohne Änderung der alten Pipeline
   erfordert das eine nachweislich überschneidungsfreie Quelle oder eine andere
   gemeinsam wirksame Koordination. Keine vorhandenen Auto20-Zustände überschreiben.
3. Einen konkreten Clip einschließlich Bild, Ton, Untertiteln, Caption und
   Veröffentlichungsrechten prüfen. Dann einen getrennten manuellen Einmal-Test
   implementieren; der Stundenplan bleibt ausgeschaltet. Dieses PR führt diesen
   Test ausdrücklich noch nicht aus.
4. Ergebnis direkt bei TikTok prüfen: richtiges Konto, eindeutige Video-ID bzw.
   URL, tatsächlich gewünschte Sichtbarkeit und abgeschlossene Verarbeitung.
   Eine Rückgabe `True` der Browserbibliothek reicht nicht. Auch das Wiederanlaufen
   nach einem Absturz zwischen Upload und Speicherung muss sicher bleiben.
5. Erst nach erfolgreicher Prüfung den Scheduler stufenweise aktivieren und
   Fehler-/Limitstopps testen. Keine Umgehung von TikTok-Limits oder Challenges.

Die offizielle [Content Posting API](https://developers.tiktok.com/docs/en/content-posting-api-get-started)
benötigt App- und Nutzerautorisierung. Nicht auditierte Clients sind auf private
Sichtbarkeit beschränkt. Die [TikTok-Richtlinien](https://developers.tiktok.com/doc/content-sharing-guidelines/)
nennen kontospezifische, über API-Clients geteilte Postinglimits und Einschränkungen
für interne Upload-Utilities. Sie ist deshalb keine automatisch verfügbare
Ersatzlösung für unbeaufsichtigte öffentliche Posts auf dem eigenen Konto.

## Offline-Prüfung

```sh
python scripts/tiktok14_prepare.py --test
python scripts/tiktok14_publish.py selftest
python -m unittest discover -s tests -v
```

Diese Prüfungen laden keine Medien oder Zugangsdaten und veröffentlichen nichts.
Die Zeichenkettenprüfungen beim Extrahieren der alten Inline-Pipeline stoppen
absichtlich, wenn sich deren erwartete Struktur ändert. Langfristig ist ein
eigenständiger Producer stabiler; die alte Pipeline wird hier nicht umgebaut.
