/* ================================================================ 設定（ブラウザに保存）
 * fg: 振り仮名 on（表示）/ tap（タップで表示）/ off（非表示）
 * hl: ハイライト表示  cn: 中国語訳表示  fs: 文字サイズ倍率  voice: 読み上げの声（空なら自動）
 * 保存できない環境（プライベートモード等）では既定値のまま動く。 */
const SETTINGS_KEY='n1lesson:settings';
let settings={fg:'on',hl:true,cn:true,fs:1,voice:''};
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
 * ブラウザに入っている日本語音声から、いちばん自然なものを自動で選ぶ:
 *   Edge の Natural（Nanami・Keita などのニューラル音声）> Chrome の「Google 日本語」>
 *   Apple の拡張音声（Kyoko など）> Windows 標準（Haruka・Sayaka > Ayumi・Ichiro）
 * 上部バーの「声」で手動でも選べる（ブラウザに保存）。
 * 会話は話者ごとに声を変え（同じくらい自然な別の声があれば使い分け、なければ声の高さを変える）、
 * 読んでいる吹き出しに色を付ける。
 * Chrome は1回の発話が長いと約15秒で止まるため、文単位で順番に読む（短い文はまとめて間延びを防ぐ）。 */
const TTS_MAX=100;
let tts={session:0,queue:[],idx:0,status:null,rate:1.0,voice:null};

function splitForTTS(text){
  const parts=[];
  const sentences=text.replace(/\s+/g,' ').split(/(?<=[。！？!?])/);
  for(let s of sentences){
    s=s.trim();if(!s)continue;
    while(s.length>TTS_MAX){
      let cut=s.lastIndexOf('、',TTS_MAX);
      if(cut<20)cut=TTS_MAX; else cut+=1;
      parts.push(s.slice(0,cut));s=s.slice(cut).trim();
    }
    if(s)parts.push(s);
  }
  // 短い文は次の文とまとめる（1文ずつ区切ると、文の間が空きすぎて機械的に聞こえる）
  const out=[];
  for(const s of parts){
    if(out.length&&(out[out.length-1]+s).length<=TTS_MAX)out[out.length-1]+=s;
    else out.push(s);
  }
  return out;
}

/* ---------- 声の選び方 */
const FEMALE=/nanami|aoi|mayu|shiori|ayumi|haruka|sayaka|kyoko|o-?ren|mizuki|female|女性/i;
const MALE=/keita|daichi|naoki|ichiro|otoya|hattori|\bmale\b|男性/i;
function voiceScore(v){
  const n=(v.name||'')+' '+(v.voiceURI||'');
  if(/natural|neural/i.test(n))return 100;          // Edge のニューラル音声
  if(/google/i.test(n))return 80;                   // Chrome の Google 日本語
  if(/premium|enhanced|siri/i.test(n))return 75;    // Apple の高品質音声
  if(/online/i.test(n))return 70;
  if(/kyoko|o-?ren|otoya|hattori/i.test(n))return 50;
  if(/haruka|sayaka/i.test(n))return 30;            // Windows 標準（比較的なめらか）
  return 20;                                        // Ayumi・Ichiro など
}
function voiceGender(v){const n=v.name||'';return FEMALE.test(n)?'f':MALE.test(n)?'m':'';}
function voiceLabel(v){
  const short=(v.name||'').replace(/^(Microsoft|Apple)\s+/i,'').replace(/\s*(Online)?\s*\(.*$/i,'').replace(/\s+-\s+.*$/,'').trim()||v.name;
  const g=voiceGender(v);
  return short+(voiceScore(v)>=70?'（自然）':'')+(g==='f'?' ♀':g==='m'?' ♂':'');
}
function jaVoices(){
  if(!window.speechSynthesis)return [];
  return window.speechSynthesis.getVoices()
    .filter(v=>v.lang&&v.lang.replace('_','-').toLowerCase().startsWith('ja'))
    .sort((a,b)=>voiceScore(b)-voiceScore(a));
}
function pickJaVoice(){
  const vs=jaVoices();
  return vs.find(v=>v.name===settings.voice)||vs[0]||null;
}
// 会話の相手役の声：品質が大きく落ちない、性別の違う声（なければ null → 同じ声で高さを変える）
function partnerVoice(main){
  if(!main)return null;
  const g=voiceGender(main),floor=voiceScore(main)-30;
  const others=jaVoices().filter(v=>v.name!==main.name&&voiceScore(v)>=floor);
  return others.find(v=>voiceGender(v)&&voiceGender(v)!==g)||others[0]||null;
}

/* ---------- 声の選択メニューとヒント */
function populateVoices(){
  const sel=document.getElementById('tool-voice');
  const vs=jaVoices();
  if(sel){
    const cur=settings.voice||'';
    sel.innerHTML='';
    const auto=document.createElement('option');
    auto.value='';auto.textContent='声：自動'+(vs[0]?'（'+voiceLabel(vs[0])+'）':'');
    sel.appendChild(auto);
    vs.forEach(v=>{const o=document.createElement('option');o.value=v.name;o.textContent='声：'+voiceLabel(v);sel.appendChild(o);});
    sel.value=vs.some(v=>v.name===cur)?cur:'';
    sel.hidden=!vs.length;
  }
  // 機械的な声しかないときは、自然な声が使えるブラウザを案内する
  const best=vs[0];
  const robotic=!!best&&voiceScore(best)<70;
  document.querySelectorAll('.voice-hint').forEach(h=>h.hidden=!robotic);
}
function setVoice(name){
  settings.voice=name;saveSettings();
  sayWord('この声で読み上げます。');
}

function setStatus(msg){if(tts.status)tts.status.textContent=msg;}
function markReading(el){
  document.querySelectorAll('.np.reading,.turn.reading').forEach(p=>{if(p!==el)p.classList.remove('reading');});
  if(el)el.classList.add('reading');
}

function speakNext(session){
  if(session!==tts.session)return;
  if(tts.idx>=tts.queue.length){setStatus('✅ 再生完了');markReading(null);return;}
  const item=tts.queue[tts.idx];
  const u=new SpeechSynthesisUtterance(item.text);
  u.lang='ja-JP';u.rate=tts.rate;u.pitch=item.pitch||1;
  try{const v=item.voice||tts.voice;if(v)u.voice=v;}catch(e){} // 音声オブジェクトが無効でも lang 指定で読み続ける
  u.onend=()=>{if(session!==tts.session)return;tts.idx++;speakNext(session);};
  u.onerror=(e)=>{
    if(session!==tts.session||e.error==='interrupted'||e.error==='canceled')return;
    setStatus('❌ エラー（'+(e.error||'unknown')+'）ページを再読み込みしてみてください');markReading(null);
  };
  tts.current=u; // GC で onend が飛ばないよう参照を保持
  markReading(item.el||null);
  setStatus('▶ 再生中... '+(tts.idx+1)+'/'+tts.queue.length+(tts.voice?'（'+voiceLabel(item.voice||tts.voice)+'）':''));
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
  if(paras.length){paras.forEach(p=>splitForTTS(speechText(p)).forEach(t=>q.push({text:t,el:p})));}
  else{splitForTTS(speechText(el)).forEach(t=>q.push({text:t,el:null}));}
  return q;
}

// 会話：吹き出しごとに、話者に割り当てた声で読む
function dialogueQueue(only){
  const main=pickJaVoice(),partner=partnerVoice(main);
  const order=[],q=[];
  document.querySelectorAll('#tab-scene .turn').forEach(t=>{
    const badge=t.querySelector('.speaker-badge');
    const sp=badge?([...badge.classList].find(c=>c.indexOf('sp-')===0)||''):'';
    let i=order.indexOf(sp);if(i<0){order.push(sp);i=order.length-1;}
    let voice=main,pitch=1;
    if(i%2===1){if(partner)voice=partner;else pitch=0.82;}  // 2人目：別の声（なければ低め）
    if(i>=2)pitch=i%2?0.9:1.12;                             // 3人目以降：高さで区別
    if(only&&t!==only)return;
    const jp=t.querySelector('.b-jp');if(!jp)return;
    splitForTTS(speechText(jp).replace(/[「」『』]/g,'')).forEach(x=>q.push({text:x,el:t,voice:voice,pitch:pitch}));
  });
  return q;
}

function playTTS(srcId,playerId,statusId){
  if(srcId==='dialogue-full'&&document.querySelector('#tab-scene .turn')){
    startQueue(dialogueQueue(null),playerId,statusId);return;
  }
  const el=document.getElementById(srcId);if(!el)return;
  startQueue(queueFor(el),playerId,statusId);
}

function playPara(btn){
  const p=btn.closest('.np'),box=btn.closest('.news-text');if(!p||!box)return;
  const q=splitForTTS(speechText(p)).map(t=>({text:t,el:p}));
  startQueue(q,box.dataset.player,box.dataset.status);
}

function playTurn(btn){
  const t=btn.closest('.turn');if(!t)return;
  startQueue(dialogueQueue(t),'ttsdlg','statusdlg');
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
  window.speechSynthesis.onvoiceschanged=()=>{window.speechSynthesis.getVoices();populateVoices();};
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
  populateVoices();
  // 会話の吹き出しにセリフ単位の再生ボタン（シャドーイング用）
  document.querySelectorAll('#tab-scene .turn .bubble').forEach(b=>{
    const btn=document.createElement('button');
    btn.type='button';btn.className='t-play no-tts';btn.textContent='▶';
    btn.title='このセリフを読み上げ';btn.setAttribute('aria-label','このセリフを読み上げ');
    btn.addEventListener('click',()=>playTurn(btn));
    b.appendChild(btn);
  });
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
