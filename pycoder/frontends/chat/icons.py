"""Line icons for the chat page, drawn in the text colour like SF Symbols: emoji come in their own
colours and sizes and clash with the rest of the type.

Each icon is SVG path data on a 24×24 grid, stroked (never filled) by the page's `.ic` style.
"""

from __future__ import annotations

_FILE = '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>'

SHAPES = {
    'todo-completed': '<circle cx="12" cy="12" r="9.5" style="fill:currentColor;stroke:none"/>'
    '<path d="m7.5 12.5 3 3 6-6.5" style="stroke:var(--bg)"/>',
    'todo-in_progress': '<circle cx="12" cy="12" r="9"/>'
    '<circle cx="8" cy="12" r="1" style="fill:currentColor;stroke:none"/>'
    '<circle cx="12" cy="12" r="1" style="fill:currentColor;stroke:none"/>'
    '<circle cx="16" cy="12" r="1" style="fill:currentColor;stroke:none"/>',
    'todo-pending': '<circle cx="12" cy="12" r="9" stroke-dasharray="3 3"/>',
    'close': '<path d="M6 6l12 12M18 6 6 18"/>',
    'thumbtack': (
        '<path d="M12 17v5"/>'
        '<path d="M9 10.8V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v5.8l2.6 3.2a1 1 0 0 1-.8 1.6H7.2'
        'a1 1 0 0 1-.8-1.6z"/>'
    ),
    'copy': (
        '<rect x="9" y="9" width="12" height="12" rx="2"/>'
        '<path d="M5 15a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2"/>'
    ),
    'rewind': '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
    'fork': (
        '<path d="M16 3h5v5"/><path d="M21 3l-9 9H3"/><path d="M16 21h5v-5"/><path d="m21 21-6.5-6.5"/>'
    ),
    'file': _FILE + '<path d="M9 13h6M9 17h4"/>',
    'file-plus': _FILE + '<path d="M12 11v6M9 14h6"/>',
    'pencil': '<path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4z"/><path d="m14.5 5.5 3 3"/>',
    'folder': '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    'search': '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    'play': '<path d="M7 4.5v15l12-7.5z"/>',
    'checklist': '<path d="m4 6 1.5 1.5L8 5M4 12l1.5 1.5L8 11M4 18l1.5 1.5L8 17M12 6h8M12 12h8M12 18h8"/>',
    'agent': '<rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 4v4M9.5 13v1.5M14.5 13v1.5"/>',
    'branch': '<circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="7" r="2"/>'
    '<path d="M6 7v10M18 9c0 5-7 4-11 8.5"/>',
    'package': '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="m3 8 9 5 9-5M12 13v8"/>',
    'book': '<path d="M3 5h6a3 3 0 0 1 3 3v12a2 2 0 0 0-2-2H3zM21 5h-6a3 3 0 0 0-3 3v12a2 2 0 0 1 2-2h7z"/>',
    'save': '<path d="M5 3h11l3 3v13a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2z"/><path d="M8 3v5h7M8 21v-7h8v7"/>',
    'globe': '<circle cx="12" cy="12" r="9"/>'
    '<path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    'phone': '<rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M11 18.5h2"/>',
    'pin': '<path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z"/>'
    '<circle cx="12" cy="9.5" r="2.5"/>',
    'compass': '<circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5z"/>',
    'speaker': '<path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12"/>',
    'mic': '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    'bell': '<path d="M6 16v-5a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
    'clipboard': '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 3h6v3H9zM9 11h6M9 15h4"/>',
    'share': '<path d="M12 3v12M8 7l4-4 4 4"/><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/>',
    'link': '<path d="M10 14a4 4 0 0 0 6 0l3-3a4 4 0 0 0-6-6l-1 1M14 10a4 4 0 0 0-6 0l-3 3a4 4 0 0'
    ' 0 6 6l1-1"/>',
    'code': '<path d="m8 7-5 5 5 5M16 7l5 5-5 5"/>',
    'image': '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.8"/>'
    '<path d="m21 16-5-5-9 9"/>',
    'download': '<path d="M12 3v12M8 11l4 4 4-4"/><path d="M5 17v2a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-2"/>',
    'bolt': '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    'question': '<circle cx="12" cy="12" r="9"/>'
    '<path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5v.5M12 17h.01"/>',
    'bookmark': '<path d="M6 3h12v18l-6-4-6 4z"/>',
    'list': '<path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>',
    'tool': '<path d="M14.5 6.5a4 4 0 0 0-5.3 5.3l-5.7 5.7 3 3 5.7-5.7a4 4 0 0 0 5.3-5.3l-2.5'
    ' 2.5-2.5-.5-.5-2.5z"/>',
    'spark': '<path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9"/>',
    'scan': '<path d="M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2"/>'
    '<path d="M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2M8 10h8M8 14h5"/>',
    'paperclip': '<path d="m20 11-8 8a5 5 0 0 1-7-7l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7L9.7 16.7a1.7 1.7'
    ' 0 0 1-2.4-2.4L15 6.5"/>',
}

TOOLS = {
    'write_file': 'file-plus',
    'move_file': 'folder',
    'delete_file': 'file',
    'edit_file': 'pencil',
    'read_file': 'file',
    'list_files': 'folder',
    'search': 'search',
    'python_code': 'search',
    'run_python': 'play',
    'run_c': 'code',
    'todo_write': 'checklist',
    'todo_update': 'checklist',
    'todo_add': 'checklist',
    'task': 'agent',
    'git': 'branch',
    'install_package': 'package',
    'read_skill': 'book',
    'save_skill': 'save',
    'web_search': 'globe',
    'web_fetch': 'globe',
    'pythonista_docs': 'book',
    'device_info': 'phone',
    'location': 'pin',
    'motion': 'compass',
    'speak': 'speaker',
    'record_audio': 'mic',
    'notify': 'bell',
    'clipboard_read': 'clipboard',
    'clipboard_write': 'clipboard',
    'share': 'share',
    'open_in_editor': 'code',
    'open_url': 'link',
    'photos': 'image',
    'look_at_screen': 'image',
    'use_screen': 'image',
    'recognize_text': 'scan',
    'import_file': 'download',
    'run_shortcut': 'bolt',
    'ask_user': 'question',
    'remember': 'bookmark',
    'recall': 'bookmark',
    'forget': 'bookmark',
    'exit_plan_mode': 'list',
}


def icon(name: str) -> str:
    return f'<svg class="ic" viewBox="0 0 24 24" aria-hidden="true">{SHAPES.get(name, SHAPES["tool"])}</svg>'


def tool_icon(tool: str) -> str:
    return icon(TOOLS.get(tool, 'tool'))
