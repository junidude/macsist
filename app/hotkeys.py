"""HotkeyManager — pynput global hotkeys, matched by virtual keycode.

pynput's stock GlobalHotKeys matches by produced character, which under a
Korean (or any non-Latin) input source never equals the config's Latin letter —
keycode 14 arrives as 'ㄷ', not 'e' — so the binding would never fire. We parse
the same "<cmd>+<shift>+e" config format but match the physical key via its
ANSI virtual keycode instead, which is layout-independent.

Callbacks fire on pynput's listener thread (a CFRunLoop thread driving a
CGEventTap): no AppKit calls there; Quartz C functions are fine.

Known limitations (acceptable for M2):
- The tap is listen-only, so the hotkey chord also reaches the front app.
  TextEdit/browsers don't bind <cmd>+<shift>+e; selective suppression
  (darwin_intercept) is a post-M2 concern.
- macOS may require Input Monitoring in addition to Accessibility for the
  hosting process (the terminal, in dev). AXIsProcessTrusted() passing does
  not guarantee the tap delivers events — hence the start log below, so a
  silently dead listener is diagnosable.
"""

import contextlib

from pynput import keyboard

_layout_context = None


def _warm_keyboard_layout_cache():
    """MUST run on the main thread, before the listener starts.

    macOS 26 asserts that TIS/TSM input-source APIs run on the main queue.
    pynput's Listener._run enters keycode_context() — TISCopyCurrentKeyboard-
    InputSource + TSMGetInputSourceProperty via ctypes — on the LISTENER
    thread, which SIGTRAPs whenever the input-source cache needs revalidation
    (observed 2026-06-11: Settings save → rebind → new listener thread → trap;
    launch usually survives only because AppKit has just warmed the cache).
    Snapshot the layout context once on the main thread and patch pynput's
    darwin backend to reuse it. A stale snapshot only affects key.char
    cosmetics — our matching is vk-based.
    """
    global _layout_context
    if _layout_context is not None:
        return
    from pynput._util import darwin as _util_darwin
    from pynput.keyboard import _darwin as _kb_darwin

    with _util_darwin.keycode_context() as ctx:
        _layout_context = ctx

    @contextlib.contextmanager
    def _cached_context():
        yield _layout_context

    _kb_darwin.keycode_context = _cached_context

# kVK_ANSI_* — physical key positions on the ANSI layout.
_US_ANSI_VK = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7,
    "c": 8, "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15,
    "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22,
    "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29,
    "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "l": 37,
    "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44,
    "n": 45, "m": 46, ".": 47, "`": 50,
}

_VK_TO_CHAR = {vk: char for char, vk in _US_ANSI_VK.items()}

_CANONICAL_MODS = {
    keyboard.Key.cmd_l: keyboard.Key.cmd, keyboard.Key.cmd_r: keyboard.Key.cmd,
    keyboard.Key.shift_l: keyboard.Key.shift,
    keyboard.Key.shift_r: keyboard.Key.shift,
    keyboard.Key.alt_l: keyboard.Key.alt, keyboard.Key.alt_r: keyboard.Key.alt,
    keyboard.Key.alt_gr: keyboard.Key.alt,
    keyboard.Key.ctrl_l: keyboard.Key.ctrl,
    keyboard.Key.ctrl_r: keyboard.Key.ctrl,
}


def _canon(key):
    return _CANONICAL_MODS.get(key, key)


def format_binding(vk, cmd=False, ctrl=False, alt=False, shift=False):
    """Build a pynput binding string ("<cmd>+<shift>+e") from a virtual keycode
    and modifier states. Returns None for keys outside the ANSI table (the
    recorder rejects those) — vk-based, so it works under any input source."""
    char = _VK_TO_CHAR.get(vk)
    if char is None:
        return None
    parts = []
    if cmd:
        parts.append("<cmd>")
    if ctrl:
        parts.append("<ctrl>")
    if alt:
        parts.append("<alt>")
    if shift:
        parts.append("<shift>")
    parts.append(char)
    return "+".join(parts)


class _VkHotKey:
    def __init__(self, binding, callback):
        self._callback = callback
        self._modifiers = set()
        self._vks = set()
        for key in keyboard.HotKey.parse(binding):
            if isinstance(key, keyboard.KeyCode):
                vk = key.vk
                if vk is None:
                    char = (key.char or "").lower()
                    vk = _US_ANSI_VK.get(char)
                if vk is None:
                    raise ValueError(f"unsupported key in hotkey binding: {binding!r}")
                self._vks.add(vk)
            else:
                self._modifiers.add(_canon(key))
        self._pressed_mods = set()
        self._pressed_vks = set()

    def press(self, key):
        if isinstance(key, keyboard.Key):
            self._pressed_mods.add(_canon(key))
            return
        vk = getattr(key, "vk", None)
        if vk is None or vk not in self._vks or vk in self._pressed_vks:
            return  # irrelevant key, or autorepeat of a held key
        self._pressed_vks.add(vk)
        if self._modifiers <= self._pressed_mods and self._pressed_vks == self._vks:
            self._callback()

    def release(self, key):
        if isinstance(key, keyboard.Key):
            self._pressed_mods.discard(_canon(key))
        else:
            vk = getattr(key, "vk", None)
            if vk is not None:
                self._pressed_vks.discard(vk)


class HotkeyManager:
    def __init__(self, bindings):
        """bindings: {"<cmd>+<shift>+e": callback, ...} — pynput HotKey.parse format."""
        self._paused = False
        self._bindings = dict(bindings)
        self._hotkeys = [_VkHotKey(b, cb) for b, cb in self._bindings.items()]
        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        # macOS 26 crash fix (M11.1): pynput converts NSSystemDefined CGEvents
        # to NSEvent on the LISTENER thread to detect media keys; for the
        # caps-lock / 한-A toggle that conversion runs TSM's caps-lock
        # press-and-hold handling (TSMAdjustCapsLockPressAndHold →
        # TISCreateInputSource…), which is main-thread-only on macOS 26 →
        # dispatch_assert_queue SIGTRAP kills the app. We never use media
        # keys, so drop NSSystemDefined from this instance's tap mask — those
        # events then never reach pynput's NSEvent conversion at all.
        from pynput.keyboard._darwin import NSSystemDefined
        from Quartz import CGEventMaskBit
        self._listener._EVENTS = (
            type(self._listener)._EVENTS & ~CGEventMaskBit(NSSystemDefined)
        )

    def _on_press(self, key):
        if self._paused:
            return
        for hotkey in self._hotkeys:
            hotkey.press(key)

    def _on_release(self, key):
        if self._paused:
            return
        for hotkey in self._hotkeys:
            hotkey.release(key)

    def start(self):
        """Call from the main thread (see _warm_keyboard_layout_cache)."""
        _warm_keyboard_layout_cache()
        self._listener.start()
        self._listener.wait()
        print("global hotkeys listening:", ", ".join(self._bindings), flush=True)

    def stop(self):
        self._listener.stop()

    def set_paused(self, paused):
        """While the Settings recorder captures a combo, the old binding must
        not fire (recording ⌘⇧E would otherwise pop the explain panel)."""
        self._paused = bool(paused)

    def rebind(self, bindings):
        """Swap bindings at runtime (Settings save). The listener keeps
        running; only the matcher list is replaced (atomic assignment, safe
        against the listener thread). Restarting the listener would spawn a
        new thread through pynput's TIS-touching startup — see
        _warm_keyboard_layout_cache."""
        self._bindings = dict(bindings)
        self._hotkeys = [_VkHotKey(b, cb) for b, cb in self._bindings.items()]
        print("global hotkeys rebound:", ", ".join(self._bindings), flush=True)
