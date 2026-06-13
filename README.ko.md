<div align="center">

<img src="app/assets/macsist-1024.png" width="128" alt="Macsist 아이콘" />

# Macsist

**선택한 무엇이든 즉시, 로컬에서, 당신의 언어로 설명해 주는 macOS 메뉴 막대 어시스턴트.**

단축키 한 번 → **선택한 텍스트**(모든 앱) 또는 드래그한 **화면 영역**의 간결한 설명이 커서 옆 떠 있는 글래스 패널에 스트리밍됩니다. **로컬** MLX 모델 — 또는 OpenAI 호환 API — 로 동작합니다. 클라우드 불필요, Electron 없음.

![macOS 26.2+](https://img.shields.io/badge/macOS-26.2%2B-black?logo=apple)
![Apple Silicon](https://img.shields.io/badge/Apple%20Silicon-arm64-555)
![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![Local-first](https://img.shields.io/badge/LLM-local%20MLX-orange)
![Languages](https://img.shields.io/badge/languages-6-brightgreen)

<a href="README.md">English</a> · <b>한국어</b> · <a href="README.zh.md">简体中文</a> · <a href="README.ja.md">日本語</a> · <a href="README.fr.md">Français</a> · <a href="README.de.md">Deutsch</a>

</div>

---

## ✨ 무엇을 하나요

텍스트를 선택하고 — 외국어 문장, 빽빽한 문단, 에러 메시지, 코드 한 조각 — `⌘⇧E`를 누르면, Macsist가 커서 옆 작은 패널에 짧은 설명을 스트리밍합니다. 창 전환도, 채팅 앱에 복사·붙여넣기도 필요 없습니다. 작업 중인 창의 포커스를 절대 빼앗지 않습니다.

- **📝 텍스트 설명** — `⌘⇧E`가 손쉬운 사용(Accessibility)으로 선택 영역을 읽습니다(클립보드 안전 합성 ⌘C 폴백 — 클립보드는 항상 복원됩니다).
- **🖼 영역 설명** — `⌘⇧R`은 ⌘⇧4 같은 십자선을 띄우고, 캡처한 이미지를 로컬 **비전** 모델로 보냅니다(다이어그램·표·스크린샷 등 선택할 수 없는 것에 좋습니다).
- **💬 이어서 질문** — 답변 후 패널에 바로 입력하세요. **Enter**로 전송, **Shift+Enter**로 줄바꿈; 입력칸이 길어지면 패널도 따라 커집니다. 같은 대화, 같은 모델 — 비전 세션은 이미지를 맥락에 유지합니다.
- **🌍 6개 언어** — 한국어 · English · 简体中文 · 日本語 · Français · Deutsch, **UI와 답변 모두**. 설정에서 즉시 전환, 재시작 불필요. 다른 언어 입력에는 자연스러운 `번역:` 줄이 먼저 붙습니다.
- **🪟 리퀴드 글래스 패널** — 커서 옆에 페이드인되는 반투명·둥근·자동 크기 패널. 배경을 잡고 **어디로든 드래그**해 옮길 수 있습니다.
- **🗂 기록** — 모든 설명이 로컬에 저장되고 검색됩니다(`⌘⇧H`). 복사하거나, 현재 모델로 **다시 질문**하거나(영역 항목은 저장된 스크린샷을 다시 보냄), 세션을 삭제 — 모두 채팅형 창에서.
- **🔌 원하는 모델로** — **로컬** MLX 서버를 돌리거나, 어떤 **OpenAI 호환 API**(OpenRouter 등)로도 연결. API 키는 macOS **Keychain**에 보관되며 디스크에 저장되지 않습니다.
- **🔒 기본이 프라이빗** — 로컬 우선, 텔레메트리 없음, Electron 없음. 진짜 서명된 `.app` 번들: Dock·Cmd-Tab·권한 목록 모두 아이콘과 함께 **Macsist**로 표시됩니다.

---

## 📸 실제 화면

<div align="center">

**텍스트 설명** — 문단을 선택하고 `⌘⇧E`를 누르면 번역과 간결한 설명이 바로 옆에 스트리밍됩니다.

<img src="assets/HotKeyEx-test.png" width="760" alt="논문에서 선택한 텍스트 설명" />

**영역 설명** — `⌘⇧R`로 그림을 드래그 선택하면 Macsist가 도식 전체를 풀어 설명합니다.

<img src="assets/HotKeyEx-image-2.png" width="760" alt="PDF에서 캡처한 도식 설명" />

</div>

---

## 🖥 요구 사항

- **Apple Silicon** 의 **macOS 26.2+**
- 로컬 모델용: 대략 **16 GB+** 통합 메모리(설치 프로그램이 RAM에 맞는 모델을 추천합니다). 메모리가 적은 기기에서는 외부 OpenAI 호환 API를 사용하면 로컬 모델이 필요 없습니다.

---

## ⬇️ 설치

```bash
git clone https://github.com/junidude/macsist.git
cd macsist
./install.sh
```

대화형 세션 하나로 모든 것이 끝나며, **멱등적**입니다 — 언제든 다시 실행해도 완료된 단계는 건너뜁니다:

1. **하드웨어 점검** → RAM에 맞는 모델 추천(Qwen 3.6 / Gemma 4 멀티모달 등급, 소형 기기는 외부 API)
2. **환경 구성** → 서버용 miniforge/conda 환경
3. **모델 다운로드**(더 빠른 다운로드를 위한 Hugging Face 토큰을 선택적으로 물어봄)
4. **백그라운드 서비스** → 서버와 앱을 launchd 에이전트로 설치(로그인 시 항상 켜짐, 크래시 시 자동 재시작)
5. **`macsist` CLI** → `PATH`에 설치
6. **권한** → macOS **손쉬운 사용**과 **화면 기록** 허용을 안내
7. **스모크 테스트** → 실제 설명 왕복으로 동작 확인

권한 허용 후 앱을 재시작하세요: `macsist restart app`.

<details>
<summary><b>수동 / 개발자 경로</b> (설치 프로그램이 자동화하는 것)</summary>

```bash
server/download_models.sh   # 모델 1회 다운로드
server/deploy.sh            # 서버 LaunchAgent 설치
app/deploy.sh               # 서명된 앱 번들 빌드 + 설치
app/run.sh                  # …또는 개발용으로 앱을 포그라운드 실행
```

`app/deploy.sh`는 py2app로 실제 서명 번들을 빌드합니다 — 프레임워크 Python이
필요합니다: `brew install python@3.13`. 전체 명세와 아키텍처:
[docs/SPEC.md](docs/SPEC.md).
</details>

---

## 🚀 사용법

| 단축키 | 동작 |
| --- | --- |
| `⌘⇧E` | 선택한 텍스트 설명 |
| `⌘⇧R` | 화면 영역을 드래그해 설명 |
| `⌘⇧H` | 기록 / 설정 창 열기 |
| `Enter` | 이어서 질문 전송 |
| `Shift+Enter` | 입력칸에서 줄바꿈 |
| `Esc` | 입력 지우기, 다시 누르면 패널 닫기 |

모든 단축키는 **설정 → 단축키**에서 다시 지정할 수 있습니다. 결과 패널은 앱을 활성화하지 않으므로 현재 창의 포커스는 그대로 유지됩니다.

---

## 🎛 설정

메뉴 막대 아이콘에서 **설정**을 엽니다(또는 `macsist settings`):

- **일반** — UI·답변 **언어**(저장 시 즉시 적용).
- **연결** — 활성 **프로바이더** 선택(로컬 서버 또는 외부 OpenAI 호환 엔드포인트), 주소·모델·API 키 설정. 키는 **Keychain**에 저장. 재시작 없이 전환.
- **응답** — **상세도**: 간단 · 보통 · 자세히(길이와 깊이 조절).
- **단축키** — 새 단축키 녹화(물리 키로 매칭되어 어떤 키보드 레이아웃에서도 동작).
- **모양** — 패널 크기, 글자 크기, 글래스 스타일.
- **고급** — 시스템 프롬프트(텍스트·이미지), temperature, max tokens, 이어서 질문 깊이, 기본값 복원 버튼.

---

## 🧰 `macsist` CLI

`install.sh`가 `PATH`에 심볼릭 링크로 설치 — 어느 디렉터리에서나 동작합니다.

| 명령 | 기능 |
| --- | --- |
| `macsist` | 두 에이전트 실행 확인 후 상태 요약 출력 |
| `macsist start\|stop\|restart [app\|server]` | launchd 에이전트 관리 |
| `macsist status` | 에이전트, 서버 상태, 프로바이더/모델, TCC 상태 |
| `macsist logs [app\|server] [-f]` | 알맞은 로그 파일 tail |
| `macsist settings` / `macsist history` | 메인 창 열기 |
| `macsist doctor` | 전체 ✓/✗ 진단: 배포, 설정, Keychain 키, 상태, TCC, 모델 캐시 |
| `macsist update` | `git pull --ff-only` + 두 에이전트 재배포 |

---

## 🏗 동작 원리

앱은 **얇은 HTTP 클라이언트**입니다. `http://127.0.0.1:8000`의 OpenAI 호환 LLM 서버 — 알맞은 MLX 백엔드로 라우팅하는 작은 FastAPI 프록시 — 와 통신합니다:

```
app ──► :8000  프록시 (FastAPI)
                 ├─ 텍스트 전용 dense 모델   ─► :8002  mlx-lm
                 └─ 멀티모달 (텍스트+이미지) ─► :8001  mlx-vlm
```

프록시는 토큰(SSE)을 그대로 흘려보내므로 앱은 언제나 `:8000`하고만 통신합니다. `model` 필드를 바꾸면 알맞은 백엔드로 투명하게 라우팅됩니다. 서버와 앱은 모두 **launchd 에이전트**로 실행됩니다(로그인 시 항상 켜짐, 크래시 시 자동 재시작). 모델은 하드코딩되지 않고 설정 가능합니다.

로그:

```bash
tail -f ~/Library/Logs/Macsist/app.log        # 메뉴 막대 앱
tail -f ~/Library/Logs/llm-server/proxy.log   # LLM 프록시
```

전체 아키텍처, 마일스톤(M0–M12), 설계 노트: **[docs/SPEC.md](docs/SPEC.md)**.

---

## 🩺 문제 해결

- **`macsist doctor`** — 배포, 설정, Keychain 키, 서버 상태, TCC 권한, 모델 캐시를 한 번에 점검.
- **단축키가 안 먹힘** → **손쉬운 사용** 허용 후 `macsist restart app`.
- **영역 캡처 실패** → **화면 기록** 허용 후 `macsist restart app`.
- **서버 연결 안 됨** → `macsist status` / `macsist logs server -f`. 첫 시작은 모델을 메모리에 올립니다(~60–90초).
- **응답 없이 스트림 종료** → thinking 모델이 토큰 예산을 다 썼을 수 있습니다. **max tokens**를 늘리거나 설정에서 모델을 확인하세요.

---

<div align="center">
<sub>Python 3.13 + PyObjC (AppKit), <code>pynput</code>, <code>httpx</code>로 제작 · FastAPI 프록시 뒤의 MLX(<code>mlx-lm</code> / <code>mlx-vlm</code>) · Apple Silicon, macOS 26.2+</sub>
</div>
