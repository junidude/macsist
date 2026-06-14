<div align="center">

<img src="app/assets/macsist-1024.png" width="128" alt="Icône Macsist" />

# Macsist

**Un assistant natif dans la barre de menus macOS qui explique tout ce que vous sélectionnez — instantanément, en local, dans votre langue.**

Un raccourci → une explication concise et en flux du **texte sélectionné** (dans n'importe quelle app) ou d'une **zone de l'écran** que vous sélectionnez à la souris, dans un panneau de verre flottant près du curseur. Propulsé par un modèle MLX **local** — ou n'importe quelle API compatible OpenAI. Sans cloud, sans Electron.

![macOS 26.2+](https://img.shields.io/badge/macOS-26.2%2B-black?logo=apple)
![Apple Silicon](https://img.shields.io/badge/Apple%20Silicon-arm64-555)
![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![Local-first](https://img.shields.io/badge/LLM-local%20MLX-orange)
![Languages](https://img.shields.io/badge/languages-6-brightgreen)

<a href="README.md">English</a> · <a href="README.ko.md">한국어</a> · <a href="README.zh.md">简体中文</a> · <a href="README.ja.md">日本語</a> · <b>Français</b> · <a href="README.de.md">Deutsch</a>

</div>

---

## ✨ Ce que ça fait

Sélectionnez du texte — une phrase en langue étrangère, un paragraphe dense, un message d'erreur, un bout de code — appuyez sur `⌘⇧E`, et Macsist diffuse une courte explication dans un petit panneau près du curseur. Pas de changement de fenêtre, pas de copier-coller dans une app de chat. Il ne vole jamais le focus à ce sur quoi vous travaillez.

- **📝 Expliquer du texte** — `⌘⇧E` lit votre sélection via l'Accessibilité (avec un repli ⌘C synthétique sûr pour le presse-papiers — toujours restauré).
- **🖼 Expliquer une zone** — `⌘⇧R` affiche un réticule comme ⌘⇧4 ; l'image capturée part vers un modèle **vision** local (idéal pour les schémas, tableaux, captures — tout ce qu'on ne peut pas sélectionner).
- **💬 Questions de suivi** — après une réponse, tapez directement dans le panneau. **Entrée** envoie, **Maj+Entrée** insère un saut de ligne ; la zone de saisie s'agrandit et le panneau suit. Même conversation, même modèle — les sessions vision gardent l'image dans le contexte.
- **🌍 6 langues** — 한국어 · English · 简体中文 · 日本語 · Français · Deutsch, pour **l'interface comme pour les réponses**. Changez en direct dans les Réglages, sans redémarrage. Une saisie dans une autre langue reçoit d'abord une ligne `Traduction :` naturelle.
- **🪟 Panneau Liquid Glass** — un panneau translucide, arrondi, à taille automatique qui apparaît en fondu près du curseur. **Glissez-le où vous voulez** par son arrière-plan.
- **🗂 Historique** — chaque explication est enregistrée localement et consultable (`⌘⇧H`). Copiez-la, reposez-la avec le modèle actuel (les entrées de zone renvoient la capture enregistrée), ou supprimez une session — le tout dans une fenêtre façon chat.
- **🔌 Votre modèle, votre choix** — un serveur MLX **local**, ou pointez Macsist vers n'importe quelle **API compatible OpenAI** (OpenRouter, etc.). Les clés API vivent dans le **Trousseau** macOS, jamais sur le disque.
- **🔒 Privé par défaut** — local d'abord, sans télémétrie, sans Electron. Un vrai bundle `.app` signé : le Dock, Cmd-Tab et les listes d'autorisations affichent tous **Macsist** avec son icône.

---

## 📸 En action

<div align="center">

**Expliquer le texte sélectionné** — surlignez un passage, appuyez sur `⌘⇧E`, et une traduction plus une explication concise s'affichent juste à côté en flux.

<img src="assets/HotKeyEx-test.png" width="760" alt="Explication d'un texte sélectionné dans un article de recherche" />

**Expliquer une zone de l'écran** — sélectionnez une figure avec `⌘⇧R` et Macsist décrypte tout le schéma.

<img src="assets/HotKeyEx-image-2.png" width="760" alt="Explication d'une figure capturée depuis un PDF" />

</div>

---

## 🖥 Prérequis

- **macOS 26.2+** sur **Apple Silicon**
- Pour un modèle local : environ **16 Go+** de mémoire unifiée (l'installateur recommande un modèle adapté à votre RAM). Sur les machines plus modestes, utilisez plutôt une API externe compatible OpenAI — aucun modèle local requis.

---

## ⬇️ Télécharger

**Vous voulez juste l'app ?** Téléchargez la dernière version :

### → [**Télécharger Macsist.dmg**](https://github.com/junidude/macsist/releases/latest/download/Macsist.dmg)

Cette version est **auto-signée** (non notariée par Apple), donc au premier lancement macOS la bloque avec *« Apple n'a pas pu vérifier que ‘Macsist' ne contient pas de logiciel malveillant »* — c'est normal, ce **n'est pas** un malware. **Ne cliquez pas sur _Placer dans la corbeille_ :**

1. Glissez **Macsist** dans **Applications**, puis cliquez **« Terminé »** sur la boîte de dialogue.
2. Ouvrez **Réglages Système → Confidentialité et sécurité**, faites défiler vers le bas et cliquez sur **« Ouvrir quand même »** à côté du message Macsist, puis confirmez — elle s'ouvre.
   *(Alternative Terminal : `xattr -dr com.apple.quarantine /Applications/Macsist.app`)*

Ensuite elle s'ouvre normalement par double-clic. Au premier lancement, Macsist demande d'utiliser une API externe ou un modèle local.

---

## 🛠 Installer depuis les sources

Pour la pile de modèle local complète :

```bash
git clone https://github.com/junidude/macsist.git
cd macsist
./install.sh
```

Une seule session interactive fait tout, et elle est **idempotente** — relancez-la à tout moment ; les étapes terminées sont ignorées :

1. **Vérification matérielle** → recommande un modèle adapté à votre RAM (paliers multimodaux Qwen 3.6 / Gemma 4, ou une API externe pour les petites machines)
2. **Environnement** → environnement miniforge/conda pour le serveur
3. **Téléchargement du modèle** (demande un jeton Hugging Face optionnel pour accélérer)
4. **Services en arrière-plan** → serveur et app installés comme agents launchd (toujours actifs à l'ouverture de session, redémarrage auto en cas de crash)
5. **CLI `macsist`** → installée dans votre `PATH`
6. **Autorisations** → vous guide pour les permissions macOS **Accessibilité** et **Enregistrement de l'écran**
7. **Test de fumée** → un véritable aller-retour d'explication pour confirmer que tout marche

Après avoir accordé les permissions, redémarrez l'app : `macsist restart app`.

<details>
<summary><b>Voie manuelle / développeur</b> (ce que l'installateur automatise)</summary>

```bash
server/download_models.sh   # téléchargement unique du modèle
server/deploy.sh            # installe le LaunchAgent du serveur
app/deploy.sh               # construit + installe le bundle d'app signé
app/run.sh                  # …ou lance l'app au premier plan pour le développement
```

`app/deploy.sh` construit un vrai bundle signé avec py2app — il faut un Python
« framework » : `brew install python@3.13`. Spécification et architecture
complètes : [docs/SPEC.md](docs/SPEC.md).
</details>

---

## 🚀 Utilisation

| Raccourci | Action |
| --- | --- |
| `⌘⇧E` | Expliquer le texte sélectionné |
| `⌘⇧R` | Sélectionner une zone de l'écran et l'expliquer |
| `⌘⇧H` | Ouvrir la fenêtre Historique / Réglages |
| `Entrée` | Envoyer une question de suivi |
| `Maj+Entrée` | Saut de ligne dans la zone de suivi |
| `Échap` | Effacer la saisie, puis fermer le panneau |

Tous les raccourcis se réassignent dans **Réglages → Raccourcis**. Le panneau de résultat n'active jamais l'app : votre fenêtre courante garde le focus tout du long.

---

## 🎛 Configuration

Ouvrez les **Réglages** depuis l'icône de la barre de menus (ou `macsist settings`) :

- **Général** — **langue** de l'interface et des réponses (appliquée dès l'enregistrement).
- **Connexion** — choisissez le **fournisseur** actif (serveur local ou point d'accès externe compatible OpenAI), son URL, ses modèles et sa clé API. Les clés sont dans le **Trousseau**. Changez de fournisseur sans redémarrer.
- **Réponse** — **niveau de détail** : Bref · Normal · Détaillé (longueur et profondeur).
- **Raccourcis** — enregistrez de nouveaux raccourcis (reconnus par touche physique : ils marchent sous n'importe quelle disposition clavier).
- **Apparence** — taille du panneau, taille de police, style de verre.
- **Avancé** — prompts système (texte et image), temperature, max tokens, profondeur de suivi, et un bouton de restauration des valeurs par défaut.

---

## 🧰 CLI `macsist`

Installée par `install.sh` comme lien symbolique dans votre `PATH` — fonctionne depuis n'importe quel dossier.

| Commande | Rôle |
| --- | --- |
| `macsist` | s'assure que les deux agents tournent, puis affiche un résumé d'état |
| `macsist start\|stop\|restart [app\|server]` | gérer les agents launchd |
| `macsist status` | agents, santé du serveur, fournisseur/modèles, état TCC |
| `macsist logs [app\|server] [-f]` | suit les bons fichiers de log |
| `macsist settings` / `macsist history` | ouvre la fenêtre principale |
| `macsist doctor` | diagnostic complet ✓/✗ : déploiement, config, clé du Trousseau, santé, TCC, cache de modèles |
| `macsist update` | `git pull --ff-only` + redéploiement des deux agents |

---

## 🏗 Comment ça marche

L'app est un **client HTTP léger**. Elle parle à un serveur LLM compatible OpenAI sur `http://127.0.0.1:8000` — un petit proxy FastAPI qui route vers le bon backend MLX :

```
app ──► :8000  proxy (FastAPI)
                 ├─ modèle texte dense       ─► :8002  mlx-lm
                 └─ multimodal (texte+image)  ─► :8001  mlx-vlm
```

Le proxy diffuse les tokens (SSE) tels quels : l'app ne parle donc qu'à `:8000` ; changer le champ `model` route de façon transparente vers le bon backend. Le serveur et l'app tournent tous deux comme **agents launchd** (toujours actifs à l'ouverture de session, redémarrage auto en cas de crash). Les modèles sont configurables, jamais codés en dur.

Logs :

```bash
tail -f ~/Library/Logs/Macsist/app.log        # l'app de la barre de menus
tail -f ~/Library/Logs/llm-server/proxy.log   # le proxy LLM
```

Architecture complète, jalons (M0–M12) et notes de conception : **[docs/SPEC.md](docs/SPEC.md)**.

---

## 🩺 Dépannage

- **`macsist doctor`** — une commande qui vérifie le déploiement, la config, la clé du Trousseau, la santé du serveur, les permissions TCC et le cache de modèles.
- **Les raccourcis ne font rien** → accordez l'**Accessibilité**, puis `macsist restart app`.
- **La capture de zone échoue** → accordez l'**Enregistrement de l'écran**, puis `macsist restart app`.
- **Serveur injoignable** → `macsist status` / `macsist logs server -f`. Le premier démarrage charge le modèle en mémoire (~60–90 s).
- **Le flux se termine sans réponse** → un modèle « thinking » a peut-être épuisé le budget de tokens ; augmentez **max tokens**, ou vérifiez le modèle dans les Réglages.

---

<div align="center">
<sub>Construit avec Python 3.13 + PyObjC (AppKit), <code>pynput</code>, <code>httpx</code> · MLX (<code>mlx-lm</code> / <code>mlx-vlm</code>) derrière un proxy FastAPI · Apple Silicon, macOS 26.2+</sub>
</div>
