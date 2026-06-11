"""Selected-text capture: AX kAXSelectedTextAttribute first, synthetic ⌘C fallback.

Hard rule: the user's clipboard is snapshotted (all items, all types) before the
synthetic ⌘C and restored afterwards — never left clobbered.

Runs entirely on a worker thread. CGEventPost is documented thread-safe;
NSPasteboard from a single background thread is the established pattern — the
module lock below guarantees that single-ness.
"""

import threading
import time

from AppKit import NSPasteboard, NSPasteboardItem, NSPasteboardTypeString
from ApplicationServices import (
    AXIsProcessTrusted,
    AXUIElementCopyAttributeValue,
    AXUIElementCreateSystemWide,
    kAXFocusedUIElementAttribute,
    kAXSelectedTextAttribute,
)
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    CGEventSourceCreate,
    CGEventSourceFlagsState,
    CGEventSourceSetLocalEventsFilterDuringSuppressionState,
    kCGEventFilterMaskPermitLocalMouseEvents,
    kCGEventFilterMaskPermitSystemDefinedEvents,
    kCGEventFlagMaskCommand,
    kCGEventFlagMaskShift,
    kCGEventSourceStateCombinedSessionState,
    kCGEventSuppressionStateSuppressionInterval,
    kCGHIDEventTap,
)

_KEY_C = 8  # kVK_ANSI_C

# One capture at a time: a second concurrent snapshot would capture the first
# capture's transient clipboard state and restore that, permanently clobbering
# the user's real clipboard.
_capture_lock = threading.Lock()


def capture_selected_text(config, force_fallback=False):
    """Return the current selection as str ('' if none)."""
    with _capture_lock:
        text = "" if force_fallback else _ax_selected_text()
        source = "ax" if text else "copy"
        if not text:
            text = _copy_fallback(config)
        if text:
            print(f"text captured via {source}: {len(text)} chars", flush=True)
        return text[: int(config.get("capture_max_chars"))]


def _ax_selected_text():
    # Any failure (no value, unsupported attribute, Electron/web/Java apps that
    # don't expose the attribute, ...) falls through to the ⌘C path — only
    # success + non-empty text counts.
    try:
        sys_wide = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(
            sys_wide, kAXFocusedUIElementAttribute, None
        )
        if err != 0 or focused is None:
            return ""
        err, text = AXUIElementCopyAttributeValue(
            focused, kAXSelectedTextAttribute, None
        )
        if err != 0 or text is None:
            return ""
        return str(text)
    except Exception:
        return ""


def _copy_fallback(config):
    pb = NSPasteboard.generalPasteboard()
    snapshot = _snapshot(pb)
    start_count = pb.changeCount()
    _post_cmd_c(config)
    changed = _wait_for_change(
        pb, start_count, float(config.get("capture_copy_timeout"))
    )
    if not changed:
        # Secure field or app ignored ⌘C: clipboard untouched, nothing to
        # restore (an unconditional restore would needlessly bump changeCount
        # and make clipboard managers record a duplicate).
        return ""
    try:
        text = pb.stringForType_(NSPasteboardTypeString)
        return str(text) if text else ""
    finally:
        _restore(pb, snapshot)


def _snapshot(pb):
    # Copy the data itself BEFORE posting ⌘C — NSPasteboardItems become invalid
    # the moment the pasteboard changes.
    snapshot = []
    for item in pb.pasteboardItems() or []:
        entries = []
        for t in item.types():
            data = item.dataForType_(t)  # lazy/promised types can return nil
            if data is not None:
                entries.append((t, data))
        if entries:
            snapshot.append(entries)
    return snapshot


def _restore(pb, snapshot):
    pb.clearContents()
    items = []
    for entries in snapshot:
        item = NSPasteboardItem.alloc().init()
        for t, data in entries:
            item.setData_forType_(data, t)
        items.append(item)
    if items:
        pb.writeObjects_(items)


def _post_cmd_c(config):
    # The user still physically holds the hotkey's ⌘⇧ when this runs; a held
    # Shift can merge into the synthetic event in some apps (⌘⇧C). Wait briefly
    # for release, then suppress local keyboard events around the post and set
    # the flags explicitly on both events (the Maccy recipe). Synthetic shift
    # key-ups would desync real hardware state; kCGEventSourceStatePrivate
    # makes flags unreliable in some apps — both deliberately avoided.
    deadline = time.monotonic() + float(
        config.get("capture_modifier_release_timeout")
    )
    while time.monotonic() < deadline:
        flags = CGEventSourceFlagsState(kCGEventSourceStateCombinedSessionState)
        if not flags & kCGEventFlagMaskShift:
            break
        time.sleep(0.01)

    src = CGEventSourceCreate(kCGEventSourceStateCombinedSessionState)
    CGEventSourceSetLocalEventsFilterDuringSuppressionState(
        src,
        kCGEventFilterMaskPermitLocalMouseEvents
        | kCGEventFilterMaskPermitSystemDefinedEvents,
        kCGEventSuppressionStateSuppressionInterval,
    )
    down = CGEventCreateKeyboardEvent(src, _KEY_C, True)
    up = CGEventCreateKeyboardEvent(src, _KEY_C, False)
    CGEventSetFlags(down, kCGEventFlagMaskCommand)
    CGEventSetFlags(up, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, down)
    CGEventPost(kCGHIDEventTap, up)


def _wait_for_change(pb, start_count, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pb.changeCount() != start_count:
            return True
        time.sleep(0.025)
    return pb.changeCount() != start_count


def _main():
    import argparse

    from config import ConfigStore

    parser = argparse.ArgumentParser(description="M2 capture smoke test")
    parser.add_argument(
        "--force-fallback", action="store_true",
        help="skip AX and exercise the synthetic-⌘C path",
    )
    parser.add_argument(
        "--delay", type=float, default=0.0,
        help="seconds to wait before capturing (time to focus another app)",
    )
    args = parser.parse_args()

    if not AXIsProcessTrusted():
        print(
            "경고: 손쉬운 사용 권한이 없습니다 — AX 읽기/합성 ⌘C가 동작하지 않습니다.",
            flush=True,
        )
    if args.delay:
        time.sleep(args.delay)
    text = capture_selected_text(ConfigStore(), force_fallback=args.force_fallback)
    print(f"captured ({len(text)} chars): {text!r}", flush=True)


if __name__ == "__main__":
    _main()
