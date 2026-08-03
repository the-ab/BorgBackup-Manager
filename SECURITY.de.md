# Sicherheitsrichtlinie

## Unterstützte Version

Sicherheitskorrekturen werden ausschließlich für die aktuelle BorgBackup-Manager-Version veröffentlicht. Der gepflegte Produktstand ist BorgBackup Manager v1.3.8.

v1.3.8 behält v1.3.5 als einmalige Kompatibilitätsgrenze bei. Jede regulär gestartete v1.3.5-Installation kann direkt aktualisiert werden; harmlose zusätzliche Datenbankobjekte werden erst nach einer geprüften verlustfreien Übernahme normalisiert. Frühere Versionen werden nicht gepflegt und können eine Neuinstallation von v1.3.8 erfordern. Manager- und Cache-Backups müssen der unterstützten Baseline v1.3.5 oder neuer entsprechen.

[English version](SECURITY.md)

## Sicherheitslücke melden

Vermutete Sicherheitslücken dürfen nicht in einem öffentlichen Issue, einer Diskussion, einem Log oder Screenshot offengelegt werden. Verwende nach Möglichkeit die private Sicherheitsmeldung von GitHub für dieses Repository. Ist diese Funktion nicht verfügbar, kontaktiere den Maintainer privat über die Kontaktmöglichkeit im GitHub-Profil des Repository-Eigentümers.

Eine Meldung sollte möglichst enthalten:

- betroffene Version und Installationsart;
- kurze Beschreibung der Auswirkung;
- reproduzierbare Schritte oder einen minimalen Proof of Concept;
- relevante, bereinigte Logs;
- Hinweis, ob Zugangsdaten, Repositories oder Sicherungsdaten betroffen sein könnten.

Niemals echte Passwörter, Passphrasen, private Schlüssel, Sitzungscookies, produktive Datenbanken oder unbereinigte Kundendaten anhängen.

Der Maintainer bestätigt eine vollständige Meldung, bewertet den Schweregrad, bereitet eine Korrektur vor und koordiniert die Veröffentlichung. Eine feste Reaktions- oder Veröffentlichungsfrist wird nicht zugesagt. Vor einer öffentlichen Offenlegung ist eine angemessene Behebungsfrist einzuräumen.

## Anforderungen an den Betrieb

- Aktuelle Version über den integrierten HTTPS-Endpunkt oder einen korrekt konfigurierten vertrauenswürdigen Reverse Proxy betreiben.
- Zugriff auf WebUI und Repository-SSH-Port per Host- oder Netzwerk-Firewall beschränken.
- `/data/security/security.db`, `/data/security/master.key`, Manager-Backups und deren Passphrasen geheim halten.
- `.env`-Dateien mit Modus `0600` schützen und niemals committen.
- Vor Updates die bereitgestellte Prüfsumme kontrollieren.
- Vor jedem Update ein verschlüsseltes Manager-Backup erstellen und prüfen.
- Unbereinigte Access-, Debug-, SSH- oder Borg-Logs nicht veröffentlichen.
