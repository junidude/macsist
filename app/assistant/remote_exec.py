"""RemoteAgentExecutor — delegate a task to an agent on a remote box (M16).

Runs the remote agent (codex / claude) in a DETACHED tmux session so the job
survives SSH drops, laptop sleep, and a Macsist restart. The agent writes its
final answer to result.txt, full log to log.txt, and its exit code to
exit_code — we poll those over SSH (BatchMode, key from ~/.ssh/config; no
ssh-agent needed). Reconnect = just SSH again and re-read the files.

codex exec runs non-interactively with --skip-git-repo-check and
--dangerously-bypass-approvals-and-sandbox (the remote box is the user's and
the dispatch was already user-approved via the confirm gate). Prompt is piped
in via a file (no shell-escaping of user text).

Threading: subprocess + ssh only — safe from a worker thread.
"""

import os
import shlex
import subprocess
import uuid
from datetime import datetime

from assistant.oplog import OpLogStore
from config import CONFIG_DIR

REMOTE_JOBS_PATH = CONFIG_DIR / "remote_jobs.jsonl"
_SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]

# per-agent non-interactive invocation; prompt is fed on stdin (< prompt.txt),
# final message -> result.txt, JSONL/log -> log.txt. {secs} = runtime cap.
_AGENT_CMD = {
    "codex": ("timeout {secs} codex exec --skip-git-repo-check "
              "--dangerously-bypass-approvals-and-sandbox -o result.txt "
              "< prompt.txt > log.txt 2>&1"),
    "claude-code": ("timeout {secs} claude -p --output-format text "
                    "< prompt.txt > result.txt 2>log.txt"),
}


def _now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class RemoteJobStore:
    def __init__(self, config, path=None):
        self.log = OpLogStore(path or REMOTE_JOBS_PATH,
                             max_lines=int(config.get("remote_jobs_max")) * 6)

    @property
    def on_changed(self):
        return self.log.on_changed

    @on_changed.setter
    def on_changed(self, cb):
        self.log.on_changed = cb

    def put(self, job):
        self.log.set(job)

    def update(self, jid, **fields):
        if self.log.get(jid):
            self.log.set({"id": jid, **fields})
        return self.log.get(jid)

    def get(self, jid):
        return self.log.get(jid)

    def all(self):
        rows = self.log.records()
        rows.sort(key=lambda r: r.get("started_ts") or "", reverse=True)
        return rows

    def running(self):
        return [j for j in self.all() if j.get("status") == "running"]


class RemoteAgentExecutor:
    def __init__(self, config):
        self.config = config

    def host(self):
        hosts = self.config.get("remote_hosts") or []
        return hosts[0] if hosts else None

    # -- ssh helpers ---------------------------------------------------------

    def _ssh(self, alias, remote_cmd, timeout=30):
        try:
            r = subprocess.run(["ssh", *_SSH_OPTS, alias, remote_cmd],
                              capture_output=True, text=True, timeout=timeout)
            return r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired:
            return 124, "", "ssh timeout"
        except OSError as exc:
            return 1, "", str(exc)

    def _ssh_input(self, alias, remote_cmd, data, timeout=30):
        try:
            r = subprocess.run(["ssh", *_SSH_OPTS, alias, remote_cmd],
                              input=data, capture_output=True, text=True,
                              timeout=timeout)
            return r.returncode, r.stdout, r.stderr
        except (subprocess.TimeoutExpired, OSError) as exc:
            return 1, "", str(exc)

    # -- lifecycle -----------------------------------------------------------

    def dispatch(self, prompt, alias=None, agent=None):
        """Start a detached remote agent job. Returns a job dict (or with an
        'error' set on failure). Does NOT block on the job — it runs in tmux."""
        host = self.host()
        if host is None:
            return {"error": "remote_hosts가 비어 있습니다"}
        alias = alias or host.get("alias")
        agent = agent or host.get("agent", "codex")
        jid = "rmt_" + uuid.uuid4().hex[:10]
        jobdir = f"~/.macsist-jobs/{jid}"
        session = f"macsist_{jid}"
        secs = int(self.config.get("remote_max_runtime"))
        agent_cmd = _AGENT_CMD.get(agent, _AGENT_CMD["codex"]).format(secs=secs)
        job = {
            "id": jid, "alias": alias, "agent": agent, "jobdir": jobdir,
            "session": session, "status": "running",
            "prompt": prompt[:500], "started_ts": _now(),
            "exit_code": None, "result_ref": None, "error": None,
        }
        # 1) write the prompt to the remote (no shell escaping of user text)
        rc, _o, err = self._ssh_input(
            alias, f"mkdir -p {jobdir} && cat > {jobdir}/prompt.txt", prompt)
        if rc != 0:
            job.update(status="failed", error=f"prompt 전송 실패: {err[:200]}")
            return job
        # 2) launch the agent in a detached tmux session
        inner = f"cd {jobdir} && {agent_cmd}; echo $? > exit_code"
        cmd = f"tmux new-session -d -s {session} {shlex.quote(inner)}"
        rc, _o, err = self._ssh(alias, cmd)
        if rc != 0:
            job.update(status="failed", error=f"tmux 시작 실패: {err[:200]}")
        else:
            print(f"remote: dispatched {jid} -> {alias} ({agent})", flush=True)
        return job

    def poll(self, job):
        """Return {status, exit_code} — running | done | failed | unreachable."""
        alias, jd = job["alias"], job["jobdir"]
        rc, out, _err = self._ssh(
            alias, f"cat {jd}/exit_code 2>/dev/null")
        if rc == 124:
            return {"status": "running"}  # ssh hiccup — keep waiting
        code = out.strip()
        if code == "":
            return {"status": "running"}
        return {"status": "done" if code == "0" else "failed",
                "exit_code": code}

    def result(self, job, limit=8000):
        """The agent's final answer (result.txt), falling back to the log tail."""
        alias, jd = job["alias"], job["jobdir"]
        rc, out, _e = self._ssh(
            alias, f"cat {jd}/result.txt 2>/dev/null | head -c {limit}")
        text = (out or "").strip()
        if text:
            return text
        rc, out, _e = self._ssh(
            alias, f"tail -c {limit} {jd}/log.txt 2>/dev/null")
        return (out or "").strip() or "(원격 출력 없음)"

    def cancel(self, job):
        """tmux kill-session — silent no-op if already gone (screencapture rule)."""
        self._ssh(job["alias"], f"tmux kill-session -t {job['session']} "
                                "2>/dev/null || true")

    def reachable(self, alias=None):
        alias = alias or (self.host() or {}).get("alias")
        if not alias:
            return False
        rc, _o, _e = self._ssh(alias, "echo ok", timeout=12)
        return rc == 0
