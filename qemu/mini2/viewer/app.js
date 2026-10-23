const $ = id => document.getElementById(id);
const el = {device:$('device'),canvas:$('matrixCanvas'),stateName:$('stateName'),qemu:$('qemu'),conn:$('conn'),clockLive:$('clock-live'),bootlog:$('bootlog'),events:$('events'),ctlHint:$('ctlHint')};
const ctx = el.canvas.getContext('2d');
let firmware = null, qemuUp = false, busy = false, logText = '', toastTimer;
const digitSegments = {'0':'ABCDEF','1':'BC','2':'ABDEG','3':'ABCDG','4':'BCFG','5':'ACDFG','6':'ACDEFG','7':'ABC','8':'ABCDEFG','9':'ABCDFG','-':'G'};
const segmentLines = {A:[5,4,20,4],B:[23,7,23,20],C:[23,27,23,40],D:[5,43,20,43],E:[2,27,2,40],F:[2,7,2,20],G:[5,24,20,24]};
function drawClock(event = {}) {
  ctx.clearRect(0,0,162,57);
  const chars = String(event.clock || '     ').replace(':','').replace(' ','').padEnd(4,' ');
  const raw = event.segs;
  const dot = (x,y,level) => {
    if (!level) return;
    ctx.fillStyle = `rgba(250,244,235,${Math.min(1,level/150)})`;
    ctx.shadowBlur=3;ctx.shadowColor='#fff6e4';
    ctx.beginPath();ctx.arc(x,y,1.35,0,Math.PI*2);ctx.fill();
  };
  for(let n=0;n<4;n++) {
    const offset = 13+n*33+(n>1?8:0);
    for(const [segment,line] of Object.entries(segmentLines)) {
      const brightness = raw ? Number(raw[segment+(n+1)] || 0) : (digitSegments[chars[n]]||'').includes(segment)?180:0;
      const [x1,y1,x2,y2]=line;
      for(let i=0;i<5;i++) dot(offset+x1+(x2-x1)*i/4,5+y1+(y2-y1)*i/4,brightness);
    }
  }
  const colon = raw ? [raw.PLUS1,raw.PLUS2] : [event.clock?.includes(':')?180:0,event.clock?.includes(':')?180:0];
  dot(79,22,colon[0]);dot(79,34,colon[1]);
  if(event.degree) {ctx.strokeStyle='#fff6e4';ctx.lineWidth=1.5;ctx.beginPath();ctx.arc(157,10,2,0,7);ctx.stroke();}
}

function applyRing(colors=[]) {
  const rgb=Array.from({length:6},(_,i)=>{
    const color=/^#[0-9a-f]{6}$/i.test(colors[i]||'')?colors[i]:'#000000';
    $('ringCore').style.setProperty('--led-'+i,color);
    return [1,3,5].map(offset=>parseInt(color.slice(offset,offset+2),16));
  });
  // Optical diffusion mixes emitted light in linear RGB, preserving its hue.
  const linear=c=>c<=10.31475?c/3294.6:Math.pow((c/255+.055)/1.055,2.4);
  const srgb=c=>Math.round(255*(c<=.0031308?12.92*c:1.055*Math.pow(c,1/2.4)-.055));
  const average=[0,1,2].map(channel=>srgb(rgb.reduce((sum,c)=>sum+linear(c[channel]),0)/6));
  const glow='#'+average.map(c=>c.toString(16).padStart(2,'0')).join('');
  const lit=rgb.some(c=>c.some(value=>value>0));
  el.device.style.setProperty('--ring-c',glow);
  el.device.classList.add('hw');
  $('ringCore').classList.toggle('lit',lit);
  $('ringGlow').style.opacity=lit?'0.7':'0';
  $('ringGlow').style.background=`radial-gradient(circle, ${glow}75, transparent 70%)`;
}
function toast(message){$('toast').textContent=message;$('toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.remove('visible'),4000);}
function pushEvent(kind,message,ts=Date.now()/1000){const li=document.createElement('li'),t=document.createElement('span'),m=document.createElement('span'),k=document.createElement('span');t.className='t';t.textContent=new Date(ts*1000).toLocaleTimeString('ru-RU');k.className='event-kind';k.textContent=kind;m.append(k,document.createTextNode(String(message)));li.append(t,m);el.events.prepend(li);while(el.events.children.length>60)el.events.lastChild.remove();$('eventCount').textContent=el.events.children.length;}
function updateControls(){const toggle=$('powerToggle');toggle.disabled=busy;$('rebootButton').disabled=busy||!qemuUp;toggle.classList.toggle('running',qemuUp);$('powerLabel').textContent=busy?'Подождите…':qemuUp?'Выключить':'Запустить';}
function setService(name,value,fresh){const node=$('service-'+name);node.className='service-status'+(fresh?(value?' ok':' wait'):' off');node.querySelector('span').textContent=!fresh?'Нет данных':value?(name==='network'?'Настроена':name==='sound'?'Доступна':'Работает'):(name==='keymaster'?'Недоступна':'Остановлен');}
async function loadFirmwareStatus(){try{const r=await fetch('/api/firmware');if(!r.ok)return;firmware=await r.json();for(const name of ['platformd','mediad','network','bluetooth','sound','keymaster'])setService(name,firmware[name],firmware.fresh);$('firmwareStatus').textContent=!qemuUp?'Станция выключена. Запустите её, чтобы проверить сервисы.':!firmware.fresh?'Ожидается отчёт из гостевой системы.':firmware.platformd?'Службы Алисы запущены. Подключение из приложения ещё не готово.':'Гостевая система работает. Службы Алисы запускаются.';el.stateName.textContent=!qemuUp?'Станция выключена':!firmware.fresh?'Загрузка системы':firmware.platformd?'Алиса · службы запущены':'Запуск служб Алисы';$('stateIndicator').style.background=firmware.fresh&&firmware.platformd?'#8eb39f':'#a993b8';}catch{}}
async function pollQemu(){try{const r=await fetch('/api/qemu');if(!r.ok)return;const j=await r.json();qemuUp=!!j.up;el.qemu.textContent=qemuUp?'QEMU запущен':'QEMU выключен';el.qemu.className=qemuUp?'pill ok':'pill dim';if(!busy)el.ctlHint.textContent=qemuUp?'Состояние и подсветка поступают из прошивки':'Включите станцию, чтобы продолжить';updateControls();}catch{el.qemu.textContent='Нет связи';el.qemu.className='pill dim';$('powerToggle').disabled=true;$('rebootButton').disabled=true;}}
async function loadConsole(){try{const r=await fetch('/api/console');if(!r.ok)return;const j=await r.json();logText=String(j.text||'').replace(/\x1b\[[0-9;?]*[ -/]*[@-~]/g,'').replace(/\r/g,'');if(el.bootlog.textContent!==logText)el.bootlog.textContent=logText;if($('autoScroll').checked)el.bootlog.scrollTop=el.bootlog.scrollHeight;}catch{}}
async function qemuAction(action){if(busy)return;busy=true;updateControls();el.ctlHint.textContent=({boot:'Запуск…',stop:'Выключение…',reboot:'Перезапуск…',clear:'Очистка…'})[action];try{const r=await fetch('/api/qemu',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});const j=await r.json();if(!r.ok||j.ok===false)throw Error(j.error||'Не удалось выполнить действие');qemuUp=!!j.up;if(action==='clear'){el.bootlog.textContent='';logText='';}if(action==='stop'){drawClock();applyRing();}toast(({boot:'Станция запускается',stop:'Станция выключена',reboot:'Станция перезапускается',clear:'Журнал очищен'})[action]);}catch(e){toast(e.message);}finally{busy=false;updateControls();await pollQemu();await loadFirmwareStatus();}}
$('powerToggle').addEventListener('click',()=>qemuAction(qemuUp?'stop':'boot'));$('rebootButton').addEventListener('click',()=>qemuAction('reboot'));document.querySelectorAll('[data-qemu]').forEach(b=>b.addEventListener('click',()=>qemuAction(b.dataset.qemu)));
$('downloadLog').addEventListener('click',async()=>{await loadConsole();const url=URL.createObjectURL(new Blob([logText],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='mini2-console.log';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
const stream=new EventSource('/api/stream');stream.onopen=()=>{el.conn.textContent='Соединено';el.conn.className='pill ok';};stream.onerror=()=>{el.conn.textContent='Нет связи';el.conn.className='pill dim';};stream.onmessage=message=>{try{const e=JSON.parse(message.data);if(e.state==='hw'){applyRing(e.ring);drawClock(e);}else if(!['boot','log'].includes(e.state))pushEvent(e.state,e.message||e.state,e.ts);}catch{}};
function updateClock(){el.clockLive.textContent=new Date().toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});}drawClock();updateClock();pollQemu().then(loadFirmwareStatus);loadConsole();setInterval(updateClock,1000);setInterval(pollQemu,2500);setInterval(loadFirmwareStatus,4000);setInterval(loadConsole,3000);
