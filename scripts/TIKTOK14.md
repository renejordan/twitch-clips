# Buffer-Publisher: bis zu 15 geprüfte TikToks täglich

Die Dateinamen tiktok14_* bleiben aus Kompatibilitätsgründen bestehen. Das Maximum ist jetzt 15 im Berliner Kalendertag und in rollierenden 24 Stunden. Eigener Versandjournal und in Buffer sichtbare Veröffentlichungen werden nach TikTok-Video-ID zusammengeführt. Eine vollständige unabhängige Historie aller manuellen Posts wird nicht behauptet. Plattformgrenzen können früher greifen; 15 erfolgreiche Posts täglich sind kein zugesicherter Durchsatz.

## Eine Route und geschützte Historie

Auto20 ist nach Nutzerfreigabe im abgestimmten Chat deaktiviert. Push-/Cron-Trigger sind entfernt und sein Job ist zusätzlich gesperrt. Der dort eingebettete Mediengenerator bleibt für den unabhängigen Generator erhalten. Vor neuem Versand prüft cloud.py, dass der überlappende Auto20-Workflow tatsächlich disabled_manually ist und keine alten laufenden oder wartenden Jobs vorhanden sind. Die bisherige Auto20-Zustandsdatei wird nur gelesen. IDs, Slugs, normalisierte Quell-URLs und bekannte verworfene Clips bleiben gesperrt.

Metricool-Einstellungen, Twitch-Aufgaben und bestehende ChatGPT-Kontrolle werden durch diesen Code nicht verändert. Der verwaiste Branch tiktok14-state enthält ausschließlich state.json. Jeder Schreibzugriff verlangt die vorherige Dateiversion. Fehlende oder beschädigte Historie muss aus Git restauriert werden; der Worker legt keinen unvollständigen Anfangszustand neu an.

## Starts und externe Nachholung

GitHub cron bietet um Minute 11, 31 und 51 Startgelegenheiten. GitHub garantiert keine pünktliche oder vollständige Zustellung. Eine abgeschlossene Prüfung wird je UTC-Stunde gespeichert; zusätzliche Starts derselben Stunde scannen nicht erneut. Technisch gescheiterte Prüfungen reservieren die Stunde nicht. Das Versandjournal begrenzt neue Posts auf einen je UTC-Stunde. Ungeklärte Uploads werden bei späteren Starts nur abgeglichen, niemals erneut gesendet. Keine blinden Massen-Uploads für ausgefallene Stunden.

python scripts/tiktok14_dispatch.py liest Zustand und aktive Läufe öffentlich und zeigt nur einen Plan. Erst --dispatch startet bei Bedarf den Workflow auf main im Modus auto. Dafür ist GH_TOKEN mit auf dieses Repository begrenztem Actions-Schreibrecht erforderlich. Keine Tokens in URLs oder Logs. Ein dauerhafter externer Scheduler ist NICHT eingerichtet. Das Skript kann auf einem vorhandenen ständig verfügbaren Scheduler alle 20 Minuten laufen. Ohne diesen Zugang bleibt das Stundenziel durch GitHub cron begrenzt.

## Produktion und tatsächliche Medienprüfung

Die konfigurierte 50er-Quellenliste behält die vorhandene Rechteerklärung des Kontoinhabers. Diese ist keine unabhängig verifizierte Lizenz. Metadaten müssen den Broadcaster belegen; creators-Liste und älterer creator-Alias werden unterstützt. Alle 30 gefundenen Clips je Kanal werden geprüft statt nur fünf. Originalalter maximal 72h, Länge 15–60s und mindestens 800 Aufrufe bleiben bestehen. 48–72h alte Clips benötigen starke Zusatzmetriken. Eine konservative Gaming-Kategorieliste lehnt fehlende bzw. nicht geprüfte Kategorien ab. Die Kategorie allein ersetzt keine Bildprüfung.

Faster-whisper small mit VAD, Wortzeitstempeln und Konfidenzprüfung ersetzt den bisher ungeprüften ASR-Erfolg. Unsichere Segmente/Wörter werden für die vollständige Prüfung im gesperrten Entwurf markiert. Der ganze kurze Clip erhält Aufbau und Pointe; eine Sprachdichte-Auswahl schneidet nicht mehr bei 42 Sekunden ab. Das bisherige Bildlayout wird NICHT automatisch semantisch zugeschnitten. Browserrahmen, winzige Gesichter, verschachtelte Streams, falsche Untertitel und fehlende Pointe erfordern weiterhin eine vollständige tatsächliche Medienprüfung.

Die Produktion legt höchstens einen Kandidaten in awaiting_review_tiktok14 ab und erfindet keine Freigabe. Das eigene Monatsrelease enthält MP4 plus EIN -review.zip mit Cover, Quell-/Ergebnis-Kontaktbildern, Worttranskript und Hash-Manifest. Zwei Assets je Clip ergeben bei 15 x 31 Clips 930 Assets. Die Kapazität von 1000 je Release wird zusätzlich geprüft; existierende Dateien werden nicht überschrieben.

Eine media_review im separaten Zustand muss Version 1, decision approved, benannten reviewer, reviewed_at (maximal 72h alt), watched_full_video true und die exakten media_sha256/transcript_sha256 des Kandidaten enthalten. checks enthält für subtitles_accuracy, frame_composition, full_clip_payoff, audio_intelligibility und gaming_context jeweils result pass und eine konkrete Medienbeobachtung unter evidence. Diese Angaben entstehen erst nach tatsächlicher Prüfung. subtitle_verified true allein genügt nicht. Video-/Transkriptänderungen machen alte Freigaben ungültig.

## Versand und Ergebnisprüfung

Neue Uploads werden zuerst dauerhaft reserviert. Eine verlorene createPost-Antwort wird nicht wiederholt; Buffer-ID bzw. exakter deterministischer Medientitel ermöglichen den späteren Abgleich. Kein blindes Minuten-Polling. Erst Buffer sent, exaktes Konto/Video und anonymes offizielles TikTok-oEmbed erlauben verified_public. Ungeklärte Ergebnisse sperren neue Posts.

Weil Buffer asynchron liefert, endet die Sendefreigabe bei 71h Originalalter. Die Reservation speichert Originalzeit und 72h-Deadline. Ein trotzdem verspätetes sentAt wird als late_publication gespeichert und sperrt weitere Posts. Buffer bietet hier keine garantierte Zustellfrist; der Puffer kann verspätete Auslieferung nicht absolut ausschließen.

Die Buffer-Prüfung verlangt My organization, Kanal 6ad16c0c778b240e2f21aca5, @ufo3103, Europe/Berlin, verbunden/entsperrt und video.publish. Freie Buffer-Zähler beweisen nicht das kontoübergreifende TikTok-Limit. Normalbetrieb benötigt ungefähr Overview + Create + späteren Post-Abgleich je Veröffentlichung; zusätzliche Kontrollen verbrauchen ebenfalls das gemeinsame API-Budget.

## Bedienung, Diagnosen und Tests

- TIKTOK14_ENABLED=true erlaubt geplanten bzw. externen automatischen Versand auf main erst nach Medien-, Konto- und Dublettenprüfung.
- diagnose: ausschließlich Metadaten; keine Mediendownloads, Zustandsänderungen, Releases oder Posts.
- prepare: höchstens ein Kandidat und Reviewpaket; kein TikTok-Post.
- commission/auto: neuer Versand oder Abgleich nur auf main. Entwurfszweige können ausschließlich prepare/diagnose ausführen.
- Push/PR führen Offline-Tests aus. Die alten Browser/Cookie-Einstiege bleiben gesperrt.

Zähler stehen in der Actions-Zusammenfassung und unter last_production im separaten Zustand. empty bedeutet kein neuer Metadatenkandidat; quality_rejected bedeutet ausgeschlossene Medienqualität. degraded bedeutet technische Download-, Render-, Modell-, Listing- oder Metadatenfehler, Exitcode 1 und mögliche spätere Wiederholung. Hosting-/Speicherfehler beenden die Kandidatenschleife sofort.

~~~sh
python scripts/tiktok14_prepare.py --test
python scripts/tiktok14_publish.py selftest
python -m unittest discover -s tests -v
~~~

Am Stand 18.10.2026 bestehen lokal 93 Offline-Tests und beide Selbsttests. Sie senden nichts und benutzen keine echten Zugangsdaten. CI und reale Prepare-Läufe müssen zusätzlich am tatsächlich verwendeten Commit geprüft werden. Erfolgreiche Vorbereitung beweist keinen öffentlichen TikTok-Post und keine verlässliche autonome Qualitätsprüfung.

## Dauerbetrieb: Entwürfe prüfen und Warteschlange freigeben

Unsichere ASR-Wörter und Segmente verwerfen einen möglichen guten Clip nicht mehr sofort. Das Transkript enthält uncertain_word_indexes, uncertain_segments und requires_correction; das Ergebnis bleibt ein gesperrter Entwurf. Dies ist keine Lockerung der Versandfreigabe. Falsche eingebrannte Untertitel müssen korrigiert und neu gerendert werden; eine Freigabe darf Fehler nicht bestätigen. Zu wenig Sprache wird weiterhin abgelehnt. Die Actions-Zusammenfassung verlinkt das fertige Video und das Prüf-ZIP auch bei späteren needs_review-Läufen.

Der Modus review nimmt über review_json eine JSON-Quittung mit clip_id und media_review entgegen. Er erhält nur den GitHub-Zugang und sendet nichts an Buffer. approved verlangt sämtliche oben genannten Prüfnachweise und exakt übereinstimmende Video-/Transkript-Hashes sowie frische Quelle und erlaubten Streamer. Erst ein späterer auto/commission-Lauf darf den freigegebenen Kandidaten senden. rejected verlangt dieselben Hashes, einen benannten Prüfer und einen konkreten reason; es archiviert den Kandidaten und gibt sofort die Suche frei. Ein Urteil zu einem inzwischen ersetzten Kandidaten wird abgelehnt. JSON wird begrenzt und doppelte Schlüssel sind unzulässig. Kein Shell-Befehl wird aus Reviewtext erzeugt.

Alle produktiven Prepare-/Review-/Publish-Jobs teilen eine feste Concurrency-Gruppe über Branchgrenzen hinweg. Damit können ein manueller Prepare-Test und der Hauptbetrieb nicht gleichzeitig unterschiedliche Kandidaten in dieselbe Warteschlange schreiben. Der bestehende Versionsvergleich bleibt als zusätzliche Sicherung bestehen.

Ein autonomer Bild-/Tonprüfer ist weiterhin nicht angebunden. Ohne tatsächliche Prüfung kann needs_review den Betrieb bis zum Ablauf des Kandidaten anhalten. Kein Softwaretest kann einen guten Inhalt, richtige Untertitel oder eine ausreichende Pointe garantieren. Ein unabhängiger externer Zeitgeber benötigt weiterhin ein auf dieses Repository begrenztes GitHub-Actions-Schreibrecht; vorhandene Hosting-Anmeldung allein genügt nicht. Bestehende ChatGPT-Kontrolle und Twitch-Aufgaben bleiben unverändert.
