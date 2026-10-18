# Buffer-Publisher: bis zu 15 geprüfte TikToks täglich

ChatGPT bleibt die bestehende Kontrolle; GitHub erstellt und versendet auf seinen Servern. Ein eingeschalteter persönlicher Rechner ist für diesen Cloudbetrieb nicht erforderlich. Ziel: höchstens ein neuer Post pro Stunde von 09 bis 23 Uhr Berlin, maximal 15 pro Berliner Kalendertag UND in rollierenden 24 Stunden. Geeignete Clips, Plattformgrenzen und Serververfügbarkeit begrenzen den tatsächlichen Durchsatz.

## Cloud-Zeitgeber

tiktok14_clock.yml betreibt einen begrenzten fünfstündigen Zeitgeber mit dem kurzlebigen GitHub-Jobtoken. Er liest aktive Publisher und den Zustand, bietet stündliche Starts an und gleicht offene Sends auch nachts ab. Vor Ende startet er genau einen Nachfolger. Ein manueller Lauf mit duration_minutes=5 prüft die Übergabe an einen regulären 300-Minuten-Nachfolger.

Native Cron-Starts bleiben Wiederanlaufmöglichkeiten: Clock alle drei Stunden, Publisher um Minute 11,31,51. GitHub kann auch diese Starts verzögern oder auslassen. Bei gescheiterter Übergabe kann bis zum nächsten tatsächlich zugestellten Watchdog-Start eine Lücke bleiben. Keine Massen-Uploads zur Nachholung alter Stunden.

Keine persönlichen Dauertokens, lokalen Dauerprozesse, kostenpflichtigen Modelle oder zusätzlichen Hosting-Verträge. Öffentliche Standardrunner und freie CPU-Modelle werden genutzt; bezahlte Runner oder Cacheerweiterungen werden nicht eingeschaltet. Der Clock erhält keinen Buffer-Zugang.

## Dauerhafter Zustand und Dubletten

Der separate Branch tiktok14-state enthält state.json. Jeder Schreibzugriff verlangt die vorherige Dateiversion. Fehlende oder beschädigte Historie muss restauriert werden und wird niemals unvollständig neu initialisiert. Alle produktiven Jobs teilen über Branchgrenzen hinweg eine Concurrency-Gruppe.

Eigener Verlauf und bisheriger Auto20-Zustand werden vor Versand gelesen. IDs, Slugs, Quell-URLs, Medien-/Quellenhashes und bekannte schlechte Clips bleiben gesperrt. Alternative Clips desselben Streamers mit bis zu zwei Minuten Abstand ihrer ursprünglichen Erstellung werden vorsorglich ausgeschlossen. Dies kann unterschiedliche nahe Ereignisse ebenfalls aussortieren; es ist kein universeller Video-Fingerabdruck. Verwendete Queue-Einträge werden archiviert und geben die Suche frei.

Abgelehnte Kandidaten werden einzeln gespeichert, bevor der nächste aufwendig geprüft wird. Ein Runner-Abbruch verliert abgeschlossene Ablehnungen nicht. Nach sieben Tagen werden abgeschlossene Einträge zu permanenten IDs verdichtet; offene Sends bleiben vollständig erhalten. Git bewahrt frühere Detailstände.

Dieser Code verändert keine Auto20-/Metricool- oder Twitch-Aufgabe. Überlappende Quellen verlangen weiterhin den bereits separat stillgelegten Auto20-Workflow disabled_manually; alte aktive Auto20-Jobs sperren neue Übergaben. Die bestehende ChatGPT-Kontrolle bleibt bestehen.

## Tatsächliche Medienprüfung

Die 50er-Quellenliste behält die Rechteerklärung des Kontoinhabers; dies ist keine unabhängig verifizierte Lizenz. 24h-/7-Tage-Listen werden zusammengeführt und Einzelmetadaten frisch geprüft. Broadcaster, Originalalter bis 72h, Dauer 15–60s, mindestens 100 Views und erlaubte Gaming-Kategorie sind Pflicht. Die frühere zusätzliche Views-Hürde für 48–72h alte Clips entfällt. Popularität und Kategorie ersetzen keine Medienprüfung.

Der getrennte Prüfprozess erhält keine Servicezugänge. Modellgewichte und CPU-Laufzeit sind an feste offizielle Revisionen und SHA256-Werte gebunden. Installation und Laufzeit-Gesundheitstest erfolgen vor Bereitstellung der Servicezugänge; ein Cache vermeidet wiederholte große Downloads.

Zwei freie Whisper-Modelle prüfen den vollständigen Ton. Wortuntertitel verlangen vollständige normalisierte Wortübereinstimmung, Konfidenz und passende Zeitstempel. Nach Nutzerfreigabe ist bei unsicherer Sprache title_only erlaubt: null Wortuntertitel, ein allgemeiner überprüfbarer Titel mit dem nachgewiesenen Streamer und kein unsicheres Transkript als Ereignisbeleg. Schlechter oder stark übersteuerter Ton bleibt gesperrt. Technische ASR-Ausfälle werden nicht als Titel-only-Erfolg behandelt.

OCR untersucht zwei tatsächliche Frames pro Sekunde. Geometrie schlägt Textregionen vor; der Bildprüfer unterscheidet HUD/Chat und Dialoguntertitel anhand vollständiger Frames und vergrößerter Ausschnitte. Unterschiedliche Texte derselben Position werden getrennt geprüft. Unklare Rollen oder mehr als 24 Textzustände führen zum technischen Halt. Entfernen vorhandener Untertitel darf keine Handlung zerstören.

Qwen prüft gleichmäßig verteilte Quellframes, frühe Details und zusätzliche Szenenwechsel. Gameplay, verständlicher Aufbau, vollständiger Ausgang, anhaltende Verständlichkeit und angemessene Komposition sind Pflicht. Auch ein Verlust kann ein vollständiger Ausgang sein. Browserrahmen, verschachtelte Wiedergabe, unklare Pointe und ungeprüfte vorhandene Untertitel sperren die Freigabe. Das ist eine Modell-Stichprobenprüfung, keine behauptete vollständige menschliche Sichtung.

Das 1080×1920-Ergebnis wird vollständig decodiert und anhand echter Frames einschließlich Ereignis erneut geprüft. Eine stabil erkannte Facecam kann als eigenes Panel erscheinen; sonst wird zentrales Gameplay vergrößert. Verlorene Handlung sperrt das Ergebnis. Titel-only verlangt einen lesbaren Titel ohne hinzugefügte Wortuntertitel.

## Quittungen, Hosting und Versand

Automatische media_review-Version 2 bindet Quell-, Ergebnis-, Transkript- und Evidenzhashes. Modelle, zeitliche Abdeckung, OCR-Regionen, Textmodus, Ton und visuelle Ergebnisse werden vor Hosting erneut geprüft. Keine Behauptung watched_full_video und keine Freigabe allein durch subtitle_verified.

Manuelle Version 1 bleibt verfügbar: tatsächliche vollständige Sichtung, benannter Prüfer, konkrete Nachweise und exakt passende Medienhashes. Modus review sendet nichts. Rejected archiviert den Entwurf und gibt die Suche frei.

Das Monatsrelease enthält pro Kandidat MP4 und ein Review-ZIP mit Kontaktbildern, Transkript, Vergleich und Evidenz. Zwei Assets je Clip ergeben bei 15×31 Kandidaten 930 Assets; die Kapazität wird geprüft. Existierende Dateien werden nicht überschrieben. Prepare kann öffentliche Reviewdateien anlegen, sendet aber keinen TikTok-Post.

TIKTOK14_ENABLED=true erlaubt geplanten Betrieb und Clock auf main. Automatische Version-2-Posts verlangen zusätzlich TIKTOK14_AUTOREVIEW_ENABLED=true; diese Einstellung bleibt bis zum bestandenen echten Medien-/Inbetriebnahmetest geschlossen.

Buffer muss exakt Organisation, verbundenen/entsperrten Kanal 6ad16c0c778b240e2f21aca5, TikTok @ufo3103, Berlin und video.publish bestätigen. Buffer-Zähler beweisen nicht das kontoübergreifende TikTok-Limit; der eigene 15er-Grenzwert gilt zusätzlich.

Neue Uploads werden vor Übergabe dauerhaft reserviert. Eine verlorene Create-Antwort wird nicht blind wiederholt. Spätere Starts gleichen Buffer-ID und deterministischen Medientitel ab. Erst Buffer sent, passendes Zielkonto/Video und anonymes offizielles TikTok-oEmbed erlauben verified_public. Ungeklärte Ergebnisse sperren neue Sends und zählen nicht als nachgewiesene öffentliche Posts.

Versand nur bis 71h Originalalter als Puffer zur 72h-Grenze. Buffer liefert asynchron ohne garantierte Frist. Verspätetes sentAt wird als late_publication gespeichert und sperrt weitere Posts.

## Bedienung und Diagnose

- diagnose: nur Metadaten; keine Mediendownloads, Zustandsänderungen oder Posts.
- prepare/prefetch: höchstens ein Kandidat bzw. gesperrter Entwurf; kein neuer TikTok-Post.
- auto/commission: nur auf main nach allen Freigaben neuer Send oder Abgleich.
- review: exakt passende manuelle Quittung ohne Buffer-Zugang.
- Entwurfszweige erlauben nur prepare/diagnose.

Zähler stehen in Actions und last_production. Empty: kein neuer geeigneter Metadatenkandidat. Quality_rejected: Inhaltsablehnung. Degraded: technischer Fehler mit späterer Wiederholungsmöglichkeit, maximal drei Suchversuche pro Stunde. Abgeschlossene Suchstunden und Sendreservationen unterdrücken Doppelarbeit. Nach erfolgreichem Versand ist eine Vorbereitung für den nächsten Slot möglich.

Zum Stoppen TIKTOK14_ENABLED deaktivieren und laufende Publisher-/Clock-Jobs prüfen bzw. abbrechen. Eine bereits an Buffer übergebene Veröffentlichung bleibt bis zur Klärung offen. Keine Reservierungen löschen, um diesen Schutz zu umgehen.

~~~sh
python scripts/tiktok14_prepare.py --test
python scripts/tiktok14_publish.py selftest
python -m unittest discover -s tests -v
~~~

Offline-Tests brauchen keine echten Zugangsdaten oder Mediendownloads. Sie beweisen keine tatsächliche Medienqualität, Cloud-Übergabe oder öffentliche Veröffentlichung; diese sind zusätzlich am verwendeten Stand zu prüfen.
