"""The chat page shown in the WebView: its design system (CSS) and the JS the frontend calls."""

from __future__ import annotations

from pygments.formatters import HtmlFormatter


def _code_css() -> str:
    """Light code colours by default; dark ones when the theme is dark, or auto on a dark iPhone."""
    light = HtmlFormatter(style='friendly').get_style_defs('.codehilite')  # type: ignore[no-untyped-call]
    dark = HtmlFormatter(style='monokai')
    forced = dark.get_style_defs('html[data-theme=dark] .codehilite')  # type: ignore[no-untyped-call]
    auto = dark.get_style_defs('html:not([data-theme=light]) .codehilite')  # type: ignore[no-untyped-call]
    return f'{light}\n{forced}\n@media (prefers-color-scheme: dark) {{\n{auto}\n}}'


CSS = """
/* Design tokens. One type scale (rem, so the font-size setting scales everything), one spacing
   scale (4, 8, 12, 16, 24), iOS system colours, and a dark theme with the same names.
   Text colours reach 4.5:1 on the surfaces they sit on (WCAG AA): --accent is for marks and lines;
   white text goes on --accent-fill, accent-coloured text uses --accent-text. */
:root {
  --bg:#ffffff; --surface:#f4f4f6; --surface-2:#e9e9ee; --fg:#1c1c1e; --fg-2:#3c3c43; --dim:#66666b;
  --line:rgba(60,60,67,.14); --accent:#d97757; --accent-fill:#ad5133; --accent-text:#ad5133;
  --accent-fg:#ffffff; --link:#2f6fd6;
  --bad:#b3261e; --warn:#9a5b13; --me:#f0f0f3; --me-fg:#1c1c1e; --codebg:rgba(0,0,0,.055);
  --switch-off:#e9e9ea;
  --shell:#1c1c1e; --shell-fg:#e5e5ea; --shell-cmd:#7ee2a8; --shell-bad:#ff8a8a;
  --mono: ui-monospace, Menlo, monospace; --sans: -apple-system, system-ui, 'PingFang SC', sans-serif;
  --t-body:1rem; --t-small:0.8125rem; --t-tiny:0.75rem;
  --r-bubble:18px; --r-card:16px; --r-chip:999px; --group-bg:#f2f2f7; --group-row:#ffffff;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme=light]) {
    --bg:#000000; --surface:#1c1c1e; --surface-2:#2c2c2e; --fg:#f2f2f7; --fg-2:#d1d1d6; --dim:#98989f;
    --line:rgba(235,235,245,.14); --link:#6aa2ff; --me:#2c2c2e; --me-fg:#f2f2f7; --codebg:rgba(255,255,255,.08);
    --shell:#111113; --bad:#ff6b6b; --warn:#c2741c; --group-bg:#000000; --group-row:#1c1c1e;
    --accent-text:#d97757; --switch-off:#39393d;
  }
}
:root[data-theme=dark] {
  --bg:#000000; --surface:#1c1c1e; --surface-2:#2c2c2e; --fg:#f2f2f7; --fg-2:#d1d1d6; --dim:#98989f;
  --line:rgba(235,235,245,.14); --link:#6aa2ff; --me:#2c2c2e; --me-fg:#f2f2f7; --codebg:rgba(255,255,255,.08);
  --shell:#111113; --bad:#ff6b6b; --warn:#c2741c; --group-bg:#000000; --group-row:#1c1c1e;
  --accent-text:#d97757; --switch-off:#39393d;
}
html { font-size:1rem; }
* { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
body { margin:0; padding:12px 16px 24px; background:var(--bg); color:var(--fg);
       font:var(--t-body)/1.55 var(--sans); -webkit-text-size-adjust:100%; word-wrap:break-word;
       -webkit-font-smoothing:antialiased; }
/* a readable line length on wide screens (iPad, Mac): about 90 characters, centred */
#chat { max-width:46rem; margin:0 auto; }
button:active { opacity:.55; }  /* a visible press, as native buttons have */


/* messages */
.row { display:flex; align-items:flex-start; gap:10px; margin:16px 0; }
.row.me { flex-direction:row-reverse; }
.avatar { flex:0 0 1.5rem; height:1.5rem; color:var(--accent); display:flex; align-items:center;
          justify-content:center; }
.avatar .ic { width:1.25rem; height:1.25rem; stroke-width:2; }
.row.me .avatar { display:none; }
@media (max-width:500px) { .row.c .avatar { display:none; } .col { max-width:100% !important; } }
.bubble { background:var(--surface); border-radius:var(--r-bubble); padding:10px 14px; min-width:0;
          max-width:80%; }
.row.me .bubble { background:var(--me); color:var(--me-fg); white-space:pre-wrap; border-radius:20px; }
/* Claude's answers are plain text on the page, as in the Claude app: full width, no box */
.col > .bubble.text { background:none; border:0; padding:0; display:block; border-radius:0; }
.bubble .thumbs { display:flex; flex-wrap:wrap; gap:6px; margin:2px 0 8px; }
.bubble .thumbs img { max-width:220px; max-height:220px; border-radius:12px; object-fit:cover; display:block; }
.bubble .attach { display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; white-space:normal; }
.bubble .attach span { font-size:var(--t-tiny); background:color-mix(in srgb, currentColor 10%, transparent); border-radius:var(--r-chip);
                       padding:2px 9px; }
.col { flex:1 1 auto; min-width:0; max-width:calc(100% - 42px); }
.col > .bubble { max-width:100%; display:inline-block; }
.col > * + * { margin-top:8px; }

/* Markdown in replies */
.text > :first-child { margin-top:0; } .text > :last-child { margin-bottom:0; }
.text h1, .text h2, .text h3, .text h4 { margin:16px 0 6px; line-height:1.3; font-weight:600; }
.text h1 { font-size:1.3em; } .text h2 { font-size:1.2em; } .text h3 { font-size:1.05em; } .text h4 { font-size:1em; }
.text p { margin:8px 0; }
.text ul, .text ol, .card ul, .card ol { padding-left:1.4em; margin:8px 0; }
.text li + li { margin-top:4px; }
.text table { border-collapse:collapse; margin:10px 0; display:block; overflow-x:auto; font-size:var(--t-small); }
.text th, .text td { border:0.5px solid var(--line); padding:6px 10px; text-align:left; min-width:5em; }  /* the table scrolls rather than squeezing CJK to a character per line */
.text th { background:var(--surface-2); font-weight:600; }
.text blockquote { margin:8px 0; padding:2px 0 2px 12px; border-left:3px solid var(--line); color:var(--fg-2); }
.text a { color:var(--link); text-decoration:none; }
.text hr { border:0; border-top:0.5px solid var(--line); margin:14px 0; }
code { font:0.85em var(--mono); background:var(--codebg); padding:.1em .35em; border-radius:5px; }
pre { margin:8px 0; overflow-x:auto; }
.codehilite { background:var(--codebg) !important; border-radius:12px; padding:10px 12px; font-size:var(--t-small); line-height:1.5; }
.codehilite pre { margin:0; } .codehilite code, pre code { background:none; padding:0; font-size:1em; }

/* thinking */
.thinking { font-size:var(--t-small); color:var(--dim); }
.thinking summary { display:flex; align-items:center; gap:6px; cursor:pointer; list-style:none; }
.thinking summary::-webkit-details-marker { display:none; }
.thinking summary .ic { flex:none; color:var(--accent); }
.thinking.live summary .ic, .row.c:has(> .col > .thinking.live:first-child) > .avatar .ic { animation:spin 2s linear infinite; }
@media (min-width:501px) { .col > .thinking:first-child summary .ic { display:none; } }  /* the avatar stands beside it */
@keyframes spin { to { transform:rotate(360deg); } }
.thinking .what { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.thinking .secs { flex:none; font-variant-numeric:tabular-nums; }
.thinking:not(.live) .secs { display:none; }
.thinking summary::after { content:''; flex:none; width:5px; height:5px; border:solid currentColor;
                           border-width:0 1.5px 1.5px 0; transform:rotate(-45deg); }
.thinking details[open] > summary::after { transform:rotate(45deg); }
.thinking div { white-space:pre-wrap; margin-top:6px; padding-left:10px; border-left:2px solid var(--line); }

/* tool calls */
.card { background:var(--surface); border:0; border-radius:var(--r-card); padding:10px 14px; font-size:var(--t-small); }
.col > .card + .card { margin-top:4px; }
.card:has(.ask) { box-shadow:inset 0 0 0 1px color-mix(in srgb, var(--accent) 45%, transparent); }
.card .head { display:flex; gap:8px; align-items:baseline; }
.card .icon { flex:none; color:var(--dim); align-self:center; display:flex; }
/* line icons (icons.py): drawn in the surrounding text colour */
.ic { width:1.1em; height:1.1em; fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round;
      stroke-linejoin:round; vertical-align:-0.18em; flex:none; }
.card .name { font:500 var(--t-small) var(--sans); color:var(--fg); flex:none; }
.card .target { font:var(--t-small) var(--mono); color:var(--dim); overflow:hidden; text-overflow:ellipsis;
                white-space:nowrap; min-width:0; }
.card .meta { color:var(--dim); font-size:var(--t-tiny); margin-left:auto; flex:none; }
.card .bar { height:2px; background:var(--line); border-radius:2px; margin-top:8px; overflow:hidden;
             animation:appear 0s .4s both; }
@keyframes appear { from { height:0; margin-top:0; opacity:0; } to { height:2px; margin-top:8px; opacity:1; } }
.card .bar div { height:100%; width:30%; background:var(--accent); animation:slide 1.1s infinite ease-in-out; }
@keyframes slide { 0% { margin-left:-30%; } 100% { margin-left:100%; } }
.card.summary { margin:12px 0; } .card.summary details { margin-top:0; }
.card details { margin-top:8px; }
.card summary { list-style:none; display:flex; align-items:center; gap:6px; }
.card summary::-webkit-details-marker { display:none; }
.card summary::before { content:''; width:5px; height:5px; border:solid currentColor; border-width:0 1.5px 1.5px 0;
                        transform:rotate(-45deg); transition:transform .15s; margin:0 2px; }
.card details[open] > summary::before { transform:rotate(45deg); } .card summary { color:var(--dim); font-size:var(--t-small); cursor:pointer; }
.card pre.out { font:var(--t-tiny)/1.5 var(--mono); white-space:pre-wrap; margin:8px 0 0; color:var(--fg-2); }
/* what a tool wrote or returned scrolls in its own small window; nothing fills the chat */
.card pre, .card .diff { max-height:16em; overflow:auto; -webkit-overflow-scrolling:touch; }
/* tool calls in a row fold into one line, as in Claude Code */
.tools { margin:4px 0; }
.tools > details > summary { list-style:none; display:inline-flex; align-items:center; gap:6px; cursor:pointer;
                             color:var(--dim); font-size:var(--t-small); padding:4px 0; }
.tools > details > summary::-webkit-details-marker { display:none; }
.tools > details > summary::after { content:''; width:5px; height:5px; border:solid currentColor;
                                    border-width:0 1.5px 1.5px 0; transform:rotate(-45deg); }
.tools > details[open] > summary::after { transform:rotate(45deg); }
/* what ran in a row: one rounded box with lines between its rows */
.tools > details > div { border:0.5px solid var(--line); border-radius:var(--r-card); overflow:hidden; margin-top:2px; }
.tools > details > div:empty { display:none; }
.tools .card { background:none; border-radius:0; }
.col > .tools .card + .card, .tools .card + .card { margin-top:0; border-top:0.5px solid var(--line); }
.tools .thinking { margin:0; padding:10px 14px; }
.tools .thinking + .card, .tools .card + .thinking { border-top:0.5px solid var(--line); }
.card .sub { font:var(--t-tiny) var(--mono); color:var(--dim); margin-top:4px; }
.diff { font:var(--t-tiny)/1.55 var(--mono); white-space:pre; overflow-x:auto; margin-top:8px;
        border-radius:8px; background:var(--codebg); padding:6px 0; display:grid; }  /* grid: every line as wide as the longest, so tints reach the end when scrolled */
.diff span { padding:0 12px; }
/* changed lines keep the normal text colour on a tint, with a coloured edge: easy to read in both themes */
.diff .add { color:var(--fg); background:rgba(46,160,67,.16); box-shadow:inset 3px 0 #2ea043; display:block; }
.diff .del { color:var(--fg); background:rgba(248,81,73,.16); box-shadow:inset 3px 0 #f85149; display:block; }
.diff .hunk { color:var(--link); display:block; } .diff .ctx { color:var(--dim); display:block; }
.plan .plan-title { font-weight:650; font-size:var(--t-body); margin-bottom:6px; }
.plan .text { font-size:var(--t-body); }
.err { color:var(--bad); margin-top:6px; } .denied { color:var(--warn); margin-top:6px; }

/* questions on cards: one filled primary button, quiet secondary ones */
.ask { margin-top:12px; display:flex; gap:8px; flex-wrap:wrap; }
.ask button { font:600 var(--t-small) var(--sans); border:0; border-radius:var(--r-chip); padding:9px 18px;
              min-height:44px; background:var(--surface-2); color:var(--fg); }
.ask .yes { background:var(--accent-fill); color:var(--accent-fg); }
.ask .no { color:var(--bad); }

/* notes from pycoder: short ones as a centred line, long ones (reports) as a readable card */
.notice { text-align:center; margin:12px auto; max-width:92%; }
.notice span { display:inline-block; font-size:var(--t-tiny); color:var(--dim); background:none;
               border-radius:var(--r-chip); padding:0; white-space:pre-wrap; text-align:left; }
.notice.warn span { color:var(--warn); }
.notice.error span { color:var(--bad); padding:3px 12px; border-radius:10px;
                     background:color-mix(in srgb, var(--bad) 12%, transparent); }
.notice.block { text-align:left; max-width:100%; }
.col > .notice { text-align:left; margin:2px 0 6px; max-width:100%; }
.notice.block span { display:block; border-radius:var(--r-card); padding:12px 14px; background:var(--surface);
                     border:0.5px solid var(--line); color:var(--fg-2); font:var(--t-small)/1.6 var(--mono);
                     white-space:pre-wrap; overflow-wrap:anywhere; }
.notice.warn.block span { color:var(--warn); border-color:color-mix(in srgb, var(--warn) 40%, transparent); }
.notice.error.block span { color:var(--bad); border-color:color-mix(in srgb, var(--bad) 40%, transparent);
                           background:color-mix(in srgb, var(--bad) 8%, var(--surface)); }
/* the session pane: context, tasks, background tasks, outputs */
.ps .t { display:flex; gap:8px; align-items:center; color:var(--fg); line-height:1.7; font-size:var(--t-small); }
.ps .t .ic { flex:none; width:1.25em; height:1.25em; }
.ps .t.completed { color:var(--dim); }
.ps { margin:4px 0 20px; }
.ps h3 { font:600 var(--t-tiny)/1.4 var(--sans); color:var(--dim); margin:0 0 6px 2px; }
.ps .none { color:var(--dim); font-size:var(--t-small); margin-left:2px; }
.ps .box { background:var(--surface); border-radius:var(--r-card); padding:10px 12px; font-size:var(--t-small); }
.ps .box + .box { margin-top:6px; }
.ps summary { cursor:pointer; list-style:none; } .ps summary::-webkit-details-marker { display:none; }
.ps .line { display:flex; align-items:center; gap:8px; min-height:24px; }
.ps .line .name { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--fg); }
.ps .line b { font-weight:600; color:var(--fg); }
.ps .num { color:var(--dim); font-variant-numeric:tabular-nums; white-space:nowrap; }
.ps .now { color:var(--dim); font-size:var(--t-tiny); margin-top:2px; overflow-wrap:anywhere; }
.ps pre { font:var(--t-tiny)/1.5 var(--mono); white-space:pre-wrap; overflow-wrap:anywhere; margin:8px 0 0; color:var(--fg-2); }
.ps button { font:600 var(--t-tiny) var(--sans); border:0; border-radius:var(--r-chip); padding:6px 12px; min-height:30px;
             background:var(--surface-2); color:var(--bad); }
.crumbs { font-size:var(--t-small); color:var(--dim); margin:0 0 10px; overflow-wrap:anywhere; }
.crumbs a { color:var(--link); cursor:pointer; } .crumbs b { color:var(--fg); font-weight:600; }
.crumbs i { font-style:normal; color:var(--dim); margin:0 2px; }
.ps .how { flex:none; font-size:var(--t-tiny); color:var(--dim); }
.ps .how.new, .ps .how.changed { color:var(--accent); } .ps .how.deleted { color:var(--bad); }
.fv .title { display:flex; flex-wrap:wrap; gap:8px; align-items:baseline; margin:0 0 10px; }
.fv .title b { color:var(--fg); overflow-wrap:anywhere; } .fv .title .num { font-size:var(--t-tiny); }
.fv .seg { display:inline-flex; background:var(--surface-2); border-radius:var(--r-chip); padding:2px; margin:0 0 10px; }
.fv .seg a { font-size:var(--t-tiny); padding:5px 14px; border-radius:var(--r-chip); color:var(--fg-2); cursor:pointer; }
.fv .seg a.on { background:var(--bg); color:var(--fg); font-weight:600; }
.fv .source { overflow-x:auto; -webkit-overflow-scrolling:touch; border-radius:12px; background:var(--codebg); }
.fv .source .codehilite { display:table; min-width:100%; box-sizing:border-box; background:none !important; border-radius:0; padding:0 12px; font-size:var(--t-tiny); }
.fv .source .codehilite:first-child { padding-top:10px; } .fv .source .codehilite:last-child { padding-bottom:10px; }
.fv .source .codehilite pre { font:inherit; font-family:var(--mono); white-space:pre; margin:0; color:inherit; overflow-wrap:normal; }
.fv .codehilite span.linenos { color:var(--dim); background:none; padding:0 12px 0 0; -webkit-user-select:none; user-select:none; }
.fv .source .diff { display:table; min-width:100%; border-radius:0; background:none; overflow:visible; }
.fv .source .diff span { display:block; white-space:pre; }
.fv .source .none { background:var(--bg); }
#more { height:1px; }
.fv button.wide { color:var(--fg); margin-top:10px; }
.ps h3 .clear { float:right; color:var(--fg-2); margin-top:-6px; }
.ps .meter { flex:1; height:6px; border-radius:3px; background:var(--surface-2); overflow:hidden; }
.ps .meter i { display:block; height:100%; background:var(--accent); }
.ps .file { display:flex; gap:10px; align-items:center; padding:8px 12px; background:var(--surface); cursor:pointer; }
.ps .file:first-of-type { border-radius:var(--r-card) var(--r-card) 0 0; }
.ps .file:last-of-type { border-radius:0 0 var(--r-card) var(--r-card); }
.ps .file:only-of-type { border-radius:var(--r-card); }
.ps .file + .file { border-top:0.5px solid var(--line); }
.ps .file .icon { flex:none; color:var(--dim); width:1rem; height:1rem; }
.ps .file .what { flex:1; min-width:0; }
.ps .file .name { color:var(--fg); font-size:var(--t-small); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.ps .file .num { font-size:var(--t-tiny); }
/* waiting for the first word of a reply: a pulsing dot where it will appear */
html.busy #chat > .row:last-child > .col:empty::before { content:''; display:block; width:.5rem; height:.5rem;
  margin-top:.55rem; border-radius:50%; background:var(--accent); animation:pulse 1.2s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity:.25; transform:scale(.8); } 50% { opacity:1; transform:scale(1); } }
.time { text-align:center; margin:20px 0 6px; font-size:var(--t-tiny); color:var(--dim); font-weight:500; }
.footer { color:var(--dim); font-size:var(--t-tiny); padding-left:0; display:flex; align-items:center;
          gap:8px; }
.actions { display:inline-flex; gap:2px; }
.actions a { display:inline-flex; width:28px; height:28px; align-items:center; justify-content:center;
             color:var(--dim); border-radius:8px; text-decoration:none; }
.actions a:hover, .actions a:active { background:var(--surface-2); }
.actions a.on { color:var(--accent); }
.actions a.words { width:auto; padding:0 8px; font-size:var(--t-small); }
.row.queued .bubble { opacity:.6; }
.actions .ic { width:16px; height:16px; }
.request-actions { display:flex; justify-content:flex-end; margin:-6px 0 2px; }
.chapter { display:flex; align-items:center; gap:10px; color:var(--dim); font-size:var(--t-tiny);
           margin:18px 0 8px; }
.chapter::before, .chapter::after { content:''; flex:1; border-top:1px solid var(--line); }

/* ! commands */
.shell { background:var(--shell); color:var(--shell-fg); border-radius:var(--r-card); padding:10px 14px; margin:12px 0;
         font:var(--t-small)/1.55 var(--mono); }
.shell .cmd { color:var(--shell-cmd); } .shell.failed pre { color:var(--shell-bad); }
.shell pre { margin:4px 0 0; white-space:pre-wrap; } .shell pre:empty { display:none; }

/* the session header */
.header { display:flex; gap:14px; align-items:center; margin:4px 0 20px; padding:14px 16px; background:var(--surface);
          border:0.5px solid var(--line); border-radius:var(--r-card); font-size:var(--t-small); color:var(--dim);
          line-height:1.6; }
.header b { color:var(--fg); font-size:var(--t-body); font-weight:650; }
.header .logo { flex:none; width:2.5rem; height:2.5rem; border-radius:12px; background:var(--accent-fill);
                color:var(--accent-fg); font:600 1.375rem/2.5rem var(--sans); text-align:center; }

/* /context: like iPhone Storage in Settings */
.context { background:var(--surface); border:0.5px solid var(--line); border-radius:var(--r-card);
           padding:16px 16px 6px; margin:12px 0; }
.context .head { display:flex; align-items:baseline; gap:8px; flex-wrap:wrap; }
.context .used { font:700 1.6rem/1.1 var(--sans); letter-spacing:-0.02em; color:var(--fg); }
.context .of { color:var(--dim); font-size:var(--t-small); }
.context .sub { color:var(--dim); font-size:var(--t-tiny); margin-top:2px; }
.context .bar { display:flex; height:10px; border-radius:5px; overflow:hidden; margin:14px 0 10px; gap:1.5px;
                background:var(--surface-2); }
.context .bar i { display:block; min-width:3px; }
.context i.free { background:var(--surface-2); }
.context i.buffer { background:repeating-linear-gradient(135deg, var(--line) 0 3px, transparent 3px 6px); }
.context .part { display:flex; align-items:center; gap:10px; padding:9px 0; font-size:var(--t-small);
                 border-top:0.5px solid var(--line); }
.context .part i { width:10px; height:10px; border-radius:3px; flex:none; }
.context .part i.free { box-shadow:inset 0 0 0 1px var(--line); }
.context .part .name { flex:1; color:var(--fg); }
.context .part .num { color:var(--fg-2); font-variant-numeric:tabular-nums; min-width:56px; text-align:right; }
.context .part .pct { color:var(--dim); font-variant-numeric:tabular-nums; min-width:48px; text-align:right; }

/* /config: an iOS-style sheet with a navigation bar, a segmented control and grouped rows */
#settings { position:fixed; inset:0; z-index:20; background:rgba(0,0,0,.32); display:flex; align-items:flex-end;
            justify-content:center; }
#settings .sheet { background:var(--group-bg); width:100%; max-width:620px; height:88vh; display:flex; flex-direction:column;
                   border-radius:16px 16px 0 0; padding:10px 16px env(safe-area-inset-bottom); box-shadow:0 -8px 30px rgba(0,0,0,.18); }
#settings .top { flex:none; display:flex; gap:10px; align-items:center; margin-bottom:12px; }
#settings .top > button { flex:none; border:0; background:none; padding:8px 4px; min-height:44px; font:var(--t-body) var(--sans); }
#settings .cancel { color:var(--fg); } #settings .save { color:var(--accent-text); font-weight:650 !important; }
#settings .tabs { flex:1; display:flex; gap:2px; background:var(--surface-2); border-radius:9px; padding:2px; }
#settings .tab { flex:1; border:0; border-radius:7px; padding:6px 4px; background:none; color:var(--fg);
                 font:500 var(--t-small) var(--sans); }
#settings .tab.on { background:var(--surface); box-shadow:0 1px 3px rgba(0,0,0,.12); font-weight:600; }
#settings .body { flex:1 1 auto; min-height:0; overflow-y:auto; -webkit-overflow-scrolling:touch;
                  overscroll-behavior:contain; padding-bottom:28px; }
#settings .page { background:var(--group-row); border-radius:var(--r-card); overflow:hidden; }
/* iOS rows: the name on the left, the value on the right; help under them, a slider across */
#settings .field { padding:10px 16px; border-bottom:0.5px solid var(--line); display:grid;
                   grid-template-columns:1fr auto; column-gap:12px; align-items:center; min-height:44px; }
#settings .field > .label { grid-area:1/1; } #settings .field > .help { grid-area:2/1/3/3; }
#settings .field > input[type=range] { grid-column:1/-1; }
#settings .field:last-child { border-bottom:0; }
#settings .label { display:flex; justify-content:space-between; align-items:center; font-weight:500; }
#settings .label span + span { color:var(--dim); font-variant-numeric:tabular-nums; }
#settings .help { color:var(--dim); font-size:var(--t-tiny); margin-top:2px; }
#settings select { grid-area:1/2; -webkit-appearance:none; appearance:none; width:auto; margin:0; border:0;
                   color:var(--dim); font:var(--t-body) var(--sans); text-align:right; text-align-last:right;
                   padding:4px 16px 4px 0; min-height:36px;
                   /* the up-and-down chevron of an iOS menu: says the value is a choice */
                   background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='14'%3E%3Cpath d='M2 5l3-3 3 3M2 9l3 3 3-3' fill='none' stroke='%238e8e93' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") no-repeat right center; }
#settings input[type=range] { width:100%; margin-top:10px; accent-color:var(--accent); }
/* on/off as an iOS switch: a track with a round knob (drawn as a gradient, so no extra markup) */
#settings input[type=checkbox] { -webkit-appearance:none; appearance:none; flex:none; width:51px; height:31px;
  margin:0; border-radius:999px; cursor:pointer; transition:background-color .2s, background-position .2s;
  background:radial-gradient(circle 13.5px, #fff 96%, transparent 100%) 2px 2px / 27px 27px no-repeat,
             var(--switch-off);
  box-shadow:inset 0 0 0 0.5px var(--line); }
#settings input[type=checkbox]:checked { background-color:var(--accent-fill); background-position:22px 2px; }
#settings table.info { width:100%; border-collapse:collapse; font-size:var(--t-small); }
#settings table.info th { text-align:left; color:var(--dim); font-weight:500; padding:10px 12px 10px 16px;
                          vertical-align:top; white-space:nowrap; border-bottom:0.5px solid var(--line); }
#settings table.info td { padding:10px 16px 10px 0; word-break:break-word; border-bottom:0.5px solid var(--line); }
#settings table.info tr:last-child th, #settings table.info tr:last-child td { border-bottom:0; }

.welcome { text-align:center; color:var(--dim); margin-top:22vh; }
.welcome b { display:block; font-size:1.375rem; color:var(--fg); margin-bottom:4px; }

/* less motion when the system asks for it: no sliding, pulsing or easing */
@media (prefers-reduced-motion: reduce) {
  *, ::before, ::after { transition:none !important; }
  .card .bar div, .thinking.live summary .ic, .row.c > .avatar .ic, html.busy #chat .col:empty::before { animation:none !important; }
  .card .bar div { width:100%; opacity:.5; }
}
"""

JS = r"""
var answers = {};
function nearBottom() { return window.innerHeight + window.scrollY >= document.body.scrollHeight - 80; }
// What the user is reading stays still. While a finger is down or the page is coasting, updates wait
// and are applied when it settles; away from the bottom, applying them keeps the line at the top of
// the screen where it is (WebKit has no scroll anchoring). New output is followed only from the
// bottom: scrolling away stops that, and scrolling back starts it again.
var follow = true, touching = false, settling = null, pending = [], ownScroll = false;
function scrollEnd() {
  ownScroll = true; window.scrollTo(0, document.body.scrollHeight);
  setTimeout(function() { ownScroll = false; }, 100);  // no event comes if it didn't move
}
function settle() {
  clearTimeout(settling);
  settling = setTimeout(function() {
    settling = null;
    if (touching) return;
    follow = nearBottom();
    flushUpdates();
  }, 180);
}
window.addEventListener('touchstart', function() { touching = true; clearTimeout(settling); settling = null; }, {passive: true});
window.addEventListener('touchend', function() { touching = false; settle(); }, {passive: true});
window.addEventListener('touchcancel', function() { touching = false; settle(); }, {passive: true});
window.addEventListener('scroll', function() { if (ownScroll) { ownScroll = false; } else { settle(); } }, {passive: true});
function readingPoint() {  // what is at the top of the screen: the element, and the row around it
  var e = document.elementFromPoint(window.innerWidth / 2, 12);
  var row = e && e.closest ? e.closest('.row') : null;
  return [e, row].filter(Boolean).map(function(x) { return {el: x, top: x.getBoundingClientRect().top}; });
}
function applyUpdates(fns) {
  var point = follow ? [] : readingPoint();
  fns.forEach(function(fn) { fn(); });
  if (follow) { scrollEnd(); return; }
  for (var i = 0; i < point.length; i++) {
    if (point[i].el.isConnected) {
      var moved = point[i].el.getBoundingClientRect().top - point[i].top;
      if (moved) { ownScroll = true; window.scrollBy(0, moved); }
      return;
    }
  }
}
function flushUpdates() { var fns = pending; pending = []; if (fns.length) applyUpdates(fns); }
function stick(fn) { if (touching || settling) { pending.push(fn); } else { applyUpdates([fn]); } }
function el(id) { return document.getElementById(id); }
function add(parentId, id, cls, html) {
  stick(function() {
    var w = el('welcome'); if (w) w.remove();
    var d = document.createElement('div'); d.id = id; d.className = cls; d.innerHTML = html;
    (el(parentId) || el('chat')).appendChild(d);
  });
}
function setChapter(turn, html) {
  stick(function() {
    var old = el('ch-' + turn), pin = el('pin-' + turn), request = el('req-' + turn);
    if (old) old.remove();
    if (pin) pin.classList.toggle('on', !!html);
    if (html && request) {
      var line = document.createElement('div');
      line.className = 'chapter'; line.id = 'ch-' + turn; line.innerHTML = html;
      request.parentNode.insertBefore(line, request);
    }
  });
}
function toChapter(turn) {
  if (!el('ch-' + turn) && typeof showEarlier === 'function') showEarlier();
  var line = el('ch-' + turn);
  if (line) { follow = false; line.scrollIntoView(); }
}
function setHtml(id, html) { stick(function() { var e = el(id); if (e) e.innerHTML = html; }); }
function appendText(id, text) { stick(function() { var e = el(id); if (e) e.insertAdjacentText('beforeend', text); }); }
// a reply streaming in: blocks that are done are added once, before the tail, which is replaced
function streamHtml(id, done, tail) {
  stick(function() {
    var e = el(id); if (!e) return;
    var t = el(id + '-tail');
    if (!t) { t = document.createElement('div'); t.id = id + '-tail'; t.style.display = 'contents'; e.appendChild(t); }
    if (done) t.insertAdjacentHTML('beforebegin', done);
    t.innerHTML = tail;
  });
}
// a resumed conversation shows its latest requests; the earlier ones wait here until asked for
var earlier = '';
function setEarlier(html) { earlier = html; }
function showEarlier() {
  var b = el('earlier'); if (!b) return;
  var below = document.body.scrollHeight - window.scrollY;  // keep what is on screen in place
  b.insertAdjacentHTML('beforebegin', earlier); b.remove(); earlier = '';
  window.scrollTo(0, document.body.scrollHeight - below);
}
function removeAfter(parentId, mark) {  // the children added after id number `mark`
  stick(function() {
    var p = el(parentId); if (!p) return;
    Array.prototype.slice.call(p.children).forEach(function(c) {
      var m = /(\d+)$/.exec(c.id || ''); if (m && +m[1] > mark) c.remove();
    });
  });
}
function remove(id) { stick(function() { var e = el(id); if (e) e.remove(); }); }
function setPane(html) {  // a pane's whole page, redrawn: what was unfolded stays unfolded
  var open = Array.from(document.querySelectorAll('details[open]')).map(function(d) { return d.id; });
  el('chat').innerHTML = html;
  open.forEach(function(id) { var d = el(id); if (d) d.open = true; });
}
function appendPane(html, more) {  // what a pane's page got to, from wantMore
  var source = document.querySelector('.source'); if (source) source.insertAdjacentHTML('beforeend', html);
  var mark = el('more'); if (!mark) return;
  if (more) delete mark.dataset.asked; else mark.remove();
}
function wantMore() {
  var mark = el('more');
  if (mark && !mark.dataset.asked && mark.getBoundingClientRect().top < window.innerHeight * 2) {
    mark.dataset.asked = '1'; act('more');
  }
}
setInterval(wantMore, 400);
var actions = [];
function act(value) { actions.push(value); }
function takeActions() { var a = actions; actions = []; return a.join('\n'); }
function endThinking(id, label) {
  stick(function() { var e = el(id); if (e) { e.classList.remove('live'); el(id + 'l').textContent = label; } });
}
setInterval(function() {  // the seconds of a thinking row, which go on when no text arrives
  document.querySelectorAll('.thinking.live .secs').forEach(function(e) {
    var s = Math.floor((Date.now() - e.dataset.since) / 1000);
    e.textContent = s < 60 ? s + 's' : Math.floor(s / 60) + 'm ' + String(s % 60).padStart(2, '0') + 's';
  });
}, 1000);
function closeDetails(id) { stick(function() { var e = el(id); if (e) e.open = false; }); }
function answer(id, value) { answers[id] = value; remove(id); }
function takeAnswer(id) { var a = answers[id] || ''; delete answers[id]; return a; }
function clearChat(html) { pending = []; el('chat').innerHTML = html || ''; earlier = ''; }
function toBottom() { clearTimeout(settling); settling = null; follow = true; flushUpdates(); scrollEnd(); }
function setMono(css) { document.documentElement.style.setProperty('--mono', css); }
function setAppearance(size, theme) {
  var root = document.documentElement; root.style.fontSize = size + 'px';
  if (theme === 'auto') root.removeAttribute('data-theme'); else root.setAttribute('data-theme', theme);
}
function showSettings(html) {
  remove('settings'); var d = document.createElement('div'); d.id = 'settings'; d.innerHTML = html;
  document.body.appendChild(d);
  document.body.style.overflow = 'hidden';  // scrolling goes to the sheet, not the chat behind it
}
function settingsValues() {
  var out = {};
  document.querySelectorAll('#settings [data-name]').forEach(function(e) {
    out[e.dataset.name] = e.type === 'checkbox' ? e.checked : (e.type === 'range' ? parseInt(e.value, 10) : e.value);
  });
  return out;
}
function showTab(n) {
  document.querySelectorAll('#settings .page').forEach(function(p, i) { p.style.display = i == n ? '' : 'none'; });
  document.querySelectorAll('#settings .tab').forEach(function(t, i) { t.classList.toggle('on', i == n); });
}
function closeSettings(save) {
  answers['settings'] = save ? JSON.stringify(settingsValues()) : 'cancel';
  remove('settings'); document.body.style.overflow = '';
}
"""

WELCOME = '<div class="welcome" id="welcome"><b>pycoder</b>Ask for code, attach a screenshot with +, or type / for commands</div>'


def page() -> str:
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover">'
        f'<style>{CSS}{_code_css()}</style></head><body>'
        f'<div id="chat">{WELCOME}</div><script>{JS}</script></body></html>'
    )
