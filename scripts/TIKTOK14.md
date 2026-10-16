# TikTok14: geprüfter Einzeltest, Dauerbetrieb noch gesperrt

Stand: 16. Oktober 2026 · @ufo3103 · renejordan/twitch-clips

## Belegter Stand

- Der GitHub-Buffer-Verbindungstest [#14](https://github.com/renejordan/twitch-clips/actions/runs/38870139971) war erfolgreich.
- Der Buffer-Schlüssel ist bereits als GitHub-Secret BUFFER_API_KEY eingerichtet. Sein Wert wurde nicht ausgelesen oder protokolliert.
- Der bestätigte 18-Sekunden-Rewinside-Testclip 761785150 wurde genau einmal veröffentlicht. Buffer-Post: 6ad1e7e9e7970040db23ebed, sent am 16.10.2026 um 09:07:25 UTC.
- [TikTok-Testbeitrag](https://www.tiktok.com/@ufo3103/video/7697189362877992225): TikTok Studio bestätigt Konto ufo3103 und Sichtbarkeit Alle. Zusätzlich bestätigt anonymes offizielles TikTok-oEmbed das exakte Konto und dieselbe Video-ID. Diesen Clip niemals erneut senden.
- TIKTOK14_ENABLED bleibt false. Die alte Datei .github/workflows/tiktok.yml und state/auto20.json sind unverändert.

## Was dieser Entwurf implementiert

Der unbestätigte Cookie-/Browser-Uploader wurde aus dem aktiven Pfad entfernt.
preflight, reserve und upload in tiktok14_publish.py enden weiter mit Exitcode 3.
Ein eingeschalteter Repository-Schalter allein kann diese Sperre nicht umgehen.
Der aktuelle Workflow enthält ausschließlich Offline-Tests und einen manuell
ausgelösten, lesenden Buffer-Verbindungstest. Er besitzt keine Live-Upload-Stufe.

tiktok14_services.py begrenzt HTTP-Ziele, verhindert Weiterleitungen mit Tokens,
begrenzt Antwortgrößen und gibt feste Fehlercodes statt Serverdetails zurück.
Buffer-Zugriffe sind auf das bestätigte Konto festgelegt. Der GitHub-Zustand
gehört auf einen eigenen verwaisten Zweig tiktok14-state, der ausschließlich
state.json enthält. Keine Kopie von main: Sie könnte den alten Push-Trigger
auslösen. Zustandsänderungen verlangen die vorherige GitHub-Dateiversion.

tiktok14_worker.py ist eine noch nicht mit einem Live-Einstieg verbundene
Steuerung. Vor jedem Senden wird eine Reservierung dauerhaft gespeichert.
Netzwerkfehler werden nicht automatisch erneut gesendet. Bekannte Buffer-IDs
werden gelesen, unbekannte Ergebnisse anhand eines eindeutigen Mediennamens
abgeglichen; Mehrdeutigkeit stoppt. sent allein reicht nicht: Konto, Video-ID,
Zeitpunkt und öffentliche TikTok-oEmbed-Bestätigung müssen passen.

Der Controller prüft Quellen, verarbeitete IDs, Mediennamen, Kanalzustand,
Buffer-Quoten, vollständige Abfrageseiten und 14 Versuche im Berliner
Kalendertag bzw. rollierenden 24 Stunden. Er verlangt zusätzlich eine frische,
unabhängige und vollständige Beobachtung anderer Veröffentlichungswege. Einen
solchen automatischen Beobachter gibt es in diesem Entwurf noch nicht.
Keine Datei mit erfundenem complete=true als Ersatz verwenden.

Die isolierte Clip-Produktion berücksichtigt alte created-IDs und Quell-Slugs,
berechnet 14 × Kalendertage statt eines festen Monatslimits von 430 und prüft
den tatsächlichen Broadcaster des Twitch-Originals. Der Zuschauer, der den Clip
erstellt hat, ist kein Nachweis für den freigegebenen Ursprungskanal.

## Offene Inbetriebnahme

Der vollständige Cloud-Ablauf aus Suche, Bearbeitung, Media-Hosting und Upload
ist noch nicht angeschlossen. Normale Läufe sollen öffentliche GitHub-Release-
MP4-Adressen an Buffer übergeben; lokale Dateiauswahl ist dafür nicht vorgesehen.
Ein Cloud-Medienentwurf und die erste reguläre Ausführung sind noch zu prüfen.

Die vorhandene 50er-Quellenliste überschneidet sich vollständig mit Auto20.
Der neue Controller sperrt solche Überschneidungen derzeit. Die alte Produktion
kann später neue TikTok14-Clips erneut auswählen, solange sie deren Journal
nicht kennt. Ein konkreter Vorschlag für eine kleine gemeinsame Dublettenprüfung
liegt lokal vor; die ursprüngliche Vorgabe, Auto20 unverändert zu lassen,
bleibt bis zu einer ausdrücklichen Entscheidung bestehen.

Ein am 16.10.2026 über Metricool bestätigter öffentlicher Beitrag mit TikTok-ID
7697173656920771862 fehlt im geprüften Buffer-Verlauf. Buffer-Importe und sein
Tageszähler sind deshalb kein vollständiger Kontonachweis. Ein kostenloser
verlässlicher Abgleich bzw. eine bestätigte sichere gemeinsame Planung ist
vor Aktivierung erforderlich. Keine niedrigeren Grenzen umgehen oder 14
zusätzliche Buffer-Posts bei gleichzeitigem Alt-Betrieb versprechen.

## Tests

```sh
python scripts/tiktok14_prepare.py --test
python scripts/tiktok14_publish.py selftest
python -m unittest discover -s tests -v
```

Aktuell 53 lokale Unit-Tests und beide Selbsttests erfolgreich. Die Tests
verwenden keine Zugangsdaten und veröffentlichen nichts. Sie sind kein
Nachweis für einen fertigen Dauerbetrieb. Der bestehende Entwurfs-PR wird
weiter geprüft; main wurde nicht geändert.

## Betrieb und Grenzen

Die stündliche Codex-Aufgabe überwacht die Inbetriebnahme und darf keinen
zweiten Publisher neben einem späteren GitHub-Worker bilden. Bei unverändertem
Zustand bleibt sie still. Scheduler können verspätet laufen oder ausfallen;
aus 24 Startgelegenheiten folgt keine Zusage von 14 erfolgreichen Posts.
Authentifizierungsfehler, unbekannte Ergebnisse, unvollständige Historie,
Challenges, Quoten und fehlende zulässige Clips stoppen den Ablauf.

[Buffer API](https://developers.buffer.com/guides/getting-started.html),
[öffentliche MP4-Adressen](https://developers.buffer.com/examples/create-video-post.html),
[TikTok oEmbed](https://developers.tiktok.com/docs/en/embed-videos),
[GitHub-Zeitpläne](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
