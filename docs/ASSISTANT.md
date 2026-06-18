# Macsist Assistant — 기획서 (v2 → "비서" 서브시스템)

> 현재 앱은 M12(서명된 py2app 번들)까지 출시됨. 이 문서는 M13부터 시작하는
> "Assistant(비서)" 서브시스템의 확정 설계다. 전체 스펙·게이트·불변식의 근거는
> `docs/SPEC.md`, 코드 규칙은 `CLAUDE.md` 참조.
>
> **이 문서는 4개 제안 + 교차비평 + 6개 도메인 심층설계의 융합 결정본이다.
> 핵심 논쟁은 모두 "결정"으로 못박았다 — 메뉴를 제시하지 않는다.**

---

## 1. 한 문단 요약

Macsist를 "선택 텍스트 설명기"에서 **능동적 개인 비서**로 확장한다. 핵심 베팅은
**"두뇌는 Macsist 안(M9 LLMClient), 게이트도 Macsist 안(결정론적 kind→risk +
구조적 승인 전제조건), Hermes는 검증된 두 가지만 — kanban.db 상태 저장과
Telegram 전송 — 담당"** 이다. 현장 검증 결과 Hermes 게이트웨이는 **현재 실행 중이
아니며**(cron 안 돎), **추론 API 키가 전부 미설정**(gpt-5.5/Codex OAuth만 로그인),
**himalaya 메일 스킬·Google/TimeTree 스킬도 미설치**다. 따라서 "Hermes가
스케줄링하고 추론하는 두뇌"라는 가정은 오늘 이 기계에서 **죽어 있다**. 그래서
우리는 추론을 Macsist의 작동하는 M9 프로바이더로 돌리고, 실행(메일 전송·SSH
위임·캘린더 쓰기)을 **Macsist 인프로세스 executor**가 수행하며, "되돌릴 수 없는
행동은 절대 자동 실행하지 않는다"는 제품의 존재 이유를 **사용자 제스처로만 쓰여진
승인 레코드가 물리적으로 존재해야 executor가 동작하는 구조적 불변식**으로 강제한다.
kanban.db는 작동하는 영속 보드이므로 작업 상태의 단일 진실원천으로 재사용하되,
**오직 `hermes` CLI를 통해서만 쓰고 read-only로만 읽는다**. Telegram은 게이트웨이
없이도 작동하는 `hermes send -t telegram` 한 줄로 붙인다. 이렇게 하면 "어디까지
했더라?" 고통을 죽이는 핵심 루프가 **인터넷·Hermes 가용성과 무관하게** 3개
마일스톤 안에 실재한다.

---

## 2. 역할 분담 (Macsist ↔ Hermes)

| 영역 | 담당 | 이유 |
|---|---|---|
| 작업 보드 영속 상태(작업/링크/코멘트/이벤트/run) | **Hermes kanban.db** (RO 읽기 + `hermes kanban` CLI 쓰기) | 검증된 풀 라이프사이클(triage→…→done) + idempotency + circuit-breaker가 이미 존재. PyObjC로 재구현은 수천 줄 낭비. |
| 작업 *스레드* + "어디까지 했더라" 요약 | **Macsist** (`threads.jsonl`) | kanban 작업 위에 얹는 비서의 멘탈 모델. kanban엔 없는, 제품의 실제 가치. |
| 스케줄링(주기 깨우기) | **Hermes cron** (`--script --no-agent`) **또는** Macsist 데몬 틱 | cron은 게이트웨이 의존(현재 죽음) → MVP는 Macsist 자체 데몬 틱이 1차, cron은 게이트웨이 살아날 때만 옵션. |
| 프로액티브 추론(무엇을 제안할지) | **Macsist M9 LLMClient** | Hermes는 추론 키가 전부 미설정. Macsist 프로바이더는 작동 중. |
| 신뢰 게이트(confirm-then-execute) | **Macsist** (네이티브 글래스 패널) | Hermes가 못 하는 단 하나. 제품의 존재 이유. 인프로세스라야 오프라인·포커스 안전. |
| 되돌릴 수 없는 실행(메일 전송/SSH 위임/캘린더 쓰기) | **Macsist 인프로세스 executor** | Keychain 토큰 + TCC가 서명 번들에 귀속. Hermes cron 컨텍스트는 이 권한 못 가짐. **`promote`가 곧 실행을 뜻하지 않게** 함. |
| 원격 Claude Code/Codex 실행 | **Macsist SSH executor** | Hermes 디스패처는 **로컬에서만** 워커를 띄움(SSH 안 함). 사용자의 실제 원격 서버 작업은 Macsist가 직접 SSH. |
| Gmail/Calendar 수집·OAuth | **Macsist 커넥터** | Hermes에 해당 스킬 없음(himalaya 미설치, Google/TimeTree 스킬 없음). |
| Telegram 전송(알림/나가있을 때) | **Hermes `hermes send -t telegram`** | 검증: 봇 토큰이면 게이트웨이·LLM 불필요. 유일하게 믿을 수 있는 Hermes seam. |

**핵심 원칙:** Hermes는 "오늘 실제로 작동하는 두 가지(영속 보드 + Telegram 파이프)"만
한다. 두뇌·게이트·실행은 Macsist. 단일 자격증명을 두 프로세스에 쪼개지 않는다.

---

## 3. 아키텍처

### 3.1 프로세스 / 스레드

- **메인 스레드(AppKit):** 모든 패널/메뉴바/알림/스토어 쓰기. `app/main.py`의 기존
  `_controller`/`_explain`/`_health`와 나란히 **새 모듈 레벨 컨트롤러
  `_assistant = AssistantController(...)`** 를 onboarding 후 `.start()`.
- **데몬 스레드(폴러들):** 전부 `app/health.py` `ServerHealthMonitor`를
  **그대로 복제**(`_wake = threading.Event()`, `poke()`,
  `AppHelper.callAfter(on_change, ...)`). AppKit 절대 안 만짐. **pynput 리스너
  새로 시작 금지 — `HotkeyManager.rebind()`만.**
  - `AssistantMonitor` — 프로액티브 틱 + 스레드 staleness (기본 300s)
  - `RemoteJobMonitor` — 원격 SSH 작업 추적 (in-flight 20s, idle 60s)
  - `GmailMonitor` / `CalendarMonitor` — 커넥터 폴 (기본 300s / 900s)
- **단기 워커 스레드:** LLM 추론(`stream_chat`), `subprocess`(hermes/ssh/scp),
  Gmail/ICS fetch. 결과는 항상 `callAfter`로 메인에 마샬링.

### 3.2 컴포넌트 (전부 `app/assistant/` 하위 신규)

```
app/assistant/
  controller.py        # AssistantController — 메인스레드 두뇌줄기(glue)
  monitor.py           # AssistantMonitor (health.py 클론)
  proactive.py         # ProactiveEngine — FIND→DIGEST→REASON→CLASSIFY→EMIT
  risk.py              # kind→risk 결정론 테이블 (제품의 안전법)
  proposal_store.py    # ProposalStore (history_store.py 패턴)
  audit_store.py       # AuditStore (append-only, never auto-prune)
  proposal_panel.py    # ProposalPanel (result_panel.py 비활성 글래스 패널 재사용)
  thread_store.py      # ThreadStore — 작업 스레드 이벤트로그 + fold
  thread_engine.py     # 스레드 staleness/요약 갱신
  hermes_bridge.py     # 유일한 Hermes 접점: CLI + RO kanban.db
  delivery.py          # Deliverer — notify_native / notify_telegram
  remote_exec.py       # RemoteAgentExecutor — SSH dispatch/poll/cancel
  remote_monitor.py    # RemoteJobMonitor (health.py 클론)
  remote_runner.sh     # 원격에 scp되는 tmux 런처
  gmail_client.py / gmail_oauth.py / gmail_triage.py / gmail_monitor.py
  calendar/ics_client.py, gcal_api.py, unify.py, monitor.py
```

### 3.3 통신 — 두 방향

- **Macsist → Hermes:** `hermes_bridge.py`만 알고 있음.
  - 쓰기: `subprocess.run(["hermes","kanban","create|comment|promote|block|complete", ..., "--json"])`,
    `hermes send -t telegram`. 전부 워커 스레드 + timeout, 비0 종료 → `{"error":...}`.
  - 읽기: `sqlite3.connect("file:" + path + "?mode=ro", uri=True)` (WAL 인식),
    `tenant`별 SELECT. **DB 직접 쓰기 절대 금지**(Hermes의 atomic claim/lock 불변식 보존).
- **Hermes → Macsist:** (a) `KanbanMonitor` 폴이 `task_events` rowid 차분으로 상태
  변화 감지 / (b) (옵션, 게이트웨이 살아날 때) Hermes cron `--script --no-agent`가
  `macsist_notify` → `NSDistributedNotificationCenter` → `main.py`의 기존
  `_RemoteCommandRelay`로 긴급 깨우기. **MVP는 (a) 폴만으로 충분 — cron 의존 없음.**

### 3.4 거부된 대안 (근거)

- **bespoke spool 프로토콜**(두 프로세스가 한 디렉터리에 tmp+os.replace+locks/로
  교신) → kanban.db가 이미 atomic claim/lock/lease를 푼다. 멀티라이터 파일 경합을
  새로 만드는 건 "프레임워크 재구현"의 변형. **채택 안 함.**
- **`promote` = 실행** (Hermes 디스패처가 메일 전송/SSH 수행) → 게이트가 남의
  데몬 안에 살고, 디스패처가 죽으면 승인 카드가 `ready`에 영원히 묶임. 게다가
  디스패처는 SSH 안 하므로 원격 위임에 부적합. **되돌릴 수 없는 실행은 Macsist
  인프로세스.**
- **OS 전역 활동 추론**(frontmost 앱/창) → 넓은 TCC 필요, MVP 제외.

---

## 4. 데이터 모델

모든 스토어는 `~/Library/Application Support/Macsist/` (`config.CONFIG_DIR`),
`history_store.py` 패턴: JSONL append + atomic temp+os.replace prune,
**corrupt-line-tolerant, 메인스레드 단일 라이터**. (스풀을 안 쓰므로 멀티라이터
위험 자체가 없음 — 두뇌가 인프로세스.)

### 4.1 작업 스레드 — `threads.jsonl` (이벤트로그, load 시 last-write-wins로 fold)

```json
{
  "schema": "macsist.thread/v1",
  "id": "thr_01HZ...",
  "ts": "2026-06-15T09:12:00+09:00",
  "op": "upsert|touch|tombstone",
  "title": "Review PR #482 (auth refactor)",
  "status": "active|paused|blocked|done",
  "priority": 0,
  "created_ts": "2026-06-14T...",
  "due_ts": "2026-06-16T18:00:00+09:00",
  "snoozed_until": null,
  "where_was_i": "diff 읽음; keychain.py의 토큰 갱신 경로가 리스크. lease 타임아웃 질문 코멘트 남김.",
  "next_action": "claim_expires 처리 재확인 후 승인/변경요청.",
  "links": ["github.com/...pull/482", "/Users/.../auth.py"],
  "tags": ["work","review"],
  "source": "manual|capture|kanban|history",
  "kanban_task_ids": ["tsk_..."],
  "activity": [{"ts":"...","kind":"explain|kanban_event|manual","note":"keychain.py 탐색"}]
}
```
- `load()`는 id별 ts 순으로 op 적용, `tombstone`은 제거. `touch(id, **fields)`는
  변경 필드만 한 줄 append(재작성 없음). 라인 수 > `assistant_thread_log_max`면
  compaction(temp+os.replace).

### 4.2 제안/승인 봉투 — `assistant_proposals.jsonl`

```json
{
  "id": "prop_01HZ...",
  "ts": "2026-06-15T09:12:03+09:00",
  "source": "stale_thread|overdue_todo|gmail|calendar|remote_done|time_of_day|manual",
  "source_ref": "thr_abc | gmail:msg_<id> | tsk_<id>",
  "thread_id": "thr_abc | null",
  "kind": "thread_resume_nudge|todo_add|reply_draft|send_reply|remote_dispatch|calendar_alert|calendar_write|...",
  "risk": "auto|confirm|never_auto",          // ★ Macsist가 kind로 결정. 모델 값 폐기.
  "title": "위원회 답장 초안 검토",
  "rationale": "왜 제안하는지 — 사용자에게 보여줄 한두 줄",
  "payload": {
    "action": "create_draft|run_remote|create_event|none",
    "args": { "draft":"...", "host":"bai-vscode", "agent":"claude-code", "prompt":"...", "event":{} },
    "blob_ref": "assistant_blobs/<id>.txt | null"
  },
  "idempotency_key": "sha1(kind + source_ref)",
  "status": "pending|approved|edited|skipped|snoozed|executed|failed",
  "approval": null,                            // ★ 사용자 제스처에서만 기록 {by,ts,gesture,edited}
  "snoozed_until": null,
  "decided_ts": null,
  "result_ref": "tsk_<id> | gmail_draft_<id> | null",
  "error": null
}
```

### 4.3 감사 로그 — `assistant_audit.jsonl` (append-only, 자동 prune 안 함)

```json
{ "ts":"iso", "proposal_id":"prop_...", "from_status":"pending", "to_status":"approved",
  "by":"user|auto_policy|system",
  "gesture":"panel_approve|cli_approve|edited|auto_policy|skip|snooze|execute|fail",
  "note":"string|null" }
```
**`assert_approved(id)`** ⇔ `to_status ∈ {approved,edited}` AND `by ∈ {user,auto_policy}`
행이 존재. 모든 부작용 executor가 호출, 없으면 `NotApproved` raise. **구조적 안전 단일 병목.**

### 4.4 원격 작업 캐시 — `remote_jobs.jsonl` (재접속 앵커)

```json
{ "task_id":"tsk_...", "alias":"bai-vscode", "jobdir":"~/.macsist-jobs/tsk_...",
  "agent":"claude-code", "last_byte_offset":48213, "last_status":"running",
  "started_ts":"...", "last_poll_ts":"...", "exit_code":null, "result_blob_ref":null, "retries":0 }
```
원격 작업 정본은 kanban.db 카드(`tenant="remote"`); 이 캐시는 kanban이 싸게 못 가지는
바이트 오프셋·재접속 상태만 보관.

### 4.5 커넥터 커서

- `assistant_gmail_state.json` — `{history_id, last_poll_ts, seen_msg_ids_ring(~500)}`
- `calendar_snapshot.json` — 병합·dedup된 upcoming window(파생 상태, 통째 atomic 덮어쓰기)
- `calendar_state.json` — 소스별 ETag/syncToken + `alerted[event_key]` dedup 맵

### 4.6 새 config 키 (DEFAULTS, snake_case) + 각각 Settings 카드

```python
# 마스터/공통
"assistant_enabled": True,                  # 읽기전용 cockpit 마스터(M13 구현):
                                            # 로컬 보드만 미러 → 기본 ON. 진짜
                                            # 옵트인은 assistant_proactive_enabled.
"assistant_tick_interval": 300.0,
"assistant_proactive_enabled": False,       # 신뢰 쌓기 전 OFF
"assistant_proactive_interval": 1800.0,
"assistant_autonomy": "propose_only",       # 결정#8: 영구 옵트인 유지
"assistant_auto_safe_kinds": [],            # 결정#8: 부작용은 전부 패널 확인 (auto 화이트리스트 비움)
"assistant_quiet_hours": [22, 8],
"assistant_away_seconds": 120,
"assistant_digest_max_chars": 6000,
"assistant_proposal_max": 200,
"assistant_model": "",                      # "" => active explain 프로바이더
"hermes_bin": "~/.local/bin/hermes",
"assistant_telegram_enabled": False,
"assistant_telegram_target": "telegram",
"hotkey_open_inbox": "<cmd>+<shift>+i",
"hotkey_capture_task": "<cmd>+<shift>+t",
# 스레드
"assistant_thread_poll_interval": 60.0,
"assistant_thread_stale_hours": 6,
"assistant_nudge_max_per_cycle": 1,
"assistant_nudge_cooldown_hours": 12,
"assistant_thread_log_max": 5000,
"assistant_kanban_db_path": "~/.hermes/kanban.db",
# 원격 위임
"remote_enabled": False,
"remote_poll_interval": 20.0, "remote_poll_interval_idle": 60.0,
"remote_comment_interval": 300.0, "remote_stale_secs": 600, "remote_max_retries": 1,
"remote_hosts": [{"alias":"nhn-container","agent":"codex","default_repo":"~","workspace":"worktree"}],  # 결정#1·2·3
"remote_default_agent": "codex",            # 결정#2: codex 1차
"remote_agent_cmds": {
  "codex":"timeout {secs} codex exec {prompt_file}",
  "claude-code":"timeout {secs} claude -p {prompt_file} --output-format stream-json --verbose"},
"hotkey_delegate_remote": "<cmd>+<shift>+r",
# Gmail
"gmail_enabled": False, "gmail_poll_interval": 300.0,
"gmail_query_filter": "is:unread newer_than:2d -category:promotions -category:social",
"gmail_account": "", "gmail_max_triage_per_poll": 15,
"gmail_one_click_send": False, "gmail_force_local_llm": True,
# Calendar
"calendar_enabled": False, "calendar_sources": [],  # 결정#7: TimeTree→Google 동기화 → Google 비공개 ICS 단일 소스(OAuth 0)
"calendar_poll_interval_sec": 900, "calendar_monitor_tick_sec": 60.0,
"calendar_window_days": 7, "calendar_alert_lead_min": 15,
"calendar_conflict_enabled": True, "calendar_telegram_when_away": True,
"gcal_oauth_enabled": False,
```

### 4.7 Keychain (`app/keychain.py`, SERVICE="com.macsist") — config.json 절대 금지

- `gmail.oauth.refresh` / `gmail.oauth.client` — Gmail OAuth 리프레시 토큰 + 클라이언트
- `gcal.oauth` — Google Calendar 리프레시 토큰
- `remote.<alias>.agent_token` — (옵션) 원격 에이전트 API 키. SSH 개인키는 저장 안 함
  (실행 중인 ssh-agent 사용).
- 액세스 토큰은 절대 영속화 안 함 — fetch마다 인메모리로 발급.

### 4.8 kind → risk 맵 (`risk.py`, 파이썬 하드코딩 — 안전 척추)

```python
RISK = {
  "thread_resume_nudge":"auto", "thread_summary_refresh":"auto",
  "todo_add":"auto", "label_suggestion":"auto", "calendar_alert":"auto",
  "reply_draft":"confirm", "remote_dispatch":"confirm", "calendar_write":"confirm",
  "send_reply":"never_auto", "calendar_delete":"never_auto", "send_money":"never_auto",
}
# 미지의 kind -> "never_auto" (fail safe). 모델이 절대 못 넓힘.
```

---

## 5. 프로액티브 루프 & 신뢰 UX

### 5.1 루프 (FIND → PROPOSE → CLASSIFY → SURFACE → CONFIRM → AUDIT)

1. **FIND** (`ProactiveEngine`, 워커): `SignalSource` 어댑터들이 신호 수집.
   MVP = `StaleThreadSource`(active+idle>임계 + open todo), `OverdueTodoSource`,
   `TimeOfDaySource`(아침 다이제스트/EOD). later = Gmail/Calendar/RemoteDone.
2. **PROPOSE**: redaction-aware 다이제스트 → `llm.stream_chat(messages, handle)`
   (버퍼에 누적, 패널 아님). i18n 시스템 프롬프트가 JSON 배열 강제. 모델은
   `{kind,title,rationale,payload}`만 반환.
3. **CLASSIFY** (결정론, 파이썬): `risk.risk_of(kind)`로 등급 부여, 모델의 risk 필드
   폐기. **이게 macsist-centric에서 훔친 최고의 아이디어 — 환각 "auto"가 절대 부작용
   실행으로 승격 못 함.**
4. **DEDUP**: `idempotency_key`로 동일 제안 재나그 방지.
5. **SURFACE / CONFIRM-THEN-EXECUTE**:
   - `auto` + 화이트리스트 + `autonomy≥auto_safe` → 승인행(`gesture="auto_policy"`)
     쓰고 즉시 실행, "했어요: X (되돌리기?)" 수동 알림. **읽기전용/가역만.**
   - `confirm` / `never_auto` / 비화이트리스트 → SURFACE(배지 + 데스크면 네이티브
     패널 / 나가있으면 Telegram). **아직 아무것도 실행 안 됨.**
   - Approve → 메인스레드에서 `approval` 감사행(`by="user"`) + status=approved →
     워커 executor → **`audit.assert_approved(id)` or raise `NotApproved`** → 결과 →
     status=executed + result_ref + 감사행.
   - Edit → 수정 payload로 재실행(`gesture="edited"`). Skip → 음성 신호로 피드백.
     Snooze → 재표면.
6. **AUDIT**: 모든 전이를 `assistant_audit.jsonl`에 기록.

### 5.2 행동 안전 클래스

| 클래스 | 의미 | 예 | 동작 |
|---|---|---|---|
| `auto` | 가역/내부 | 스레드 요약 갱신, todo 추가, 라벨 제안, 캘린더 알림 | autonomy 켜져 있으면 자동, 아니면 패널 |
| `confirm` | 자원 소비/외부지만 복구가능 | 답장 초안(Gmail DRAFT), 원격 디스패치, 캘린더 이벤트 생성 | 항상 패널 |
| `never_auto` | 되돌릴 수 없음 | **메일 전송**, 캘린더 삭제, 송금 | 어떤 config·모델 출력에도 자동 불가; 명시적 사용자 제스처만 |

**4중 안전:** (a) status=approved, (b) 사용자 제스처 approval 레코드, (c) executor
전제조건 assert, (d) `send_reply` 등이 하드 `never_auto`. 어느 하나라도 빠지면 실행 안 됨.

### 5.3 네이티브 UX

- **메뉴바 배지** — `StatusItemController`(menubar.py)가 기존 `_SERVER_STATES` 아이콘
  로직처럼 pending confirm/never_auto 개수 배지 + "비서" 서브메뉴(받은 작업함, 스레드 목록).
- **ProposalPanel** — `result_panel.py`의 비활성 Liquid Glass `NSGlassEffectView`
  재사용: `canBecomeKeyWindow`는 **Edit 필드 포커스 중일 때만 True**(M6 규칙),
  `setHidesOnDeactivate_(False)`, `orderFrontRegardless()`. 커서 근처(핫키) 또는
  중앙(깨우기). 절대 포커스 안 뺏음. 레이아웃: 제목·소스 pill·risk 색 배지·rationale·
  구체 행동(초안/호스트+cmd/diff/이벤트 변경) · Approve(⏎) Edit(⌘E) Skip(⌫) Snooze(▾).
  ⌘W = pending 유지 닫기.
- **알림** — `NSUserNotification` + 배지(데스크). 긴급은 `macsist_notify` 릴레이로
  앱 idle여도 패널 팝업.
- **Telegram** — `Deliverer.notify_telegram(text)` = `hermes send -t telegram -q`
  (게이트웨이 불필요, 검증됨). 나가있을 때/quiet-hours 베스트에포트. 실패해도 루프
  안 막음 — 네이티브가 이미 떴음.
- **CLI 미러** — `_RemoteCommandRelay`에 `com.macsist.assistant.*` 옵저버 추가:
  `macsist propose|approve <id>|tasks|scan|todo`. (스크린샷 없이 검증 — 프로젝트 메모리
  `verify-ui-without-screenshots` 준수.)

---

## 6. 5대 기능 설계

### 6.1 TODO / "어디까지 했더라"

- **결정:** kanban.db가 *작업*의 단일 진실원천. Macsist는 그 위에 **스레드 레이어**를
  소유 — 스레드는 1+ kanban 작업 + 로컬 노트를 묶고, LLM이 유지하는 `where_was_i` +
  `next_action`을 carry. **kanban 작업을 복제하지 않음**(id 참조만).
- `ThreadStore`(이벤트로그+fold) + `ThreadMonitor`(health 클론, kanban `task_events`
  RO 차분 + staleness 랭킹) + `ThreadEngine`(요약 갱신 via M9 LLM, auto 등급).
- staleness 결정론: active + idle>`stale_hours` + `next_action` 존재 + quiet-hours 밖.
  랭킹: overdue → 오래된 last_touched → priority. cycle당 최대 1개(과잉 나그 방지 =
  전 비평의 #1 신뢰 리스크). cooldown 12h.
- 캡처: 기존 explain 캡처 파이프라인(AX 선택텍스트 → ⌘C fallback, 페이스트보드
  스냅샷/복원) 재사용, `hotkey_capture_task`(rebind). 메뉴바 "+새 스레드", `macsist thread add`.
- **resume 카드**(result_panel 클론): title·where_was_i·next_action·연결 작업 상태 +
  Resume/Edit/Snooze/Done. Resume는 가역(링크 열기/스레드 포커스), 게이트 없음.
- **MVP cut:** ThreadStore + ThreadMonitor + ThreadEngine + 메뉴바 배지/서브메뉴 +
  resume 카드 + 스레드 탭. **Hermes 게이트웨이 의존 ZERO**(요약은 M9). 이것만으로
  컨텍스트-스위치 고통 사망. kanban 없으면 로컬 전용으로 우아하게 degrade.

### 6.2 프로액티브 엔진

- **결정:** 두뇌는 Macsist M9 LLMClient(Hermes 키 없음). 게이트는 결정론 risk 맵 +
  구조적 assert. (§5 그대로.)
- `proactive.py`/`risk.py`/`proposal_store.py`/`audit_store.py`/`proposal_panel.py`/
  `monitor.py`. 모델은 kind만 제안, 앱이 게이트 결정.
- **MVP cut (M14):** `StaleThreadSource`+`OverdueTodoSource`+수동 `todo_add`만.
  로컬 신호 → 제안 → 결정론 게이트 → 비활성 패널 → Approve/Edit/Skip/Snooze →
  `assert_approved` executor → 감사. proactive 기본 OFF(신뢰 먼저), autonomy=propose_only.
- later: 커넥터 신호 추가는 `SignalSource` 한 개씩 — 엔진 코드 불변.

### 6.3 원격 Claude Code / Codex 위임

- **결정적 사실:** Hermes 디스패처는 **로컬에서만** 에이전트를 띄움(SSH 안 함).
  사용자의 실제 원격 서버 작업은 **Macsist 소유 SSH executor**가 수행. "로컬 worktree
  워커 == 원격"이라는 미끼 거부.
- **메커니즘:** **원격 tmux 세션 + 구조적 JSONL transcript + status/exit_code 센티넬 +
  SSH tail 폴링.** (`nohup`+`kill -0` PID 추적, 라이브 SSH 스트림은 둘 다 sleep/재접속에
  취약 → 거부.) 작업이 tmux에 살아 노트북 sleep·Wi-Fi 변화·Macsist 재시작 생존; 재접속은
  "다시 SSH해서 last_byte_offset부터 tail".
- **디스패치 시퀀스:** `remote_job` 카드를 `--initial-status blocked --idempotency-key
  "remote:<alias>:<sha>"`로 생성 → ConfirmPanel이 호스트+에이전트+정확한 프롬프트 표시 →
  Approve가 승인 코멘트 기록 + executor가 책임(Hermes 디스패처 아님) → `remote_exec.dispatch()`:
  `mkdir jobdir` → `scp remote_runner.sh`(content-hash 멱등) → 프롬프트 파일 →
  `ssh "tmux new-session -d -s macsist_<id> '$JOBDIR/run.sh <agent> <repo>'"` →
  `run.sh`가 `timeout`으로 에이전트 감싸 실행, transcript+exit_code 기록.
- **추적:** 폴마다 `status`+byte-size → 새 바이트만 tail → 요약을 스로틀(5분)로 kanban
  코멘트(최신 코멘트 = "어디까지 했더라"). 완료(exit 0) → `review`(사용자 확인 후 complete);
  비0 → `block` + retry 카운트.
- **2중 회로차단:** 원격 `timeout`(하드 킬) + 모니터의 `remote_stale_secs` 무성장 감지.
  취소: `tmux kill-session`(없으면 silent no-op, screencapture-cancel 규율).
- **인증:** 기존 `~/.ssh/config` + ssh-agent. `-o BatchMode=yes -o ConnectTimeout=5`.
  옵션 `remote.<alias>.agent_token`만 Keychain.
- **risk:** `remote_dispatch`→`confirm` 하드. executor가 SSH 열기 전 승인 assert.
- **MVP cut (M16):** **nhn-container 단일 호스트**, **codex 1차**(claude-code 포함),
  **디스패치마다 git worktree**(run.sh가 `git worktree add`/완료 시 정리 — 동시 위임 충돌 0),
  confirm-게이트, tmux+폴, 완료→review+Telegram(home 채널). later: 라이브 tail 오버레이,
  멀티호스트, ControlMaster, AWS-SSM ProxyCommand 경유 호스트.

### 6.4 Gmail 모니터링 (→ Hermes → Telegram)

- **결정적 사실:** Hermes 추론 키 없음, himalaya 미설치, Gmail-API 툴 없음. → **수집·트리아지·
  초안 전부 Macsist**(Gmail API + Keychain OAuth + M9 LLM). Hermes는 Telegram 전송만.
- `gmail_oauth.py`(루프백 PKCE, Settings "Gmail 연결" 버튼, 리프레시 토큰 Keychain) +
  `gmail_client.py`(`history.list` 증분, 404→`messages.list` resync) + `gmail_monitor.py`
  (health 클론, 기본 OFF) + `gmail_triage.py`(헤더+snippet 다이제스트, 답장 필요한 1~2건만
  full body fetch — 프라이버시+토큰).
- **dedup:** threadId 키 제안 + seen_msg_ids_ring + historyId 커서 + send idempotency_key.
- **risk:** `summarize/label/todo_add`→auto, `reply_draft`→confirm, **`send_reply`→never_auto(하드)**.
- **2단계 전송:** Approve `reply_draft` → 실제 Gmail DRAFT 생성(가역) → *두 번째* 명시
  "지금 보내기" 제스처만 `send_draft` 호출. **어떤 경로도 자동 전송 안 함.**
  `gmail_one_click_send`(파워유저)도 전송은 여전히 사용자 제스처.
- **프라이버시:** `gmail_force_local_llm` 기본 ON — active_provider가 외부여도 트리아지는
  로컬 MLX 강제(설정 가능).
- **결정#4·5:** **Macsist 동봉 desktop client_id**(loopback PKCE, "연결" 버튼만),
  scope = `gmail.compose` + `gmail.send`(2단계 전송). Telegram은 home 채널.
- **MVP cut (M17):** OAuth+읽기+트리아지+공유 ProposalPanel 표면+Telegram 다이제스트(home)+
  Approve시 DRAFT 생성. 검수: 실제 메일 → 한 폴 안에 Telegram 한 줄 + 합리적 편집가능
  초안 카드; Edit&Approve가 DRAFT 생성; 두 번째 명시 제스처가 전송; 자동 전송 경로 없음.
  later: 원클릭 전송, Telegram 회신("APPROVE <id>") — 게이트웨이 살아야 함, 멀티계정.

### 6.5 TimeTree + Google Calendar

- **결정적 사실:** Hermes에 캘린더 스킬 없음 → **Macsist 커넥터**. TimeTree 개발자 API는
  사실상 폐기 → **ICS 우선**(공식 per-calendar export URL). Google도 MVP는 **ICS 읽기**
  (read 경로 OAuth ZERO). Google OAuth는 풍부 필드/빠른 sync/쓰기용 later.
- `ics_client.py`(httpx + If-None-Match/304 + 작은 RFC-5545 파서, 새 의존성 없음) +
  `unify.py`(normalize/merge_dedup/conflict/window 순수함수) + `calendar/monitor.py`
  (health 클론). 스냅샷은 통째 atomic 덮어쓰기(파생 상태).
- **알림은 결정론 앱사이드**(LLM에 "급한가" 안 물음): imminent(lead_min 내) /
  conflict(소스 교차 겹침, dedup 후) → `calendar_alert`(risk=auto) → 네이티브 알림 +
  배지 + (나가있으면) Telegram. once-per-event dedup(`alerted[event_key]`).
- **"준비해드릴까요?"** = 프로액티브 엔진 핸드오프: 모니터는 컨텍스트 팩트
  (`calendar_imminent`)만 다이제스트에 넣고, 엔진이 `prep_draft`/`remote_job`(risk=confirm)
  제안 생성. *알림은 auto, 행동은 confirm.*
- **쓰기 경로(later):** `calendar_write`→confirm, Macsist gcal executor(Keychain `gcal.oauth`),
  승인 assert. TimeTree는 쓰기 API 없음 → 읽기 전용 영구.
- **MVP cut (M18) — 결정#7로 축소:** **Google Calendar 비공개 ICS 단일 소스**
  (TimeTree는 Google과 이미 동기화 → 별도 연동 불필요) + 결정론 imminent/conflict 알림 +
  Telegram-when-away(home). **OAuth 0.** later: 멀티 ICS 소스, Google OAuth API(빠른 sync·
  풍부 필드), 캘린더 쓰기(confirm), 자동 prep, TimeTree 동기화 깨질 시 직접 ICS 폴백.

---

## 7. 마일스톤 로드맵

가치/노력 순. 초기 마일스톤일수록 기존 기계(HistoryStore, health 스레드, M9 LLM,
result_panel) 최대 재사용. **모든 마일스톤은 Hermes 게이트웨이 가용성에 의존하지 않음**
(Telegram은 게이트웨이-옵셔널, 두뇌는 Macsist).

### M13 — 읽기전용 cockpit + 브리지 강화 (3~4일) — ✅ 출시 (2026-06-15)
- **목표:** Hermes seam을 실제 `--json` 출력에 대해 굳히기, 쓰기 0.
- **출시:** `hermes_bridge.py`(RO kanban.db WAL 읽기 + `hermes kanban list --json` 드라이버),
  `AssistantMonitor`(health 클론) + 메뉴바 배지, main_window.py "작업" 탭(kanban 카드 렌더),
  `macsist doctor` 확장(**게이트웨이/cron 미실행 + Hermes 추론 키 미설정 플래그** — 전 필드의
  맹점), `_assistant` 컨트롤러 와이어링.
- **검수:** 터미널에서 `hermes kanban create` → 한 폴 안에 Macsist 작업 탭에 등장.
- **MVP=전체.**

### M14 — confirm-then-execute 루프 (로컬 두뇌) (~1.5주, 핵심 산출물) — ✅ 출시 (2026-06-15)
- **목표:** "어디까지 했더라" 사망 + propose-first 실증, inert 인프라 베팅 없이.
- **출시:** `ThreadStore`/`SeenStore`, `proposal_store.py`/`audit_store.py`/`risk.py`,
  `proactive.py`(StaleThread+OverdueTodo+수동 todo_add), `proposal_panel.py`(result_panel 재사용,
  Edit 포커스 게이트), `assistant_controller.py`, `monitor.py`, 메뉴바 배지/"비서" 서브메뉴,
  Settings "비서" 카드(트러스트 다이얼, propose_only 기본), `macsist propose|approve|tasks|scan`,
  resume 카드, 4개 i18n 프롬프트 키 × 6언어, `hotkey_capture_task`/`hotkey_open_inbox`(rebind).
- **검수:** (1) `macsist propose "..."` → 패널/inbox에 pending; (2) idle>stale_hours +
  open todo 스레드 → 다음 패스에 `thread_resume_nudge`; (3) Approve는 approval 감사행이
  있어서만 executor 실행 — reject/skip은 부작용 0; (4) pending 제안 보유 채로 재시작 생존;
  (5) `never_auto` kind는 autonomy 무관 절대 자동 실행 불가.
- **MVP=전체.** later: 라벨/요약 auto 경로.

### M15 — Telegram 전송 + 스레드 깨우기 (3~4일)
- **목표:** 첫 Hermes 접점(검증됨), 폰으로 nudge.
- **출시:** `delivery.py`(`hermes send -t telegram`), away-detection(CGEventSource idle),
  quiet-hours 라우팅, 스레드 staleness nudge → Telegram. (옵션) Hermes cron `--script
  --no-agent` 깨우기 — **`macsist doctor` 게이트웨이-liveness 게이트 + 원클릭 `hermes gateway
  install` 제안 뒤에서만.**
- **검수:** 나가있는 상태 시뮬 → 제안이 Telegram으로; quiet-hours엔 억제 후 복귀 시 표면.
- **MVP=Telegram 전송.** later: proactive 기본 ON 전환, auto_safe 경로.

### M16 — 원격 Claude Code 위임 (~1주)
- **목표:** 사용자의 실제 원격 서버에서 에이전트 실행 + 추적.
- **출시:** `remote_exec.py`(tmux+JSONL+센티넬), `remote_monitor.py`(health 클론, offset 재접속),
  `remote_runner.sh`, confirm-게이트 디스패치 + executor 승인 assert, 진행 코멘트(스로틀),
  완료→review+Telegram, `remote_jobs.jsonl`+blob, `macsist doctor` 호스트 도달성(`command -v
  claude tmux`), Settings "원격 위임" 카드, `hotkey_delegate_remote`, i18n.
- **검수:** 위임 승인 → 설정 호스트에서 `claude` 실행 → transcript 작업 탭에 tail → 완료 Telegram.
- **MVP=호스트1+claude-code.** later: Codex, 라이브 tail, 멀티호스트, AWS-SSM ProxyCommand.

### M17 — Gmail (~1주, Keychain 게이트) — ✅ 출시 (2026-06-17)
- **목표:** 처리 필요한 메일이 준비된 초안 + 폰 nudge로 표면.
- **출시:** §6.4 MVP cut — `gmail_oauth.py`/`gmail_client.py`/`gmail_triage.py`/`gmail_monitor.py`,
  proactive `reply_draft`/`send_reply` executor(컨트롤러 워커 디스패치, 메인 비차단), ProposalPanel
  "지금 보내기" 2단계 제스처, Settings "Gmail" 카드 + OAuth 연결 버튼, `macsist gmail`/doctor, i18n×6.
- **검수:** 임포트/구성·트리아지 enrich·MIME 헤더·GmailState 라운드트립·GUI 빌드(Settings 카드
  렌더, 크래시 0)·CLI 모두 통과. **실제 받은편지함 E2E는 GCP 클라이언트 JSON 주입 후** (현재 빈 파일
  → doctor 경고). later: 원클릭 전송, Telegram 회신, 멀티계정.

### M18 — Calendar (ICS) (~1주) — ✅ 출시 (2026-06-18)
- **목표:** TimeTree+Google 통합 + "N분 후 일정" 깨우기.
- **출시:** §6.5 MVP cut. **OAuth ZERO.** `calendar_ics.py`(httpx + ETag/304 + 무의존성
  RFC-5545 파서 + zoneinfo + 윈도우 내 반복 전개), `calendar_unify.py`(normalize/merge_dedup/
  imminent/conflict_pairs/event_key 순수함수), `calendar_monitor.py`(monitor 클론, 빠른 틱 +
  ETag 재fetch, snapshot atomic, `alerted{key}` once-per-event dedup). 알림은 **결정론 앱사이드**
  (LLM 0) → `calendar_alert`(risk=auto) 제안으로 표면(글래스 패널 "확인" + 배지 + away면 Telegram).
  ICS 비밀 URL은 Keychain(`calendar.ics.primary`), Settings "Calendar" 카드에 붙여넣기.
  `macsist calendar status|sync` + doctor.
- **검수:** 파서/unify 단위테스트(timed/all-day/주간·일간 반복/충돌/imminent/dedup) 통과,
  calendar_alert propose→확인→executed(noop, 감사), GUI 빌드(Settings 카드 + 알림 카드 렌더,
  크래시 0), CLI/doctor 통과. **실제 캘린더 E2E는 비공개 iCal URL 주입 후.**
- later: Google OAuth API 경로 + 캘린더 쓰기(confirm), 자동 prep 제안.

### later / optional (M18+)
- Hermes에 추론 키 provisioning 후 무거운 추론을 `hermes chat -q`로 라우팅(옵션).
- `hermes mcp serve`로 Claude Code가 Hermes 세션 직접 구동.
- OS 전역 활동 추론(넓은 TCC, 명시 옵트인), task_links 의존성 그래프 UI.

---

## 8. 불변식 준수 체크

- **스레딩/AppKit 메인:** 모든 폴러는 `health.py` 데몬 패턴 복제, AppKit 절대 안 만짐,
  결과는 `AppHelper.callAfter`로 메인 마샬링. 스토어 쓰기·패널·알림은 전부 메인스레드. ✅
- **pynput:** 새 리스너 시작 금지 — 비서 핫키(open_inbox/capture_task/delegate_remote)는
  전부 `HotkeyManager.rebind()` 단일 경로(`_explain.reloadHotkeys()` 통합). ✅
- **TCC:** Gmail/Calendar/SSH executor가 서명 번들에 귀속된 권한을 사용하므로 Macsist
  인프로세스에 둠(Hermes cron 컨텍스트는 못 가짐). ✅
- **번들:** 새 파일은 전부 `app/assistant/` 안 — `CFBundleIdentifier` 불변, ad-hoc 서명
  안 함, 에셋은 `config.asset_dir()`(RESOURCEPATH), 자기-재실행 `EXECUTABLEPATH`, ditto 복사. ✅
- **Keychain:** 모든 OAuth/원격 토큰은 Keychain(`com.macsist`), config.json엔 절대 없음.
  액세스 토큰 비영속. SSH 개인키 미저장(ssh-agent 사용). ✅
- **포커스 안 뺏기:** ProposalPanel/resume 카드는 result_panel의 비활성 글래스 머신을
  재사용 — `canBecomeKeyWindow`는 Edit 필드 포커스 중에만 True, `setHidesOnDeactivate_(False)`,
  `orderFrontRegardless()`. 앱은 절대 활성화 안 됨. ✅
- **안전 프로액티비티:** kind→risk는 모델이 아닌 Macsist 파이썬 결정. `never_auto`는
  어떤 config·모델 출력에도 자동 실행 불가. 모든 부작용 executor가 `assert_approved` 또는
  raise(구조적 단일 병목). 제안 채널은 단일 라이터(Macsist 메인) — HistoryStore의
  단일-라이터 가정 위반 없음(스풀 거부). 과잉 nudge 하드캡(cycle당 1 + cooldown + quiet-hours). ✅
- **취소/스테일니스:** 새 틱이 in-flight 추론을 `StreamHandle.cancel()`로 선점,
  staleness 체크는 메인스레드. 원격 취소는 `tmux kill-session`(없으면 silent no-op). ✅
- **단일 진실원천:** kanban.db는 RO 읽기 + `hermes kanban` CLI 쓰기만. DB 직접 쓰기 금지. ✅

---

## 9. 결정 완료 (2026-06-15)

§1~8의 모든 열린 결정이 확정됨. 아래 표가 정본이며 §4·§6의 해당 키/MVP에 반영됨.

| # | 결정사항 | 확정 | 코드 영향 |
|---|---|---|---|
| 1 | 원격 1차 호스트 | **nhn-container** (yuhs_elee@59.150.35.1) | `remote_hosts` 단일 엔트리, M16 단일 타깃 |
| 2 | 원격 에이전트 | **codex 1차** + claude-code 포함 | `remote_default_agent="codex"`, `remote_agent_cmds` 양쪽 |
| 3 | 워크스페이스 | **디스패치마다 git worktree** | `workspace:"worktree"`; `remote_runner.sh`가 worktree add/정리 |
| 4 | Gmail 범위 | **2단계 전송** (DRAFT→명시 전송 제스처) | scope `gmail.compose`+`gmail.send`; `gmail_one_click_send=False` |
| 5 | Gmail 인증 | **Macsist 동봉 desktop client_id** | loopback PKCE, "연결" 버튼; 리프레시 토큰 Keychain |
| 6 | Telegram 타깃 | **home 채널** | `assistant_telegram_target="telegram"`, `hermes send -t telegram` |
| 7 | TimeTree | **Google과 이미 동기화** → Google 단일 소스 | M18이 Google 비공개 ICS 1개로 축소, **OAuth 0** |
| 8 | 신뢰 다이얼 | **영구 옵트인** (부작용 전부 패널) | `assistant_autonomy="propose_only"`, `assistant_auto_safe_kinds=[]` |
| privacy | Gmail 트리아지 | **로컬 MLX 강제** (기본 ON) | `gmail_force_local_llm=True` |

### M16 착수 전 사전점검 (결정이 아니라 검증 작업 — `macsist doctor`로 자동화)

1. **헤드리스 인증:** `ssh nhn-container 'codex exec --help'`가 비대화형 tmux 셸에서
   토큰/로그인 상태로 동작하는지. 안 되면 원격에서 codex 인증을 1회 완료하거나
   `remote.nhn-container.agent_token`을 Keychain에.
2. **원격 OS/툴:** `ssh nhn-container 'uname; command -v codex claude tmux git timeout'`
   — Linux면 `timeout`, macOS면 `gtimeout`. codex/git/tmux 존재 확인.
3. **launchd SSH:** 현재 ssh-agent에 로딩된 키 0개. 서명 번들이 launchd에서 SSH하려면
   `~/.ssh/config`에 IdentityFile 명시 또는 로그인 ssh-agent 상속 경로 확보 필요.

이 셋은 M16 첫 커밋에서 `macsist doctor`의 원격 도달성 체크로 편입한다.

---

## 부록 A — M13~M15 as-built & 설계 진화 (2026-06-16)

구현하며 사용자 피드백으로 §2~§7의 일부 결정이 바뀌었다. 아래가 **실제 출시된 동작**이며,
충돌 시 이 부록이 우선한다.

### A.1 에이전트 백엔드 = 선택형, 로컬 우선 (§2·§6.1 갱신)
"Hermes = 상태 저장의 단일 진실원천" 가정을 완화했다. `assistant_backend`(`auto`|`local`|
`hermes`, 기본 `auto`)로 백엔드를 고른다. **로컬이 1급 시민** — 외부 에이전트 없이도 할 일·
제안·답변이 100% 동작한다. 백엔드가 `local`(또는 Hermes 부재)이면 비서 탭의 "칸반 작업"
섹션을 숨기고 상태 줄을 "로컬 전용"으로 표시한다. `hermes_bridge.backend()/is_active()`.
Settings 비서 카드에 백엔드 선택기. OpenClaw/Pi는 확장점만(미배선).

### A.2 답변 라우팅 — Hermes가 "어려운 작업"을 추론한다 (§2 전제 변경)
원안의 "**Hermes는 추론을 절대 안 한다**"는 폐기됐다. 비서 탭 입력 + **답변** 버튼은
요청을 라우팅한다(`assistant_route_mode` = `auto`|`local`|`hermes`, 기본 `auto`):
- 쉬움(짧고 비-agentic) → **로컬 M9 LLM** (explain 글래스 패널에 스트리밍, follow-up 재사용)
- 어려움(>200자 또는 조사/검색/분석/코드/배포/research… 키워드) → **Hermes 에이전트**
  (`hermes_bridge.run_agent` = `hermes chat -q`, 게이트웨이 불필요, codex 두뇌). 결과 패널에
  "⚕ Hermes" 표기. Hermes CLI 부재 시 항상 로컬 폴백.
- 부작용 있는 행동(메일 전송·원격 위임 등)은 여전히 제안→확인(§5). 답변은 부작용 없는
  텍스트 생성이라 즉시 실행.
- explain_controller.`_routeFor`/`answer_question`/`_runAnswerHermes`. Settings에 "답변 라우팅" 선택기.

### A.3 비서 탭 = 인터랙티브 (M14 UI 확정)
입력창 + 버튼 4개(**답변 / 제안 / 할 일 추가 / 스캔**) + **받은 작업함**(대기 제안 카드, 승인/
건너뛰기 인라인) + **할 일**(작업 스레드, "작업 스레드"→"할 일"로 개명) + **칸반 작업**(연결 시).
맨 위 Hermes 연결 상태 줄 + 흐름 안내 한 줄. `i18n.t()`는 키 누락 시 키 문자열로 폴백(크래시 방지).

### A.4 창 외형 = explain 패널과 분리 (가독성)
메인/Settings 창은 `window_glass_enabled`/`window_glass_style`/`window_tint_alpha`(기본 0.9 ≈
불투명, 가독성)로 패널(`glass_*`)과 독립. Settings "창 모양" 섹션. 저장은 스크롤 보존 +
초록 "저장됨 ✓"(2.5s 자동 소멸); 창 외형은 창 재오픈 시 적용(windowWillClose가 window=None).

### A.5 M15 Telegram 전송 (출시, 단 이 망에서 미검증)
자리 비움/조용 시간이면 제안을 `hermes send -t telegram`으로 전송(게이트웨이 불필요,
best-effort 워커). `assistant_telegram_enabled`(기본 OFF)/`assistant_telegram_target`/
`assistant_away_seconds`. `assistant/delivery.py`. **주의:** 이 머신에선 Telegram **봇 API가
네트워크 차단**(루트 302, `/bot…/sendMessage` 15s 타임아웃 http=000)이라 실제 전송 미검증 —
파이프는 올바르며 도달 가능한 망에서 `macsist tg "..."`로 검증할 것.

### A.6 출시 마일스톤 상태
- **M13·M14·M15·M16 출시 (2026-06-16). M17 Gmail 출시 (2026-06-17). M18 Calendar 출시 (2026-06-18).**
- **M16 원격 위임**: `remote_exec.py`로 nhn-container에 `codex exec`를 detached tmux로
  디스패치(prompt stdin, `-o result.txt`, exit_code 센티넬), `RemoteJobMonitor`가 폴링,
  완료 시 결과를 할 일 스레드로 + away면 Telegram. SSH는 `~/.ssh/config` IdentityFile(ssh-agent
  불필요). 검증: dispatch→poll→result "REMOTE_OK"(exit 0). risk=confirm 게이트 경유.
  MVP=호스트1/codex/scratch+`--skip-git-repo-check`; later=디스패치별 git worktree(default_repo),
  라이브 tail, 멀티호스트, claude-code. (A.2의 "Hermes 답변 위임"은 codex@ChatGPT-백엔드로
  로컬 실행 — 원격 파일 접근 없음; M16은 nhn-container의 실제 파일/repo에서 실행 — 별개 경로.)
- **M17 Gmail**: 수집·트리아지·초안 전부 인프로세스(`gmail_oauth.py` 루프백-PKCE → Keychain
  `gmail.oauth.refresh`/`.client`, `gmail_client.py` httpx REST: `history.list` 증분 + 404→
  `messages.list` resync + `drafts.create`/`drafts.send`, `gmail_triage.py` 헤더+snippet 다이제스트
  → LLM이 답장 필요한 1~2건 골라 초안, `gmail_monitor.py` health 클론(기본 OFF) +
  `assistant_gmail_state.json` 커서). **2단계 전송**: reply_draft 승인(confirm)→실제 DRAFT 생성
  →send_reply 카드(never_auto) "지금 보내기" 제스처만 `drafts.send`. 초안/전송 네트워크는 컨트롤러
  워커 스레드(메인 비차단). 트리아지는 active provider(결정: `gmail_force_local_llm=False` 기본).
  Settings "Gmail" 카드(연결 버튼/상태/주기/필터), `macsist gmail status|connect|sync`, doctor
  Gmail 점검. **GCP Desktop OAuth 클라이언트 JSON은 사용자 제공**(`tokens_and_keys/gcp-gmail-api.key`,
  git-ignored); 비어 있으면 doctor가 경고 — 실제 받은편지함 E2E 검증은 키 주입 후. later: 원클릭
  전송, Telegram 회신, 멀티계정.
- **M18 Calendar**: 읽기전용 ICS 커넥터. `calendar_ics.py`(httpx ETag/304 + 무의존성 RFC-5545
  파서 + zoneinfo + 윈도우 내 DAILY/WEEKLY/MONTHLY 반복 전개), `calendar_unify.py`(순수함수:
  merge_dedup/imminent/conflict_pairs/event_key), `calendar_monitor.py`(monitor 클론, 빠른 틱 +
  ETag 재fetch + snapshot atomic + `alerted{key}` once-per-event). 알림은 **LLM 0 결정론** →
  `calendar_alert`(auto) 제안으로 기존 패널/배지/Telegram 파이프라인 재사용("확인" 단일 제스처).
  비밀 iCal URL은 Keychain(`config.CALENDAR_ICS_ACCOUNT`), Settings "Calendar" 카드 붙여넣기.
  결정#7대로 Google 비공개 ICS 단일 소스(TimeTree는 Google 동기화). later: 멀티소스, Google OAuth
  API, 캘린더 쓰기(confirm)+자동 prep, 진짜 Notification Center 전송.
- **M13–M18 전 마일스톤 출시 완료.** Telegram 봇 API 도달성은 환경 의존(차단 시 네이티브만).
