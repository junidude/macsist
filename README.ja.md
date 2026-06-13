<div align="center">

<img src="app/assets/macsist-1024.png" width="128" alt="Macsist アイコン" />

# Macsist

**選択したものを何でも、即座に、ローカルで、あなたの言語で説明する macOS メニューバーアシスタント。**

ホットキーを押す → **選択テキスト**（どのアプリでも）やドラッグ選択した**画面領域**の簡潔な説明が、カーソル横の浮遊するガラスパネルにストリーミングされます。**ローカル** MLX モデル ── または任意の OpenAI 互換 API ── で動作。クラウド不要、Electron なし。

![macOS 26.2+](https://img.shields.io/badge/macOS-26.2%2B-black?logo=apple)
![Apple Silicon](https://img.shields.io/badge/Apple%20Silicon-arm64-555)
![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![Local-first](https://img.shields.io/badge/LLM-local%20MLX-orange)
![Languages](https://img.shields.io/badge/languages-6-brightgreen)

<a href="README.md">English</a> · <a href="README.ko.md">한국어</a> · <a href="README.zh.md">简体中文</a> · <b>日本語</b> · <a href="README.fr.md">Français</a> · <a href="README.de.md">Deutsch</a>

</div>

---

## ✨ 何ができるのか

テキストを選んで ── 外国語の一文、密度の高い段落、エラーメッセージ、コードの断片 ── `⌘⇧E` を押すと、Macsist がカーソル横の小さなパネルに短い説明をストリーミングします。ウィンドウの切り替えも、チャットアプリへのコピペも不要。作業中のウィンドウからフォーカスを奪うことはありません。

- **📝 テキストを説明** ── `⌘⇧E` がアクセシビリティ経由で選択範囲を読み取ります（クリップボード安全な合成 ⌘C のフォールバック付き ── クリップボードは常に復元されます）。
- **🖼 領域を説明** ── `⌘⇧R` で ⌘⇧4 のような十字カーソルを表示し、取り込んだ画像をローカルの**ビジョン**モデルへ送ります（図・表・スクリーンショットなど、選択できないものに最適）。
- **💬 追加質問** ── 回答の後、パネルにそのまま入力。**Enter** で送信、**Shift+Enter** で改行。入力欄は伸び、パネルもそれに追従します。同じ会話、同じモデル ── ビジョンのセッションは画像を文脈に保持します。
- **🌍 6 言語** ── 한국어 · English · 简体中文 · 日本語 · Français · Deutsch を、**UI と回答の両方**で。設定でライブ切り替え、再起動不要。別言語の入力にはまず自然な `翻訳:` 行が付きます。
- **🪟 リキッドグラスのパネル** ── 半透明・角丸・自動サイズのパネルがカーソル横にフェードイン。背景をつかんで**どこへでもドラッグ**して移動できます。
- **🗂 履歴** ── すべての説明がローカルに保存され検索可能（`⌘⇧H`）。コピー、現在のモデルで**もう一度質問**（領域の項目は保存したスクリーンショットを再送信）、セッションの削除 ── すべてチャット風のウィンドウで。
- **🔌 モデルは自由に** ── **ローカル** MLX サーバーを動かすか、任意の **OpenAI 互換 API**（OpenRouter など）を指定。API キーは macOS の**キーチェーン**に保存され、ディスクには残りません。
- **🔒 既定でプライベート** ── ローカル優先、テレメトリなし、Electron なし。本物の署名済み `.app` バンドル：Dock・Cmd-Tab・権限リストはアイコン付きで **Macsist** と表示されます。

---

## 📸 実際の動作

<div align="center">

**選択テキストを説明** ── 文章を選んで `⌘⇧E` を押すと、訳と簡潔な説明がすぐ隣にストリーミングされます。

<img src="assets/HotKeyEx-test.png" width="760" alt="論文で選択したテキストを説明" />

**画面領域を説明** ── `⌘⇧R` で図をドラッグ選択すると、Macsist が図解全体を読み解きます。

<img src="assets/HotKeyEx-image-2.png" width="760" alt="PDF から取り込んだ図を説明" />

</div>

---

## 🖥 必要環境

- **Apple Silicon** の **macOS 26.2+**
- ローカルモデルにはおよそ **16 GB 以上**のユニファイドメモリ（インストーラーがメモリに合ったモデルを推奨）。メモリの少ないマシンでは外部の OpenAI 互換 API を使えば、ローカルモデルは不要です。

---

## ⬇️ インストール

```bash
git clone https://github.com/junidude/macsist.git
cd macsist
./install.sh
```

対話セッション 1 回ですべてが完了し、**冪等**です ── いつ再実行しても、完了済みの手順はスキップされます：

1. **ハードウェア確認** → メモリに合ったモデルを推奨（Qwen 3.6 / Gemma 4 のマルチモーダル各層、小型マシンは外部 API）
2. **環境構築** → サーバー用の miniforge/conda 環境
3. **モデルのダウンロード**（より速いダウンロードのため、任意の Hugging Face トークンを尋ねます）
4. **バックグラウンドサービス** → サーバーとアプリを launchd エージェントとして導入（ログイン時に常駐、クラッシュ時に自動再起動）
5. **`macsist` CLI** → `PATH` に導入
6. **権限** → macOS の**アクセシビリティ**と**画面収録**の許可を案内
7. **スモークテスト** → 実際の説明の往復で動作を確認

許可の付与後、アプリを再起動します：`macsist restart app`。

<details>
<summary><b>手動 / 開発者向けの手順</b>（インストーラーが自動化する内容）</summary>

```bash
server/download_models.sh   # モデルの一度きりのダウンロード
server/deploy.sh            # サーバーの LaunchAgent を導入
app/deploy.sh               # 署名済みアプリバンドルをビルド + 導入
app/run.sh                  # …または開発用にアプリをフォアグラウンド実行
```

`app/deploy.sh` は py2app で本物の署名バンドルをビルドします ── フレームワーク版の
Python が必要です：`brew install python@3.13`。完全な仕様とアーキテクチャ：
[docs/SPEC.md](docs/SPEC.md)。
</details>

---

## 🚀 使い方

| ホットキー | 動作 |
| --- | --- |
| `⌘⇧E` | 選択したテキストを説明 |
| `⌘⇧R` | 画面領域をドラッグ選択して説明 |
| `⌘⇧H` | 履歴 / 設定ウィンドウを開く |
| `Enter` | 追加質問を送信 |
| `Shift+Enter` | 入力欄で改行 |
| `Esc` | 入力をクリア、もう一度でパネルを閉じる |

すべてのホットキーは**設定 → ショートカット**で再割り当てできます。結果パネルはアプリをアクティブにしないため、現在のウィンドウのフォーカスはずっと保たれます。

---

## 🎛 設定

メニューバーのアイコンから**設定**を開きます（または `macsist settings`）：

- **一般** ── UI と回答の**言語**（保存時に即適用）。
- **接続** ── アクティブな**プロバイダー**を選択（ローカルサーバーまたは外部 OpenAI 互換エンドポイント）、その URL・モデル・API キーを設定。キーは**キーチェーン**に保存。再起動なしで切り替え。
- **応答** ── **詳しさ**：簡単 · 普通 · 詳しく（長さと深さを調整）。
- **ショートカット** ── 新しいショートカットを記録（物理キーで照合するため、どのキーボード配列でも有効）。
- **外観** ── パネルサイズ、フォントサイズ、ガラススタイル。
- **詳細** ── システムプロンプト（テキストと画像）、temperature、max tokens、追加質問の深さ、デフォルトに戻すボタン。

---

## 🧰 `macsist` CLI

`install.sh` がシンボリックリンクとして `PATH` に導入 ── どのディレクトリからでも使えます。

| コマンド | 機能 |
| --- | --- |
| `macsist` | 両エージェントの稼働を確認し、状態サマリーを表示 |
| `macsist start\|stop\|restart [app\|server]` | launchd エージェントを管理 |
| `macsist status` | エージェント、サーバー状態、プロバイダー/モデル、TCC 状態 |
| `macsist logs [app\|server] [-f]` | 適切なログファイルを tail |
| `macsist settings` / `macsist history` | メインウィンドウを開く |
| `macsist doctor` | 完全な ✓/✗ 診断：デプロイ、設定、キーチェーンのキー、ヘルス、TCC、モデルキャッシュ |
| `macsist update` | `git pull --ff-only` + 両エージェントの再デプロイ |

---

## 🏗 仕組み

アプリは**薄い HTTP クライアント**です。`http://127.0.0.1:8000` の OpenAI 互換 LLM サーバー ── 適切な MLX バックエンドへルーティングする小さな FastAPI プロキシ ── と通信します：

```
app ──► :8000  プロキシ (FastAPI)
                 ├─ テキスト専用 dense モデル   ─► :8002  mlx-lm
                 └─ マルチモーダル (テキスト+画像) ─► :8001  mlx-vlm
```

プロキシはトークン（SSE）をそのまま流すため、アプリは常に `:8000` だけと通信します。`model` フィールドを切り替えると、適切なバックエンドへ透過的にルーティングされます。サーバーとアプリはどちらも **launchd エージェント**として動作します（ログイン時に常駐、クラッシュ時に自動再起動）。モデルは設定可能で、ハードコードされません。

ログ：

```bash
tail -f ~/Library/Logs/Macsist/app.log        # メニューバーアプリ
tail -f ~/Library/Logs/llm-server/proxy.log   # LLM プロキシ
```

完全なアーキテクチャ、マイルストーン（M0–M12）、設計ノート：**[docs/SPEC.md](docs/SPEC.md)**。

---

## 🩺 トラブルシューティング

- **`macsist doctor`** ── デプロイ、設定、キーチェーンのキー、サーバー状態、TCC 権限、モデルキャッシュを 1 コマンドで確認。
- **ホットキーが効かない** → **アクセシビリティ**を許可し、`macsist restart app`。
- **領域キャプチャが失敗** → **画面収録**を許可し、`macsist restart app`。
- **サーバーに接続できない** → `macsist status` / `macsist logs server -f`。初回起動はモデルをメモリに読み込みます（約 60〜90 秒）。
- **応答なしでストリームが終わる** → thinking モデルがトークン予算を使い切った可能性があります。**max tokens** を上げるか、設定でモデルを確認してください。

---

<div align="center">
<sub>Python 3.13 + PyObjC (AppKit)、<code>pynput</code>、<code>httpx</code> で構築 · FastAPI プロキシ越しの MLX（<code>mlx-lm</code> / <code>mlx-vlm</code>）· Apple Silicon、macOS 26.2+</sub>
</div>
