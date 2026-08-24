(function(){
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
