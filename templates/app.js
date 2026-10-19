/* ================================================================ 設定（ブラウザに保存）
 * fg: 振り仮名 on（表示）/ tap（タップで表示）/ off（非表示）
 * hl: ハイライト表示  cn: 中国語訳表示  fs: 文字サイズ倍率
 * 保存できない環境（プライベートモード等）では既定値のまま動く。 */
const SETTINGS_KEY='n1lesson:settings';
let settings={fg:'on',hl:true,cn:true,fs:1};
try{Object.assign(settings,JSON.parse(localStorage.getItem(SETTINGS_KEY)||'null')||{});}catch(e){}
function saveSettings(){try{localStorage.setItem(SETTINGS_KEY,JSON.stringify(settings));}catch(e){}}
const FG_LABEL={on:'ふりがな：表示',tap:'ふりがな：タップで表示',off:'ふりがな：非表示'};
function applySettings(){
  const b=document.body;
  b.classList.remove('fg-on','fg-tap','fg-off');
  b.classList.add('fg-'+settings.fg);
  b.classList.toggle('hl-off',!settings.hl);
  b.classList.toggle('cn-blur',!settings.cn);
  document.documentElement.style.setProperty('--fs',String(settings.fs));
  const set=(id,text,on)=>{const el=document.getElementById(id);if(el){el.textContent=text;el.classList.toggle('off',!on);}};
  set('tool-fg',FG_LABEL[settings.fg]||FG_LABEL.on,settings.fg==='on');
  set('tool-hl','ハイライト：'+(settings.hl?'表示':'非表示'),settings.hl);
  set('tool-cn','中文：'+(settings.cn?'表示':'ぼかす'),settings.cn);
}
function cycleFurigana(){
  const order=['on','tap','off'];
  settings.fg=order[(order.indexOf(settings.fg)+1)%order.length];
  document.querySelectorAll('ruby.show').forEach(r=>r.classList.remove('show'));
  applySettings();saveSettings();
}
function toggleSetting(k){settings[k]=!settings[k];applySettings();saveSettings();}
function fontStep(d){
  settings.fs=Math.round(Math.min(1.5,Math.max(0.85,settings.fs+d*0.1))*100)/100;
  applySettings();saveSettings();closeTooltip();
}

/* ================================================================ タブ */
function switchTab(name){
  const names=['news','scene','ext'];
  names.forEach(t=>document.getElementById('tab-'+t).classList.add('hidden'));
  document.getElementById('tab-'+name).classList.remove('hidden');
  document.querySelectorAll('.tab').forEach((el,i)=>el.classList.toggle('active',names[i]===name));
  stopTTS();closeTooltip();
  try{sessionStorage.setItem(storeKey('tab'),name);}catch(e){}
}

/* ================================================================ 読み上げ用テキスト
 * 振り仮名（rt）は読み上げない。ただし本文に明示した振り仮名（固有名詞など）は
 * 読みのほうを読ませる（TTSの誤読を防ぐ）。ボタン類（.no-tts）は除く。 */
function speechText(el){
  const c=el.cloneNode(true);
  c.querySelectorAll('.no-tts,rp').forEach(n=>n.remove());
  c.querySelectorAll('ruby').forEach(r=>{
    const rt=r.querySelector('rt');
    if(rt&&r.classList.contains('rb-x')){r.replaceWith(document.createTextNode(rt.textContent));}
    else{r.querySelectorAll('rt').forEach(n=>n.remove());}
  });
  return (c.textContent||'').replace(/\s+/g,' ').trim();
}

/* ================================================================ 解説ポップオーバー */
let popAnchor=null;
function showTooltip(id,anchor){
  const pop=document.getElementById('tip-pop');
  const src=document.getElementById(id);
  if(!src)return;
  if(!pop||!anchor){src.classList.toggle('hidden');return;} // 旧形式の呼び出しにも対応
  if(popAnchor===anchor&&!pop.hidden){closeTooltip();return;}
  closeTooltip();
  popAnchor=anchor;anchor.classList.add('active');
  pop.querySelector('.tip-pop-body').innerHTML=src.innerHTML;
  pop.querySelector('.tip-pop-word').textContent=speechText(anchor);
  pop.hidden=false;
  if(window.matchMedia('(max-width: 768px)').matches){pop.style.top='';pop.style.left='';return;}
  const r=anchor.getBoundingClientRect(),w=pop.offsetWidth,h=pop.offsetHeight;
  const sx=window.scrollX,sy=window.scrollY,vw=document.documentElement.clientWidth;
  let left=Math.min(Math.max(8,r.left),vw-w-8);
  let top=r.bottom+8;
  if(top+h>window.innerHeight&&r.top-h-8>70)top=r.top-h-8; // 下に入らなければ上に出す
  pop.style.left=(left+sx)+'px';pop.style.top=(top+sy)+'px';
}
function closeTooltip(){
  const pop=document.getElementById('tip-pop');
  if(pop)pop.hidden=true;
  if(popAnchor){popAnchor.classList.remove('active');popAnchor=null;}
}
function sayPopWord(){if(popAnchor)sayWord(speechText(popAnchor));}

/* ================================================================ 音声読み上げ（TTS）
 * Chrome は1回の発話が長いと約15秒で無言のまま止まるため、文単位に分けて順番に読む。
 * 分割は「。！？」で行い、長すぎる文はさらに「、」で切る。
 * ニュースは段落ごとにキューを作り、読んでいる段落に色を付ける。 */
const TTS_MAX=110;
let tts={session:0,queue:[],idx:0,status:null,rate:1.0,voice:null};

function splitForTTS(text){
  const out=[];
  const sentences=text.replace(/\s+/g,' ').split(/(?<=[。！？!?])/);
  for(let s of sentences){
    s=s.trim();if(!s)continue;
    while(s.length>TTS_MAX){
      let cut=s.lastIndexOf('、',TTS_MAX);
      if(cut<20)cut=TTS_MAX; else cut+=1;
      out.push(s.slice(0,cut));s=s.slice(cut).trim();
    }
    if(s)out.push(s);
  }
  return out;
}

function pickJaVoice(){
  if(!window.speechSynthesis)return null;
  const vs=window.speechSynthesis.getVoices().filter(v=>v.lang&&v.lang.replace('_','-').toLowerCase().startsWith('ja'));
  // Edge の自然音声（Natural）> ローカル音声 > その他
  return vs.find(v=>/natural/i.test(v.name))||vs.find(v=>v.localService)||vs[0]||null;
}

function setStatus(msg){if(tts.status)tts.status.textContent=msg;}
function markReading(para){
  document.querySelectorAll('.np.reading').forEach(p=>{if(p!==para)p.classList.remove('reading');});
  if(para)para.classList.add('reading');
}

function speakNext(session){
  if(session!==tts.session)return;
  if(tts.idx>=tts.queue.length){setStatus('✅ 再生完了');markReading(null);return;}
  const item=tts.queue[tts.idx];
  const u=new SpeechSynthesisUtterance(item.text);
  u.lang='ja-JP';u.rate=tts.rate;
  try{if(tts.voice)u.voice=tts.voice;}catch(e){} // 音声オブジェクトが無効でも lang 指定で読み続ける
  u.onend=()=>{if(session!==tts.session)return;tts.idx++;speakNext(session);};
  u.onerror=(e)=>{
    if(session!==tts.session||e.error==='interrupted'||e.error==='canceled')return;
    setStatus('❌ エラー（'+(e.error||'unknown')+'）ページを再読み込みしてみてください');markReading(null);
  };
  tts.current=u; // GC で onend が飛ばないよう参照を保持
  markReading(item.para||null);
  setStatus('▶ 再生中... '+(tts.idx+1)+'/'+tts.queue.length);
  window.speechSynthesis.speak(u);
}

function startQueue(queue,playerId,statusId){
  if(!window.speechSynthesis){alert('お使いのブラウザは音声合成に対応していません。Chrome/Edgeをお試しください。');return;}
  if(!queue.length)return;
  window.speechSynthesis.cancel();
  if(tts.status&&tts.status.id!==statusId)setStatus('▶ 再生ボタンを押してください');
  markReading(null);
  const sel=document.getElementById('speed-'+playerId);
  tts={session:tts.session+1,queue:queue,idx:0,
       status:document.getElementById(statusId),rate:sel?parseFloat(sel.value):1.0,voice:pickJaVoice()};
  if(!tts.voice)setStatus('⚠️ 日本語音声が見つかりません（OSの音声設定を確認）');
  const s=tts.session;
  setTimeout(()=>speakNext(s),60); // cancel 直後の speak は Chrome で無視されることがある
}

function queueFor(el){
  const paras=el.querySelectorAll('p.np');
  const q=[];
  if(paras.length){paras.forEach(p=>splitForTTS(speechText(p)).forEach(t=>q.push({text:t,para:p})));}
  else{splitForTTS(speechText(el)).forEach(t=>q.push({text:t,para:null}));}
  return q;
}

function playTTS(srcId,playerId,statusId){
  const el=document.getElementById(srcId);if(!el)return;
  startQueue(queueFor(el),playerId,statusId);
}

function playPara(btn){
  const p=btn.closest('.np'),box=btn.closest('.news-text');if(!p||!box)return;
  const q=splitForTTS(speechText(p)).map(t=>({text:t,para:p}));
  startQueue(q,box.dataset.player,box.dataset.status);
}

function sayWord(text){
  if(!window.speechSynthesis||!text)return;
  stopTTS();
  const u=new SpeechSynthesisUtterance(text);
  u.lang='ja-JP';u.rate=0.9;
  try{const v=pickJaVoice();if(v)u.voice=v;}catch(e){}
  setTimeout(()=>window.speechSynthesis.speak(u),60);
}

function pauseTTS(){
  const s=window.speechSynthesis;if(!s)return;
  if(s.speaking&&!s.paused){s.pause();setStatus('⏸ 一時停止中');}
  else if(s.paused){s.resume();setStatus('▶ 再生中... '+(tts.idx+1)+'/'+tts.queue.length);}
}

function stopTTS(){
  if(!window.speechSynthesis)return;
  tts.session++;
  window.speechSynthesis.cancel();
  markReading(null);
  if(tts.status&&tts.queue.length)setStatus('⏹ 停止しました');
}

if(window.speechSynthesis){
  window.speechSynthesis.getVoices();
  window.speechSynthesis.onvoiceschanged=()=>window.speechSynthesis.getVoices();
  window.addEventListener('beforeunload',()=>window.speechSynthesis.cancel());
}

/* ================================================================ 操作のイベント */
function storeKey(k){return 'n1lesson:'+(document.body.dataset.date||location.pathname)+':'+k;}

document.addEventListener('click',e=>{
  const t=e.target;
  // 振り仮名「タップで表示」モード
  const rb=t.closest&&t.closest('ruby');
  if(rb&&document.body.classList.contains('fg-tap'))rb.classList.toggle('show');
  // 中国語訳ぼかしモード：タップした訳だけ表示
  const cn=t.closest&&t.closest('.b-cn,.hl-cn');
  if(cn&&document.body.classList.contains('cn-blur'))cn.classList.toggle('reveal');
  // ポップオーバーの外をクリックしたら閉じる
  const pop=document.getElementById('tip-pop');
  if(pop&&!pop.hidden&&!pop.contains(t)&&!(t.closest&&t.closest('.vocab-hl,.grammar-hl')))closeTooltip();
});
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){closeTooltip();return;}
  const t=e.target;
  if((e.key==='Enter'||e.key===' ')&&t.classList&&(t.classList.contains('vocab-hl')||t.classList.contains('grammar-hl'))){
    e.preventDefault();showTooltip(t.dataset.tip,t);
  }
});
// 幅が変わったときだけ閉じる（スマホはスクロールでアドレスバーが出入りし、高さだけの resize が頻発する）
let lastWidth=window.innerWidth;
window.addEventListener('resize',()=>{if(window.innerWidth!==lastWidth){lastWidth=window.innerWidth;closeTooltip();}});

document.addEventListener('DOMContentLoaded',()=>{
  applySettings();
  // 語彙カードに発音ボタン
  document.querySelectorAll('.vocab-card,.scene-vocab-card').forEach(card=>{
    const jp=card.querySelector('.vc-jp,.svc-jp');if(!jp)return;
    const b=document.createElement('button');
    b.type='button';b.className='say no-tts';b.textContent='🔊';b.title='発音を聞く';b.setAttribute('aria-label','発音を聞く');
    b.addEventListener('click',()=>{
      const text=speechText(jp).replace(/[（(][^）)]*[）)]/g,'').replace(/[〜~]/g,'').replace(/[／/]/g,'、');
      sayWord(text);
    });
    card.appendChild(b);
  });
  // メモ欄の自動保存（教材の日付ごと）
  document.querySelectorAll('textarea.notes-area').forEach((ta,i)=>{
    const key=storeKey('notes'+i);
    try{const v=localStorage.getItem(key);if(v)ta.value=v;}catch(e){}
    let timer=null;
    ta.addEventListener('input',()=>{
      clearTimeout(timer);
      timer=setTimeout(()=>{try{localStorage.setItem(key,ta.value);}catch(e){}},400);
    });
  });
  // 「先頭へ」ボタン
  const top=document.getElementById('to-top');
  if(top)window.addEventListener('scroll',()=>{top.hidden=window.scrollY<600;},{passive:true});
  try{const t=sessionStorage.getItem(storeKey('tab'));if(t&&t!=='news'&&document.getElementById('tab-'+t))switchTab(t);}catch(e){}
});
