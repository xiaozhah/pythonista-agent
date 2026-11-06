"""The device: asking the user, notifications, clipboard, photos, sensors, speech and Shortcuts.

ask_user works in every frontend. The rest need Pythonista's modules and are offered only there.
Anything that reads private data (location, clipboard, photos, the microphone) or acts outside
pycoder (Shortcuts, URLs) is not read-only, so the permission mode decides whether to ask first.
"""

from __future__ import annotations

import io
import os
import shutil
import time
import urllib.parse
from typing import Any

from ..host import images
from ..host.main_thread import call_on_main
from ..types import Block
from .base import Tool, ToolContext, ToolError, prop

MAX_RECORDING = 120  # seconds
BLOCKED_SCHEMES = ('shortcuts', 'pythonista', 'pythonista3', 'workflow', 'x-callback-url')


# ---- every frontend


def ask_user(ctx: ToolContext, question: str, options: list[str] | None = None) -> str:
    if ctx.agent is not None:
        ctx.agent.on_attention(question)  # a notification if the user is in another app
    if options:
        picked = ctx.frontend.choose(question, options)
        return 'The user did not answer' if picked is None else f'The user chose: {options[picked]}'
    answer = ctx.frontend.ask_text(question)
    return 'The user did not answer' if answer is None else f'The user answered: {answer}'


COMMON = [
    Tool(
        'ask_user',
        'Ask the user a question and wait for the answer: with options, they pick one; without, they '
        'type. Use it when you are blocked on a decision only the user can make, not to confirm '
        'routine steps.',
        {
            'question': prop('string', 'The question, short'),
            'options': prop('array', '2–6 answers to pick from (optional)', items={'type': 'string'}),
        },
        ask_user,
        required=['question'],
    ),
]


# ---- Pythonista only


def notify(ctx: ToolContext, message: str, title: str = 'pycoder', delay: int = 0) -> str:
    import notification

    notification.schedule(message=message, delay=max(0, delay), sound_name='default', title=title)
    return f'Notification scheduled{f" in {delay} s" if delay else ""}'


def clipboard_read(ctx: ToolContext) -> str | list[Block]:
    import clipboard

    text = call_on_main(clipboard.get)
    if text:
        return str(text)
    image = call_on_main(clipboard.get_image)
    if image is None:
        return '(the clipboard is empty)'
    return [images.block_from_pil(image), {'type': 'text', 'text': 'The clipboard holds this image'}]


def clipboard_write(ctx: ToolContext, text: str) -> str:
    import clipboard

    call_on_main(clipboard.set, text)
    return f'Copied {len(text)} characters to the clipboard'


def share(ctx: ToolContext, text: str = '', path: str = '') -> str:
    if path:
        import console

        app = console.open_in(ctx.workspace.resolve(path))
        return f'Opened in {app}' if app else 'The user closed the share sheet'
    if not text:
        raise ToolError('Give text or a path')
    import dialogs

    dialogs.share_text(text)
    return 'Shown in the share sheet'


def open_in_editor(ctx: ToolContext, path: str, line: int = 0, note: str = '') -> str:
    import editor

    full = ctx.workspace.resolve(path)
    if not os.path.isfile(full):
        raise ToolError(f'No such file: {path}')
    editor.open_file(full, new_tab=True)
    if line:
        editor.annotate_line(line, note, 'warning' if note else 'success', True, filename=full, scroll=True)
    return f'Opened {path}' + (f' at line {line}' if line else '')


def photos_tool(ctx: ToolContext, action: str, count: int = 1, path: str = '') -> str | list[Block]:
    import photos

    if action == 'save':
        full = ctx.workspace.resolve(path)
        if os.path.splitext(full)[1].lower() not in images.MEDIA_TYPES:
            raise ToolError('Only images can be saved to Photos')
        photos.create_image_asset(full)
        return f'Saved {path} to Photos'
    if action == 'pick':
        asset = photos.pick_asset(title='Pick a photo for pycoder')
        if asset is None:
            return 'The user did not pick a photo'
        chosen = [asset]
    elif action == 'screenshots':
        album = photos.get_screenshots_album()
        chosen = (album.assets if album else [])[-max(1, min(count, 5)) :]
    elif action == 'recent':
        chosen = photos.get_assets('image')[-max(1, min(count, 5)) :]
    elif action == 'camera':
        image = photos.capture_image()
        if image is None:
            return 'The user cancelled the camera'
        return [images.block_from_pil(image), {'type': 'text', 'text': 'Photo just taken'}]
    else:
        raise ToolError('action must be pick, screenshots, recent, camera or save')
    if not chosen:
        return 'No photos found'
    blocks: list[Block] = []
    for asset in reversed(chosen):  # newest first
        blocks.append(images.block_from_pil(asset.get_image()))
        blocks.append({'type': 'text', 'text': f'taken {asset.creation_date}'})
    return blocks


def import_file(ctx: ToolContext, folder: str = '.') -> str:
    import dialogs

    picked = dialogs.pick_document(types=['public.item'])
    if not picked:
        return 'The user did not pick a file'
    target_dir = ctx.workspace.resolve(folder)
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, os.path.basename(picked))
    ctx.checkpoints.before_write(target)
    shutil.copyfile(picked, target)
    return f'Imported {ctx.workspace.rel(target)} ({os.path.getsize(target)} bytes)'


def get_location(ctx: ToolContext, address: bool = True) -> str:
    import location

    location.start_updates()
    try:
        fix = None
        for _ in range(50):  # the first fix can take a few seconds
            if ctx.cancel.cancelled:
                break
            fix = location.get_location()
            if fix and fix.get('horizontal_accuracy', 1e9) < 200:
                break
            time.sleep(0.2)
    finally:
        location.stop_updates()
    if not fix:
        if not location.is_authorized():
            raise ToolError('No location: allow Pythonista to use location in Settings')
        raise ToolError(
            'No location fix within 10 seconds (weak signal, or the first fix is slow); try again'
        )
    keys = ('latitude', 'longitude', 'altitude', 'horizontal_accuracy', 'speed', 'course')
    out = ', '.join(f'{k}={fix[k]}' for k in keys if k in fix)
    if address:
        places = location.reverse_geocode(fix) or []
        if places:
            out += '\naddress: ' + ', '.join(str(v) for k, v in places[0].items() if v and k != 'Country')
    return out


def read_motion(ctx: ToolContext, seconds: float = 1.0) -> str:
    import motion

    motion.start_updates()
    try:
        time.sleep(0.3)  # the first readings are zeros
        samples = []
        end = time.monotonic() + max(0.1, min(seconds, 10))
        while time.monotonic() < end:
            samples.append(
                (
                    motion.get_gravity(),
                    motion.get_user_acceleration(),
                    motion.get_attitude(),
                    motion.get_magnetic_field(),
                )
            )
            time.sleep(0.1)
    finally:
        motion.stop_updates()
    names = ('gravity (g)', 'user acceleration (g)', 'attitude roll/pitch/yaw (rad)', 'magnetic field (µT)')
    lines = [f'{len(samples)} samples over {seconds} s; averages:']
    for i, name in enumerate(names):
        values = [s[i] for s in samples]
        avg = [sum(v[j] for v in values) / len(values) for j in range(len(values[0]))]
        lines.append(f'{name}: ' + ', '.join(f'{x:.3f}' for x in avg[:3]))
    return '\n'.join(lines)


def record_audio(ctx: ToolContext, seconds: int = 10, language: str = '', keep: str = '') -> str:
    """Record from the microphone: how loud it was, then what was said (iOS speech recognition)."""
    import sound
    import speech

    seconds = max(1, min(seconds, MAX_RECORDING))
    path = ctx.workspace.resolve(keep) if keep else os.path.join(ctx.workspace.root, '.pycoder-recording.m4a')
    recorder = sound.Recorder(path)
    recorder.record()
    averages: list[float] = []
    peak = -160.0
    try:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if ctx.cancel.cancelled:
                break
            meters = recorder.meters  # dB, 0 is the loudest the microphone takes
            averages.append(max(meters['average']))
            peak = max(peak, *meters['peak'])
            time.sleep(0.1)
    finally:
        recorder.stop()
    level = (
        f'Level: average {sum(averages) / len(averages):.0f} dB, peak {peak:.0f} dB (0 dB is the loudest '
        'the microphone records; about -50 is a quiet room, -20 loud speech)'
        if averages
        else ''
    )
    try:
        result: Any = speech.recognize(path, language) if language else speech.recognize(path)
        text = _transcript(result)
    except RuntimeError:
        text = ''  # nothing recognizable, or speech recognition is unavailable
    finally:
        if not keep and os.path.exists(path):
            os.remove(path)
    said = f'Transcript: {text}' if text else 'Nothing recognizable was said'
    return '\n'.join(filter(None, [level, said]))


def _transcript(result: Any) -> str:
    """speech.recognize returns candidate transcriptions with confidences; take the best."""
    if not result:
        return ''
    first = result[0]
    return str(first[0] if isinstance(first, (list, tuple)) else first)


def speak(ctx: ToolContext, text: str, language: str = '', rate: float = 0.5) -> str:
    import speech

    speech.say(text, language or None, rate)
    return 'Spoken'


def run_shortcut(ctx: ToolContext, name: str, input: str = '', wait: int = 0) -> str:
    """Run a Shortcuts shortcut; its output comes back through the clipboard when wait > 0."""
    import webbrowser

    import clipboard

    query = urllib.parse.urlencode(
        {'name': name, 'input': 'text', 'text': input}, quote_via=urllib.parse.quote
    )
    before = call_on_main(clipboard.get)
    webbrowser.open('shortcuts://run-shortcut?' + query)
    if wait <= 0:
        return f'Started the shortcut {name}'
    end = time.monotonic() + min(wait, 300)
    while time.monotonic() < end and not ctx.cancel.cancelled:
        time.sleep(0.5)
        now = call_on_main(clipboard.get)
        if now != before:
            return f'The shortcut {name} copied:\n{now}'
    return f'Started the shortcut {name}; nothing new appeared on the clipboard within {wait} s'


def open_url(ctx: ToolContext, url: str) -> str:
    import webbrowser

    scheme = urllib.parse.urlparse(url).scheme.lower()
    if not scheme:
        raise ToolError('Give a full URL, e.g. https://… or an app scheme such as maps://')
    if scheme in BLOCKED_SCHEMES:  # these run code or shortcuts: use the tools that ask for that
        raise ToolError(f'{scheme}:// URLs are not opened here; use run_shortcut or run_python')
    webbrowser.open(url)
    return f'Opened {url}'


def device_info(ctx: ToolContext) -> str:
    import ui
    from objc_util import ObjCClass

    device = ObjCClass('UIDevice').currentDevice()
    process = ObjCClass('NSProcessInfo').processInfo()
    on_mac = bool(process.isiOSAppOnMac()) if process.respondsToSelector_('isiOSAppOnMac') else False
    disk = shutil.disk_usage(ctx.workspace.root)
    thermal = ['nominal', 'fair', 'serious', 'critical']
    thermal_state = int(process.thermalState())
    width, height = ui.get_screen_size()
    return '\n'.join(
        [
            f'model: {device.model()} · iOS {device.systemVersion()}'
            + (' (the iPad app running on a Mac)' if on_mac else ''),
            'battery: ' + (_mac_battery() if on_mac else _ios_battery(device)),
            f'screen: {width:.0f}×{height:.0f} points',
            f'storage free: {disk.free / 1e9:.1f} GB of {disk.total / 1e9:.1f} GB',
            _memory(int(process.physicalMemory()), on_mac),
            f'thermal state: {thermal[thermal_state] if 0 <= thermal_state < 4 else thermal_state}',
        ]
    )


def _memory(total: int, on_mac: bool) -> str:
    """Memory in use across the device (Mach VM statistics) and, on iOS, how much more Pythonista
    may take before iOS stops it."""
    import ctypes

    line = f'memory: {total / 1e9:.1f} GB'
    try:
        libc = ctypes.CDLL(None)
        counts = (ctypes.c_uint32 * 64)()  # vm_statistics64: page counts first, then 64-bit counters
        size = ctypes.c_uint32(38)  # HOST_VM_INFO64_COUNT
        libc.mach_host_self.restype = ctypes.c_uint32
        if (
            libc.host_statistics64(libc.mach_host_self(), 4, counts, ctypes.byref(size)) == 0
        ):  # HOST_VM_INFO64
            free, inactive = counts[0], counts[2]  # free_count, active_count, inactive_count, …
            used = total - (free + inactive) * int(libc.getpagesize())
            if 0 < used <= total:
                line = f'memory: {used / 1e9:.1f} GB of {total / 1e9:.1f} GB in use'
    except (AttributeError, OSError):
        pass
    if not on_mac:
        try:
            available = ctypes.CDLL(None).os_proc_available_memory
            available.restype = ctypes.c_size_t
            line += f' ({int(available()) / 1e9:.1f} GB more available to Pythonista)'
        except (AttributeError, OSError):
            pass
    return line


def _ios_battery(device: Any) -> str:
    device.setBatteryMonitoringEnabled_(True)
    level = float(device.batteryLevel())
    states = {0: 'unknown', 1: 'unplugged', 2: 'charging', 3: 'full'}
    state = states.get(int(device.batteryState()), '?')
    return f'{round(level * 100)}% ({state})' if level >= 0 else 'unknown'


def _mac_battery() -> str:
    """The Mac's own battery, from macOS's power API: UIDevice there doesn't see the real one."""
    import ctypes

    from objc_util import ObjCInstance

    try:
        iokit = ctypes.CDLL('/System/Library/Frameworks/IOKit.framework/IOKit')
        for name in ('IOPSCopyPowerSourcesInfo', 'IOPSCopyPowerSourcesList', 'IOPSGetPowerSourceDescription'):
            getattr(iokit, name).restype = ctypes.c_void_p
        iokit.IOPSCopyPowerSourcesList.argtypes = [ctypes.c_void_p]
        iokit.IOPSGetPowerSourceDescription.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        info = iokit.IOPSCopyPowerSourcesInfo()
        sources = ObjCInstance(iokit.IOPSCopyPowerSourcesList(info))
        for i in range(int(sources.count())):
            ref = sources.objectAtIndex_(i)
            desc = ObjCInstance(iokit.IOPSGetPowerSourceDescription(info, ref.ptr))
            if str(desc.objectForKey_('Type')) != 'InternalBattery':
                continue
            now = int(desc.objectForKey_('Current Capacity').intValue())
            full = int(desc.objectForKey_('Max Capacity').intValue()) or 100
            source = str(desc.objectForKey_('Power Source State'))
            charging = bool(desc.objectForKey_('Is Charging').boolValue())
            how = 'charging' if charging else ('plugged in' if source == 'AC Power' else 'on battery')
            return f"{round(100 * now / full)}% ({how}; the Mac's battery)"
        return 'none (this Mac has no battery)'
    except Exception as e:  # the iPad app's sandbox may not allow it
        return f"unknown (the iPad app on a Mac cannot read the Mac's battery: {type(e).__name__})"


def look_at_screen(ctx: ToolContext, wait: float = 0.5, close: bool = False) -> list[Block]:
    """What Pythonista shows now, as an image: the model checks a UI by looking at it, instead of
    asking the user for a screenshot. Only this app's windows are in it. With close, first closes
    the windows code presented (each run_python is a new __main__, so it may have lost them)."""
    if close:
        _close_presented()
    time.sleep(min(max(wait, 0), 10))  # a view just presented is still sliding in
    png = _screen_png()
    from PIL import Image

    with Image.open(io.BytesIO(png)) as image:
        block = images.block_from_pil(image)
    return [{'type': 'text', 'text': 'The screen now:'}, block]


def _close_presented() -> None:
    """Close what code presented, one window at a time, top first: closing anything more dismisses
    the window under it, which may be pycoder's own."""
    for _ in range(20):
        windows = call_on_main(presented_windows)
        if not windows:
            return
        call_on_main(windows[-1].close)
        time.sleep(0.7)


def presented_windows() -> list[Any]:
    """The windows code presented, not pycoder's. Leaf controls are never windows, though the ones
    inside a table's cells look like them (on screen, with no superview)."""
    import gc

    import ui

    controls = (
        ui.Label,
        ui.Button,
        ui.ImageView,
        ui.TextField,
        ui.TextView,
        ui.Switch,
        ui.Slider,
        ui.SegmentedControl,
        ui.TableViewCell,
        ui.DatePicker,
    )
    return _top_last(
        [
            o
            for o in gc.get_objects()
            if isinstance(o, ui.View)
            and not isinstance(o, controls)
            and not type(o).__module__.startswith('pycoder.')
            and o.on_screen
            and o.superview is None
        ]
    )


def _top_last(windows: list[Any]) -> list[Any]:
    """In the order they were presented: the order of gc.get_objects differs between devices."""
    if len(windows) < 2:
        return windows
    try:
        from objc_util import ObjCClass, ObjCInstance

        controller = ObjCClass('UIApplication').sharedApplication().keyWindow().rootViewController()
        presented = []
        while controller:
            presented.append(controller.view())
            controller = controller.presentedViewController()

        def depth(window: Any) -> int:
            view = ObjCInstance(window)
            return max((i for i, p in enumerate(presented) if view.isDescendantOfView_(p)), default=-1)

        return sorted(windows, key=depth)
    except Exception:
        return windows


def _screen_png() -> bytes:
    import ui
    from objc_util import ObjCClass, on_main_thread

    @on_main_thread
    def draw() -> bytes:
        app = ObjCClass('UIApplication').sharedApplication()
        windows = [w for w in app.windows() if not w.isHidden()]
        if not windows:
            raise ToolError('Nothing on screen')
        size = windows[0].bounds().size
        with ui.ImageContext(size.width, size.height) as ctx:
            for window in windows:  # from the back: a dialog may have a window of its own
                window.drawViewHierarchyInRect_afterScreenUpdates_(window.bounds(), False)
            png: bytes = ctx.get_image().to_png()
        return png

    return draw()


def _str(description: str) -> dict[str, Any]:
    return prop('string', description)


PYTHONISTA = [
    Tool(
        'look_at_screen',
        'See what is on the screen now (a view you presented, a form, a game), as an image. Check a UI '
        'with this instead of asking the user for a screenshot. Only shows this app. Use close when '
        'you are done, so your windows do not stay over pycoder.',
        {
            'wait': prop('number', 'Seconds to wait first (default 0.5, for a view still sliding in)'),
            'close': prop('boolean', 'First close every window your code presented'),
        },
        look_at_screen,
    ),
    Tool(
        'notify',
        'Show an iOS notification now or after a delay (a reminder or a timer). pycoder already '
        'notifies when a long request ends or needs the user while they are in another app.',
        {
            'message': _str('The text'),
            'title': _str('Title (default pycoder)'),
            'delay': prop('integer', 'Seconds from now (default 0)'),
        },
        notify,
        required=['message'],
    ),
    Tool(
        'clipboard_read',
        "Read the clipboard (text, or an image). Private: only when the user's request needs it.",
        {},
        clipboard_read,
        readonly=False,
    ),
    Tool(
        'clipboard_write',
        'Put text on the clipboard so the user can paste it elsewhere.',
        {'text': _str('The text')},
        clipboard_write,
        required=['text'],
        readonly=False,
    ),
    Tool(
        'share',
        'Open the iOS share sheet with text, or with a workspace file (to AirDrop, Files, other apps).',
        {'text': _str('Text to share'), 'path': _str('Or a workspace file to share')},
        share,
    ),
    Tool(
        'open_in_editor',
        "Open a workspace file in Pythonista's editor, optionally marking a line with a note.",
        {
            'path': _str('Workspace-relative path'),
            'line': prop('integer', 'Line to mark (1-based)'),
            'note': _str('Note shown at that line'),
        },
        open_in_editor,
        required=['path'],
    ),
    Tool(
        'photos',
        "The user's photo library and camera, when the user wants a photo used. pick: the user picks "
        'one; screenshots / recent: the latest few (count); camera: the user takes a photo; save: save '
        'a workspace image (path) to the library. The images come back for you to look at. To look at '
        'an image file, such as one your code made, use read_file instead.',
        {
            'action': prop('string', 'What to do', enum=['pick', 'screenshots', 'recent', 'camera', 'save']),
            'count': prop('integer', 'How many, for screenshots / recent (1–5)'),
            'path': _str('For save: the workspace image'),
        },
        photos_tool,
        required=['action'],
        readonly=False,
        safe_input=lambda inp: inp.get('action') in ('pick', 'camera'),  # the user chooses: no question
    ),
    Tool(
        'import_file',
        'Let the user pick a file from the Files app (iCloud Drive, other apps) and copy it into the '
        'workspace.',
        {'folder': _str('Workspace folder to copy it into (default: the root)')},
        import_file,
        readonly=False,  # it may replace a workspace file of the same name
    ),
    Tool(
        'location',
        "The device's GPS position and, optionally, its street address. Private: only when needed.",
        {'address': prop('boolean', 'Also look up the address (default true)')},
        get_location,
        readonly=False,
    ),
    Tool(
        'motion',
        'Read the motion sensors for a moment: gravity, acceleration, attitude, magnetic field. Ask the '
        'user to hold the device the way that matters (flat, upright) while it measures.',
        {'seconds': prop('number', 'How long to sample (default 1, at most 10)')},
        read_motion,
    ),
    Tool(
        'record_audio',
        'Record from the microphone: returns how loud it was (average and peak dB) and a transcript '
        'from iOS speech recognition. For the user to dictate, or to hear the room.',
        {
            'seconds': prop('integer', f'How long (default 10, at most {MAX_RECORDING})'),
            'language': _str('Language code such as en-US or zh-CN (default: the system language)'),
            'keep': _str('Workspace path to keep the recording at (.m4a); otherwise it is deleted'),
        },
        record_audio,
        readonly=False,
    ),
    Tool(
        'speak',
        'Say something aloud with text to speech.',
        {
            'text': _str('What to say'),
            'language': _str('Language code such as en-US or zh-CN'),
            'rate': prop('number', 'Speed from 0 to 1 (default 0.5)'),
        },
        speak,
        required=['text'],
    ),
    Tool(
        'run_shortcut',
        "Run one of the user's Shortcuts with text input. To get output back, the shortcut must end "
        'with Copy to Clipboard; set wait to the seconds to wait for it.',
        {
            'name': _str('The shortcut name, exactly'),
            'input': _str('Text passed to the shortcut'),
            'wait': prop('integer', 'Seconds to wait for output on the clipboard (default 0)'),
        },
        run_shortcut,
        required=['name'],
        readonly=False,
    ),
    Tool(
        'open_url',
        'Open a URL: a web page in the browser, or an app through its scheme (maps://, mailto:, …).',
        {'url': _str('The URL')},
        open_url,
        required=['url'],
        readonly=False,
    ),
    Tool(
        'device_info',
        'Battery, storage, memory, screen size, iOS version and thermal state of this device, read from '
        'the right source; trust what it reports, "unknown" included. It says when this is the iPad app '
        'running on a Mac: then platform and os.uname() name an iPad model that is not the real '
        'hardware, and location, motion, the camera and the microphone may be missing or approximate.',
        {},
        device_info,
    ),
]
