"""MarketMind visual identity: a compact, vibrant "rainbow AI" console.

Palette  space #090818 · glass #15132D · rainbow red #FF5E7E · orange #FF9F43 · yellow #FFD93D · green #3DDC97
         · sky #2EC5FF · violet #8B6CFF · pink #FF5FD2
Type     Sora (display) + DM Sans (body) + JetBrains Mono (ids)
Epistemic colours still carry meaning: fact=green, inference=violet, recommendation=sky, uncertainty=yellow.
"""
import html
from pathlib import Path

E = html.escape
RAINBOW = "linear-gradient(90deg,#FF5E7E,#FF9F43,#FFD93D,#3DDC97,#2EC5FF,#8B6CFF,#FF5FD2)"
LOGO_PATH = Path(__file__).resolve().parents[2] / "assets" / "agent_logo.svg"
ICON_PATH = Path(__file__).resolve().parents[2] / "assets" / "agent_icon.png"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@500;700;800&family=DM+Sans:wght@400;500;700&family=JetBrains+Mono:wght@500&display=swap');
:root{--space:#090818;--glass:#15132D;--glass2:#1C1940;--line:#2C2860;--text:#F2F0FF;--muted:#A9A5D6;
--red:#FF5E7E;--orange:#FF9F43;--yellow:#FFD93D;--green:#3DDC97;--sky:#2EC5FF;--violet:#8B6CFF;--pink:#FF5FD2;
--rainbow:linear-gradient(90deg,#FF5E7E,#FF9F43,#FFD93D,#3DDC97,#2EC5FF,#8B6CFF,#FF5FD2);}
html,body,[class*="css"],.stMarkdown,.stTextInput,.stTextArea,.stSelectbox,button{font-family:'DM Sans',system-ui,sans-serif;}
h1,h2,h3,h4{font-family:'Sora','DM Sans',sans-serif!important;letter-spacing:-.015em;}
.stApp{color:var(--text);background:
  radial-gradient(900px 420px at 92% -8%,rgba(255,95,210,.16),transparent 60%),
  radial-gradient(800px 420px at -8% 10%,rgba(46,197,255,.14),transparent 60%),
  radial-gradient(700px 420px at 50% 115%,rgba(255,217,61,.08),transparent 60%),var(--space)!important;background-attachment:fixed!important}
.stApp::before{content:"";position:fixed;inset:0 0 auto 0;height:3px;background:var(--rainbow);background-size:200% 100%;
  animation:mm-flow 8s linear infinite;z-index:999991}
[data-testid="stHeader"]{background:rgba(9,8,24,.6)!important;backdrop-filter:blur(10px)}
section[data-testid="stSidebar"]{background:linear-gradient(180deg,#100E26,#090818)!important;border-right:1px solid var(--line)}
section[data-testid="stSidebar"] .block-container,section[data-testid="stSidebar"] [data-testid="stSidebarContent"]{padding-top:.4rem}
.block-container{padding-top:1.2rem;padding-bottom:1.5rem;max-width:1280px;}
.stApp h2{font-size:1.25rem}.stApp h3{font-size:1.05rem;margin-top:.4rem}
[data-testid="stVerticalBlock"]{gap:.6rem}

/* ---------- hero ---------- */
.mm-hero{position:relative;display:grid;grid-template-columns:auto 1fr auto;gap:18px;align-items:center;padding:16px 20px;border-radius:18px;
  background:linear-gradient(135deg,rgba(139,108,255,.14),rgba(46,197,255,.06) 50%,rgba(255,95,210,.10));margin-bottom:10px;isolation:isolate}
.mm-hero::before{content:"";position:absolute;inset:0;border-radius:18px;padding:1.5px;background:var(--rainbow);background-size:200% 100%;
  animation:mm-flow 10s linear infinite;-webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);
  -webkit-mask-composite:xor;mask-composite:exclude;z-index:-1}
.mm-hero .agent{width:78px;height:78px;filter:drop-shadow(0 6px 18px rgba(139,108,255,.45));animation:mm-float 5s ease-in-out infinite}
.mm-hero h1{font-size:2.05rem;line-height:1.05;margin:0 0 .25rem;font-weight:800;padding:0;
  background:var(--rainbow);background-size:200% 100%;-webkit-background-clip:text;background-clip:text;color:transparent;animation:mm-flow 12s linear infinite}
.mm-hero p{color:var(--muted);font-size:.93rem;max-width:68ch;margin:0;line-height:1.45}
.mm-hero .tags{margin-top:8px;display:flex;flex-wrap:wrap;gap:6px;}
.mm-tag{font-size:.72rem;padding:3px 9px;border-radius:999px;border:1px solid var(--line);background:rgba(255,255,255,.04);color:var(--text);white-space:nowrap}
.mm-ring{--p:0;width:74px;height:74px;border-radius:50%;display:grid;place-items:center;
  background:conic-gradient(from 0deg,#FF5E7E,#FF9F43,#FFD93D,#3DDC97,#2EC5FF,#8B6CFF,#FF5FD2 calc(var(--p)*1%),#24204A 0);}
.mm-ring div{width:58px;height:58px;border-radius:50%;background:var(--space);display:grid;place-items:center;text-align:center;
  font-family:'Sora';font-weight:800;font-size:1rem;line-height:1}
.mm-ring small{display:block;font-family:'DM Sans';font-weight:500;font-size:.58rem;color:var(--muted);margin-top:2px}
@media (max-width:760px){.mm-hero{grid-template-columns:auto 1fr}.mm-ring{display:none}.mm-hero .agent{width:56px;height:56px}.mm-hero h1{font-size:1.6rem}}

/* ---------- stepper ---------- */
.mm-steps{display:flex;gap:4px;margin:2px 0 4px;overflow-x:auto;scrollbar-width:none}
.mm-step{flex:1;min-width:84px;padding:6px 8px;border-radius:10px;background:var(--glass);border:1px solid var(--line);
  font-size:.74rem;color:var(--muted);white-space:nowrap;text-align:center;font-weight:600}
.mm-step.done{color:var(--text);border-color:rgba(61,220,151,.45);background:rgba(61,220,151,.08)}
.mm-step.now{color:#fff;border-color:transparent;background:linear-gradient(var(--glass2),var(--glass2)) padding-box,var(--rainbow) border-box;
  border:1.5px solid transparent;box-shadow:0 0 18px -6px rgba(139,108,255,.8)}
.mm-bar{height:4px;border-radius:99px;background:#1E1B40;overflow:hidden;margin-bottom:10px}
.mm-bar i{display:block;height:100%;background:var(--rainbow);border-radius:99px;transition:width .5s}

/* ---------- stat chips ---------- */
.mm-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:8px;margin:2px 0 10px}
.mm-stat{position:relative;background:var(--glass);border:1px solid var(--line);border-radius:12px;padding:8px 12px;overflow:hidden}
.mm-stat::after{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--c,var(--violet))}
.mm-stat small{display:block;color:var(--muted);font-size:.7rem;text-transform:uppercase;letter-spacing:.05em}
.mm-stat b{font-family:'Sora';font-size:1.1rem}
.mm-stat em{font-style:normal;color:var(--muted);font-size:.72rem;margin-left:4px}

/* ---------- cards & badges ---------- */
.mm-card{background:linear-gradient(160deg,rgba(28,25,64,.9),rgba(21,19,45,.9));border:1px solid var(--line);border-radius:14px;padding:12px 14px;margin-bottom:8px;}
.mm-card h4{margin:0 0 6px;font-size:.95rem}
.mm-kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;}
.mm-kv div{background:rgba(255,255,255,.03);border-radius:10px;padding:8px 10px;border:1px solid var(--line)}
.mm-kv small{color:var(--muted);display:block;font-size:.7rem;text-transform:uppercase;letter-spacing:.04em}
.mm-kv span{font-weight:600;font-size:.9rem}
.badge{display:inline-block;padding:1px 8px;border-radius:999px;font-size:.7rem;font-weight:700;border:1px solid;margin-right:5px;white-space:nowrap}
.b-fact,.b-ok{color:var(--green);border-color:rgba(61,220,151,.5);background:rgba(61,220,151,.1)}
.b-inference{color:#B9A6FF;border-color:rgba(139,108,255,.6);background:rgba(139,108,255,.14)}
.b-recommendation{color:var(--sky);border-color:rgba(46,197,255,.5);background:rgba(46,197,255,.1)}
.b-uncertainty,.b-medium{color:var(--yellow);border-color:rgba(255,217,61,.5);background:rgba(255,217,61,.08)}
.b-high{color:var(--red);border-color:rgba(255,94,126,.5);background:rgba(255,94,126,.1)}
.b-low,.b-open{color:var(--muted);border-color:var(--line);background:rgba(255,255,255,.03)}
.verdict{padding:9px 14px;border-radius:12px;font-family:'Sora';font-weight:700;font-size:.92rem;margin-bottom:8px}
.v-pass{background:rgba(61,220,151,.1);border:1px solid rgba(61,220,151,.45);color:var(--green)}
.v-fail{background:rgba(255,94,126,.1);border:1px solid rgba(255,94,126,.5);color:var(--red)}
.v-warn{background:rgba(255,217,61,.08);border:1px solid rgba(255,217,61,.45);color:var(--yellow)}
.v-info{background:rgba(46,197,255,.08);border:1px solid rgba(46,197,255,.4);color:var(--sky)}
table.mm-matrix{border-collapse:separate;border-spacing:3px;width:100%;font-size:.78rem}
table.mm-matrix th{color:var(--muted);font-weight:600;text-align:left;padding:4px 6px}
table.mm-matrix td{background:var(--glass2);border-radius:8px;padding:6px 8px;vertical-align:top;border:1px solid var(--line)}
td.ne{color:#6E6A99;background:repeating-linear-gradient(45deg,#14122c,#14122c 6px,#1a1838 6px,#1a1838 12px)!important;font-style:italic}
td.cf{border-color:rgba(255,217,61,.6)!important}
.mm-wrap{overflow-x:auto}
.ev-line{padding:7px 10px;border-left:3px solid var(--c,var(--line));margin:5px 0;background:rgba(255,255,255,.025);border-radius:0 10px 10px 0;font-size:.88rem}
.mm-muted{color:var(--muted)}
.mm-id{font-family:'JetBrains Mono',monospace;font-size:.78rem;color:var(--sky)}
.mm-doc{background:var(--glass);border:1px solid var(--line);border-radius:12px;padding:8px 12px;margin-bottom:6px;font-size:.86rem}
.mm-doc b{font-family:'Sora'}
mark{background:rgba(255,217,61,.28);color:#FFF6CC;border-radius:3px;padding:0 2px}
.mm-foot{text-align:center;margin-top:1.4rem;font-size:.8rem;color:var(--muted)}
.mm-foot span{background:var(--rainbow);-webkit-background-clip:text;background-clip:text;color:transparent;font-weight:700}

/* ---------- streamlit widgets ---------- */
div[data-testid="stMetric"]{background:var(--glass);border:1px solid var(--line);border-radius:12px;padding:6px 12px}
div[data-testid="stMetricValue"]{font-size:1.25rem;font-family:'Sora'}
[data-testid="stExpander"] details{background:rgba(21,19,45,.7);border:1px solid var(--line)!important;border-radius:12px!important}
[data-testid="stExpander"] summary{padding:.45rem .8rem}
.stTabs [data-baseweb="tab-list"]{gap:3px;flex-wrap:wrap;background:var(--glass);padding:4px;border-radius:12px;border:1px solid var(--line)}
.stTabs [data-baseweb="tab"]{height:auto;background:transparent;border-radius:9px;padding:5px 11px;font-size:.84rem}
.stTabs [data-baseweb="tab"] p{font-size:.84rem}
.stTabs [aria-selected="true"]{background:linear-gradient(110deg,rgba(255,94,126,.35),rgba(139,108,255,.4),rgba(46,197,255,.35))!important}
.stTabs [data-baseweb="tab-highlight"],.stTabs [data-baseweb="tab-border"]{display:none}
.stButton>button,.stDownloadButton>button{border-radius:10px;font-weight:600;border:1px solid var(--line);background:var(--glass2);
  padding:.3rem .8rem;min-height:2.2rem;transition:transform .15s,box-shadow .15s}
.stButton>button:not(:disabled):hover,.stDownloadButton>button:not(:disabled):hover{border-color:var(--violet);transform:translateY(-1px);box-shadow:0 6px 18px -8px rgba(139,108,255,.8)}
.stButton>button[kind="primary"]{background:linear-gradient(100deg,#FF5E7E,#FF9F43 30%,#8B6CFF 70%,#2EC5FF);background-size:180% 100%;border:0;color:#fff;
  text-shadow:0 1px 2px rgba(0,0,0,.35);animation:mm-flow 6s linear infinite}
.stButton>button[kind="primary"]:disabled{filter:grayscale(.85) brightness(.6);animation:none}
.stButton>button:focus-visible{outline:2px solid var(--yellow);outline-offset:2px}
[data-baseweb="input"],[data-baseweb="textarea"],[data-baseweb="select"]>div{background:#100E26!important;border-color:var(--line)!important;border-radius:10px!important}
[data-testid="stAlert"]{border-radius:12px;padding:.1rem .2rem}
[data-testid="stProgress"] [role="progressbar"]>div>div>div{background:var(--rainbow)!important}
@keyframes mm-flow{0%{background-position:0% 50%}100%{background-position:200% 50%}}
@keyframes mm-float{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
</style>
"""


def agent_svg(size: int = 34, cls: str = "") -> str:
    """The MarketMind AI agent mark, inlined (gradient ids are unique per size to avoid clashes)."""
    raw = LOGO_PATH.read_text(encoding="utf-8")
    raw = raw[raw.index("<svg"):]
    sfx = f"_{size}"
    for gid in ("rb", "face", "eye", "spark"):
        raw = raw.replace(f'id="{gid}"', f'id="{gid}{sfx}"').replace(f"url(#{gid})", f"url(#{gid}{sfx})")
    raw = raw.replace('width="128" height="128"', f'width="{size}" height="{size}" class="{cls}" role="img" aria-label="MarketMind AI agent"', 1)
    return raw


LOGO = f"""<div style="display:flex;align-items:center;gap:10px;margin:0 0 8px">{agent_svg(40)}
<div><div style="font-family:Sora;font-weight:800;font-size:1.08rem;background:{RAINBOW};-webkit-background-clip:text;background-clip:text;color:transparent">MarketMind AI</div>
<div style="color:#A9A5D6;font-size:.72rem">🤖 Research agent · Verity Strategy Partners</div></div></div>"""

STAGES = [("🧭", "Scope"), ("🗺️", "Plan"), ("🔬", "Research"), ("🏁", "Compare"), ("🧠", "Synthesise"),
          ("🧪", "Check"), ("✅", "Approve")]
STAGE_INDEX = {"created": -1, "request_analyser": 0, "planner": 1, "researcher": 2, "comparison": 3, "synthesis": 4,
               "quality_control": 5, "report_generator": 5, "awaiting_approval": 6, "published": 7, "archived_rejected": 7}
EPISTEMIC = {"fact": "#3DDC97", "inference": "#8B6CFF", "recommendation": "#2EC5FF", "uncertainty": "#FFD93D"}


def progress_pct(stage: str) -> int:
    return round((STAGE_INDEX.get(stage, -1) + 1) / len(STAGES) * 100)


def hero_html(stage: str) -> str:
    pct = progress_pct(stage)
    tags = ["🔧 Hand-built agent loop", "📐 Strict schemas", "🧾 Evidence-bound claims", "🛡️ Injection-aware", "🧑‍⚖️ Human approval gate"]
    return (f'<div class="mm-hero">{agent_svg(78, "agent")}<div><h1>MarketMind AI</h1>'
            "<p>An autonomous business-research agent whose every claim can be checked: planned, gathered by tools, typed as "
            "fact or inference, audited by a quality checker, and published only when a named person approves.</p>"
            '<div class="tags">' + "".join(f'<span class="mm-tag">{t}</span>' for t in tags) + "</div></div>"
            f'<div class="mm-ring" style="--p:{pct}" title="Pipeline progress"><div>{pct}%<small>pipeline</small></div></div></div>')


def badge(kind: str, label: str | None = None) -> str:
    icons = {"fact": "🟢", "inference": "🟣", "recommendation": "🔵", "uncertainty": "🟡"}
    text = label or f"{icons.get(kind, '')} {kind}"
    return f'<span class="badge b-{E(kind)}">{E(text)}</span>'


def steps_html(stage: str) -> str:
    cur = STAGE_INDEX.get(stage, -1)
    out = []
    for i, (ic, name) in enumerate(STAGES):
        cls = "done" if i < cur else "now" if i == cur else ""
        mark = "✓ " if i < cur else ""
        out.append(f'<div class="mm-step {cls}" title="Step {i + 1} of {len(STAGES)}">{mark}{ic} {name}</div>')
    return ('<div class="mm-steps">' + "".join(out) + f'</div><div class="mm-bar"><i style="width:{progress_pct(stage)}%"></i></div>')


def stats_html(items: list[tuple[str, str, str, str]]) -> str:
    """items: (label, value, sub, colour)."""
    return '<div class="mm-stats">' + "".join(
        f'<div class="mm-stat" style="--c:{c}"><small>{E(l)}</small><b>{E(v)}</b>{f"<em>{E(s)}</em>" if s else ""}</div>'
        for l, v, s, c in items) + "</div>"


def matrix_html(m: dict) -> str:
    if not m or not m.get("cells"):
        return '<div class="mm-muted">No entities established yet.</div>'
    attrs = m["attributes"]
    h = ['<div class="mm-wrap"><table class="mm-matrix"><tr><th>Vendor</th>'] + [f"<th>{E(a.replace('_', ' '))}</th>" for a in attrs] + ["</tr>"]
    for ent, row in m["cells"].items():
        h.append(f"<tr><th>{E(ent)}</th>")
        for a in attrs:
            c = row.get(a, {"status": "NOT_ESTABLISHED", "values": []})
            if c["status"] == "NOT_ESTABLISHED":
                h.append('<td class="ne">not established</td>')
            else:
                v = c["values"][0]
                ids = ", ".join(x["evidence_id"] for x in c["values"])
                warn = "⚠️ conflicting · " if c["status"] == "conflicting" else ""
                h.append(f'<td class="{"cf" if warn else ""}">{warn}{E(v["claim"][:110])}<br><span class="mm-muted">[{E(ids)}]</span></td>')
        h.append("</tr>")
    h.append("</table></div>")
    return "".join(h)
