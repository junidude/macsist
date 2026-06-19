"""Headless geometry audit for the 비서 (assistant) tab.

Neither the model nor a subagent can see rendered pixels, so this builds the
real AppKit view tree offscreen at several window widths, then measures every
subview and flags layout defects that ARE detectable from geometry:

  - off-canvas / overflow (a subview sticking out of its parent)
  - text clipping (a label/button whose needed width > its frame width)
  - button overlap
  - the content column not centered, or stretched too wide on big windows
  - cards overrunning the column

Run:  .venv/bin/python _uiaudit.py [width ...]
Exit code is non-zero if any ERROR-level defect is found (WARN is advisory).
"""

import sys

from AppKit import NSMakeRect, NSButton, NSTextField, NSView

import config as cfgmod
import main_window as mw

_THREADS = [
    {"id": "t1", "title": "내일 오후 2시 회의 일정 확인", "status": "active",
     "where_was_i": "회의 일정을 확인하다가 중단", "next_action": "상세 일정·자료 확인",
     "last_touched_ts": "2026-06-18T10:00:00+09:00",
     "activity": [{"ts": "2026-06-18T16:00:00+09:00", "kind": "resumed",
                   "note": "비서가 1~3문단 맞춤법을 다듬었습니다. 다음은 4문단입니다."}]},
    {"id": "t2", "title": "s41586-025-09529-3.pdf", "status": "active",
     "where_was_i": "PDF 작업 진행 중", "next_action": "내용 확인",
     "last_result": "초록과 1~2장을 요약했습니다. 다음은 방법 섹션입니다.",
     "last_touched_ts": "2026-06-17T16:00:00+09:00", "activity": []},
    {"id": "t3", "title": "춤을춰", "status": "done", "where_was_i": "춤을춰",
     "next_action": "", "last_touched_ts": "2026-06-18T09:00:00+09:00",
     "activity": []},
]
_PROPS = [
    {"id": "p1", "kind": "todo_add", "risk": "auto", "title": "보고서 마감",
     "rationale": "내일까지 분기 보고서를 제출해야 합니다"},
    {"id": "p2", "kind": "remote_dispatch", "risk": "confirm", "title": "원격 빌드 실행",
     "rationale": "nhn-container에서 테스트 스위트를 돌립니다"},
    {"id": "p3", "kind": "send_reply", "risk": "never_auto", "title": "고객 메일 답장 발송",
     "rationale": "문의에 대한 답장 초안이 준비되었습니다"},
]


class _Threads:
    @staticmethod
    def idle_hours(t):
        return 6.7

    def for_display(self):
        return _THREADS

    def get(self, tid):
        return next((t for t in _THREADS if t["id"] == tid), None)


class _Props:
    def pending(self):
        return _PROPS


class _Bridge:
    def board_tasks(self):
        return [{"title": "칸반 작업1", "status": "doing", "body": "본문",
                 "created_at": "1718668800"}]

    def status(self):
        return {"connected": True, "gateway": "running", "board_count": 1}


def _abs_frame(view, root):
    """View frame in the coordinate space of `root` (sum of origins up chain)."""
    x, y = 0.0, 0.0
    v = view
    while v is not None and v is not root:
        f = v.frame()
        x += f.origin.x
        y += f.origin.y
        v = v.superview()
    f = view.frame()
    return x, y, f.size.width, f.size.height


def _needed_width(view):
    """Intrinsic width the view wants, to detect clipping. None if N/A."""
    try:
        if isinstance(view, NSButton):
            return float(view.cell().cellSize().width)
        if isinstance(view, NSTextField):
            return float(view.cell().cellSizeForBounds_(
                NSMakeRect(0, 0, 1e6, 1e6)).width)
    except Exception:
        return None
    return None


def _walk(view, root, out):
    for sub in view.subviews():
        out.append(sub)
        _walk(sub, root, out)


def audit(width):
    cfg = cfgmod.ConfigStore()

    class _Hist:
        def load(self):
            return []

    mwc = mw.MainWindowController.alloc().initWithConfig_history_(cfg, _Hist())
    container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, 760))
    mwc._buildAssistantTab_(container)
    mwc.assistant_threads = _Threads()
    mwc.assistant_proposals = _Props()
    mwc.assistant_bridge = _Bridge()
    mwc._busy_thread = "t1"  # exercise the "작업 중" state path
    import time as _t
    mwc._busy_ts = _t.monotonic()
    mwc.refreshAssistant()

    errors, warns, notes = [], [], []

    # routing echo must not bleed over the status line (opaque + pinned top)
    mwc.assistantShowRouting_("내일 회의 자료 정리해줘")
    rb = mwc._routing_box
    if rb is not None:
        rx, ry, rw, rh = _abs_frame(rb, mwc.assistant_doc)
        if ry > 8:
            warns.append(f"routing echo not pinned to top: y={ry:.0f}")
    mwc.assistantClearRouting()

    # 1) input field + 전송 button must be inside the container, not off the right
    bar_items = [v for v in container.subviews()
                 if isinstance(v, (NSButton,))]
    for v in container.subviews():
        x, y, w, h = _abs_frame(v, container)
        if x + w > width + 0.5:
            errors.append(f"toolbar item off right edge: x+w={x + w:.0f} > {width}")
        if x < -0.5:
            errors.append(f"toolbar item off left edge: x={x:.0f}")

    # 2) walk the scroll doc cards
    doc = mwc.assistant_doc
    col_w = mwc.assistant_scroll.contentSize().width
    # vertical fit: the doc must be tall enough for all content (no clipped last
    # card) and not wildly over-tall (big empty gap). Measure deepest child.
    deepest = 0.0
    _dv = []
    _walk(doc, doc, _dv)
    for v in _dv:
        _, vy, _, vh = _abs_frame(v, doc)
        deepest = max(deepest, vy + vh)
    doc_h = doc.frame().size.height
    if doc_h < deepest - 0.5:
        errors.append(f"doc too short: height={doc_h:.0f} < content={deepest:.0f} "
                      f"(last card clipped)")
    elif doc_h > deepest + 40:
        warns.append(f"doc over-tall: height={doc_h:.0f} vs content={deepest:.0f} "
                     f"(empty gap at bottom)")
    sx, sy, sw, sh = _abs_frame(mwc.assistant_scroll, container)
    notes.append(f"window={width} column(scroll)_w={col_w:.0f} "
                 f"scroll_x={sx:.0f} left_margin={sx:.0f} "
                 f"right_margin={width - (sx + sw):.0f}")

    # column should be readable (not full-width) and centered on wide windows
    if width >= 1200:
        if col_w > 980:
            warns.append(f"column too wide on {width}px window: {col_w:.0f}px "
                         f"(cards will look stretched)")
        if abs(sx - (width - (sx + sw))) > 24:
            warns.append(f"column not centered: left={sx:.0f} "
                         f"right={width - (sx + sw):.0f}")

    allviews = []
    _walk(doc, doc, allviews)
    cards = [v for v in doc.subviews()]
    for card in cards:
        cx, cy, cw, ch = _abs_frame(card, doc)
        if cw > col_w + 0.5:
            errors.append(f"card overruns column: cw={cw:.0f} > col={col_w:.0f}")
    # clipping + overflow + overlap within each card
    buttons_by_card = {}
    for v in allviews:
        x, y, w, h = _abs_frame(v, doc)
        need = _needed_width(v)
        if need is not None and need > w + 1.0:
            label = ""
            try:
                label = str(v.title()) if isinstance(v, NSButton) \
                    else str(v.stringValue())
            except Exception:
                pass
            if isinstance(v, NSButton):
                errors.append(f"clipped button need={need:.0f} "
                              f"frame_w={w:.0f} :: {label[:30]!r}")
            else:
                # a label with a truncating line-break mode is MEANT to truncate
                # (… ellipsis) — not a defect. Only flag non-truncating overflow.
                truncates = False
                try:
                    truncates = int(v.lineBreakMode()) in (3, 4, 5)  # any truncate
                except Exception:
                    pass
                if not truncates:
                    warns.append(f"clipped text need={need:.0f} "
                                 f"frame_w={w:.0f} :: {label[:30]!r}")

    # button overlap inside cards
    for card in cards:
        btns = []
        stack = list(card.subviews())
        while stack:
            v = stack.pop()
            stack.extend(v.subviews())
            if isinstance(v, NSButton):
                btns.append(v)
        for i in range(len(btns)):
            for j in range(i + 1, len(btns)):
                ax, ay, aw, ah = _abs_frame(btns[i], doc)
                bx, by, bw, bh = _abs_frame(btns[j], doc)
                if (ax < bx + bw and bx < ax + aw
                        and ay < by + bh and by < ay + bh):
                    errors.append(
                        f"button overlap: {btns[i].title()!r} ↔ {btns[j].title()!r}")

    return errors, warns, notes


def main():
    import i18n
    widths = [int(a) for a in sys.argv[1:]] or [540, 620, 760, 900, 1400, 2000]
    total_err = 0
    for w in widths:
        errs, warns, notes = audit(w)
        print(f"\n=== width {w} (ko) ===")
        for n in notes:
            print("  note:", n)
        for x in warns:
            print("  WARN:", x)
        for e in errs:
            print("  ERROR:", e)
        total_err += len(errs)
    # i18n width stress: the longest languages at the narrow floor catch button
    # /chip clipping that ko hides (e.g. de "Überspringen").
    for lang in ("de", "fr", "ja", "zh"):
        i18n.set_language(lang)
        errs, warns, _ = audit(560)
        i18n.set_language("ko")
        clip = [x for x in errs + warns if "clipped" in x]
        if clip:
            print(f"\n=== i18n {lang} @560 ===")
            for c in clip:
                print(" ", c)
            total_err += len([c for c in clip if c.startswith("clipped button")
                              or "clipped button" in c])
    print(f"\nTOTAL ERRORS: {total_err}")
    sys.exit(1 if total_err else 0)


if __name__ == "__main__":
    main()
