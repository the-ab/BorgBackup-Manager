(() => {
  'use strict';

  const exact = {
    'Zentrale für deine Backups.': 'Your backup control center.',
    'Benutzername': 'Username', 'Passwort': 'Password', 'Verwaltung öffnen': 'Open management',
    'Version': 'Version', 'Menü': 'Menu', 'Betrieb': 'Operations', 'Übersicht': 'Dashboard',
    'Backup-Jobs': 'Backup jobs', 'Zeitpläne': 'Schedules', 'Ausführungen': 'Runs', 'Daten': 'Data',
    'Archive': 'Archives', 'Wiederherstellen': 'Restore', 'Repositories': 'Repositories',
    'Infrastruktur': 'Infrastructure', 'Geräte': 'Devices', 'System': 'System', 'Systembereiche': 'System sections', 'Manager-Backup': 'Manager backup',
    'Benachrichtigungen': 'Notifications', 'Benachrichtigungszentrale': 'Notification center',
    'Ereignisse zentral per E-Mail, Webhook, Discord oder Telegram versenden.': 'Send events centrally by email, webhook, Discord or Telegram.',
    'Konfiguration speichern': 'Save configuration', 'Benachrichtigungen global aktivieren': 'Enable notifications globally',
    'Installationsname': 'Instance name', 'Zeitlimit je Versand (Sekunden)': 'Delivery timeout (seconds)',
    'Gefilterten Diagnoseausschnitt in Benachrichtigungen aufnehmen': 'Include a filtered diagnostic excerpt in notifications',
    'Ereignisse': 'Events', 'Erfolgsbenachrichtigungen sind optional, damit die Zentrale nicht unnötig viele Meldungen erzeugt.': 'Success notifications are optional to avoid unnecessary messages.',
    'Backup fehlgeschlagen': 'Backup failed', 'Backup mit Warnungen': 'Backup completed with warnings', 'Backup erfolgreich': 'Backup successful',
    'Ausführung abgebrochen': 'Run cancelled', 'Repository-Aktion fehlgeschlagen': 'Repository action failed',
    'Repository-Aktion mit Warnungen': 'Repository action completed with warnings', 'Repository-Aktion erfolgreich': 'Repository action successful',
    'Zeitplanausführung fehlgeschlagen': 'Scheduled run failed', 'Zeitplanausführung mit Warnungen': 'Scheduled run completed with warnings',
    'Zeitplanausführung erfolgreich': 'Scheduled run successful', 'Sonstige Aktion fehlgeschlagen': 'Other action failed',
    'Sonstige Aktion mit Warnungen': 'Other action completed with warnings', 'Sonstige Aktion erfolgreich': 'Other action successful',
    'E-Mail über SMTP': 'Email via SMTP', 'E-Mail testen': 'Test email', 'E-Mail-Kanal aktivieren': 'Enable email channel',
    'SMTP-Server': 'SMTP server', 'Transportverschlüsselung': 'Transport encryption', 'TLS/SSL direkt': 'Direct TLS/SSL', 'Keine': 'None',
    'SMTP-Benutzer': 'SMTP username', 'SMTP-Passwort': 'SMTP password', 'Gespeichertes Passwort löschen': 'Delete stored password',
    'Absender': 'Sender', 'E-Mail-Empfänger': 'Email recipients', 'Webhook oder Discord': 'Webhook or Discord',
    'Webhook testen': 'Test webhook', 'Webhook-Kanal aktivieren': 'Enable webhook channel', 'Typ': 'Type',
    'Generischer JSON-Webhook': 'Generic JSON webhook', 'Discord-Webhook': 'Discord webhook', 'Webhook-URL': 'Webhook URL',
    'Gespeicherte URL löschen': 'Delete stored URL',
    'Der generische Webhook erhält ein JSON-Dokument mit Ereignis, Schweregrad, Titel, Nachricht, Ausführungs-ID und Zeitstempel.': 'The generic webhook receives a JSON document containing event, severity, title, message, run ID and timestamp.',
    'Telegram-Kanal aktivieren': 'Enable Telegram channel', 'Telegram testen': 'Test Telegram', 'Bot-Token': 'Bot token',
    'Chat-ID oder Kanal': 'Chat ID or channel', 'Gespeichertes Token löschen': 'Delete stored token',
    'Letzte Zustellungen': 'Recent deliveries', 'Erfolge und Fehler der Benachrichtigungskanäle, unabhängig vom Ergebnis des Borg-Laufs.': 'Successes and failures of notification channels, independent of the Borg run result.',
    'Protokoll leeren': 'Clear log', 'Kanal': 'Channel', 'Ereignis': 'Event', 'Titel': 'Title', 'Ergebnis': 'Result',
    'Einstellungen': 'Settings', 'Benutzer': 'Users', 'Information': 'Information', 'Anleitung': 'Manual',
    'Release Notes': 'Release notes', 'Dienst erreichbar': 'Service available', 'Darstellung & Sprache': 'Appearance & language',
    'Passwort ändern': 'Change password', 'Abmelden': 'Sign out', 'Kontrollzentrum': 'Control center',
    'Aktuell': 'Up to date', 'Dunkel': 'Dark', 'Hell': 'Light', 'Aktualisieren': 'Refresh',
    'Alle Backup-Jobs': 'All backup jobs', 'Letzte Aktivitäten': 'Recent activity', 'Alle Protokolle': 'All logs',
    'Systemdiagnose': 'System diagnostics', 'Borg-Version, Repository-Speicher, SSH-Dienst und Serverprotokolle zentral prüfen.': 'Centrally check the Borg version, repository storage, SSH service and server logs.', 'Diagnose laden': 'Load diagnostics', 'Diagnose schließen': 'Close diagnostics',
    'Borg-Version, Repository-Speicher und Serverprotokoll bei Bedarf laden.': 'Load the Borg version, repository storage and server log when needed.',
    'Gerät hinzufügen': 'Add device', 'Installiere zuerst diesen Controller-Schlüssel beim SSH-Benutzer des Geräts:': 'First install this controller key for the device SSH user:',
    'Kopieren': 'Copy', 'Die sicherheitskritische Erneuerung befindet sich unter': 'Security-critical rotation is available under',
    'System → Einstellungen → Controller-Schlüssel': 'System → Settings → Controller Key', 'Einstellungen → Controller-Schlüssel': 'Settings → Controller Key', 'Name': 'Name', 'Adresse': 'Address',
    'SSH-Benutzer': 'SSH user', 'Port': 'Port', 'SSH-Fingerprint prüfen': 'Verify SSH fingerprint',
    'Der Hostschlüssel muss vor dem Speichern bestätigt werden.': 'The host key must be accepted before saving.',
    'Fingerprint bestätigen': 'Accept fingerprint', 'Verwerfen': 'Discard', 'Gerät aktivieren': 'Enable device', 'Gerät ist deaktiviert': 'Device is disabled',
    'Gerät speichern': 'Save device', 'Abbrechen': 'Cancel', 'Verbundene Geräte': 'Connected devices',
    'Repository hinzufügen': 'Add repository', 'Verwaltete Repositories neu erstellen oder ein bereits vorhandenes externes Borg-Repository anbinden.': 'Create managed repositories or connect an existing external Borg repository.',
    'Typ': 'Type', 'Verschlüsselung': 'Encryption', 'Verwaltet – neues Repository im eingebundenen Speicher': 'Managed – new repository in mounted storage',
    'Extern – vorhandenes Borg-Repository hinzufügen': 'External – add existing Borg repository',
    'Speicherplatz-Sperre': 'Storage guard', 'Globale Einstellung übernehmen': 'Inherit global setting',
    'Für dieses Repository aktivieren': 'Enable for this repository', 'Für dieses Repository deaktivieren': 'Disable for this repository',
    'Eigene Sperrgrenze in Prozent': 'Custom threshold in percent',
    'Die Prüfung verwendet das tatsächliche Dateisystem dieses Repository-Verzeichnisses. Eine leere eigene Grenze übernimmt den globalen Wert.': 'The check uses the actual filesystem of this repository directory. An empty custom threshold inherits the global value.',
    'URL des vorhandenen Borg-Repositorys': 'Existing Borg repository URL',
    '„Hinzufügen“ initialisiert oder überschreibt das externe Repository nicht. Der Manager speichert ausschließlich die Verbindungskonfiguration und öffnet das vorhandene Repository später mit': '“Add” does not initialize or overwrite the external repository. The manager only stores connection settings and later opens the existing repository with',
    'Eigenen Ed25519-Schlüssel im Manager erzeugen': 'Generate an Ed25519 key in the manager',
    'Vorhandenen privaten Ed25519-Schlüssel übernehmen': 'Import an existing private Ed25519 key',
    'SSH-Hostkey direkt vom Manager abrufen': 'Retrieve SSH host key from the manager',
    'known_hosts-Eintrag': 'known_hosts entry', 'Repository-Passphrase': 'Repository passphrase',
    'Passphrase wiederholen': 'Repeat passphrase', 'Vorhandener Borg-Keyfile-Inhalt': 'Existing Borg keyfile content',
    'Sensibler Inhalt:': 'Sensitive content:', 'wird verschlüsselt gespeichert': 'stored encrypted',
    'Repository erstellen': 'Create repository', 'Verzeichnis durchsuchen': 'Browse directory',
    'Repository fehlt': 'Repository missing', 'Zurücksetzen': 'Reset',
    'Manager-Repository-ID': 'Manager repository ID',
    'Repository fehlt oder ist nicht initialisiert': 'Repository is missing or not initialized',
    'Nur verwaltete Repositorys können zurückgesetzt werden': 'Only managed repositories can be reset',
    'Repository hat eine wartende oder laufende Ausführung': 'Repository has a queued or running execution',
    'Repository besitzt noch einen aktiven Archiv-Mount': 'Repository still has an active archive mount',
    'Verwaltetes Repository fehlt; zuerst zurücksetzen und erneut initialisieren': 'Managed repository is missing; reset and initialize it again',
    'Repository-Managerstatus ist veraltet; das leere Repository vor der Initialisierung zurücksetzen': 'Repository manager state is stale; reset the empty repository before initialization',
    'Repository ist bereits initialisiert': 'Repository is already initialized',
    'Verwaltetes Repository fehlt oder ist nicht initialisiert; zuerst zurücksetzen und erneut initialisieren': 'Managed repository is missing or not initialized; reset and initialize it again',
    'Repository-Verzeichnis enthält weiterhin eine Borg-Konfiguration; Zurücksetzen ist nicht zulässig': 'Repository directory still contains a Borg config; reset is not permitted',
    'Das verwaltete Repository-Verzeichnis ist nicht vorhanden': 'Managed repository directory does not exist',
    'Der Pfad eines verwalteten Repositorys darf kein symbolischer Link sein': 'Managed repository path must not be a symbolic link',
    'Repository-Pfad liegt außerhalb des verwalteten Speicherbereichs': 'Repository path is outside the managed storage root',
    'Vorhandene lokale Repositories einbinden': 'Import existing local repositories',
    'Durchsucht direkte Unterverzeichnisse des eingebundenen Repository-Pfads nach Borg-Konfigurationen.': 'Searches direct subdirectories of the mounted repository path for Borg configurations.',
    'Backup-Job erstellen': 'Create backup job', 'Grunddaten kompakt festlegen; erweiterte Optionen bei Bedarf öffnen.': 'Define basic data compactly; open advanced options when needed.',
    'Gerät': 'Device', 'Repository': 'Repository', 'Quellpfade': 'Source paths', 'Ausschlüsse': 'Exclusions',
    'Ausschlussvorlage': 'Exclusion template', 'Keine Vorlage ausgewählt': 'No template selected',
    'Vorlagen ergänzen ohne Duplikate.': 'Add template patterns without duplicates.', 'Archivnamensvorlage': 'Archive name template',
    'Automatisches Job-Präfix wird beim Speichern ergänzt.': 'The automatic job prefix is added when saving.',
    'Kompression': 'Compression', 'Eigene Kompressionsspezifikation': 'Custom compression specification',
    'Erweiterte Borg-Spezifikation …': 'Advanced Borg specification …', 'Aufbewahrung': 'Retention',
    'Dateisystem- und Konsistenzoptionen': 'Filesystem and consistency options', 'Nur jeweiliges Quelldateisystem': 'Stay on each source filesystem',
    'CACHEDIR.TAG ausschließen': 'Exclude CACHEDIR.TAG', 'nodump-Dateien ausschließen': 'Exclude nodump files',
    'Numerische IDs speichern': 'Store numeric IDs', 'Verarbeitete Dateien im Live-Protokoll anzeigen': 'Show processed files in the live log',
    'Datei-Cache': 'Files cache', 'Checkpoint (Sekunden)': 'Checkpoint (seconds)', 'Job aktivieren': 'Enable job',
    'Job speichern': 'Save job', 'Zentrale Zeitpläne': 'Central schedules',
    'Ein Zeitplan kann einzelne oder mehrere Geräte, ausgewählte Jobs oder alle Jobs eines Repositorys steuern.': 'A schedule can control one or more devices, selected jobs or all jobs in a repository.',
    'Zentralen Zeitplan erstellen': 'Create central schedule', 'Zielgruppe': 'Target group',
    'Ausgewählte Geräte': 'Selected devices', 'Alle Geräte/Jobs eines Repositorys': 'All devices/jobs in a repository',
    'Ausgewählte Backup-Jobs': 'Selected backup jobs', 'Rhythmus': 'Frequency', 'Täglich': 'Daily',
    'Montag bis Freitag': 'Monday to Friday', 'Wochenende': 'Weekend', 'Ausgewählte Wochentage': 'Selected weekdays',
    'Monatlich': 'Monthly', 'Erweiterter Cron-Zeitplan': 'Advanced cron schedule', 'Ausführungszeiten': 'Run times',
    'Uhrzeit hinzufügen': 'Add time', 'Tag im Monat': 'Day of month', 'Cron-Ausdrücke': 'Cron expressions',
    'Mehrere Uhrzeiten pro Tag sind möglich.': 'Multiple times per day are supported.', 'Zeitplan aktivieren': 'Enable schedule',
    'Zeitplan speichern': 'Save schedule', 'Maximal parallele Ausführungen': 'Maximum parallel runs',
    '0 = nur globale Grenze': '0 = global limit only', 'Parallelität': 'Parallelism', 'globale Grenze': 'global limit',
    'Sortierung': 'Sort order', 'Name A–Z': 'Name A–Z', 'Name Z–A': 'Name Z–A',
    'Gerät A–Z': 'Device A–Z', 'Repository A–Z': 'Repository A–Z', 'Aktive zuerst': 'Active first',
    'Letzter Lauf – neueste zuerst': 'Latest run – newest first', 'Letzter Lauf – älteste zuerst': 'Latest run – oldest first', 'Sicherungsgröße absteigend': 'Backup size descending',
    'Adresse': 'Address', 'Borg-Version absteigend': 'Borg version descending', 'Bereite zuerst': 'Ready first',
    'Verwaltete zuerst': 'Managed first', 'Meiste Jobs zuerst': 'Most jobs first', 'Größe absteigend': 'Size descending',
    'Zeitplan A–Z': 'Schedule A–Z', 'Ausführungsprotokolle': 'Run logs', 'Alle Ausführungen': 'All runs',
    'Laufend/wartend': 'Running/queued', 'Laufend': 'Running', 'Wartend': 'Queued', 'Fehlgeschlagen': 'Failed',
    'Warnungen': 'Warnings', 'Erfolgreich': 'Successful', 'Abgebrochen': 'Cancelled', 'Suche': 'Search', 'Anzahl': 'Count',
    '0 angezeigt': '0 shown', 'Archivübersicht': 'Archive list', 'Alle Geräte / alle Archive': 'All devices / all archives',
    'Unvollständige Checkpoint-Archive anzeigen': 'Show incomplete checkpoint archives', 'Archive anzeigen': 'Show archives',
    'Neu aus Repository einlesen': 'Reload from repository', 'Die zuletzt geladene Archivliste wird persistent zwischengespeichert.': 'The most recently loaded archive list is cached persistently.',
    'Nach erfolgreichen Backups, Prune-Läufen, Umbenennungen oder Löschungen wird der Zwischenspeicher automatisch verworfen. „Neu aus Repository einlesen“ ist nur für Änderungen erforderlich, die außerhalb des Managers vorgenommen wurden.': 'The cache is invalidated automatically after successful backups, prune runs, renames or deletions. “Reload from repository” is only required for changes made outside the manager.',
    'Zuerst ein Repository auswählen und die Archivliste anzeigen.': 'First select a repository and show the archive list.',
    'Archivinhalt durchsuchen': 'Browse archive contents', 'Browser schließen': 'Close browser', 'Eine Ebene höher': 'One level up',
    'Noch nichts ausgewählt.': 'Nothing selected yet.', 'Auswahl exportieren (.tar.gz)': 'Export selection (.tar.gz)',
    'Auswahl wiederherstellen': 'Restore selection', 'Archive vergleichen': 'Compare archives', 'Älteres Archiv': 'Older archive',
    'Neueres Archiv': 'Newer archive', 'Änderungen zwischen zwei Sicherungsständen mit Borg Diff anzeigen.': 'Show changes between two backup states using Borg Diff.',
    'Dateien wiederherstellen': 'Restore files', 'Zuerst Backup-Job auswählen': 'Select a backup job first',
    'Archivname': 'Archive name', 'Pfade im Archiv': 'Paths in archive', '(einer pro Zeile; für Originalpfad erforderlich)': '(one per line; required for original location)',
    'Wiederherstellungsziel': 'Restore target', 'Am ursprünglichen Speicherort': 'At original location',
    'In alternatives Zielverzeichnis': 'To alternative target directory', 'Zielverzeichnis auf dem Gerät': 'Target directory on device',
    'Anordnung im Ziel': 'Layout at target', 'Ausgewählte Datei/Ordner direkt im Ziel ablegen': 'Place selected file/directory directly in target',
    'Vollständige Archivpfade beibehalten': 'Preserve full archive paths', 'Nur testen (empfohlen)': 'Dry run only (recommended)',
    'Ich bestätige, dass vorhandene Dateien am Originalpfad ersetzt werden können.': 'I confirm that existing files at the original location may be overwritten.',
    'Legacy-/fremdes Archiv dieses Repositorys ausdrücklich zulassen': 'Explicitly allow a legacy/foreign archive from this repository',
    'Restore testen': 'Test restore', 'Wiederherstellung starten': 'Start restore',
    'Manager-Backup erstellen': 'Create manager backup', 'Bezeichnung': 'Label', '(optional)': '(optional)',
    'Backup mit eigener Passphrase verschlüsseln': 'Encrypt backup with a separate passphrase', 'Backup-Passphrase': 'Backup passphrase',
    'Backup erstellen': 'Create backup', 'Manager-Backup hochladen': 'Upload manager backup', 'Backup hochladen': 'Upload backup',
    'Vorhandene .bbm- oder historische .zip-Datei sicher übernehmen.': 'Securely add an existing .bbm or historical .zip file.',
    'Backup-Datei': 'Backup file',
    'Dateiname, Größe und Format werden serverseitig geprüft. Vorhandene Dateien werden niemals überschrieben. Verschlüsselte Backups werden beim Hochladen strukturell geprüft und erst bei der Wiederherstellung mit der Passphrase authentifiziert.': 'File name, size and format are validated by the server. Existing files are never overwritten. Encrypted backups are structurally checked during upload and authenticated with the passphrase only during restore.',
    'Manager-Backup wiederherstellen': 'Restore manager backup',
    'Stellt Manager-Daten wieder her und startet den Container automatisch neu.': 'Restores manager data and restarts the container automatically.',
    'Backup auswählen': 'Select backup', '(nur bei verschlüsselten Backups)': '(encrypted backups only)',
    'Aktuelle Manager-Daten werden ersetzt; laufende Jobs sind vorher zu beenden.': 'Current manager data will be replaced; stop running jobs first.',
    'Vorhandene Backups': 'Existing backups', 'Aktivieren': 'Enable', 'Deaktivieren': 'Disable',
    'Benutzer anlegen': 'Create user',
    'Passwörter werden ausschließlich als scrypt-Prüfwerte gespeichert.': 'Passwords are stored only as scrypt verifiers.',
    'Rolle': 'Role', 'Benutzer – operativer Zugriff': 'User – operational access',
    'Administrator – vollständige Verwaltung': 'Administrator – full management', 'Temporäres Passwort': 'Temporary password',
    'Passwort wiederholen': 'Repeat password', 'Passwortwechsel bei der nächsten Anmeldung erzwingen': 'Require password change at next sign-in',
    'Benutzerkonto aktiv': 'User account enabled', 'Benutzer anlegen': 'Create user', 'Benutzerverwaltung': 'User management',
    'Sicherheitsdaten werden geladen …': 'Loading security data …', 'Systemweite Anzeigegrenzen': 'System-wide display limits',
    'Darstellungsdichte': 'Display density', 'Komfortabel – größere Abstände': 'Comfortable – larger spacing',
    'Kompakt – mehr Einträge sichtbar': 'Compact – more entries visible',
    'Die Dichte verändert Tabellen, Formulare, Karten, Navigation und Abstände sofort sichtbar. „Kompakt“ ist für Installationen mit vielen Geräten und Jobs vorgesehen.': 'Density immediately changes tables, forms, cards, navigation and spacing. “Compact” is intended for installations with many devices and jobs.',
    'Letzte Läufe im Dashboard': 'Recent runs on dashboard', 'Läufe in Protokollliste': 'Runs in log list',
    'Zusätzliche Hintergrundaktualisierung (Sekunden)': 'Additional background refresh (seconds)',
    'Maximale Höhe der Archivübersicht und weiterer Scrolllisten (Pixel)': 'Maximum height of archive and other scroll lists (pixels)',
    'Die Listenhöhe gilt unter anderem für Archivübersicht, Repository-Suche, Manager-Backups und weitere bewusst begrenzte Listen. Tabellen mit eigener Seitenansicht bleiben vollständig sichtbar.': 'The list height applies to the archive list, repository search, manager backups and other intentionally bounded lists. Tables with their own page remain fully visible.',
    'Parallelitätsgrenzen': 'Parallelism limits',
    'Begrenzt gleichzeitig laufende Borg-Ausführungen auch dann, wenn sie unterschiedliche Repositorys verwenden.': 'Limits concurrently running Borg operations even when they use different repositories.',
    'Maximal parallele Ausführungen global': 'Maximum parallel runs globally',
    '0 bedeutet unbegrenzt. Die feste Regel „höchstens eine schreibende oder prüfende Aktion je Repository“ bleibt zusätzlich bestehen. Ein Zeitplan kann unter „Zeitpläne“ einen niedrigeren eigenen Grenzwert erhalten.': '0 means unlimited. The fixed rule of at most one write or check operation per repository remains in effect. A schedule can define a lower limit under Schedules.',
    'Controller-Schlüssel': 'Controller key',
    'Öffentlichen Schlüssel kopieren oder den zentralen Controller-Zugang nach ausdrücklicher Sicherheitsbestätigung erneuern.': 'Copy the public key or rotate central controller access after explicit security confirmation.',
    'Achtung:': 'Warning:', 'Eine Erneuerung unterbricht alle bestehenden Controller-SSH-Zugänge. Der neue öffentliche Schlüssel muss anschließend auf jedem Client hinterlegt werden.': 'Rotation interrupts all existing controller SSH access. The new public key must then be installed on every client.',
    'Controller-Schlüssel erneuern': 'Rotate controller key', 'Nur verwenden, wenn der bestehende Controller-Schlüssel ersetzt werden muss.': 'Use only when the existing controller key must be replaced.',
    'Ausführungsprotokolle': 'Run logs', 'Vollständige neue Live-Protokolle liegen als Dateien; die Datenbank enthält nur begrenzte Vorschauen und Metadaten.': 'Complete new live logs are stored as files; the database contains only bounded previews and metadata.',
    'Aufbewahren (Tage, 0 = unbegrenzt)': 'Retain (days, 0 = unlimited)', 'Maximalgröße je Logdatei (MiB)': 'Maximum size per log file (MiB)',
    'Maximal in der WebUI anzeigen (KiB)': 'Maximum displayed in the web UI (KiB)', 'Protokollspeicher wird geladen …': 'Loading log storage …',
    'Abgelaufene jetzt bereinigen': 'Clean expired now', 'Alle abgeschlossenen löschen': 'Delete all completed',
    'Die automatische Bereinigung läuft täglich um 03:30 Uhr. Aktive oder wartende Läufe werden nie gelöscht. Bei manueller Bereinigung wird SQLite zusätzlich komprimiert.': 'Automatic cleanup runs daily at 03:30. Active or queued runs are never deleted. Manual cleanup also compacts SQLite.',
    'Schreibende Backup-Läufe werden auf dem tatsächlichen Dateisystem des jeweiligen verwalteten Repositorys geprüft.': 'Write backup runs are checked against the actual filesystem of the relevant managed repository.',
    'Speicherplatz-Sperre global aktivieren': 'Enable storage guard globally', 'Globale Sperrgrenze in Prozent': 'Global threshold in percent',
    'Repositories übernehmen diese Werte standardmäßig. Unter „Repositories → Bearbeiten“ kann die Sperre pro Repository deaktiviert oder mit einer eigenen Grenze versehen werden.': 'Repositories inherit these values by default. Under “Repositories → Edit”, the guard can be disabled or assigned a custom threshold per repository.',
    'Repository-Größe nach manuellen Schreibvorgängen und nach Abschluss eines Zeitplans automatisch aktualisieren': 'Automatically update repository size after manual writes and after a schedule completes',
    'Nach erfolgreichem geplanten Prune automatisch Compact ausführen': 'Automatically run compact after a successful scheduled prune',
    'Ausschlussvorlagen': 'Exclusion templates', 'Zentrale, wiederverwendbare Ausschlusslisten für neue und bestehende Backup-Jobs.': 'Central reusable exclusion lists for new and existing backup jobs.',
    'Vorlage zur Liste hinzufügen': 'Add template to list', 'Die Vorlage wird beim Job nur in dessen Ausschlussliste kopiert. Spätere Änderungen an einer Vorlage verändern bereits gespeicherte Jobs nicht automatisch.': 'A template is copied only into the job’s exclusion list. Later template changes do not modify saved jobs automatically.',
    'Einstellungen speichern': 'Save settings', 'Darstellung & Sprache': 'Appearance & language',
    'Diese Auswahl gilt nur für das aktuell angemeldete Benutzerkonto.': 'This selection applies only to the currently signed-in user account.',
    'Sprache': 'Language', 'Deutsch': 'German', 'English': 'English', 'Farbschema': 'Theme', 'Automatisch': 'Automatic',
    'Sprache und Farbschema werden benutzerbezogen gespeichert und verändern keine systemweite Einstellung.': 'Language and theme are stored per user and do not change any system-wide setting.',
    'Persönliche Einstellungen speichern': 'Save personal preferences', 'Eigenes Passwort ändern': 'Change own password',
    'Nach dem Wechsel ist eine erneute Anmeldung erforderlich.': 'You must sign in again after changing it.', 'Aktuelles Passwort': 'Current password',
    'Neues Passwort': 'New password', 'Neues Passwort wiederholen': 'Repeat new password',
    'Mindestens 12 Zeichen und mindestens drei Gruppen aus Groß-/Kleinbuchstaben, Zahlen und Sonderzeichen.': 'At least 12 characters and at least three groups among uppercase, lowercase, numbers and special characters.',
    'Benutzerpasswort setzen': 'Set user password', 'Neues temporäres Passwort': 'New temporary password', 'Passwort setzen': 'Set password',
    'Mindestens 12 Zeichen und mindestens drei Gruppen aus Groß-/Kleinbuchstaben, Zahlen und Sonderzeichen. Bestehende Sitzungen des Benutzers werden beendet.': 'At least 12 characters and at least three groups among uppercase, lowercase, numbers and special characters. Existing user sessions will be revoked.',
    'Dieser Vorgang unterbricht alle Controller-SSH-Zugänge, bis der neue öffentliche Schlüssel auf jedem Client hinterlegt wurde.': 'This action interrupts all controller SSH access until the new public key is installed on every client.',
    'Sicherheitsbestätigung:': 'Security confirmation:', 'Laufende oder wartende Ausführungen blockieren den Vorgang. Der bisherige Schlüssel wird nicht weiter verwendet.': 'Running or queued runs block this action. The previous key will no longer be used.',
    'Zur Bestätigung exakt eingeben:': 'Type exactly to confirm:', 'Schlüssel endgültig erneuern': 'Rotate key permanently',
    'Ausführung': 'Run', 'Ausführungsdetails': 'Run details', 'Schließen': 'Close', 'Lesbare Ausgabe': 'Readable output',
    'Technische Details': 'Technical details', 'Ausgeführter Befehl': 'Executed command', 'Standardausgabe': 'Standard output',
    'Fehlerausgabe (gefiltert)': 'Error output (filtered)', 'Anleitung wird geladen …': 'Loading manual …',
    'Status': 'Status', 'Suche bei Bedarf starten.': 'Start a search when needed.', 'Aktiv': 'Active', 'Inaktiv': 'Inactive',
    'Mo': 'Mon', 'Di': 'Tue', 'Mi': 'Wed', 'Do': 'Thu', 'Fr': 'Fri', 'Sa': 'Sat', 'So': 'Sun',
    'Wöchentlich': 'Weekly', 'Stündlich': 'Hourly', 'Jährlich': 'Yearly',
    '(einer pro Zeile)': '(one per line)', '(Mehrfachauswahl möglich)': '(multiple selection supported)',
    'Optionale Pfade, eine Zeile je relativer Archivpfad': 'Optional paths, one relative archive path per line',
    'Originalpfad oder alternatives Ziel.': 'Original location or alternative target.', 'Testlauf öffnet sofort das Protokoll.': 'The test run opens the log immediately.',
    'Nur Inhaltsänderungen': 'Content changes only', 'Kontrollierter Restore': 'Controlled restore',
    'Vorhandene Backups': 'Existing backups', 'Download': 'Download', 'Löschen': 'Delete', 'Bearbeiten': 'Edit',
    'Mehr': 'More', 'Prüfen': 'Checks', 'Repository-Zugang': 'Repository access', 'Speicherpflege': 'Storage maintenance',
    'Verwalten': 'Management', 'Verbindung': 'Connection', 'Borg-Version': 'Borg version', 'Job-Info': 'Job info',
    'Aufbewahrung anwenden': 'Apply retention', 'Compact ausführen': 'Run compact', 'Job löschen': 'Delete job',
    'Backup starten': 'Start backup', 'Manuell': 'Manual', 'manuell': 'manual', 'Zeitplan': 'Schedule',
    'Original': 'Original', 'Komprimiert': 'Compressed', 'Dedupliziert': 'Deduplicated', 'Dateien': 'Files', 'Dauer': 'Duration',
    'Quellenstatistik:': 'Source statistics:', 'Noch keine Quellenstatistik gespeichert': 'No source statistics stored yet',
    'Statistik': 'Statistics', 'noch kein Backup': 'no backup yet',
    'Details': 'Details', 'Inhalt durchsuchen': 'Browse contents', 'Archiv löschen': 'Delete archive', 'Umbenennen': 'Rename',
    'Auswählen': 'Select', 'Archiv auswählen': 'Select archive', 'Sichtbare Archive auswählen': 'Select visible archives',
    'Ausgewählte Archive löschen': 'Delete selected archives', '0 ausgewählt': '0 selected',
    'Mehrere Geräte': 'Multiple devices', 'Gerät nicht eindeutig': 'Device not uniquely identified',
    'Compact direkt am Repository': 'Compact directly on repository',
    'Für Restore/Umbenennen muss das Gerät eindeutig einem Backup-Job zugeordnet sein.': 'For restore/rename, the device must be assigned unambiguously to a backup job.',
    'Keine Release Notes vorhanden.': 'No release notes available.', 'Wird geladen …': 'Loading …', 'Wird gespeichert …': 'Saving …',
    'Wird gestartet …': 'Starting …', 'Wird gelöscht …': 'Deleting …', 'Wird berechnet …': 'Calculating …',
    'Aktualisiere …': 'Refreshing …', 'Wird ausgeführt …': 'Running …', 'Wird bestätigt …': 'Confirming …',
    'Borg wird geprüft …': 'Checking Borg …', 'Zugang wird eingerichtet …': 'Configuring access …',
    'Verbindung wird geprüft …': 'Testing connection …', 'Cache wird gelöscht …': 'Clearing cache …',
    'Abbruch läuft …': 'Cancelling …', 'Fingerprint wird gelesen …': 'Reading fingerprint …',
    'Schlüssel wird erneuert …': 'Rotating key …', 'Backup wird erstellt …': 'Creating backup …',
    'Backup wird hochgeladen …': 'Uploading backup …', 'Wird aktiviert …': 'Enabling …', 'Wird deaktiviert …': 'Disabling …',
    'Einstellungen werden gespeichert …': 'Saving settings …', 'Einstellungen übernommen': 'Settings applied',
    'Einstellungen gespeichert': 'Settings saved', 'Einstellungen konnten nicht gespeichert werden': 'Settings could not be saved',
    'Controller-Schlüssel kopiert': 'Controller key copied', 'Controller-Schlüssel erneuert': 'Controller key rotated',
    'Schlüsselerneuerung fehlgeschlagen': 'Key rotation failed', 'Manager-Backup erstellt': 'Manager backup created',
    'Manager-Backup hochgeladen': 'Manager backup uploaded', 'Gerät aktiviert': 'Device enabled', 'Gerät deaktiviert': 'Device disabled',
    'Backup-Job aktiviert': 'Backup job enabled', 'Backup-Job deaktiviert': 'Backup job disabled',
    'Benachrichtigungskonfiguration gespeichert': 'Notification configuration saved', 'Benachrichtigungsprotokoll geleert': 'Notification log cleared',
    'Kein SMTP-Passwort gespeichert.': 'No SMTP password stored.', 'SMTP-Passwort ist verschlüsselt gespeichert.': 'SMTP password is stored encrypted.',
    'Keine Webhook-URL gespeichert.': 'No webhook URL stored.', 'Webhook-URL ist verschlüsselt gespeichert.': 'Webhook URL is stored encrypted.',
    'Kein Bot-Token gespeichert.': 'No bot token stored.', 'Telegram-Bot-Token ist verschlüsselt gespeichert.': 'Telegram bot token is stored encrypted.',
    'Noch keine Benachrichtigungen versendet.': 'No notifications have been sent yet.', 'versendet': 'sent',
    'Systemdiagnose aktualisiert': 'System diagnostics refreshed', 'Systemdiagnose geschlossen': 'System diagnostics closed',
    'Systemdiagnose konnte nicht geladen werden': 'System diagnostics could not be loaded',
    'Kein kopierbarer Inhalt vorhanden': 'No content available to copy', 'Text kopieren': 'Copy text',
    'Repository-Verwaltung': 'Repository management', 'Ausführung': 'Run', 'Laufende Aufgaben': 'Active tasks',
    'Ausgewählte Pfade': 'Selected paths', 'Backup': 'Backup', 'Backup-Job': 'Backup job',
    'Automatische Ausführungen werden zentral unter': 'Automatic runs are configured centrally under',
    'Datenbank, Einstellungen, SSH-/TLS- und Repository-Schlüssel.': 'Database, settings, SSH/TLS and repository keys.',
    'Der private Schlüssel wird nicht als Klartextdatei abgelegt: verschlüsselt in': 'The private key is not stored as a plaintext file: encrypted in',
    'Ein Manager-Backup enthält Manager-Datenbank, Sicherheitsdatenbank, Master-Key sowie SSH-, TLS- und Borg-Schlüssel. Sicher verwahren. Repository-Nutzdaten sind nicht enthalten.': 'A manager backup contains the manager database, security database, master key and SSH, TLS and Borg keys. Store it securely. Repository payload data is not included.',
    'Erfasst automatisch alle aktiven Backup-Jobs dieses Repositorys – auch später neu angelegte.': 'Automatically includes all active backup jobs for this repository, including jobs added later.',
    'Geeignet zum Prüfen oder Kopieren an einen anderen Ort.': 'Suitable for verification or copying to another location.',
    'Nur für Mount-Sitzungen aus Version 0.7/0.8. Neue Archivbrowser-Sitzungen benötigen kein FUSE.': 'Only for mount sessions from version 0.7/0.8. New archive browser sessions do not require FUSE.',
    'Unterstützt unter Borg 1.2 bis 1.4: none, lz4, zstd, zlib, lzma, auto und obfuscate.': 'Supported with Borg 1.2 through 1.4: none, lz4, zstd, zlib, lzma, auto and obfuscate.',
    'Unvollständige Checkpoint-Archive zur Auswahl anzeigen': 'Show incomplete checkpoint archives in selections',
    'Verbindung, Borg-Nutzdaten, Archive und Verwaltung zentral im Manager.': 'Manage connectivity, Borg data, archives and administration centrally.',
    'Verschlüsselte Backups erhalten die Endung': 'Encrypted backups use the extension',
    'Verwaltete Repositories werden direkt im Manager-Container geöffnet. SSH zum Backup-Client ist dafür nicht erforderlich.': 'Managed repositories are opened directly in the manager container. SSH to the backup client is not required.',
    'Vorher wird automatisch ein lokales Sicherheitsbackup erstellt. Nach dem Einspielen werden Benutzerkonten, Sitzungen und der zum Backup gehörende Master-Key übernommen; bestehende Browser-Sitzungen müssen sich anschließend neu anmelden.': 'A local safety backup is created automatically first. Restoring replaces user accounts, sessions and the backup master key; existing browser sessions must sign in again afterward.',
    'authenticated – unverschlüsselt, authentifiziert': 'authenticated – unencrypted, authenticated',
    'authenticated-blake2 – unverschlüsselt, authentifiziert': 'authenticated-blake2 – unencrypted, authenticated',
    'keyfile – verschlüsselt, separater Schlüssel': 'keyfile – encrypted, separate key',
    'keyfile-blake2 – verschlüsselt, separater Schlüssel': 'keyfile-blake2 – encrypted, separate key',
    'none – unverschlüsselt und nicht authentifiziert': 'none – unencrypted and unauthenticated',
    'repokey – verschlüsselt, SHA-256': 'repokey – encrypted, SHA-256',
    'repokey-blake2 – verschlüsselt, Schlüssel im Repository': 'repokey-blake2 – encrypted, key stored in repository',
    'zstd,6 – stärker': 'zstd,6 – stronger',
    '„Nur testen“ liest und prüft die ausgewählten Daten, schreibt aber keine Dateien.': '“Dry run only” reads and verifies the selected data but does not write files.',
    ', die danach automatisch entfernt wird.': ', which is then removed automatically.',
    ', geschützt durch': ', protected by',
    '. Beim alternativen Ziel kann das gemeinsame übergeordnete Archivverzeichnis automatisch entfernt werden, sodass nur die ausgewählte Datei oder der ausgewählte Ordner direkt im Ziel landet.': '. For an alternative target, the common parent archive directory can be removed automatically so only the selected file or directory is placed directly in the target.',
    '. Die Passphrase wird nicht gespeichert.': '. The passphrase is not stored.',
    '. Nur während eines Borg-Aufrufs entsteht eine temporäre Datei unter': '. A temporary file is created under only while Borg is running',
    'wird wieder zu': 'becomes',
    'Verschlüsselung ist verpflichtend:': 'Encryption is mandatory:',
    'Neue Manager-Backups werden ausschließlich als verschlüsselte': 'New manager backups are created only as encrypted',
    'Dateien erstellt.': 'files.',
    'Passphrase für Sicherheitsbackup': 'Safety backup passphrase',
    'Sicherheits-Passphrase wiederholen': 'Repeat safety passphrase',
    '(nur für das ausgewählte verschlüsselte Backup)': '(only for the selected encrypted backup)',
    'Vorher wird automatisch ein lokal gespeichertes und mit der gesonderten Sicherheits-Passphrase verschlüsseltes Backup erstellt. Nach dem Einspielen werden Benutzerkonten, Sitzungen und der zum Backup gehörende Master-Key übernommen; bestehende Browser-Sitzungen müssen sich anschließend neu anmelden.': 'A locally stored backup encrypted with the separate safety passphrase is created automatically first. Restoring replaces user accounts, sessions and the backup master key; existing browser sessions must sign in again afterward.',
    'Zu viele Anmeldeversuche von dieser Quelle. Bitte später erneut versuchen.': 'Too many sign-in attempts from this source. Please try again later.',
    'Missing anti-CSRF request header': 'The required browser security header is missing.',
    'Request origin does not match this BorgBackup Manager': 'The request origin does not match this BorgBackup Manager.',
    'Administrator': 'Administrator', 'Benutzer': 'User'
  };

  Object.assign(exact, {
    '0 Zeitpläne': '0 schedules',
    'Aktion konnte nicht gestartet werden': 'Action could not be started',
    'Alle Bereiche aktualisiert': 'All areas refreshed',
    'Alle Bereiche werden aktualisiert …': 'Refreshing all areas …',
    'Alle abgeschlossenen Ausführungsprotokolle und zugehörigen Logdateien wirklich löschen? Laufende Jobs bleiben erhalten.': 'Delete all completed run records and related log files? Running jobs are preserved.',
    'Alter Archiv-Mount wurde ausgehängt': 'Legacy archive mount was unmounted',
    'Archive werden angezeigt …': 'Loading archives …',
    'Archive werden geladen …': 'Loading archives …',
    'Archivinhalt konnte nicht gelesen werden. Die Fehlermeldung bleibt oberhalb sichtbar.': 'Archive contents could not be read. The error remains visible above.',
    'Archivinhalt wird gelesen …': 'Reading archive contents …',
    'Archivliste konnte nicht geladen werden.': 'Archive list could not be loaded.',
    'Archivliste nicht verfügbar': 'Archive list unavailable',
    'Archivliste nicht verfügbar. Die Fehlermeldung steht oberhalb der Liste.': 'Archive list unavailable. The error is shown above the list.',
    'Archivliste wird manuell aktualisiert …': 'Refreshing archive list manually …',
    'Archivlöschung konnte nicht gestartet werden': 'Archive deletion could not be started',
    'Archivumbenennung konnte nicht gestartet werden': 'Archive rename could not be started',
    'Archivvergleich konnte nicht gestartet werden': 'Archive comparison could not be started',
    'Auswahl geändert – gespeicherte Archivliste anzeigen oder Repository neu einlesen.': 'Selection changed – show the cached archive list or reload the repository.',
    'Automatisches Präfix wird nach dem Speichern erzeugt.': 'The automatic prefix is generated after saving.',
    'Backup auswählen': 'Select backup',
    'Backup gelöscht': 'Backup deleted',
    'Backup konnte nicht gelöscht werden': 'Backup could not be deleted',
    'Backup wird geprüft und für die Wiederherstellung vorbereitet …': 'Verifying backup and preparing restore …',
    'Backup-Job bearbeiten': 'Edit backup job',
    'Backup-Job ist deaktiviert': 'Backup job is disabled',
    'Backup-Job wirklich löschen? Vorhandene Borg-Archive und abgeschlossene Protokolle bleiben erhalten.': 'Delete this backup job? Existing Borg archives and completed logs are preserved.',
    'Benutzer aktualisiert': 'User updated',
    'Benutzer angelegt': 'User created',
    'Benutzer bearbeiten': 'Edit user',
    'Benutzer gelöscht': 'User deleted',
    'Benutzer konnte nicht gespeichert werden': 'User could not be saved',
    'Benutzer wird gespeichert …': 'Saving user …',
    'Benutzerkonto wirklich löschen? Alle Sitzungen dieses Kontos werden beendet.': 'Delete this user account? All sessions for this account will be ended.',
    'Bestehendes Repository: ': 'Existing repository: ',
    'Bitte die mögliche Ersetzung vorhandener Dateien ausdrücklich bestätigen.': 'Please explicitly confirm that existing files may be replaced.',
    'Bitte zuerst eine Ausschlussvorlage auswählen': 'Select an exclusion template first',
    'Borg-Prüfung fehlgeschlagen': 'Borg check failed',
    'Borg-Version wird geprüft …': 'Checking Borg version …',
    'Cache-Löschung fehlgeschlagen': 'Cache deletion failed',
    'Controller-Schlüssel fehlt – Installer erneut ausführen.': 'Controller key is missing – run the installer again.',
    'Controller-Schlüssel wird erneuert …': 'Rotating controller key …',
    'Dabei werden keine Archive, keine Repository-Konfiguration und keine Passphrase gelöscht.': 'This does not delete archives, repository configuration or passphrases.',
    'Das temporäre Passwort muss vor der weiteren Nutzung geändert werden.': 'The temporary password must be changed before continuing.',
    'Daten bleiben lesbar, Manipulationen werden mit BLAKE2b erkannt.': 'Data remains readable; tampering is detected with BLAKE2b.',
    'Daten bleiben lesbar, Manipulationen werden mit SHA-256 erkannt.': 'Data remains readable; tampering is detected with SHA-256.',
    'Der Browser hat die Sitzung nicht übernommen.': 'The browser did not retain the session.',
    'Der automatische Neustart dauert ungewöhnlich lange. Containerstatus und Logs prüfen.': 'The automatic restart is taking unusually long. Check container status and logs.',
    'Der letzte Administrator kann nicht gelöscht werden': 'The last administrator cannot be deleted',
    'Der nächste Zugriff kann länger dauern, weil Borg den Cache neu aufbaut.': 'The next access may take longer while Borg rebuilds the cache.',
    'Diagnose wird geladen …': 'Loading diagnostics …',
    'Eigenes Konto · letzter Administrator geschützt': 'Own account · last administrator protected',
    'Eigenes Passwort über die Seitenleiste ändern': 'Change your own password from the sidebar',
    'Export wird im Manager erstellt. Bei größeren Verzeichnissen kann dies dauern …': 'The export is being created in the manager. Large directories may take some time …',
    'Für den Archivvergleich wird derzeit ein Backup-Job dieses Repositorys benötigt': 'Archive comparison currently requires a backup job for this repository',
    'Für den Export wird ein Backup-Job dieses verwalteten Repositorys benötigt': 'Export requires a backup job for this managed repository',
    'Für den Vergleich zwei unterschiedliche Archive auswählen': 'Select two different archives for comparison',
    'Für die Wiederherstellung am Originalpfad muss mindestens eine Datei oder ein Ordner ausgewählt sein.': 'At least one file or directory must be selected to restore to the original location.',
    'Gerät bearbeiten': 'Edit device', 'Gerät wirklich entfernen?': 'Remove this device?',
    'Gespeicherte Änderungen werden angezeigt …': 'Showing saved changes …',
    'Gespeicherter Hostschlüssel wird beibehalten.': 'The stored host key is preserved.',
    'Größe': 'Size', 'Größe letzte Sicherung': 'Latest backup size',
    'Größenberechnung fehlgeschlagen': 'Size calculation failed',
    'Hostkey gespeichert': 'Host key saved',
    'Initialisierung konnte nicht gestartet werden': 'Initialization could not be started',
    'Jede Ausschlussvorlage benötigt einen Namen': 'Every exclusion template requires a name',
    'Kein Befehl gespeichert.': 'No command stored.',
    'Keine Fehler oder Warnungen erkannt.': 'No errors or warnings detected.',
    'Keine Standardausgabe.': 'No standard output.',
    'Keine Verschlüsselung und keine Authentifizierung. Nur verwenden, wenn dies ausdrücklich gewünscht ist.': 'No encryption and no authentication. Use only when explicitly intended.',
    'Keine technischen Details gespeichert.': 'No technical details stored.',
    'Keine Ausschlussvorlage angelegt.': 'No exclusion template created.',
    'Keine Benutzer vorhanden.': 'No users available.',
    'Keine noch nicht registrierten Borg-Repositories gefunden.': 'No unregistered Borg repositories found.',
    'Keine passenden Archive vorhanden.': 'No matching archives available.',
    'Keine passenden Ausführungen vorhanden.': 'No matching runs available.',
    'Keine passenden Backup-Jobs vorhanden.': 'No matching backup jobs available.',
    'Noch keine Aktivitäten.': 'No activity yet.',
    'Noch keine Geräte angelegt.': 'No devices created yet.',
    'Noch keine zentralen Zeitpläne angelegt. Alle Backup-Jobs werden manuell ausgeführt.': 'No central schedules created yet. All backup jobs run manually.',
    'Repository-Verzeichnis wird durchsucht …': 'Searching repository directory …',
    '„Archive anzeigen“ verwendet den persistenten Zwischenspeicher; „Neu aus Repository einlesen“ erzwingt einen Borg-Scan.': '“Show archives” uses the persistent cache; “Reload from repository” forces a Borg scan.',
    'Lauf': 'Run', 'Legacy-/fremdes Archiv': 'Legacy/foreign archive', 'Letzter Job': 'Latest run',
    'Löschen fehlgeschlagen': 'Deletion failed', 'Löschung wird gestartet …': 'Starting deletion …',
    'Manager-Backup konnte nicht erstellt werden': 'Manager backup could not be created',
    'Ein Manager-Backup mit diesem Dateinamen ist bereits vorhanden': 'A manager backup with this file name already exists',
    'Ungültiger Backup-Dateiname': 'Invalid backup file name',
    'Nur .bbm- und historische .zip-Manager-Backups werden unterstützt': 'Only .bbm and historical .zip manager backups are supported',
    'Backup verwendet nicht unterstützte Verschlüsselungsparameter': 'The backup uses unsupported encryption parameters',
    'Verschlüsseltes Backup ist unvollständig': 'The encrypted backup is incomplete',
    'Gerät kann während laufender oder wartender Ausführungen nicht deaktiviert werden': 'The device cannot be disabled while runs are active or queued',
    'Backup-Job kann während einer laufenden oder wartenden Ausführung nicht deaktiviert werden': 'The backup job cannot be disabled while a run is active or queued',
    'Manager-Backup wird erstellt …': 'Creating manager backup …',
    'Manager-Backup wirklich löschen?': 'Delete this manager backup?',
    'Mindestens eine Ausführungszeit festlegen': 'Specify at least one run time',
    'Mindestens eine Uhrzeit auswählen': 'Select at least one time',
    'Mindestens einen Wochentag auswählen': 'Select at least one weekday',
    'Namen von Ausschlussvorlagen müssen eindeutig sein': 'Exclusion template names must be unique',
    'Neuer Archivname. Das Job-Präfix muss erhalten bleiben:': 'New archive name. The job prefix must be preserved:',
    'Passwort gesetzt; bestehende Sitzungen wurden beendet': 'Password set; existing sessions were ended',
    'Passwort geändert. Bitte mit dem neuen Passwort erneut anmelden.': 'Password changed. Please sign in again with the new password.',
    'Persönliche Einstellungen gespeichert': 'Personal settings saved',
    'Prüfung erforderlich': 'Check required', 'Prüfung fehlgeschlagen': 'Check failed',
    'Repository bearbeiten': 'Edit repository', 'Repository prüfen und einbinden': 'Verify and import repository',
    'Repository wird eingelesen …': 'Reading repository …',
    'Repository-Aktion erfolgreich': 'Repository action successful',
    'Repository-Aktion fehlgeschlagen': 'Repository action failed',
    'Repository-Aktion läuft': 'Repository action running',
    'Repository-Cache wird gelöscht …': 'Clearing repository cache …',
    'Repository-Eintrag wirklich entfernen? Repository-Daten werden dadurch nicht automatisch gelöscht.': 'Remove this repository entry? Repository data is not deleted automatically.',
    'Repository-Größe wird berechnet …': 'Calculating repository size …',
    'Repository-ID: ': 'Repository ID: ',
    'Repository-Prüfung fehlgeschlagen': 'Repository check failed',
    'Repository-Verbindung wird geprüft …': 'Testing repository connection …',
    'Repository-Zugang eingerichtet': 'Repository access configured',
    'Repository-Zugang für den Backup-Job wird eingerichtet …': 'Configuring repository access for the backup job …',
    'Repository-Zugang zuerst einrichten': 'Configure repository access first',
    'Repository-Zugang zuerst im Backup-Job einrichten': 'Configure repository access in the backup job first',
    'Repository-Zugänge': 'Repository access',
    'Repository-Speicher konnte nicht ermittelt werden.': 'Repository storage could not be determined.',
    'Repository-Zugang fehlt': 'Repository access missing',
    'Restore konnte nicht gestartet werden: ': 'Restore could not be started: ',
    'SSH-Fingerprint bestätigt': 'SSH fingerprint accepted',
    'SSH-Fingerprint muss geprüft werden.': 'SSH fingerprint must be verified.',
    'SSH-Fingerprint wird vom Gerät abgerufen …': 'Retrieving SSH fingerprint from device …',
    'SSH-Fingerprint zuerst prüfen': 'Verify SSH fingerprint first',
    'Schlüssel erneuert. Der neue öffentliche Schlüssel muss jetzt auf allen Geräten hinterlegt werden.': 'Key rotated. The new public key must now be installed on every device.',
    'Separater BLAKE2b-Schlüssel. Beim Import muss der vorhandene Borg-Keyfile-Inhalt angegeben werden.': 'Separate BLAKE2b key. Import requires the existing Borg keyfile content.',
    'Separater Schlüssel. Beim Import muss der vorhandene Borg-Keyfile-Inhalt angegeben werden.': 'Separate key. Import requires the existing Borg keyfile content.',
    'Sicherheitsprüfung OK': 'Security check OK', 'Sicherheitsprüfung erforderlich': 'Security check required',
    'Standortbestätigung konnte nicht gestartet werden': 'Location confirmation could not be started',
    'Nur bestätigen, wenn dieses Repository absichtlich verschoben oder unter einer neuen URL eingebunden wurde und SSH-Fingerprint sowie Zielpfad geprüft wurden. Die Aktion wird repositoryweit eingereiht; mehrere Jobs desselben Geräts verwenden denselben Bestätigungslauf. Borg aktualisiert anschließend den Sicherheitsstatus dieses Clients. Fortfahren?': 'Confirm only when this repository was intentionally moved or connected through a new URL and the SSH fingerprint and target path have been verified. The action is queued repository-wide; multiple jobs on the same device reuse the same confirmation run. Borg then updates this client’s security state. Continue?',
    'Systemdiagnose wird geladen …': 'Loading system diagnostics …',
    'Technische Details anzeigen': 'Show technical details',
    'Technische Repository-Details': 'Technical repository details',
    'Vergleich wird gestartet …': 'Starting comparison …',
    'Verschlüsselter Schlüssel liegt im Repository; BLAKE2b ist auf vielen Systemen schneller.': 'The encrypted key is stored in the repository; BLAKE2b is faster on many systems.',
    'Verschlüsselter Schlüssel liegt im Repository; kompatibel mit älteren Borg-Versionen.': 'The encrypted key is stored in the repository; compatible with older Borg versions.',
    'Version prüfen': 'Check version',
    'Verwaltetes Repository erstellen': 'Create managed repository',
    'Vorhandenes Repository einbinden': 'Import existing repository',
    'Vorhandenes externes Repository hinzufügen': 'Add existing external repository',
    'Vorhandenes lokales Repository einbinden': 'Import existing local repository',
    'Warnung': 'Warning', 'Wiederherstellung konnte nicht gestartet werden: ': 'Restore could not be started: ',
    'Wiederholung konnte nicht gestartet werden': 'Retry could not be started',
    'Wird aktualisiert …': 'Refreshing …',
    'Zeitplan aktualisiert': 'Schedule updated', 'Zeitplan bearbeiten': 'Edit schedule',
    'Zeitplan erstellt': 'Schedule created', 'Zeitplan gelöscht': 'Schedule deleted',
    'Zeitplan konnte nicht gespeichert werden': 'Schedule could not be saved',
    'Zeitplan wird gespeichert …': 'Saving schedule …',
    'Zuerst mindestens eine Datei oder einen Ordner auswählen': 'Select at least one file or directory first',
    'Zwei Archive auswählen': 'Select two archives',
    'alle': 'all', 'erfolgreich': 'successful', 'erfolgreich abgeschlossen': 'completed successfully',
    'gespeichert': 'saved', 'läuft': 'running', 'mit Warnung abgeschlossen': 'completed with warning',
    'nicht geprüft': 'not checked', 'noch nicht aktualisiert': 'not refreshed yet',
    'unvollständig': 'incomplete', 'verschlüsselt': 'encrypted', 'wartet': 'queued',
    'Änderungen speichern': 'Save changes', 'Änderungen werden gespeichert …': 'Saving changes …',
    'Änderungen werden übernommen …': 'Applying changes …',
    'Öffentlicher Repository-Schlüssel kopiert': 'Public repository key copied',
    'Checkpoint · unvollständig': 'Checkpoint · incomplete',
    'Für Restore/Änderungen zuerst einen Backup-Job für dieses Repository anlegen.': 'Create a backup job for this repository before restore or modification.',
    'keine Statistik gespeichert': 'no statistics stored',
    'Letzter Administrator': 'Last administrator', 'Letzter Administrator · geschützt': 'Last administrator · protected',
    'Das Archiv wurde erstellt, die genannten Dateien können aber einen inkonsistenten Zwischenstand enthalten.': 'The archive was created, but the listed files may contain an inconsistent intermediate state.',
    'Schreibintensive Anwendungen möglichst per Snapshot sichern oder während des Backups kurz anhalten.': 'Back up write-intensive applications from a snapshot or pause them briefly during the backup.',
    'Das Archiv wurde erstellt, die betroffenen Dateien fehlen jedoch möglicherweise oder wurden nur unvollständig übernommen.': 'The archive was created, but affected files may be missing or only partially included.',
    'Berechtigungen, verschwundene Pfade und mögliche I/O-Fehler prüfen; danach den Backup-Lauf wiederholen.': 'Check permissions, disappeared paths and possible I/O errors, then repeat the backup run.',
    'Das Archiv wurde gespeichert, enthält wegen der aufgeführten Warnungen aber möglicherweise nicht alle Daten konsistent oder vollständig.': 'The archive was saved, but due to the listed warnings it may not contain all data consistently or completely.',
    'Die Warnungsliste prüfen, Ursache beheben und den Backup-Lauf anschließend wiederholen.': 'Review the warning list, fix the cause and then repeat the backup run.',
    'Borg meldete eine Warnung ohne Detailzeile': 'Borg reported a warning without a detail line',
    'Der Lauf endete mit RC 1, im von Borg ausgegebenen Text war jedoch keine konkrete Ursache enthalten.': 'The run ended with rc 1, but Borg did not include a concrete cause in its output.',
    'Den vollständigen Lauf prüfen und den Backup-Job erneut beobachten. Bleibt die Ursache unbekannt, Borg auf dem Gerät aktualisieren und die Dateiliste testweise aktivieren.': 'Review the complete run and observe the backup job again. If the cause remains unknown, update Borg on the device and temporarily enable the file list.',
    'Repository-Sperre trotz Warteschlange nicht frei': 'Repository lock still unavailable after queueing',
    'Die Manager-Warteschlange hat die Standortbestätigung serialisiert. Borg selbst konnte die Repository-Sperre jedoch innerhalb von 600 Sekunden nicht erhalten.': 'The manager queue serialized the location confirmation, but Borg itself could not acquire the repository lock within 600 seconds.',
    'Prüfen, ob außerhalb des BorgBackup Managers noch ein Borg-Prozess auf dieses Repository zugreift. Nur wenn sicher kein Prozess mehr läuft, die verwaiste Sperre mit break-lock entfernen.': 'Check whether a Borg process outside BorgBackup Manager is still accessing this repository. Only remove the stale lock with break-lock when no process is definitely running.',
    'Repository-Aktionen werden serialisiert; Borg wartet bei Bedarf bis zu 600 Sekunden auf eine aktive Sperre.': 'Repository actions are serialized; Borg waits up to 600 seconds for an active lock when necessary.'
  });

  const patterns = [
    [/^(\d+) Jobs$/, '$1 jobs'], [/^(\d+) Zeitpläne$/, '$1 schedules'], [/^(\d+) angezeigt$/, '$1 shown'],
    [/^(\d+) ausgewählt$/, '$1 selected'], [/^Gerät: (.+)$/, 'Device: $1'],
    [/^(\d+) Aufgabe aktiv$/, '$1 active task'], [/^(\d+) Aufgaben aktiv$/, '$1 active tasks'],
    [/^(\d+) läuft$/, '$1 running'], [/^(\d+) wartet$/, '$1 queued'],
    [/^Lauf #(\d+) wurde angenommen …$/, 'Run #$1 was accepted …'],
    [/^Standortbestätigung #(\d+) eingereiht$/, 'Location confirmation #$1 queued'],
    [/^WARTESCHLANGE: Warte auf Repository-Ausführung #(\d+)\.$/, 'QUEUE: waiting for repository run #$1.'],
    [/^WARTESCHLANGE: Globale Parallelitätsgrenze (\d+) erreicht; warte auf Ausführung #(\d+)\.$/, 'QUEUE: global parallelism limit $1 reached; waiting for run #$2.'],
    [/^WARTESCHLANGE: Zeitplan „(.+)“ erlaubt maximal (\d+) parallele Ausführung\(en\); warte auf Ausführung #(\d+)\.$/, 'QUEUE: schedule “$1” allows at most $2 parallel runs; waiting for run #$3.'],
    [/^max\. (\d+)$/, 'max. $1'],
    [/^Lauf #(\d+) gestartet$/, 'Run #$1 started'], [/^Protokoll #(\d+) gelöscht$/, 'Log #$1 deleted'],
    [/^Job (\d+)$/, 'Job $1'], [/^Zeitplan: (.+)$/, 'Schedule: $1'], [/^Version (.+)$/, 'Version $1'],
    [/^([\d.,]+) abgeschlossene Protokolle$/, '$1 completed logs'],
    [/^Noch keine (.+) vorhanden\.$/, 'No $1 available yet.'],
    [/^Anmeldung fehlgeschlagen: (.+)$/, 'Sign-in failed: $1'],
    [/^Sitzung konnte nicht wiederhergestellt werden: (.+)$/, 'Session could not be restored: $1'],
    [/^Passwort geändert\. Bitte mit dem neuen Passwort erneut anmelden\.$/, 'Password changed. Please sign in again with the new password.'],
    [/^(.+) als Lauf #(\d+) gestartet\.$/, '$1 started as run #$2.'],
    [/^(.+) #(\d+) gestartet$/, '$1 #$2 started'],
    [/^([\d.]+) Min\.$/, '$1 min'], [/^([\d.]+) Sek\.$/, '$1 sec'], [/^([\d.]+) Std\.$/, '$1 hr'],
    [/^Dauer (.+) · $/, 'Duration $1 · '],
    [/^Letztes Backup · (.+)$/, 'Latest backup · $1'],
    [/^Live-Scan vor Ausschlüssen · (.+)$/, 'Live scan before exclusions · $1'],
    [/^täglich · (.+)$/, 'daily · $1'], [/^monatlich am (\d+)\. · (.+)$/, 'monthly on day $1 · $2'],
    [/^Vorlage „(.+)“ hinzugefügt$/, 'Template “$1” added'],
    [/^Die Ausschlussvorlage „(.+)“ enthält keine Muster$/, 'Exclusion template “$1” contains no patterns'],
    [/^(.+) wird geprüft …$/, 'Checking $1 …'], [/^(.+) wird geladen …$/, 'Loading $1 …'],
    [/^(\d+) Datei wurde während der Sicherung verändert$/, '$1 file changed during the backup'],
    [/^(\d+) Dateien wurden während der Sicherung verändert$/, '$1 files changed during the backup'],
    [/^(\d+) Datei konnte nicht vollständig gelesen werden$/, '$1 file could not be read completely'],
    [/^(\d+) Dateien konnten nicht vollständig gelesen werden$/, '$1 files could not be read completely'],
    [/^Backup mit (\d+) konkreten Warnhinweisen$/, 'Backup with $1 concrete warning causes'],
    [/^Repository-Verzeichnis ist nicht leer\. Es wurden keine Dateien gelöscht\. Vorhandene Einträge: (.+)$/, 'Repository directory is not empty. No files were deleted. Existing entries: $1'],
    [/^Repository-Verzeichnis ist nicht leer; Initialisierung wurde nicht gestartet\. Vorhandene Einträge: (.+)$/, 'Repository directory is not empty; initialization was not started. Existing entries: $1'],
    [/^Repository-Verzeichnis kann nicht geprüft werden: (.+)$/, 'Repository directory cannot be inspected: $1'],
    [/^Der Pfad des verwalteten Repositorys kann nicht aufgelöst werden: (.+)$/, 'Managed repository path cannot be resolved: $1'],
  ];

  const reverseExact = new Map(Object.entries(exact).map(([de, en]) => [en, de]));
  const textSources = new WeakMap();
  const attributeSources = new WeakMap();
  let currentLanguage = (() => {
    try { return localStorage.getItem('bbm-language') === 'en' ? 'en' : 'de'; } catch { return 'de'; }
  })();
  let translating = false;

  function translateRaw(value) {
    const text = String(value ?? '');
    if (currentLanguage !== 'en' || !text.trim()) return text;
    const leading = text.match(/^\s*/)?.[0] || '';
    const trailing = text.match(/\s*$/)?.[0] || '';
    const core = text.slice(leading.length, text.length - trailing.length || undefined);
    if (exact[core]) return leading + exact[core] + trailing;
    for (const [pattern, replacement] of patterns) {
      if (pattern.test(core)) return leading + core.replace(pattern, replacement) + trailing;
    }
    return text;
  }

  function sourceForNewValue(value, previous = '') {
    const text = String(value ?? '');
    if (currentLanguage === 'en' && reverseExact.has(text.trim())) return previous || reverseExact.get(text.trim());
    return text;
  }

  function skipped(node) {
    const element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
    return Boolean(element?.closest('[data-i18n-skip], code, pre, script, style'));
  }

  function translateTextNode(node) {
    if (skipped(node)) return;
    const previous = textSources.get(node) || '';
    if (!translating) textSources.set(node, sourceForNewValue(node.nodeValue, previous));
    const source = textSources.get(node) ?? node.nodeValue;
    const translated = currentLanguage === 'de' ? source : translateRaw(source);
    // MutationObserver callbacks run asynchronously, after `translating` has
    // already been reset. Writing an identical value would therefore create a
    // new mutation record and can trap the browser in an endless callback loop.
    if (node.nodeValue !== translated) node.nodeValue = translated;
  }

  function translateAttributes(element) {
    if (skipped(element)) return;
    const names = ['placeholder', 'title', 'aria-label'];
    let sources = attributeSources.get(element);
    if (!sources) { sources = {}; attributeSources.set(element, sources); }
    for (const name of names) {
      if (!element.hasAttribute(name)) continue;
      const value = element.getAttribute(name) || '';
      if (!translating) sources[name] = sourceForNewValue(value, sources[name] || '');
      const source = sources[name] ?? value;
      const translated = currentLanguage === 'de' ? source : translateRaw(source);
      // Avoid self-triggering attribute mutations for values that are already
      // translated (or already restored to German).
      if (value !== translated) element.setAttribute(name, translated);
    }
  }

  function translateDom(root = document.body) {
    if (!root) return;
    translating = true;
    try {
      if (root.nodeType === Node.TEXT_NODE) translateTextNode(root);
      else {
        if (root.nodeType === Node.ELEMENT_NODE) translateAttributes(root);
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
          if (node.nodeType === Node.TEXT_NODE) translateTextNode(node);
          else translateAttributes(node);
        }
      }
      document.documentElement.lang = currentLanguage;
    } finally { translating = false; }
  }

  function setLanguage(language, persist = true) {
    currentLanguage = language === 'en' ? 'en' : 'de';
    if (persist) {
      try { localStorage.setItem('bbm-language', currentLanguage); } catch { /* optional browser storage */ }
    }
    translateDom(document.body);
    document.dispatchEvent(new CustomEvent('bbm-language-changed', {detail: {language: currentLanguage}}));
  }

  function translateMessage(message) { return translateRaw(message); }
  function language() { return currentLanguage; }

  const observer = new MutationObserver((mutations) => {
    if (translating) return;
    for (const mutation of mutations) {
      if (mutation.type === 'characterData') translateTextNode(mutation.target);
      else if (mutation.type === 'attributes') translateAttributes(mutation.target);
      else for (const node of mutation.addedNodes) translateDom(node);
    }
  });

  function start() {
    translateDom(document.body);
    observer.observe(document.documentElement, {subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['placeholder', 'title', 'aria-label']});
  }

  window.BBMI18n = {setLanguage, translateDom, translateMessage, language};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true}); else start();
})();
