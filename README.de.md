<div align="center">

<img src="app/assets/macsist-1024.png" width="128" alt="Macsist-Symbol" />

# Macsist

**Ein nativer macOS-Menüleisten-Assistent, der alles Markierte erklärt — sofort, lokal, in deiner Sprache.**

Kurzbefehl drücken → eine knappe, gestreamte Erklärung des **markierten Texts** (in jeder App) oder eines per Ziehen gewählten **Bildschirmbereichs**, in einem schwebenden Glas-Panel direkt am Cursor. Angetrieben von einem **lokalen** MLX-Modell — oder jeder OpenAI-kompatiblen API. Keine Cloud, kein Electron.

![macOS 26.2+](https://img.shields.io/badge/macOS-26.2%2B-black?logo=apple)
![Apple Silicon](https://img.shields.io/badge/Apple%20Silicon-arm64-555)
![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![Local-first](https://img.shields.io/badge/LLM-local%20MLX-orange)
![Languages](https://img.shields.io/badge/languages-6-brightgreen)

<a href="README.md">English</a> · <a href="README.ko.md">한국어</a> · <a href="README.zh.md">简体中文</a> · <a href="README.ja.md">日本語</a> · <a href="README.fr.md">Français</a> · <b>Deutsch</b>

</div>

---

## ✨ Was es macht

Markiere etwas Text — einen fremdsprachigen Satz, einen dichten Absatz, eine Fehlermeldung, ein Stück Code — drücke `⌘⇧E`, und Macsist streamt eine kurze Erklärung in ein kleines Panel neben dem Cursor. Kein Fensterwechsel, kein Kopieren in eine Chat-App. Es nimmt der App, in der du arbeitest, nie den Fokus.

- **📝 Text erklären** — `⌘⇧E` liest die Auswahl über die Bedienungshilfen (mit einem zwischenablagesicheren synthetischen ⌘C als Rückfall — die Zwischenablage wird stets wiederhergestellt).
- **🖼 Bereich erklären** — `⌘⇧R` zeigt ein Fadenkreuz wie ⌘⇧4; das aufgenommene Bild geht an ein lokales **Vision**-Modell (ideal für Diagramme, Tabellen, Screenshots — alles, was sich nicht markieren lässt).
- **💬 Nachfragen** — tippe nach einer Antwort direkt ins Panel. **Enter** sendet, **Umschalt+Enter** fügt einen Zeilenumbruch ein; das Eingabefeld wächst und das Panel folgt. Gleiches Gespräch, gleiches Modell — Vision-Sitzungen behalten das Bild im Kontext.
- **🌍 6 Sprachen** — 한국어 · English · 简体中文 · 日本語 · Français · Deutsch, für **Oberfläche und Antworten**. In den Einstellungen live umschaltbar, ohne Neustart. Eine Eingabe in einer anderen Sprache erhält zuerst eine natürliche `Übersetzung:`-Zeile.
- **🪟 Liquid-Glass-Panel** — ein durchscheinendes, abgerundetes, selbstgrößendes Panel, das am Cursor einblendet. **Zieh es am Hintergrund** überallhin.
- **🗂 Verlauf** — jede Erklärung wird lokal gespeichert und ist durchsuchbar (`⌘⇧H`). Kopieren, mit dem aktuellen Modell **erneut fragen** (Bereichseinträge senden den gespeicherten Screenshot erneut) oder eine Sitzung löschen — alles in einem Chat-artigen Fenster.
- **🔌 Dein Modell, deine Wahl** — betreibe einen **lokalen** MLX-Server oder richte Macsist auf jede **OpenAI-kompatible API** (OpenRouter usw.). API-Schlüssel liegen im macOS-**Schlüsselbund**, nie auf der Festplatte.
- **🔒 Standardmäßig privat** — lokal zuerst, keine Telemetrie, kein Electron. Ein echtes signiertes `.app`-Bundle: Dock, Cmd-Tab und die Berechtigungslisten zeigen alle **Macsist** mit Symbol.

---

## 📸 In Aktion

<div align="center">

**Markierten Text erklären** — markiere eine Passage, drücke `⌘⇧E`, und eine Übersetzung plus eine knappe Erklärung erscheinen direkt daneben im Stream.

<img src="assets/HotKeyEx-test.png" width="760" alt="Erklärung von markiertem Text aus einem Forschungsartikel" />

**Bildschirmbereich erklären** — wähle eine Abbildung mit `⌘⇧R` und Macsist erklärt das ganze Diagramm.

<img src="assets/HotKeyEx-image-2.png" width="760" alt="Erklärung einer aus einem PDF aufgenommenen Abbildung" />

</div>

---

## 🖥 Voraussetzungen

- **macOS 26.2+** auf **Apple Silicon**
- Für ein lokales Modell: etwa **16 GB+** Unified Memory (der Installer empfiehlt ein zu deinem RAM passendes Modell). Auf kleineren Maschinen nutze stattdessen eine externe OpenAI-kompatible API — kein lokales Modell nötig.

---

## ⬇️ Installation

```bash
git clone https://github.com/junidude/macsist.git
cd macsist
./install.sh
```

Eine interaktive Sitzung erledigt alles, und sie ist **idempotent** — jederzeit erneut ausführbar; abgeschlossene Schritte werden übersprungen:

1. **Hardware-Prüfung** → empfiehlt ein zum RAM passendes Modell (Qwen 3.6 / Gemma 4 multimodale Stufen, oder eine externe API für kleine Maschinen)
2. **Umgebung** → miniforge/conda-Umgebung für den Server
3. **Modell-Download** (fragt nach einem optionalen Hugging-Face-Token für schnellere Downloads)
4. **Hintergrunddienste** → Server und App als launchd-Agents installiert (immer aktiv bei der Anmeldung, Auto-Neustart bei Absturz)
5. **`macsist`-CLI** → in deinem `PATH` installiert
6. **Berechtigungen** → führt durch die macOS-Freigaben **Bedienungshilfen** und **Bildschirmaufnahme**
7. **Rauchtest** → ein echter Erklär-Durchlauf zur Bestätigung

Nach dem Erteilen der Berechtigungen die App neu starten: `macsist restart app`.

<details>
<summary><b>Manueller / Entwickler-Weg</b> (was der Installer automatisiert)</summary>

```bash
server/download_models.sh   # einmaliger Modell-Download
server/deploy.sh            # Server-LaunchAgent installieren
app/deploy.sh               # signiertes App-Bundle bauen + installieren
app/run.sh                  # …oder die App zur Entwicklung im Vordergrund starten
```

`app/deploy.sh` baut mit py2app ein echtes signiertes Bundle — es braucht ein
Framework-Python: `brew install python@3.13`. Vollständige Spezifikation und
Architektur: [docs/SPEC.md](docs/SPEC.md).
</details>

---

## 🚀 Bedienung

| Kurzbefehl | Aktion |
| --- | --- |
| `⌘⇧E` | Markierten Text erklären |
| `⌘⇧R` | Bildschirmbereich ziehen und erklären |
| `⌘⇧H` | Verlauf-/Einstellungsfenster öffnen |
| `Enter` | Nachfrage senden |
| `Umschalt+Enter` | Zeilenumbruch im Eingabefeld |
| `Esc` | Eingabe leeren, dann Panel schließen |

Alle Kurzbefehle sind unter **Einstellungen → Kurzbefehle** neu belegbar. Das Ergebnis-Panel aktiviert die App nie, dein aktuelles Fenster behält durchgehend den Fokus.

---

## 🎛 Konfiguration

Öffne die **Einstellungen** über das Menüleistensymbol (oder `macsist settings`):

- **Allgemein** — **Sprache** von Oberfläche und Antworten (gilt sofort beim Sichern).
- **Verbindung** — aktiven **Anbieter** wählen (lokaler Server oder externer OpenAI-kompatibler Endpunkt), dessen URL, Modelle und API-Schlüssel setzen. Schlüssel liegen im **Schlüsselbund**. Anbieterwechsel ohne Neustart.
- **Antwort** — **Detailgrad**: Kurz · Normal · Ausführlich (Länge und Tiefe).
- **Kurzbefehle** — neue Kurzbefehle aufnehmen (nach physischer Taste erkannt, daher unter jeder Tastaturbelegung gültig).
- **Darstellung** — Panel-Größe, Schriftgröße, Glas-Stil.
- **Erweitert** — System-Prompts (Text und Bild), temperature, max tokens, Nachfrage-Tiefe und eine Schaltfläche zum Zurücksetzen auf Standardwerte.

---

## 🧰 `macsist`-CLI

Von `install.sh` als Symlink in deinem `PATH` installiert — funktioniert aus jedem Verzeichnis.

| Befehl | Funktion |
| --- | --- |
| `macsist` | stellt sicher, dass beide Agents laufen, und gibt eine Statusübersicht aus |
| `macsist start\|stop\|restart [app\|server]` | die launchd-Agents verwalten |
| `macsist status` | Agents, Serverzustand, Anbieter/Modelle, TCC-Status |
| `macsist logs [app\|server] [-f]` | die passenden Logdateien verfolgen |
| `macsist settings` / `macsist history` | das Hauptfenster öffnen |
| `macsist doctor` | vollständige ✓/✗-Diagnose: Deploy, Konfig, Schlüsselbund-Schlüssel, Zustand, TCC, Modell-Cache |
| `macsist update` | `git pull --ff-only` + erneutes Deployen beider Agents |

---

## 🏗 Funktionsweise

Die App ist ein **schlanker HTTP-Client**. Sie spricht mit einem OpenAI-kompatiblen LLM-Server unter `http://127.0.0.1:8000` — einem kleinen FastAPI-Proxy, der zum richtigen MLX-Backend routet:

```
app ──► :8000  Proxy (FastAPI)
                 ├─ reines Textmodell (dense)  ─► :8002  mlx-lm
                 └─ multimodal (Text+Bild)     ─► :8001  mlx-vlm
```

Der Proxy streamt Tokens (SSE) unverändert durch, sodass die App stets nur mit `:8000` spricht; ein Wechsel des `model`-Felds routet transparent zum richtigen Backend. Server und App laufen beide als **launchd-Agents** (immer aktiv bei der Anmeldung, Auto-Neustart bei Absturz). Modelle sind konfigurierbar, nie fest codiert.

Logs:

```bash
tail -f ~/Library/Logs/Macsist/app.log        # die Menüleisten-App
tail -f ~/Library/Logs/llm-server/proxy.log   # der LLM-Proxy
```

Vollständige Architektur, Meilensteine (M0–M12) und Designnotizen: **[docs/SPEC.md](docs/SPEC.md)**.

---

## 🩺 Fehlerbehebung

- **`macsist doctor`** — ein Befehl prüft Deploy, Konfig, Schlüsselbund-Schlüssel, Serverzustand, TCC-Berechtigungen und Modell-Cache.
- **Kurzbefehle tun nichts** → **Bedienungshilfen** erteilen, dann `macsist restart app`.
- **Bereichsaufnahme schlägt fehl** → **Bildschirmaufnahme** erteilen, dann `macsist restart app`.
- **Server nicht erreichbar** → `macsist status` / `macsist logs server -f`. Der erste Start lädt das Modell in den Speicher (~60–90 s).
- **Stream endet ohne Antwort** → ein „thinking“-Modell hat evtl. das Token-Budget verbraucht; erhöhe **max tokens** oder prüfe das Modell in den Einstellungen.

---

<div align="center">
<sub>Gebaut mit Python 3.13 + PyObjC (AppKit), <code>pynput</code>, <code>httpx</code> · MLX (<code>mlx-lm</code> / <code>mlx-vlm</code>) hinter einem FastAPI-Proxy · Apple Silicon, macOS 26.2+</sub>
</div>
