/* ---------------------------------------------------------------- タブ */
function switchTab(name){
  const names=['news','scene','ext'];
  names.forEach(t=>document.getElementById('tab-'+t).classList.add('hidden'));
  document.getElementById('tab-'+name).classList.remove('hidden');
  document.querySelectorAll('.tab').forEach((el,i)=>el.classList.toggle('active',names[i]===name));
  stopTTS();
  try{sessionStorage.setItem(storeKey('tab'),name);}catch(e){}
}

/* ---------------------------------------------------------------- ツールチップ */
let openTooltip=null;
function showTooltip(id){
  if(openTooltip&&openTooltip!==id){const p=document.getElementById(openTooltip);if(p)p.classList.add('hidden');}
  const el=document.getElementById(id);if(!el)return;
  el.classList.toggle('hidden');
  openTooltip=el.classList.contains('hidden')?null:id;
  // 解説は本文の下にまとめて置かれるので、画面外なら見える位置まで寄せる
  if(openTooltip&&el.scrollIntoView)el.scrollIntoView({block:'nearest',behavior:'smooth'});
}

/* ---------------------------------------------------------------- 音声読み上げ（TTS）
 * Chrome は1回の発話が長いと約15秒で無言のまま止まるため、文単位に分けて順番に読む。
 * 分割は「。！？」で行い、長すぎる文はさらに「、」で切る。 */
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
  const vs=window.speechSynthesis.getVoices().filter(v=>v.lang&&v.lang.replace('_','-').toLowerCase().startsWith('ja'));
  // Edge の自然音声（Natural）> ローカル音声 > その他
  return vs.find(v=>/natural/i.test(v.name))||vs.find(v=>v.localService)||vs[0]||null;
}

function setStatus(msg){if(tts.status)tts.status.textContent=msg;}

function speakNext(session){
  if(session!==tts.session)return;
  if(tts.idx>=tts.queue.length){setStatus('✅ 再生完了');return;}
  const u=new SpeechSynthesisUtterance(tts.queue[tts.idx]);
  u.lang='ja-JP';u.rate=tts.rate;
  try{if(tts.voice)u.voice=tts.voice;}catch(e){} // 音声オブジェクトが無効でも lang 指定で読み続ける
  u.onend=()=>{if(session!==tts.session)return;tts.idx++;speakNext(session);};
  u.onerror=(e)=>{
    if(session!==tts.session||e.error==='interrupted'||e.error==='canceled')return;
    setStatus('❌ エラー（'+(e.error||'unknown')+'）ページを再読み込みしてみてください');
  };
  tts.current=u; // GC で onend が飛ばないよう参照を保持
  setStatus('▶ 再生中... '+(tts.idx+1)+'/'+tts.queue.length);
  window.speechSynthesis.speak(u);
}

function playTTS(srcId,playerId,statusId){
  if(!window.speechSynthesis){alert('お使いのブラウザは音声合成に対応していません。Chrome/Edgeをお試しください。');return;}
  const el=document.getElementById(srcId);if(!el)return;
  const text=(el.innerText||el.textContent).trim();if(!text)return;
  window.speechSynthesis.cancel();
  if(tts.status&&tts.status.id!==statusId)setStatus('▶ 再生ボタンを押してください');
  const sel=document.getElementById('speed-'+playerId);
  tts={session:tts.session+1,queue:splitForTTS(text),idx:0,
       status:document.getElementById(statusId),rate:sel?parseFloat(sel.value):1.0,voice:pickJaVoice()};
  if(!tts.voice)setStatus('⚠️ 日本語音声が見つかりません（OSの音声設定を確認）');
  const s=tts.session;
  setTimeout(()=>speakNext(s),60); // cancel 直後の speak は Chrome で無視されることがある
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
  if(tts.status&&tts.queue.length)setStatus('⏹ 停止しました');
}

if(window.speechSynthesis){
  window.speechSynthesis.getVoices();
  window.speechSynthesis.onvoiceschanged=()=>window.speechSynthesis.getVoices();
  window.addEventListener('beforeunload',()=>window.speechSynthesis.cancel());
}

/* ---------------------------------------------------------------- メモ欄の自動保存
 * ブラウザ内（localStorage）に教材の日付ごとに保存する。使えない環境では何もしない。 */
function storeKey(k){return 'n1lesson:'+(document.body.dataset.date||location.pathname)+':'+k;}
document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('textarea.notes-area').forEach((ta,i)=>{
    const key=storeKey('notes'+i);
    try{const v=localStorage.getItem(key);if(v)ta.value=v;}catch(e){}
    let timer=null;
    ta.addEventListener('input',()=>{
      clearTimeout(timer);
      timer=setTimeout(()=>{try{localStorage.setItem(key,ta.value);}catch(e){}},400);
    });
  });
  try{const t=sessionStorage.getItem(storeKey('tab'));if(t&&t!=='news'&&document.getElementById('tab-'+t))switchTab(t);}catch(e){}
});
