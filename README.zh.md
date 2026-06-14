<div align="center">

<img src="app/assets/macsist-1024.png" width="128" alt="Macsist 图标" />

# Macsist

**一款原生 macOS 菜单栏助手，即时、本地、用你的语言解释你选中的任何内容。**

按下快捷键 → 在光标旁悬浮的玻璃面板中，流式获得对**选中文本**（任意 App）或拖选**屏幕区域**的简洁解释。由**本地** MLX 模型驱动 —— 或任意 OpenAI 兼容 API。无需云端，没有 Electron。

![macOS 26.2+](https://img.shields.io/badge/macOS-26.2%2B-black?logo=apple)
![Apple Silicon](https://img.shields.io/badge/Apple%20Silicon-arm64-555)
![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![Local-first](https://img.shields.io/badge/LLM-local%20MLX-orange)
![Languages](https://img.shields.io/badge/languages-6-brightgreen)

<a href="README.md">English</a> · <a href="README.ko.md">한국어</a> · <b>简体中文</b> · <a href="README.ja.md">日本語</a> · <a href="README.fr.md">Français</a> · <a href="README.de.md">Deutsch</a>

</div>

---

## ✨ 它能做什么

选中一段文字 —— 一句外语、一段密集的文字、一条报错、一小段代码 —— 按 `⌘⇧E`，Macsist 就会在光标旁的小面板中流式输出简短解释。无需切换窗口，无需复制粘贴到聊天 App。它绝不会从你正在使用的窗口抢走焦点。

- **📝 解释文本** —— `⌘⇧E` 通过辅助功能（Accessibility）读取你的选区（并有剪贴板安全的合成 ⌘C 兜底 —— 剪贴板始终会被还原）。
- **🖼 解释区域** —— `⌘⇧R` 给你一个类似 ⌘⇧4 的十字光标；截取的图像送往本地**视觉**模型（非常适合图表、表格、截图等无法选中的内容）。
- **💬 追问对话** —— 得到回答后，直接在面板里输入。**Enter** 发送，**Shift+Enter** 换行；输入框随输入变长，面板也随之增大。同一段对话、同一个模型 —— 视觉会话会在上下文中保留图像。
- **🌍 6 种语言** —— 한국어 · English · 简体中文 · 日本語 · Français · Deutsch，**界面与回答**皆可。在设置中实时切换，无需重启。其他语言的输入会先附上自然的 `翻译：` 一行。
- **🪟 液态玻璃面板** —— 半透明、圆角、自动调整大小的面板在光标旁淡入。**抓住背景即可拖动**到任意位置。
- **🗂 历史记录** —— 每次解释都本地保存并可搜索（`⌘⇧H`）。可复制、用当前模型**再次提问**（区域条目会重发已保存的截图），或删除某个会话 —— 全在聊天式窗口中完成。
- **🔌 你的模型，你做主** —— 运行**本地** MLX 服务器，或将 Macsist 指向任意 **OpenAI 兼容 API**（OpenRouter 等）。API 密钥保存在 macOS **钥匙串**中，绝不落盘。
- **🔒 默认私密** —— 本地优先，无遥测，无 Electron。真正签名的 `.app` 包：Dock、Cmd-Tab 和权限列表都以图标显示为 **Macsist**。

---

## 📸 实际效果

<div align="center">

**解释选中文本** —— 高亮一段文字，按 `⌘⇧E`，翻译与简洁解释便在一旁流式呈现。

<img src="assets/HotKeyEx-test.png" width="760" alt="解释论文中选中的文本" />

**解释屏幕区域** —— 用 `⌘⇧R` 拖选一张图，Macsist 为你拆解整张图示。

<img src="assets/HotKeyEx-image-2.png" width="760" alt="解释从 PDF 截取的图示" />

</div>

---

## 🖥 系统要求

- **Apple Silicon** 上的 **macOS 26.2+**
- 本地模型需大约 **16 GB+** 统一内存（安装程序会推荐与你内存匹配的模型）。内存较小的机器可改用外部 OpenAI 兼容 API，无需本地模型。

---

## ⬇️ 下载

**只想要 App？** 下载最新版本：

### → [**下载 Macsist.dmg**](https://github.com/junidude/macsist/releases/latest/download/Macsist.dmg)

该版本为**自签名**（未经 Apple 公证），首次打开时 macOS 会拦截并提示 *"Apple 无法验证 'Macsist' 是否包含恶意软件"* —— 这是正常的，**并非**恶意软件。**不要点击"移到废纸篓"：**

1. 把 **Macsist** 拖入**应用程序**，在弹窗上点击**"完成"**。
2. 打开**系统设置 → 隐私与安全性**，向下滚动，点击 Macsist 提示旁的**"仍要打开"**，确认后即可打开。
   *(终端替代方案：`xattr -dr com.apple.quarantine /Applications/Macsist.app`)*

之后即可正常双击打开。首次启动时会询问使用外部 API 还是本地模型。

---

## 🛠 从源码安装

如需完整的本地模型栈：

```bash
git clone https://github.com/junidude/macsist.git
cd macsist
./install.sh
```

一次交互式会话即可完成全部，并且是**幂等的** —— 随时可重新运行，已完成的步骤会被跳过：

1. **硬件检查** → 推荐与内存匹配的模型（Qwen 3.6 / Gemma 4 多模态档位，小机器用外部 API）
2. **环境配置** → 服务器所用的 miniforge/conda 环境
3. **下载模型**（询问一个可选的 Hugging Face 令牌以加快下载）
4. **后台服务** → 将服务器与 App 安装为 launchd 代理（登录时常驻，崩溃自动重启）
5. **`macsist` CLI** → 安装到 `PATH`
6. **权限** → 引导你完成 macOS **辅助功能**与**屏幕录制**授权
7. **冒烟测试** → 一次真实的解释往返以确认可用

授权后重启 App：`macsist restart app`。

<details>
<summary><b>手动 / 开发者路径</b>（安装程序所自动化的内容）</summary>

```bash
server/download_models.sh   # 一次性下载模型
server/deploy.sh            # 安装服务器 LaunchAgent
app/deploy.sh               # 构建并安装签名的 App 包
app/run.sh                  # …或在前台运行 App 以便开发
```

`app/deploy.sh` 用 py2app 构建真正的签名包 —— 需要框架版 Python：
`brew install python@3.13`。完整规格与架构：
[docs/SPEC.md](docs/SPEC.md)。
</details>

---

## 🚀 使用

| 快捷键 | 操作 |
| --- | --- |
| `⌘⇧E` | 解释选中的文本 |
| `⌘⇧R` | 拖选屏幕区域并解释 |
| `⌘⇧H` | 打开历史记录 / 设置窗口 |
| `Enter` | 发送追问 |
| `Shift+Enter` | 在追问框中换行 |
| `Esc` | 清空输入，再次按下关闭面板 |

所有快捷键都可在**设置 → 快捷键**中重新绑定。结果面板不会激活 App，因此你当前的窗口始终保持焦点。

---

## 🎛 配置

从菜单栏图标打开**设置**（或 `macsist settings`）：

- **通用** —— 界面与回答**语言**（保存即时生效）。
- **连接** —— 选择活动**提供方**（本地服务器或外部 OpenAI 兼容端点），设置其地址、模型与 API 密钥。密钥存于**钥匙串**。切换提供方无需重启。
- **回答** —— **详细程度**：简短 · 普通 · 详细（控制长度与深度）。
- **快捷键** —— 录制新快捷键（按物理按键匹配，因此在任意键盘布局下都有效）。
- **外观** —— 面板大小、字号、玻璃样式。
- **高级** —— 系统提示词（文本与图像）、temperature、max tokens、追问深度，以及恢复默认按钮。

---

## 🧰 `macsist` CLI

由 `install.sh` 作为软链接安装到 `PATH` —— 在任意目录均可使用。

| 命令 | 功能 |
| --- | --- |
| `macsist` | 确保两个代理在运行，然后打印状态摘要 |
| `macsist start\|stop\|restart [app\|server]` | 管理 launchd 代理 |
| `macsist status` | 代理、服务器健康、提供方/模型、TCC 状态 |
| `macsist logs [app\|server] [-f]` | tail 对应的日志文件 |
| `macsist settings` / `macsist history` | 打开主窗口 |
| `macsist doctor` | 完整 ✓/✗ 诊断：部署、配置、钥匙串密钥、健康、TCC、模型缓存 |
| `macsist update` | `git pull --ff-only` + 重新部署两个代理 |

---

## 🏗 工作原理

App 是一个**轻量 HTTP 客户端**。它与 `http://127.0.0.1:8000` 上的 OpenAI 兼容 LLM 服务器通信 —— 一个将请求路由到正确 MLX 后端的小型 FastAPI 代理：

```
app ──► :8000  代理 (FastAPI)
                 ├─ 纯文本 dense 模型      ─► :8002  mlx-lm
                 └─ 多模态 (文本+图像)     ─► :8001  mlx-vlm
```

代理将 token（SSE）原样转发，因此 App 始终只与 `:8000` 通信；切换 `model` 字段即可透明地路由到正确的后端。服务器与 App 都作为 **launchd 代理**运行（登录时常驻，崩溃自动重启）。模型可配置，绝不硬编码。

日志：

```bash
tail -f ~/Library/Logs/Macsist/app.log        # 菜单栏 App
tail -f ~/Library/Logs/llm-server/proxy.log   # LLM 代理
```

完整架构、里程碑（M0–M12）与设计说明：**[docs/SPEC.md](docs/SPEC.md)**。

---

## 🩺 故障排查

- **`macsist doctor`** —— 一条命令检查部署、配置、钥匙串密钥、服务器健康、TCC 权限与模型缓存。
- **快捷键无反应** → 授予**辅助功能**，然后 `macsist restart app`。
- **区域截图失败** → 授予**屏幕录制**，然后 `macsist restart app`。
- **服务器无法连接** → `macsist status` / `macsist logs server -f`。首次启动会把模型加载进内存（约 60–90 秒）。
- **流结束却没有回答** → thinking 模型可能用尽了 token 预算；调高 **max tokens**，或在设置中检查模型。

---

<div align="center">
<sub>使用 Python 3.13 + PyObjC (AppKit)、<code>pynput</code>、<code>httpx</code> 构建 · FastAPI 代理之后的 MLX（<code>mlx-lm</code> / <code>mlx-vlm</code>）· Apple Silicon，macOS 26.2+</sub>
</div>
