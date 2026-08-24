"""Static site: index, one page per episode (player + show notes + full post copy), markdown copies."""
from __future__ import annotations
import html as H
import re, shutil
from pathlib import Path
from urllib.parse import urlparse
from .config import DOCS, PODCAST, SITE_URL, FEED_URL, SOURCES, ROOT
from .util import parse_iso, http_get, log, hms

# Brand family (matches the episode artwork): ink / cream / "book cloth" rust,
# plus one deep flat color per source.
CSS = """
:root{
  --bg:#f6f1e7;--bg2:#efe8da;--card:#fffdf7;--fg:#1c1a16;--muted:#6f675b;
  --line:#e4dcca;--code:#f0e9da;--accent:#cc785c;--link:#9a4a28;
  --research:#1f403b;--news:#7a3423;--blog:#2d3460;
  --ink:#1c1a16;--cream:#f4efe6;
  --radius:16px;
  --shadow:0 1px 2px rgba(28,26,22,.05),0 6px 20px rgba(28,26,22,.07);
  --shadow-lift:0 2px 4px rgba(28,26,22,.07),0 14px 34px rgba(28,26,22,.13);
}
@media(prefers-color-scheme:dark){
  :root{
    --bg:#161310;--bg2:#1c1814;--card:#211d17;--fg:#ede6d7;--muted:#a79d8b;
    --line:#352e26;--code:#2b261e;--accent:#cc785c;--link:#e69b76;
    --shadow:0 1px 2px rgba(0,0,0,.3),0 6px 20px rgba(0,0,0,.35);
    --shadow-lift:0 2px 4px rgba(0,0,0,.4),0 14px 34px rgba(0,0,0,.5);
  }
}
*{box-sizing:border-box}
[hidden]{display:none!important}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{margin:0;font:16px/1.6 "Space Grotesk",-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;background:var(--bg);color:var(--fg)}
img{max-width:100%}
a{color:var(--link)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
.wrap{max-width:1100px;margin:0 auto;padding:0 clamp(1rem,4vw,2rem)}

/* ---- hero (index) ---- */
.hero{background:var(--ink);color:var(--cream);position:relative;overflow:hidden}
.hero::before{content:"";position:absolute;inset:0;pointer-events:none;background:
  radial-gradient(640px 320px at 88% -12%,rgba(204,120,92,.38),transparent 62%),
  radial-gradient(560px 300px at -6% 112%,rgba(45,52,96,.55),transparent 60%),
  radial-gradient(420px 240px at 40% 130%,rgba(31,64,59,.4),transparent 65%)}
.hero .wrap{position:relative;display:grid;grid-template-columns:auto 1fr;gap:clamp(1.4rem,3.5vw,2.6rem);align-items:center;padding-top:clamp(2rem,5vw,3.4rem);padding-bottom:clamp(1.8rem,4.5vw,3rem)}
.hero .cover{width:clamp(128px,17vw,196px);aspect-ratio:1;border-radius:22px;display:block;
  box-shadow:0 16px 44px rgba(0,0,0,.5);border:1px solid rgba(244,239,230,.16)}
.hero .kicker{margin:0 0 .55rem;font-size:.76rem;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--accent)}
.hero h1{margin:0 0 .5rem;font-size:clamp(1.9rem,4.6vw,3.1rem);line-height:1.04;letter-spacing:-.025em;font-weight:700}
.hero .tag{margin:0;max-width:56ch;color:rgba(244,239,230,.78);font-size:clamp(.95rem,1.6vw,1.05rem)}
.sub-row{display:flex;flex-wrap:wrap;gap:.55rem;margin-top:1.25rem}
.btn{display:inline-flex;align-items:center;gap:.4rem;padding:.52rem 1rem;border-radius:999px;font-size:.88rem;font-weight:500;
  text-decoration:none;color:var(--cream);background:rgba(244,239,230,.08);border:1px solid rgba(244,239,230,.28);
  cursor:pointer;font-family:inherit;transition:background .18s ease,transform .18s ease}
.btn:hover{background:rgba(244,239,230,.18);transform:translateY(-1px)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--ink);font-weight:700}
.btn.primary:hover{background:#d8896d}
.feed-line{margin:1rem 0 0;font-size:.8rem;color:rgba(244,239,230,.62)}
.feed-line code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.78rem;
  background:rgba(244,239,230,.1);border:1px solid rgba(244,239,230,.14);padding:.14rem .45rem;border-radius:6px;word-break:break-all;color:rgba(244,239,230,.85)}
.feed-line a{color:rgba(244,239,230,.85)}

/* ---- top nav (inner pages) ---- */
.topnav{position:sticky;top:0;z-index:20;background:var(--bg);background:color-mix(in srgb,var(--bg) 86%,transparent);
  -webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}
.topnav .wrap{display:flex;align-items:center;justify-content:space-between;gap:1rem;padding-top:.72rem;padding-bottom:.72rem}
.brand{display:inline-flex;align-items:center;gap:.6rem;font-weight:700;letter-spacing:-.01em;text-decoration:none;color:inherit}
.brand img{width:30px;height:30px;border-radius:8px}
.topnav .back{font-size:.88rem;text-decoration:none;color:var(--muted)}
.topnav .back:hover{color:var(--link)}

/* ---- index sections ---- */
main{padding:0 0 4.5rem}
.section-head{display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap;margin:2.6rem 0 1.1rem}
.sec{margin:0;font-size:.82rem;font-weight:700;text-transform:uppercase;letter-spacing:.15em;color:var(--muted)}
.filter{display:flex;gap:.4rem;flex-wrap:wrap}
.filter button{font:inherit;font-size:.82rem;padding:.34rem .85rem;border-radius:999px;border:1px solid var(--line);
  background:var(--card);color:var(--muted);cursor:pointer;transition:all .15s ease}
.filter button:hover{border-color:var(--accent);color:var(--link)}
.filter button[aria-pressed="true"]{background:var(--fg);color:var(--bg);border-color:var(--fg)}
.idx-tools{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap}
.search{font:inherit;font-size:.85rem;padding:.38rem .95rem;border-radius:999px;border:1px solid var(--line);
  background:var(--card);color:var(--fg);min-width:200px}
.search::placeholder{color:var(--muted)}
.stats{margin:.3rem 0 0;font-size:.82rem;color:var(--muted)}
.no-results{color:var(--muted);font-size:.95rem;margin:1.2rem 0}

.badge{display:inline-block;font-size:.66rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;
  padding:.2rem .6rem;border-radius:999px;color:var(--cream);background:#555}
.badge.research{background:var(--research)}.badge.news{background:var(--news)}.badge.claude-blog{background:var(--blog)}
.meta{color:var(--muted);font-size:.82rem}

.feature{display:grid;grid-template-columns:minmax(220px,330px) 1fr;background:var(--card);border:1px solid var(--line);
  border-radius:var(--radius);overflow:hidden;box-shadow:var(--shadow)}
.feature-art{display:block;background:var(--bg2)}
.feature-art img{display:block;width:100%;height:100%;object-fit:cover;aspect-ratio:1}
.feature-body{padding:clamp(1.2rem,2.6vw,1.9rem);display:flex;flex-direction:column;justify-content:center;gap:.55rem;min-width:0}
.feature .row{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap}
.feature h2{margin:0;font-size:clamp(1.3rem,2.6vw,1.75rem);line-height:1.18;letter-spacing:-.015em}
.feature h2 a{color:inherit;text-decoration:none}
.feature h2 a:hover{color:var(--link)}
.feature .sub{margin:0;color:var(--muted);font-size:.95rem}
.feature audio{width:100%;margin:.35rem 0 0}
.feature .more{font-size:.86rem}

.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(252px,1fr));gap:1.3rem}
.card{display:flex;flex-direction:column;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  overflow:hidden;text-decoration:none;color:inherit;box-shadow:0 1px 2px rgba(28,26,22,.05);
  transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
.card:hover{transform:translateY(-4px);box-shadow:var(--shadow-lift);border-color:var(--accent)}
.card img{width:100%;aspect-ratio:1;object-fit:cover;display:block;background:var(--bg2)}
.card .body{padding:1rem 1.1rem 1.15rem;display:flex;flex-direction:column;gap:.42rem}
.card .row{display:flex;align-items:center;gap:.55rem;flex-wrap:wrap}
.card h3{margin:0;font-size:1.05rem;line-height:1.32;letter-spacing:-.01em}
.card .sub{margin:0;color:var(--muted);font-size:.86rem;line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}

/* ---- episode page ---- */
.ep-head{display:grid;grid-template-columns:minmax(230px,330px) 1fr;gap:clamp(1.5rem,3.5vw,2.6rem);align-items:start;margin:2.4rem 0 1.6rem}
.ep-art{width:100%;border-radius:var(--radius);display:block;box-shadow:var(--shadow-lift);border:1px solid var(--line)}
.ep-info .row{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;margin-bottom:.7rem}
h1.ep-title{margin:.1rem 0 .5rem;font-size:clamp(1.55rem,3.4vw,2.35rem);line-height:1.12;letter-spacing:-.022em}
.ep-sub{margin:0 0 .4rem;color:var(--muted);font-size:1.02rem}
.player{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:.95rem 1.05rem .8rem;box-shadow:var(--shadow);margin:1.1rem 0 .9rem}
.player .plabel{display:flex;justify-content:space-between;align-items:baseline;gap:1rem;margin:0 .1rem .45rem;
  font-size:.72rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.player .plabel .dur{letter-spacing:.02em}
audio{width:100%;display:block}

/* ---- custom player (progressive enhancement over the native <audio>) ---- */
.player.enhanced>audio{display:none}
.p-main{display:flex;align-items:center;gap:.9rem;margin-top:.2rem}
.p-play{flex:none;width:54px;height:54px;border-radius:50%;border:none;background:var(--accent);color:var(--ink);
  display:inline-flex;align-items:center;justify-content:center;cursor:pointer;padding:0;
  box-shadow:0 2px 8px rgba(204,120,92,.35);transition:transform .15s ease,background .15s ease}
.p-play:hover{background:#d8896d;transform:scale(1.06)}
.p-play svg{width:24px;height:24px;fill:currentColor;display:block}
.p-right{flex:1;min-width:0}
.p-bar{position:relative;height:24px;cursor:pointer;touch-action:none}
.p-bar::before{content:"";position:absolute;left:0;right:0;top:50%;height:6px;transform:translateY(-50%);border-radius:999px;background:var(--line)}
.p-buf,.p-fill{position:absolute;left:0;top:50%;height:6px;max-width:100%;transform:translateY(-50%);border-radius:999px;pointer-events:none}
.p-buf{background:color-mix(in srgb,var(--muted) 28%,transparent)}
.p-fill{background:var(--accent)}
.p-knob{position:absolute;top:50%;left:0;width:14px;height:14px;border-radius:50%;background:var(--accent);
  border:2px solid var(--card);box-shadow:0 1px 4px rgba(0,0,0,.35);transform:translate(-50%,-50%);pointer-events:none}
.p-times{display:flex;justify-content:space-between;align-items:baseline;gap:.8rem;margin-top:.1rem;
  font-size:.78rem;color:var(--muted);font-variant-numeric:tabular-nums}
.p-chap{flex:1;min-width:0;text-align:center;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--fg);font-weight:500}
.p-ctl{display:flex;justify-content:center;align-items:center;gap:.45rem;margin-top:.6rem;flex-wrap:wrap}
.p-ctl button{font:inherit;font-size:.78rem;font-weight:600;padding:.34rem .72rem;border-radius:999px;border:1px solid var(--line);
  background:var(--card);color:var(--fg);cursor:pointer;font-variant-numeric:tabular-nums;transition:border-color .15s ease,color .15s ease}
.p-ctl button:hover{border-color:var(--accent);color:var(--link)}
.p-rate{min-width:4.6em}
.p-resume{margin:.6rem .1rem 0;font-size:.8rem;color:var(--muted)}
.p-resume button{font:inherit;font-size:.8rem;border:none;background:none;padding:0;color:var(--link);cursor:pointer;text-decoration:underline}

/* ---- chapters ---- */
.chapters{background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);margin:0 0 .9rem;padding:.85rem 1.05rem .55rem}
.chapters .c-h{margin:0 0 .35rem;font-size:.72rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.chapters ol{list-style:none;margin:0;padding:0}
.chapters li{border-top:1px solid var(--line)}
.chapters li:first-child{border-top:none}
.chapters li button{display:flex;align-items:baseline;gap:.75rem;width:100%;text-align:left;font:inherit;font-size:.9rem;
  padding:.44rem .15rem;border:none;background:none;color:var(--fg);cursor:pointer}
.chapters .c-t{flex:none;min-width:3.4em;font-size:.78rem;color:var(--muted);font-variant-numeric:tabular-nums}
.chapters li button:hover .c-n{color:var(--link)}
.chapters li button.now .c-n{color:var(--link);font-weight:700}
.chapters li button.now .c-t{color:var(--accent);font-weight:700}
.actions{display:flex;flex-wrap:wrap;gap:.5rem;margin:.9rem 0 0}
.chip{font-size:.83rem;padding:.42rem .9rem;border-radius:999px;border:1px solid var(--line);background:var(--card);
  text-decoration:none;color:var(--fg);transition:border-color .15s ease,color .15s ease}
.chip:hover{border-color:var(--accent);color:var(--link)}

.panel{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);box-shadow:0 1px 2px rgba(28,26,22,.05);margin:1.3rem 0}
div.panel{padding:1.35rem 1.6rem}
details.panel>summary{padding:1.05rem 1.6rem;cursor:pointer;font-weight:700;font-size:1rem;list-style:none;
  display:flex;justify-content:space-between;align-items:center;gap:1rem}
details.panel>summary::-webkit-details-marker{display:none}
details.panel>summary::after{content:"+";font-size:1.35rem;font-weight:500;line-height:1;color:var(--accent);transition:transform .2s ease}
details.panel[open]>summary::after{transform:rotate(45deg)}
details.panel>.inner{padding:1.1rem 1.6rem 1.5rem;border-top:1px solid var(--line)}
.panel h2:first-child{margin-top:0}
.panel h2{font-size:1.05rem;letter-spacing:-.01em}
.notes ul{padding-left:1.25rem}
.notes li{margin:.3rem 0}
.tr-out{white-space:pre-wrap;font-size:.98rem;line-height:1.7;margin:0}
.tr-body{position:relative;max-height:min(62vh,540px);overflow-y:auto;padding-right:.4rem;overscroll-behavior:contain;scroll-behavior:smooth}
.tr-body p{margin:0 0 1.05em;font-size:.98rem;line-height:1.72}
.cue{cursor:pointer;border-radius:4px;padding:.04em .1em;transition:background .15s ease}
.cue:hover,.cue:focus-visible{background:var(--code)}
.cue.now{background:color-mix(in srgb,var(--accent) 30%,transparent)}

/* ---- long-form post copy: editorial serif ---- */
article.post{font-family:"Source Serif 4",Georgia,"Times New Roman",serif;font-size:1.07rem;line-height:1.75}
article.post h2,article.post h3,article.post h4{font-family:"Space Grotesk",-apple-system,sans-serif;letter-spacing:-.01em;line-height:1.25;margin:1.9em 0 .6em}
article.post img{max-width:100%;height:auto;border-radius:10px}
article.post figure{margin:1.7rem 0}
article.post figcaption{font-family:"Space Grotesk",sans-serif;font-size:.85rem;color:var(--muted);margin-top:.5rem}
article.post pre{background:var(--code);border:1px solid var(--line);padding:1rem;border-radius:10px;overflow-x:auto;font-size:.84rem;line-height:1.55}
article.post code{background:var(--code);padding:.1rem .3rem;border-radius:4px;font-size:.88em;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
article.post pre code{background:none;padding:0}
article.post blockquote{border-left:3px solid var(--accent);margin:1.2rem 0;padding:.2rem 1.1rem;color:var(--muted)}
article.post table{border-collapse:collapse;width:100%;font-size:.9rem;overflow-x:auto;display:block}
article.post td,article.post th{border:1px solid var(--line);padding:.45rem .65rem;vertical-align:top;text-align:left}
article.post a{color:var(--link)}

footer{border-top:1px solid var(--line);color:var(--muted);font-size:.84rem;margin-top:3rem}
footer .wrap{padding-top:1.6rem;padding-bottom:2.4rem}
.small{font-size:.85rem}

@media(max-width:720px){
  .hero .wrap{grid-template-columns:1fr;text-align:left;gap:1.2rem}
  .hero .cover{width:132px}
  .feature{grid-template-columns:1fr}
  .ep-head{grid-template-columns:1fr}
  .ep-art{max-width:330px}
}
@media(prefers-reduced-motion:reduce){
  *,*::before,*::after{transition:none!important;animation:none!important}
  html{scroll-behavior:auto}
}
"""

FONTS_HEAD = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700'
    '&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&display=swap" rel="stylesheet">'
)


def _layout(title: str, body: str, *, depth: int = 0, extra_head: str = "",
            header_html: str = "", description: str = "", og_image: str = "") -> str:
    rel = "../" * depth
    desc = H.escape(description or PODCAST["subtitle"], quote=True)
    og = og_image or f"{SITE_URL}/cover.jpg"
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{H.escape(title)}</title>
<meta name="description" content="{desc}">
<meta property="og:title" content="{H.escape(title, quote=True)}">
<meta property="og:description" content="{desc}">
<meta property="og:image" content="{H.escape(og, quote=True)}">
<meta name="twitter:card" content="summary_large_image">
<link rel="alternate" type="application/rss+xml" title="{H.escape(PODCAST['title'])} (podcast)" href="{FEED_URL}">
<link rel="alternate" type="application/rss+xml" title="{H.escape(PODCAST['title'])} (full-text posts)" href="{SITE_URL}/posts.xml">
{FONTS_HEAD}
<link rel="stylesheet" href="{rel}style.css">
<link rel="icon" type="image/png" sizes="64x64" href="{rel}favicon.png">
<link rel="apple-touch-icon" href="{rel}apple-touch-icon.png">{extra_head}
</head><body>
{header_html}
<main class="wrap">{body}</main>
<footer><div class="wrap">Unofficial. Post content © Anthropic, PBC — copied here for the audio edition with links back to the originals. Audio generated automatically with Kokoro TTS. Not affiliated with or endorsed by Anthropic. <a href="https://github.com/JacobBrooke95/anthropic-audio">Source &amp; pipeline on GitHub</a>.</div></footer>
</body></html>"""


def _topnav() -> str:
    return f"""<nav class="topnav" aria-label="Site"><div class="wrap">
<a class="brand" href="../../"><img src="../../cover.jpg" alt="">{H.escape(PODCAST['title'])}</a>
<a class="back" href="../../">← All episodes</a>
</div></nav>"""


def _hero() -> str:
    feed = FEED_URL
    return f"""<header class="hero"><div class="wrap">
<img class="cover" src="cover.jpg" alt="{H.escape(PODCAST['title'], quote=True)} podcast cover art">
<div>
<p class="kicker">Unofficial · auto-generated podcast</p>
<h1>{H.escape(PODCAST['title'])}</h1>
<p class="tag">{H.escape(PODCAST['subtitle'])}. Every new post from
<a href="https://www.anthropic.com/research" style="color:inherit">Research</a>,
<a href="https://www.anthropic.com/news" style="color:inherit">News</a>, and the
<a href="https://claude.com/blog" style="color:inherit">Claude&nbsp;Blog</a>
becomes a complete spoken episode within about an hour, Mon–Fri 8am–6pm PT.</p>
<div class="sub-row" role="group" aria-label="Subscribe">
<button class="btn primary" type="button" data-feed="{feed}">Copy feed URL</button>
<a class="btn" href="podcast://{feed.replace('https://','')}">Apple Podcasts</a>
<a class="btn" href="https://overcast.fm/itunes?url={feed}">Overcast</a>
<a class="btn" href="pktc://subscribe/{feed.replace('https://','')}">Pocket Casts</a>
<a class="btn" href="{feed}">RSS</a>
<a class="btn" href="{SITE_URL}/posts.xml" title="Full-text RSS of the posts, for feed readers">Text RSS</a>
</div>
<p class="feed-line">Feed URL: <code>{feed}</code> — paste it into any podcast app.
Prefer reading? The <a href="{SITE_URL}/posts.xml">text feed</a> carries each post in full (Anthropic publishes no RSS of its own).</p>
</div>
</div></header>"""


INDEX_JS = """<script>
document.querySelectorAll('[data-feed]').forEach(function(b){b.addEventListener('click',async function(){
  try{await navigator.clipboard.writeText(b.dataset.feed)}catch(e){window.prompt('Copy the feed URL:',b.dataset.feed);return}
  var t=b.textContent;b.textContent='Copied ✓';setTimeout(function(){b.textContent=t},1800)})});
var fb=document.querySelectorAll('.filter button');
var q=document.getElementById('epsearch');
var nores=document.getElementById('noresults');
var activeSrc='all';
function applyFilters(){
  var query=(q&&q.value||'').trim().toLowerCase(),shown=0;
  document.querySelectorAll('[data-source]').forEach(function(c){
    var hide=(activeSrc!=='all'&&c.dataset.source!==activeSrc)||
             (query&&(c.dataset.search||'').indexOf(query)<0);
    c.hidden=hide;if(!hide)shown++});
  if(nores)nores.hidden=shown>0}
fb.forEach(function(btn){btn.addEventListener('click',function(){
  fb.forEach(function(x){x.setAttribute('aria-pressed',String(x===btn))});
  activeSrc=btn.dataset.filter;applyFilters()})});
if(q)q.addEventListener('input',applyFilters);
</script>"""

# Shared episode-page script (docs/player.js): custom audio player, synced VTT
# transcript, chapters. Pure progressive enhancement — with JS off the native
# <audio controls> element stays visible and everything still works.
PLAYER_JS = r"""(function(){
'use strict';
var player=document.getElementById('player');
if(!player)return;
var audio=player.querySelector('audio');
if(!audio)return;

function fmt(t){t=Math.max(0,Math.round(t));var h=Math.floor(t/3600),m=Math.floor(t%3600/60),s=t%60;
  function p(n){return (n<10?'0':'')+n}
  return h?h+':'+p(m)+':'+p(s):m+':'+p(s)}

/* ---------- enhance the player ---------- */
var ui=player.querySelector('.pui');
audio.removeAttribute('controls');
audio.preload='metadata';
player.classList.add('enhanced');
if(ui)ui.hidden=false;

var slug=player.dataset.slug||location.pathname;
var KEY='anthropic-audio:'+slug;
var chapters=[],cues=[],trBody=null,activeCue=null,lastUserScroll=0,progScrollUntil=0;
var epDur=parseFloat(player.dataset.dur)||0;
function dur(){return (isFinite(audio.duration)&&audio.duration>0)?audio.duration:epDur}
function store(){try{return JSON.parse(localStorage.getItem(KEY))||{}}catch(e){return {}}}
function save(patch){try{var s=store();for(var k in patch)s[k]=patch[k];s.t=Date.now();
  localStorage.setItem(KEY,JSON.stringify(s))}catch(e){}}

var playBtn=player.querySelector('.p-play'),bar=player.querySelector('.p-bar'),
    fill=player.querySelector('.p-fill'),buf=player.querySelector('.p-buf'),
    knob=player.querySelector('.p-knob'),curEl=player.querySelector('.p-cur'),
    durEl=player.querySelector('.p-dur'),chapEl=player.querySelector('.p-chap'),
    rateBtn=player.querySelector('.p-rate'),resumeEl=player.querySelector('.p-resume');

var ICON_PLAY='<path d="M8 5v14l11-7z"/>',ICON_PAUSE='<path d="M6 5h4v14H6zM14 5h4v14h-4z"/>';
function setIcon(){playBtn.querySelector('svg').innerHTML=audio.paused?ICON_PLAY:ICON_PAUSE;
  playBtn.setAttribute('aria-label',audio.paused?'Play':'Pause')}

/* speed */
var RATES=[1,1.25,1.5,1.75,2],rate=1,st0=store();
if(st0.r&&RATES.indexOf(st0.r)>-1)rate=st0.r;
audio.playbackRate=rate;
function rateLabel(){rateBtn.textContent=rate+'×'}
rateLabel();
rateBtn.addEventListener('click',function(){
  rate=RATES[(RATES.indexOf(rate)+1)%RATES.length];
  audio.playbackRate=rate;rateLabel();save({r:rate})});

/* resume */
var pendingSeek=null;
if(st0.p>30&&epDur-st0.p>60){
  pendingSeek=st0.p;
  if(resumeEl){resumeEl.querySelector('.p-resume-t').textContent=fmt(st0.p);resumeEl.hidden=false}
}
var restart=player.querySelector('.p-restart');
if(restart)restart.addEventListener('click',function(){
  pendingSeek=null;try{audio.currentTime=0}catch(e){}
  save({p:0});resumeEl.hidden=true;paint()});
audio.addEventListener('loadedmetadata',function(){
  if(pendingSeek!=null&&pendingSeek<audio.duration-1)audio.currentTime=pendingSeek;
  pendingSeek=null;paint()});

/* paint loop */
function pos(){return pendingSeek!=null?pendingSeek:audio.currentTime}
function paint(){
  var d=dur()||1,t=pos(),pct=Math.min(100,t/d*100);
  fill.style.width=pct+'%';knob.style.left=pct+'%';
  curEl.textContent=fmt(t);durEl.textContent=fmt(d);
  bar.setAttribute('aria-valuemax',String(Math.round(d)));
  bar.setAttribute('aria-valuenow',String(Math.round(t)));
  bar.setAttribute('aria-valuetext',fmt(t)+' of '+fmt(d));
  try{var b=audio.buffered;if(b.length)buf.style.width=Math.min(100,b.end(b.length-1)/d*100)+'%'}catch(e){}
  syncChapter(t);syncCue(t)}

function seekTo(t){
  t=Math.max(0,Math.min(t,(dur()||1)-.05));
  if(audio.readyState<1){pendingSeek=t;try{audio.load()}catch(e){}}
  else{audio.currentTime=t}
  save({p:t});paint()}
function skip(d){seekTo(pos()+d)}
function toggle(){if(audio.paused)audio.play();else audio.pause()}

playBtn.addEventListener('click',toggle);
player.querySelectorAll('[data-skip]').forEach(function(b){
  b.addEventListener('click',function(){skip(parseFloat(b.dataset.skip))})});

/* seek bar: click + drag */
var dragging=false;
function barSeek(ev){var r=bar.getBoundingClientRect();
  seekTo(Math.max(0,Math.min(1,(ev.clientX-r.left)/r.width))*dur())}
bar.addEventListener('pointerdown',function(e){
  dragging=true;try{bar.setPointerCapture(e.pointerId)}catch(x){}barSeek(e);e.preventDefault()});
bar.addEventListener('pointermove',function(e){if(dragging)barSeek(e)});
bar.addEventListener('pointerup',function(){dragging=false});
bar.addEventListener('pointercancel',function(){dragging=false});

/* keyboard: space play/pause, arrows seek — when focus is inside the player */
player.addEventListener('keydown',function(e){
  if(e.key===' '||e.code==='Space'){
    if(e.target.tagName==='BUTTON')return;
    e.preventDefault();toggle()}
  else if(e.key==='ArrowLeft'){e.preventDefault();skip(-15)}
  else if(e.key==='ArrowRight'){e.preventDefault();skip(15)}});

audio.addEventListener('play',setIcon);
audio.addEventListener('pause',function(){setIcon();save({p:audio.currentTime})});
audio.addEventListener('ended',function(){setIcon();save({p:0})});
var lastSave=0;
audio.addEventListener('timeupdate',function(){paint();
  var n=Date.now();if(!audio.paused&&n-lastSave>5000){lastSave=n;save({p:audio.currentTime})}});
audio.addEventListener('progress',paint);
audio.addEventListener('ratechange',function(){if(RATES.indexOf(audio.playbackRate)>-1){rate=audio.playbackRate;rateLabel()}});
window.addEventListener('pagehide',function(){
  if(audio.currentTime>1&&!audio.ended)save({p:audio.currentTime})});
setIcon();paint();

/* ---------- chapters ---------- */
var chapNav=document.getElementById('chapters');
function syncChapter(t){
  if(!chapters.length)return;
  var c=null;
  for(var i=0;i<chapters.length;i++){if(t>=chapters[i].startTime-.3)c=chapters[i];else break}
  if(chapEl)chapEl.textContent=c?c.title:'';
  chapters.forEach(function(x){if(x.el)x.el.classList.toggle('now',x===c)})}
if(chapNav&&window.fetch){
  fetch(chapNav.dataset.src).then(function(r){if(!r.ok)throw 0;return r.json()}).then(function(j){
    chapters=(j.chapters||[]).filter(function(c){
      return typeof c.startTime==='number'&&c.title}).sort(function(a,b){return a.startTime-b.startTime});
    if(!chapters.length)return;
    var h=document.createElement('h2');h.className='c-h';h.textContent='Chapters';
    var ol=document.createElement('ol');
    chapters.forEach(function(c){
      var li=document.createElement('li'),b=document.createElement('button');
      b.type='button';
      var tt=document.createElement('span');tt.className='c-t';tt.textContent=fmt(c.startTime);
      var nn=document.createElement('span');nn.className='c-n';nn.textContent=c.title;
      b.appendChild(tt);b.appendChild(nn);
      b.addEventListener('click',function(){seekTo(c.startTime);if(audio.paused)audio.play()});
      c.el=b;li.appendChild(b);ol.appendChild(li)});
    chapNav.appendChild(h);chapNav.appendChild(ol);chapNav.hidden=false;paint()
  }).catch(function(){})}

/* ---------- synced transcript ---------- */
var tr=document.getElementById('transcript');

function parseVTT(text){
  var out=[],lines=text.replace(/\r/g,'').split('\n'),i=0;
  var TIME=/(?:(\d+):)?(\d+):(\d+)[.,](\d+)\s*-->\s*(?:(\d+):)?(\d+):(\d+)[.,](\d+)/;
  while(i<lines.length){
    var m=TIME.exec(lines[i]);
    if(m){
      var s=(m[1]?+m[1]*3600:0)+ +m[2]*60+ +m[3]+ +('0.'+m[4]);
      var e=(m[5]?+m[5]*3600:0)+ +m[6]*60+ +m[7]+ +('0.'+m[8]);
      i++;var txt=[];
      while(i<lines.length&&lines[i].trim()!==''){txt.push(lines[i].trim());i++}
      var body=txt.join(' ').replace(/<[^>]+>/g,'').trim();
      if(body)out.push({s:s,e:e,text:body})
    }
    i++}
  return out}

function buildSynced(vtt){
  cues=parseVTT(vtt);
  if(!cues.length)return false;
  trBody=tr.querySelector('.tr-body');
  trBody.innerHTML='';
  var p=null,plen=0,prevEnd=-10;
  cues.forEach(function(c){
    if(!p||c.s-prevEnd>1.4||plen>650){
      p=document.createElement('p');trBody.appendChild(p);plen=0}
    else p.appendChild(document.createTextNode(' '));
    var sp=document.createElement('span');
    sp.className='cue';sp.textContent=c.text;sp.tabIndex=0;sp.setAttribute('role','button');
    sp.setAttribute('aria-label','Play from '+fmt(c.s));
    function go(){seekTo(c.s+.01);if(audio.paused)audio.play()}
    sp.addEventListener('click',go);
    sp.addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();go()}});
    p.appendChild(sp);c.el=sp;plen+=c.text.length;prevEnd=c.e});
  trBody.addEventListener('scroll',function(){
    if(Date.now()<progScrollUntil)return;lastUserScroll=Date.now()});
  syncCue(pos());
  return true}

function syncCue(t){
  if(!cues.length||!tr||!tr.open)return;
  var c=null;
  for(var i=0;i<cues.length;i++){
    if(t>=cues[i].s-.15&&t<cues[i].e+.35){c=cues[i];break}}
  if(c===activeCue)return;
  if(activeCue&&activeCue.el)activeCue.el.classList.remove('now');
  activeCue=c;
  if(c&&c.el){
    c.el.classList.add('now');
    if(!audio.paused&&trBody&&Date.now()-lastUserScroll>4000){
      var top=c.el.getBoundingClientRect().top-trBody.getBoundingClientRect().top+trBody.scrollTop;
      progScrollUntil=Date.now()+1200;
      trBody.scrollTop=Math.max(0,top-trBody.clientHeight/2)}}}

if(tr){tr.addEventListener('toggle',function(){
  if(!tr.open||tr.dataset.done)return;tr.dataset.done='1';
  var o=tr.querySelector('.tr-out');
  o.textContent='Loading transcript…';
  function fallback(){
    fetch(tr.dataset.txt).then(function(r){if(!r.ok)throw 0;return r.text()})
      .then(function(t){o.textContent=t})
      .catch(function(){o.textContent='Could not load the transcript here — use the “Transcript (text)” link above instead.'})}
  fetch(tr.dataset.vtt).then(function(r){if(!r.ok)throw 0;return r.text()})
    .then(function(t){if(!buildSynced(t))fallback()})
    .catch(fallback)})}
})();
"""


def render_blocks_html(blocks: list[dict], img_prefix: str = "") -> str:
    out = []
    for b in blocks:
        t = b["type"]
        if t == "heading":
            lvl = min(max(b["level"], 2), 4)
            out.append(f"<h{lvl}>{b['html']}</h{lvl}>")
        elif t == "paragraph":
            out.append(f"<p>{b['html']}</p>")
        elif t == "list":
            tag = "ol" if b["ordered"] else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{i['html']}</li>" for i in b["items"]) + f"</{tag}>")
        elif t == "quote":
            out.append(f"<blockquote>{b['html']}</blockquote>")
        elif t == "code":
            out.append(f"<pre><code>{H.escape(b['text'])}</code></pre>")
        elif t == "image":
            src = (img_prefix + b["local"]) if b.get("local") else b["src"]
            cap = f"<figcaption>{H.escape(b['caption'])}</figcaption>" if b.get("caption") else ""
            out.append(f'<figure><img src="{H.escape(src)}" alt="{H.escape(b.get("alt") or "")}" loading="lazy">{cap}</figure>')
        elif t == "table":
            cap = f"<figcaption>{H.escape(b['caption'])}</figcaption>" if b.get("caption") else ""
            out.append(f"<figure>{b['html']}{cap}</figure>")
        elif t == "footnotes":
            out.append("<h3>Footnotes</h3><ol>" + "".join(f"<li>{i['html']}</li>" for i in b["items"]) + "</ol>")
    return "\n".join(out)


def render_blocks_md(blocks: list[dict]) -> str:
    out = []
    for b in blocks:
        t = b["type"]
        if t == "heading":
            out.append("#" * min(max(b["level"], 2), 4) + " " + b["text"])
        elif t == "paragraph":
            out.append(_md_inline(b["html"]))
        elif t == "list":
            out.append("\n".join((f"{n}. " if b["ordered"] else "- ") + _md_inline(i["html"]) for n, i in enumerate(b["items"], 1)))
        elif t == "quote":
            out.append("> " + _md_inline(b["html"]).replace("\n", "\n> "))
        elif t == "code":
            out.append(f"```{b.get('lang') or ''}\n{b['text']}\n```")
        elif t == "image":
            out.append(f"![{b.get('alt') or ''}]({b['src']})" + (f"\n\n*{b['caption']}*" if b.get("caption") else ""))
        elif t == "table":
            rows = b["rows"]
            if rows:
                w = max(len(r) for r in rows)
                rows = [r + [""] * (w - len(r)) for r in rows]
                md = "| " + " | ".join(rows[0]) + " |\n|" + "---|" * w + "\n" + "\n".join("| " + " | ".join(r) + " |" for r in rows[1:])
                out.append(md)
        elif t == "footnotes":
            out.append("\n".join(f"[^{i['n']}]: {_md_inline(i['html'])}" for i in b["items"]))
    return "\n\n".join(out)


def _md_inline(html_: str) -> str:
    s = html_
    s = re.sub(r'<a href="([^"]+)">(.*?)</a>', r"[\2](\1)", s, flags=re.S)
    s = re.sub(r"</?(em)>", "*", s); s = re.sub(r"</?(strong)>", "**", s); s = re.sub(r"</?code>", "`", s)
    s = re.sub(r"<[^>]+>", "", s)
    return H.unescape(s)


def localize_images(post, post_dir: Path, max_images: int = 60) -> None:
    """Download the post's images into docs/posts/<slug>/img/ so the copy is self-contained."""
    imgdir = post_dir / "img"
    n = 0
    for b in post.blocks:
        if b["type"] != "image" or b.get("local"):
            continue
        if n >= max_images:
            break
        n += 1
        src = b["src"]
        ext = (Path(urlparse(src).path).suffix or ".jpg").lower()
        if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"):
            ext = ".jpg"
        name = f"{n:02d}{ext}"
        try:
            u = src + ("&" if "?" in src else "?") + "w=1600&auto=format" if "cdn.sanity.io" in src or "www-cdn.anthropic.com" in src else src
            data = http_get(u, binary=True)
            imgdir.mkdir(parents=True, exist_ok=True)
            (imgdir / name).write_bytes(data)
            b["local"] = f"img/{name}"
        except Exception as e:
            log.warning("image download failed %s: %s", src, e)


def _badge(source: str) -> str:
    return f'<span class="badge {H.escape(source)}">{H.escape(SOURCES[source]["label"])}</span>'


def write_episode_assets(post, ep: dict, transcript_txt: str) -> None:
    """Write per-episode HTML page, markdown copy, transcript text."""
    from .feed import show_notes_html
    src = SOURCES[post.source]
    pdir = DOCS / "posts" / post.slug
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "post.json").write_text(__import__("json").dumps(post.to_dict(), indent=1, ensure_ascii=False))
    md = f"# {post.title}\n\n" + (f"*{post.subtitle}*\n\n" if post.subtitle else "") + \
         f"Source: {post.url}  \nPublished: {post.date[:10]} · {src['name']}" + (f" · {', '.join(post.authors)}" if post.authors else "") + \
         "\n\n---\n\n" + render_blocks_md(post.blocks) + "\n"
    (pdir / "post.md").write_text(md)
    (DOCS / "transcripts").mkdir(parents=True, exist_ok=True)
    (DOCS / "transcripts" / f"{post.slug}.txt").write_text(transcript_txt)
    # episode page
    edir = DOCS / "episodes" / post.slug
    edir.mkdir(parents=True, exist_ok=True)
    body_html = render_blocks_html(post.blocks, img_prefix=f"../../posts/{post.slug}/")
    epno = f"Episode {ep['episode']} · " if ep.get("episode") else ""
    authors = " · " + H.escape(", ".join(post.authors)) if post.authors else ""
    subtitle_html = f'<p class="ep-sub">{H.escape(post.subtitle)}</p>' if post.subtitle else ""
    page = f"""
<article>
<header class="ep-head">
<img class="ep-art" src="../../art/{post.slug}.jpg" alt="Episode artwork for “{H.escape(post.title, quote=True)}”">
<div class="ep-info">
<div class="row">{_badge(post.source)}<span class="meta">{epno}{parse_iso(post.date).strftime('%B %-d, %Y')}{authors} · {post.word_count:,} words</span></div>
<h1 class="ep-title">{H.escape(post.title)}</h1>
{subtitle_html}
<div class="player" id="player" data-slug="{post.slug}" data-dur="{ep['duration']:.1f}">
<p class="plabel"><span>Listen to this episode</span><span class="dur">{hms(ep['duration'])}</span></p>
<audio controls preload="none" src="../../audio/{post.slug}.mp3"></audio>
<div class="pui" hidden>
<div class="p-main">
<button type="button" class="p-play" aria-label="Play"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg></button>
<div class="p-right">
<div class="p-bar" role="slider" tabindex="0" aria-label="Seek" aria-valuemin="0" aria-valuemax="{ep['duration']:.0f}" aria-valuenow="0" aria-valuetext="0:00">
<div class="p-buf"></div><div class="p-fill"></div><div class="p-knob"></div>
</div>
<div class="p-times"><span class="p-cur">0:00</span><span class="p-chap"></span><span class="p-dur">{hms(ep['duration'])}</span></div>
</div>
</div>
<div class="p-ctl">
<button type="button" data-skip="-30" title="Back 30 seconds" aria-label="Back 30 seconds">−30s</button>
<button type="button" data-skip="-15" title="Back 15 seconds" aria-label="Back 15 seconds">−15s</button>
<button type="button" class="p-rate" title="Playback speed" aria-label="Playback speed">1×</button>
<button type="button" data-skip="15" title="Forward 15 seconds" aria-label="Forward 15 seconds">+15s</button>
<button type="button" data-skip="30" title="Forward 30 seconds" aria-label="Forward 30 seconds">+30s</button>
</div>
<p class="p-resume" hidden>Resumed at <span class="p-resume-t"></span> — <button type="button" class="p-restart">start over</button></p>
</div>
</div>
<nav class="chapters" id="chapters" hidden aria-label="Chapters" data-src="../../chapters/{post.slug}.json"></nav>
<div class="actions">
<a class="chip" href="../../audio/{post.slug}.mp3" download>Download MP3</a>
<a class="chip" href="../../transcripts/{post.slug}.vtt">Transcript (VTT)</a>
<a class="chip" href="../../transcripts/{post.slug}.txt">Transcript (text)</a>
<a class="chip" href="../../posts/{post.slug}/post.md">Markdown</a>
<a class="chip" href="../../posts/{post.slug}/post.json">JSON</a>
<a class="chip" href="{H.escape(post.url)}">Original post ↗</a>
</div>
</div>
</header>
<details class="panel notes">
<summary>Show notes &amp; every link in the post</summary>
<div class="inner">{show_notes_html(ep)}</div>
</details>
<details class="panel" id="transcript" data-vtt="../../transcripts/{post.slug}.vtt" data-txt="../../transcripts/{post.slug}.txt">
<summary>Transcript</summary>
<div class="inner"><p class="meta">Click any line to jump the audio there. Also available as <a href="../../transcripts/{post.slug}.vtt">WebVTT (timed)</a> or <a href="../../transcripts/{post.slug}.txt">plain text</a>.</p>
<div class="tr-body"><pre class="tr-out"></pre></div>
<noscript><p class="meta">JavaScript is off — read the transcript via the links above.</p></noscript></div>
</details>
<details class="panel" open>
<summary>Full text of the post</summary>
<div class="inner"><article class="post">
<p class="meta">Copied from <a href="{H.escape(post.url)}">{H.escape(post.url)}</a> on {post.fetched_at[:10]} for the audio edition. © Anthropic, PBC.</p>
{body_html}
</article></div>
</details>
</article>
<script src="../../player.js" defer></script>"""
    html_page = _layout(f"{post.title} — {PODCAST['title']}", page, depth=2,
                        header_html=_topnav(),
                        description=(post.subtitle or post.title),
                        og_image=f"{SITE_URL}/art/{post.slug}.jpg")
    (edir / "index.html").write_text(html_page)


def _search_attr(ep: dict) -> str:
    """Lower-cased title+subtitle blob for the client-side search box."""
    blob = f"{ep.get('title') or ''} {ep.get('subtitle') or ''}".lower()
    return H.escape(re.sub(r"\s+", " ", blob).strip(), quote=True)


def _card(ep: dict) -> str:
    sub = (ep.get("subtitle") or "").strip()
    sub_html = f'<p class="sub">{H.escape(sub[:200])}</p>' if sub else ""
    return f"""<a class="card" data-source="{H.escape(ep['source'])}" data-search="{_search_attr(ep)}" href="episodes/{ep['slug']}/">
<img src="art/{ep['slug']}.600.jpg" alt="" loading="lazy">
<div class="body">
<div class="row">{_badge(ep['source'])}<span class="meta">Ep. {ep['episode']} · {parse_iso(ep['date']).strftime('%b %-d, %Y')} · {hms(ep['duration'])}</span></div>
<h3>{H.escape(ep['title'])}</h3>
{sub_html}
</div></a>"""


def _feature(ep: dict) -> str:
    sub = (ep.get("subtitle") or "").strip()
    sub_html = f'<p class="sub">{H.escape(sub[:260])}</p>' if sub else ""
    return f"""<section aria-label="Latest episode" data-source="{H.escape(ep['source'])}" data-search="{_search_attr(ep)}">
<div class="section-head"><h2 class="sec">Latest episode</h2></div>
<article class="feature">
<a class="feature-art" href="episodes/{ep['slug']}/" aria-hidden="true" tabindex="-1"><img src="art/{ep['slug']}.600.jpg" alt=""></a>
<div class="feature-body">
<div class="row">{_badge(ep['source'])}<span class="meta">Ep. {ep['episode']} · {parse_iso(ep['date']).strftime('%B %-d, %Y')} · {hms(ep['duration'])}</span></div>
<h2><a href="episodes/{ep['slug']}/">{H.escape(ep['title'])}</a></h2>
{sub_html}
<audio controls preload="none" src="audio/{ep['slug']}.mp3"></audio>
<p class="more"><a href="episodes/{ep['slug']}/">Show notes, transcript &amp; full text</a> · <a href="{H.escape(ep['url'])}">Original post ↗</a></p>
</div></article></section>"""


def _listen_time(total_seconds: float) -> str:
    """'6.4 hours' / '54 minutes' for the index stats strip."""
    if total_seconds >= 3600:
        h = total_seconds / 3600
        return f"{h:.1f} hours".replace(".0 ", " ")
    return f"{max(1, round(total_seconds / 60))} minutes"


def write_index(episodes: list[dict]) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "style.css").write_text(CSS)
    (DOCS / "player.js").write_text(PLAYER_JS)
    (DOCS / ".nojekyll").write_text("")
    eps = sorted(episodes, key=lambda e: e["date"], reverse=True)
    body = ""
    if eps:
        body += _feature(eps[0])
        rest = eps[1:]
        filt = "".join(
            f'<button type="button" data-filter="{k}" aria-pressed="false">{H.escape(s["label"])}</button>'
            for k, s in SOURCES.items())
        stats = f"{len(eps)} episodes · {_listen_time(sum(e['duration'] for e in eps))} of listening"
        body += f"""<section aria-label="All episodes">
<div class="section-head"><div><h2 class="sec">All episodes</h2><p class="stats">{stats}</p></div>
<div class="idx-tools">
<input class="search" id="epsearch" type="search" placeholder="Search episodes…" aria-label="Search episodes by title">
<div class="filter" role="group" aria-label="Filter by source">
<button type="button" data-filter="all" aria-pressed="true">All</button>{filt}</div></div></div>
<div class="grid">{''.join(_card(e) for e in rest)}</div>
<p class="no-results" id="noresults" hidden>No episodes match — try a different search or filter.</p></section>"""
    body += INDEX_JS
    (DOCS / "index.html").write_text(_layout(
        f"{PODCAST['title']} — unofficial audio editions of Anthropic's posts",
        body, header_html=_hero(), description=PODCAST["description"]))
