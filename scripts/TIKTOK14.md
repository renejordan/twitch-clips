# TikTok14: eigenständiger Buffer-Publisher

Die neue Route verarbeitet freigegebene Twitch-Gaming-Clips für @ufo3103.
Auf ausdrücklichen Nutzerauftrag läuft sie ohne Metricool-Abgleich. Die
bestehende Auto20-Pipeline, ihre Zustandsdatei und Metricool-Einstellungen
werden nicht geändert.

## Ablauf

Der stündliche GitHub-Zeitplan bietet 24 Startgelegenheiten, verarbeitet pro
Lauf höchstens einen neuen Clip und begrenzt die eigene Route auf 14 Versuche
im Berliner Kalendertag und in rollierenden 24 Stunden. Tage mit 25 Stunden
werden berücksichtigt. Der bestätigte Einzeltest vom 16.10.2026 wird als
bereits veröffentlicht initialisiert und nicht erneut verwendet.

scripts/tiktok14_config.json enthält die ausdrücklich erklärte vorhandene
50er-Quellenliste und accounting_mode independent. Die Erlaubniserklärung
wurde nicht unabhängig bei den Erstellern verifiziert. Der tatsächliche
Twitch-Broadcaster muss dem jeweiligen Quellkanal entsprechen. Clips müssen
höchstens 72 Stunden alt sein; bestehende Mindestmetriken, Originallänge,
automatisch erzeugte echte Untertitel und 1080x1920-Prüfungen bleiben erhalten.

scripts/tiktok14_cloud.py verwendet die getrennte generierte Produktion,
stellt das MP4 in einem eigenen öffentlichen GitHub Release bereit und
übermittelt die URL über die Buffer-API. Lokale Dateiauswahl oder ein laufender
Nutzer-PC sind für diesen GitHub-Ablauf nicht nötig. Öffentliche Mediendateien
werden vor dem Senden anhand ihrer SHA-256 geprüft. Bestehende Assets werden
nicht überschrieben. Ein Fehler beim Hosting oder dauerhaften Speichern beendet
die Kandidatenschleife, statt weitere Releases nach einem Zustandsfehler anzulegen.

Bekannte Auto20-Clip-IDs und Slugs werden aus dessen aktuellem Zustand nur
gelesen und ausgeschlossen. Eine erkannte laufende Auto20-Produktion wird
übersprungen. TikTok14 verwendet eine eigene Ausführungssperre; es verdrängt
keine wartenden Auto20-Läufe. Da Auto20 unverändert bleibt und Metricool nicht
abgeglichen wird, ist ein späterer erneuter Vorschlag durch die alte Route
nicht global ausgeschlossen. Die neue Route verhindert ihre eigenen Dubletten.

## Veröffentlichung und Zustand

Ein separater verwaister Git-Zweig tiktok14-state enthält ausschließlich
state.json. Er enthält keine Kopie der Workflow-Dateien und löst damit nicht
versehentlich die alte Push-Produktion aus. Jeder Schreibzugriff verlangt die
vorherige GitHub-Dateiversion. Ein bestehender beschädigter Zustand wird nicht
neu initialisiert oder überschrieben.

Vor jedem Senden wird dauerhaft reserviert. Nach verlorenem Ergebnis erfolgt
kein erneutes Senden. Der Worker gleicht bekannte Buffer-IDs und eindeutige
Mediennamen ab. Erst Buffer sent plus exaktes Zielkonto, TikTok-Video-ID und
anonyme offizielle oEmbed-Bestätigung erlauben den Status verified_public.
Unbekannte Ergebnisse sperren weitere Posts. Nach einem neuen Post erfolgen
höchstens drei lesende Statusprüfungen im Abstand von jeweils einer Minute;
danach bleibt die Reservierung für den nächsten Abgleich bestehen.

Der bereits belegte [Einzeltest](https://www.tiktok.com/@ufo3103/video/7697189362877992225)
ist Buffer-Post 6ad1e7e9e7970040db23ebed, veröffentlicht 16.10.2026 09:07:25 UTC.
TikTok Studio bestätigte Konto ufo3103, 18 Sekunden und Alle; anonymes oEmbed
bestätigte dieselbe Video-ID. Dieser Clip bleibt dauerhaft ausgeschlossen.

## Steuerung

- Der Repository-Schalter TIKTOK14_ENABLED steuert ausschließlich geplante
  regelmäßige Läufe auf main. Das Setzen allein ersetzt keine Inbetriebnahme.
- Manueller Modus prepare erzeugt höchstens einen Kandidaten ohne TikTok-Post.
  Er ist auf main und dem festgelegten geprüften Entwurfszweig verfügbar.
- Manueller Modus commission veröffentlicht bzw. klärt auf main genau einen
  reservierten Post. Veröffentlichungen vom Entwurfszweig sind im Workflow
  und im Python-Einstieg gesperrt.
- Pushes und Pull Requests führen nur Offline-Tests aus. Der alte Cookie-
  Uploader bleibt abgeschaltet; dessen frühere preflight/reserve/upload-
  Einstiege enden weiterhin mit Exitcode 3. Der neue Einstieg ist cloud.py.

Der Workflow hat standardmäßig Leserechte. Nur der Cloud-Job erhält contents:
write für seinen eigenen Zustand und Releases sowie actions:read zur lesenden
Erkennung von Auto20-Läufen. Medienwerkzeuge werden vor der Bereitstellung
von Service-Secrets installiert. BUFFER_API_KEY ist ausschließlich im
Veröffentlichungsschritt vorhanden. Medien-Unterprozesse bekommen keine
Buffer-, GitHub- oder TikTok-Zugangsdaten; nur der feste GitHub-Hostingaufruf
erhält dessen scoped GitHub-Token. Keine Cookie-Exporte oder geheimen Werte
in Logs, Chat oder Artefakten. Authentifizierte HTTP-Redirects sind gesperrt.

## Grenzen und Prüfungen

Die 14er-Grenze zählt die neue Route. Metricool und manuelle Posts können
zusätzlich stattfinden und sind kein Bestandteil dieses Zählers. Es wird
keine Vollständigkeit einer gemeinsamen Historie behauptet. Buffer-Quoten
und tatsächliche TikTok-Ablehnungen gehen vor; keine Limitumgehung oder
automatische Sende-Wiederholung. Challenges, Authentifizierungsfehler,
ungeklärte eigene Ergebnisse und ungeeignete Clips stoppen den Ablauf.
Täglich 14 erfolgreiche Posts sind wegen Quellenangebot, Ausfällen und
Plattformgrenzen nicht garantiert. Es wird kein kostenpflichtiger Dienst
eingerichtet. Die Codex-Aufgabe überwacht ausschließlich diesen Publisher.

```sh
python scripts/tiktok14_prepare.py --test
python scripts/tiktok14_publish.py selftest
python -m unittest discover -s tests -v
```

67 Offline-Tests und beide Selbsttests bestehen am lokal geprüften Stand.
Die Tests veröffentlichen nichts und verwenden keine echten Zugangsdaten.
Inbetriebnahme verlangt zusätzlich einen geprüften GitHub-Produktionslauf
und einen bestätigten Cloud-Upload vor der regelmäßigen Aktivierung.
