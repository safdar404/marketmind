"""MarketMind visual identity: a night-shift analyst console.

Palette  ink #0F0D24 · panel #1A1638 · violet #8B6CFF · cyan #2EE6D6 · magenta #FF5FA2 · amber #FFB547 · mint #3DDC97
Type     Sora (display) + DM Sans (body)
Epistemic colours carry meaning everywhere: fact=mint, inference=violet, recommendation=cyan, uncertainty=amber.
"""
import html

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700;800&family=DM+Sans:wght@400;500;700&display=swap');
:root{--ink:#0F0D24;--panel:#1A1638;--panel2:#221D48;--line:#332C66;--violet:#8B6CFF;--cyan:#2EE6D6;
--magenta:#FF5FA2;--amber:#FFB547;--mint:#3DDC97;--text:#ECEAFF;--muted:#A8A3D1;--red:#FF6B6B;}
html,body,[class*="css"],.stMarkdown,.stTextInput,.stTextArea,.stSelectbox,button{font-family:'DM Sans',system-ui,sans-serif;}
h1,h2,h3,h4{font-family:'Sora','DM Sans',sans-serif !important;letter-spacing:-.01em;}
.stApp{background:
  radial-gradient(1100px 500px at 85% -10%,rgba(139,108,255,.22),transparent 60%),
  radial-gradient(800px 400px at -10% 20%,rgba(46,230,214,.10),transparent 60%),
  radial-gradient(700px 500px at 60% 110%,rgba(255,95,162,.10),transparent 60%),var(--ink);}
section[data-testid="stSidebar"]{background:linear-gradient(180deg,#151231,#0F0D24);border-right:1px solid var(--line);}
.block-container{padding-top:1.6rem;max-width:1320px;}
.mm-hero{display:grid;grid-template-columns:1.25fr 1fr;gap:24px;align-items:center;padding:26px 30px;border-radius:22px;
  background:linear-gradient(135deg,rgba(139,108,255,.16),rgba(46,230,214,.06));border:1px solid var(--line);margin-bottom:14px;}
.mm-hero h1{font-size:2.9rem;line-height:1.02;margin:0 0 .4rem 0;font-weight:800;
  background:linear-gradient(90deg,#fff 0%,#CFC4FF 45%,var(--cyan) 100%);-webkit-background-clip:text;background-clip:text;color:transparent;}
.mm-hero p{color:var(--muted);font-size:1.05rem;max-width:56ch;margin:.2rem 0 0;}
.mm-hero .tags{margin-top:14px;display:flex;flex-wrap:wrap;gap:8px;}
.mm-tag{font-size:.8rem;padding:4px 10px;border-radius:999px;border:1px solid var(--line);background:rgba(255,255,255,.03);color:var(--text);}
@media (max-width:900px){.mm-hero{grid-template-columns:1fr}.mm-hero svg{display:none}}
.mm-steps{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0 14px;}
.mm-step{flex:1;min-width:110px;padding:8px 10px;border-radius:12px;background:var(--panel);border:1px solid var(--line);font-size:.82rem;color:var(--muted);}
.mm-step b{display:block;color:var(--text);font-family:'Sora';font-size:.9rem}
.mm-step.done{border-color:rgba(61,220,151,.5);background:rgba(61,220,151,.07)}
.mm-step.now{border-color:var(--violet);box-shadow:0 0 0 1px var(--violet) inset;background:rgba(139,108,255,.12)}
.mm-card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px 18px;margin-bottom:12px;}
.mm-card h4{margin:0 0 6px;font-size:1rem}
.mm-kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;}
.mm-kv div{background:var(--panel2);border-radius:12px;padding:10px 12px;border:1px solid var(--line)}
.mm-kv small{color:var(--muted);display:block;font-size:.75rem}
.mm-kv span{font-weight:600}
.badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:.74rem;font-weight:700;border:1px solid;margin-right:6px;white-space:nowrap}
.b-fact{color:var(--mint);border-color:rgba(61,220,151,.5);background:rgba(61,220,151,.1)}
.b-inference{color:#B9A6FF;border-color:rgba(139,108,255,.6);background:rgba(139,108,255,.14)}
.b-recommendation{color:var(--cyan);border-color:rgba(46,230,214,.5);background:rgba(46,230,214,.1)}
.b-uncertainty{color:var(--amber);border-color:rgba(255,181,71,.55);background:rgba(255,181,71,.1)}
.b-high{color:var(--red);border-color:rgba(255,107,107,.5);background:rgba(255,107,107,.1)}
.b-medium{color:var(--amber);border-color:rgba(255,181,71,.5);background:rgba(255,181,71,.08)}
.b-low{color:var(--muted);border-color:var(--line);background:rgba(255,255,255,.03)}
.b-ok{color:var(--mint);border-color:rgba(61,220,151,.5);background:rgba(61,220,151,.1)}
.b-open{color:var(--muted);border-color:var(--line)}
.verdict{padding:14px 18px;border-radius:14px;font-family:'Sora';font-weight:700;font-size:1.05rem;margin-bottom:10px}
.v-pass{background:rgba(61,220,151,.12);border:1px solid rgba(61,220,151,.5);color:var(--mint)}
.v-fail{background:rgba(255,107,107,.1);border:1px solid rgba(255,107,107,.5);color:var(--red)}
.v-warn{background:rgba(255,181,71,.1);border:1px solid rgba(255,181,71,.5);color:var(--amber)}
table.mm-matrix{border-collapse:separate;border-spacing:4px;width:100%;font-size:.8rem}
table.mm-matrix th{color:var(--muted);font-weight:600;text-align:left;padding:4px 6px}
table.mm-matrix td{background:var(--panel2);border-radius:8px;padding:6px 8px;vertical-align:top;border:1px solid var(--line)}
td.ne{color:#6E6A99;background:repeating-linear-gradient(45deg,#1b1838,#1b1838 6px,#201c43 6px,#201c43 12px)!important;font-style:italic}
td.cf{border-color:rgba(255,181,71,.6)!important}
.mm-wrap{overflow-x:auto}
.ev-line{padding:8px 10px;border-left:3px solid var(--line);margin:6px 0;background:rgba(255,255,255,.02);border-radius:0 10px 10px 0}
.mm-muted{color:var(--muted)}
div[data-testid="stMetric"]{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:10px 14px}
.stTabs [data-baseweb="tab-list"]{gap:4px;flex-wrap:wrap}
.stTabs [data-baseweb="tab"]{background:var(--panel);border-radius:10px 10px 0 0;padding:8px 14px}
.stTabs [aria-selected="true"]{background:linear-gradient(180deg,rgba(139,108,255,.35),rgba(139,108,255,.12))}
.stButton>button{border-radius:12px;font-weight:600;border:1px solid var(--line)}
.stButton>button[kind="primary"]{background:linear-gradient(90deg,var(--violet),#6F4CFF);border:0}
.stButton>button:focus-visible{outline:2px solid var(--cyan);outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
.pulse{animation:pulse 2.6s ease-in-out infinite;transform-origin:center}
@keyframes pulse{0%,100%{opacity:.55}50%{opacity:1}}
</style>
"""

HERO_SVG = """
<svg viewBox="0 0 420 240" width="100%" role="img" aria-label="Agent pipeline constellation">
 <defs>
  <linearGradient id="g1" x1="0" x2="1"><stop offset="0" stop-color="#8B6CFF"/><stop offset="1" stop-color="#2EE6D6"/></linearGradient>
  <radialGradient id="core"><stop offset="0" stop-color="#fff"/><stop offset=".35" stop-color="#B9A6FF"/><stop offset="1" stop-color="#8B6CFF" stop-opacity="0"/></radialGradient>
 </defs>
 <g stroke="url(#g1)" stroke-width="1.6" fill="none" opacity=".75">
  <path d="M40 60 C110 30,150 40,210 120"/><path d="M40 180 C110 210,150 200,210 120"/>
  <path d="M210 120 C260 70,300 60,370 50"/><path d="M210 120 C270 130,310 140,380 120"/>
  <path d="M210 120 C260 180,310 200,370 196"/><path d="M370 50 L380 120 L370 196" stroke-dasharray="4 5"/>
 </g>
 <circle class="pulse" cx="210" cy="120" r="46" fill="url(#core)"/>
 <circle cx="210" cy="120" r="9" fill="#fff"/>
 <g font-family="DM Sans" font-size="11" fill="#ECEAFF">
  <circle cx="40" cy="60" r="7" fill="#2EE6D6"/><text x="22" y="44">Request</text>
  <circle cx="40" cy="180" r="7" fill="#8B6CFF"/><text x="26" y="204">Plan</text>
  <circle cx="370" cy="50" r="7" fill="#3DDC97"/><text x="340" y="34">Facts</text>
  <circle cx="380" cy="120" r="7" fill="#B9A6FF"/><text x="338" y="106">Inference</text>
  <circle cx="370" cy="196" r="7" fill="#FFB547"/><text x="330" y="222">Uncertainty</text>
  <text x="186" y="176" fill="#A8A3D1">agent loop</text>
 </g>
</svg>
"""

LOGO = """<div style="display:flex;align-items:center;gap:10px;margin:2px 0 10px">
<svg width="34" height="34" viewBox="0 0 34 34"><defs><linearGradient id="lg" x1="0" x2="1"><stop offset="0" stop-color="#8B6CFF"/><stop offset="1" stop-color="#2EE6D6"/></linearGradient></defs>
<rect x="1" y="1" width="32" height="32" rx="10" fill="#1A1638" stroke="url(#lg)"/><circle cx="17" cy="17" r="4" fill="#fff"/>
<circle cx="8" cy="10" r="2.4" fill="#2EE6D6"/><circle cx="26" cy="10" r="2.4" fill="#3DDC97"/><circle cx="26" cy="24" r="2.4" fill="#FFB547"/><circle cx="8" cy="24" r="2.4" fill="#8B6CFF"/>
<path d="M8 10L17 17L26 10M8 24L17 17L26 24" stroke="url(#lg)" stroke-width="1.2" fill="none"/></svg>
<div><div style="font-family:Sora;font-weight:800;font-size:1.1rem">MarketMind AI</div>
<div style="color:#A8A3D1;font-size:.75rem">Verity Strategy Partners</div></div></div>"""

STAGES = [("🧭", "Scope"), ("🗺️", "Plan"), ("🔬", "Research"), ("🏁", "Compare"), ("🧠", "Synthesise"),
          ("🧪", "Check"), ("✅", "Approve")]
STAGE_INDEX = {"created": -1, "request_analyser": 0, "planner": 1, "researcher": 2, "comparison": 3, "synthesis": 4,
               "quality_control": 5, "report_generator": 5, "awaiting_approval": 6, "published": 7, "archived_rejected": 7}

E = html.escape


def badge(kind: str, label: str | None = None) -> str:
    icons = {"fact": "🟢", "inference": "🟣", "recommendation": "🔵", "uncertainty": "🟠"}
    text = label or f"{icons.get(kind, '')} {kind}"
    return f'<span class="badge b-{E(kind)}">{E(text)}</span>'


def steps_html(stage: str) -> str:
    cur = STAGE_INDEX.get(stage, -1)
    out = []
    for i, (ic, name) in enumerate(STAGES):
        cls = "done" if i < cur else "now" if i == cur else ""
        out.append(f'<div class="mm-step {cls}"><b>{ic} {name}</b>step {i + 1} of {len(STAGES)}</div>')
    return '<div class="mm-steps">' + "".join(out) + "</div>"


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
