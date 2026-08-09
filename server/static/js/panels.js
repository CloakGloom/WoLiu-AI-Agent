/**
 * AI Agent 面板模块 —— Spine动画 + 音乐条 + 设置 + GPU释放 + ComfyUI + 工具库 + 初始化
 * 依赖：core.js（全局变量 ws, connect 等）
 */

// ===== 输入框事件 =====
(function() {
    const inputBox = document.getElementById('inputBox');
    if (!inputBox) return;
    inputBox.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    inputBox.addEventListener('input', () => {
        inputBox.style.height = 'auto';
        inputBox.style.height = Math.min(inputBox.scrollHeight, 120) + 'px';
    });
})();

// ===== Spine 2D 动画 =====
let spinePlayer = null, spineReady = false, pendingSkin = null;

function initSpineAnimation() {
    const container = document.getElementById('spinePlayer');
    if (!container) return;
    function doInit() {
        try {
            spinePlayer = new spine.SpinePlayer(container, {
                jsonUrl: '/static/spine/character.json', atlasUrl: '/static/spine/character.atlas',
                skin: 'default', animation: 'blink', premultipliedAlpha: false, alpha: true,
                backgroundColor: '#00000000', showControls: false,
                success: (player) => { spinePlayer=player; spineReady=true; if(pendingSkin){switchSpineSkinDirect(pendingSkin);pendingSkin=null;} },
                error: () => fallbackAvatar()
            });
        } catch (e) { fallbackAvatar(); }
    }
    function fallbackAvatar() {
        const sc = document.getElementById('spineContainer');
        if (sc) sc.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:48px;"><i class="fas fa-robot"></i></div>';
    }
    if (typeof spine !== 'undefined' && spine.SpinePlayer) doInit();
    else { const s=document.createElement('script'); s.src='/static/spine-player.js'; s.onload=doInit; s.onerror=fallbackAvatar; document.head.appendChild(s); }
}

function switchSpineSkinDirect(skin) {
    if (!['default','happy','unhappy'].includes(skin)) return;
    if (!spineReady||!spinePlayer||!spinePlayer.skeleton) { pendingSkin=skin; return; }
    try {
        const mouthMap = { default:'mouth_smile', happy:'mouth_open', unhappy:'mouth_unhappy' };
        spinePlayer.skeleton.setAttachment('mouth', mouthMap[skin]);
        spinePlayer.skeleton.setSlotsToSetupPose();
    } catch(e) {}
}

// ===== 启动 =====
connect();
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initSpineAnimation);
else initSpineAnimation();

setTimeout(() => {
    const ib = document.getElementById('inputBox'), sb = document.getElementById('sendBtn'), ub = document.getElementById('uploadBtn');
    if (ib && ib.disabled) { ib.disabled=false; if(sb)sb.disabled=false; if(ub)ub.disabled=false; }
}, 3000);

// ===== 音乐播放条 =====
let musicBarVisible=false, musicBarPlaying=false, musicBarPosition=0, musicBarDuration=0, musicBarPollTimer=null, musicBarSeeking=false;

function updateMusicBar(content) {
    const bar = document.getElementById('musicBar'); if (!bar) return;
    const m = content.match(/\[MUSIC:(\w+)(?:\|([^|]*))?(?:\|([^|]*))?(?:\|([^|]*))?(?:\|([^|\]]*))?\]/); if (!m) return;
    const status=m[1], title=m[2]||'', pos=parseFloat(m[4])||0, dur=parseFloat(m[5])||0;
    if (status==='playing') { musicBarVisible=true;musicBarPlaying=true;musicBarPosition=pos;musicBarDuration=dur;bar.style.display='flex';bar.classList.remove('paused','stopped');setElText('musicBarTitle',title||'正在播放...');document.getElementById('musicBtnPlay').innerHTML='&#10074;&#10074;';updateProgressBar(pos,dur);startMusicPolling(); }
    else if(status==='paused') { musicBarVisible=true;musicBarPlaying=false;bar.style.display='flex';bar.classList.add('paused');bar.classList.remove('stopped');setElText('musicBarTitle',title||'已暂停');document.getElementById('musicBtnPlay').innerHTML='&#9654;';updateProgressBar(musicBarPosition,musicBarDuration);stopMusicPolling(); }
    else if(status==='stopped') { musicBarVisible=true;musicBarPlaying=false;bar.style.display='flex';bar.classList.add('paused','stopped');setElText('musicBarTitle','播放结束');document.getElementById('musicBtnPlay').innerHTML='&#9654;';stopMusicPolling(); }
}

function updateProgressBar(pos,dur){const s=document.getElementById('musicBarSlider');if(!s)return;const pct=dur>0?(pos/dur)*100:0;if(!musicBarSeeking)s.value=pct;setElText('musicBarTime',formatTime(pos));setElText('musicBarDuration',formatTime(dur));}
function formatTime(seconds){const s=Math.max(0,Math.floor(seconds||0));return`${Math.floor(s/60)}:${(s%60).toString().padStart(2,'0')}`;}
function startMusicPolling(){stopMusicPolling();musicBarPollTimer=setInterval(()=>{if(!musicBarPlaying||musicBarSeeking)return;musicBarAction('status');},2000);}
function stopMusicPolling(){if(musicBarPollTimer){clearInterval(musicBarPollTimer);musicBarPollTimer=null;}}
function onMusicSeek(pct){musicBarSeeking=true;const dur=musicBarDuration||0;setElText('musicBarTime',formatTime((pct/100)*dur));}
function onMusicSeekEnd(){const s=document.getElementById('musicBarSlider');if(!s||!musicBarDuration){musicBarSeeking=false;return;}const pct=parseFloat(s.value);if(ws&&ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'music_control',action:'seek',seek_seconds:Math.round((pct/100)*musicBarDuration)}));musicBarSeeking=false;}
function toggleMusicPlay(){musicBarAction(musicBarPlaying?'pause':'resume');}
function musicBarAction(action){if(ws&&ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'music_control',action}));}
function closeMusicBar(){const bar=document.getElementById('musicBar');if(bar){bar.style.display='none';musicBarVisible=false;musicBarPlaying=false;stopMusicPolling();}}

// ===== 自启动管理 =====
function toggleAutostart(service){fetch('/api/autostart/'+service,{method:'POST'}).then(r=>r.json()).then(d=>updateAutostartBtn(service,d.enabled)).catch(()=>{});}
function updateAutostartBtn(service,enabled){var a=document.getElementById('as-'+service),b=document.getElementById('s_as_'+service);if(a){a.className='svc-btn svc-btn--auto'+(enabled?' is-on':'');a.textContent=enabled?'已自启':'自启动';}if(b){b.className='svc-btn svc-btn--auto'+(enabled?' is-on':'');b.textContent=enabled?'已自启':'自启动';}}
function loadAutostartConfig(){fetch('/api/autostart').then(r=>r.json()).then(cfg=>{for(var k in cfg)updateAutostartBtn(k,cfg[k]);}).catch(()=>{});}
setTimeout(loadAutostartConfig,1500);

// ===== GPU 释放 / 退出 =====
function releaseGPU(){var a=document.getElementById('gpu-release-btn'),b=document.getElementById('s_gpu_release_btn');upd=function(btn){if(!btn)return;btn.disabled=true;btn.textContent='释放中...';};upd(a);upd(b);if(ws&&ws.readyState===WebSocket.OPEN){ws.send(JSON.stringify({type:'gpu_release'}));updateComfyUIButton(false);updateSvcBtn('s_comfyui_btn',false);setTimeout(function(){res=function(btn){if(!btn)return;btn.disabled=false;btn.textContent='释放 GPU 显存';};res(a);res(b);},3000);}}
function quitApp(){if(!confirm('确定退出程序？\n\n点击"确定"后会询问是否保留后台服务。'))return;var k=[];if(confirm('保留 ComfyUI（AI绘画/视频）后台运行？\n点"确定"保留，点"取消"关闭'))k.push('comfyui');if(ws&&ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'shutdown',keep_services:k}));setTimeout(()=>window.close(),500);}

// ===== ComfyUI =====
let comfyuiPollTimer=null,comfyuiStarting=false;

function updateComfyUIButton(running){
    const btn=document.getElementById('comfyui-btn'),st=document.getElementById('comfyui-status');if(!btn||!st)return;
    if(running){btn.className='svc-btn svc-btn--toggle is-on';btn.textContent='已就绪';btn.title='点击关闭 ComfyUI';btn.onclick=stopComfyUI;btn.onmouseenter=function(){this.textContent='关闭';};btn.onmouseleave=function(){this.textContent='已就绪';};st.textContent='绘画功能可用';clearInterval(comfyuiPollTimer);comfyuiPollTimer=null;comfyuiStarting=false;}
    else{if(comfyuiStarting)return;btn.className='svc-btn svc-btn--toggle is-off';btn.textContent='已关闭';btn.title='点击开启 ComfyUI';btn.onclick=toggleComfyUI;btn.onmouseenter=function(){this.textContent='开启';};btn.onmouseleave=function(){this.textContent='已关闭';};st.textContent='点击按钮开启';}
}
function stopComfyUI(){var b=document.getElementById('comfyui-btn'),s=document.getElementById('comfyui-status');if(!b)return;b.className='svc-btn svc-btn--toggle is-loading';b.textContent='关闭中...';b.onclick=null;b.onmouseenter=null;b.onmouseleave=null;if(s)s.textContent='正在关闭...';if(ws&&ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'comfyui_stop'}));setTimeout(()=>{b.className='svc-btn svc-btn--toggle is-off';b.textContent='已关闭';b.onclick=toggleComfyUI;b.onmouseenter=function(){this.textContent='开启';};b.onmouseleave=function(){this.textContent='已关闭';};if(s)s.textContent='已关闭';},2000);}
function toggleComfyUI(){const b=document.getElementById('comfyui-btn'),s=document.getElementById('comfyui-status');if(!b||!s)return;comfyuiStarting=true;b.className='svc-btn svc-btn--toggle is-loading';b.textContent='启动中...';b.title='';b.onclick=null;b.onmouseenter=null;b.onmouseleave=null;s.textContent='正在启动 ComfyUI...';if(ws&&ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'comfyui_start'}));}
function restartComfyUI(){const b=document.getElementById('comfyui-btn'),s=document.getElementById('comfyui-status');if(!b||!s)return;b.className='svc-btn svc-btn--toggle is-loading';b.textContent='重启中...';b.title='';b.onclick=null;b.onmouseenter=null;b.onmouseleave=null;s.textContent='正在重启 ComfyUI...';if(ws&&ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'comfyui_restart'}));}
function pollComfyUIStatus(){clearInterval(comfyuiPollTimer);let attempts=0;comfyuiPollTimer=setInterval(()=>{attempts++;if(ws&&ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'comfyui_status'}));if(attempts>=60){clearInterval(comfyuiPollTimer);comfyuiPollTimer=null;comfyuiStarting=false;updateComfyUIButton(false);const s=document.getElementById('comfyui-status');if(s)s.textContent='启动超时，请检查 ComfyUI';}},2000);}

// ===== 服务管理面板 =====
function openServicesPanel(){var m=document.getElementById('servicesModal');if(m)m.style.display='flex';if(typeof ws!=='undefined'&&ws&&ws.readyState===WebSocket.OPEN){ws.send(JSON.stringify({type:'comfyui_status'}));ws.send(JSON.stringify({type:'tts_status'}));ws.send(JSON.stringify({type:'jadeai_status'}));ws.send(JSON.stringify({type:'presenton_status'}));ws.send(JSON.stringify({type:'ollama_status'}));ws.send(JSON.stringify({type:'autolabel_status'}));}}

// 通用服务按钮状态更新（配合 setupStopStart 的 _doStart/_doStop）
function updateSvcBtn(id,running){
  var b=document.getElementById(id);if(!b||!b._doStart)return;
  // 按钮处于过渡中（is-loading）：仅 running=true 时允许更新（服务已启动就绪）；
  // running=false 时跳过（轮询状态查询，不应覆盖 _doStart/_doStop 设置的"启动中..."/"关闭中..."文本）
  if(b.className.indexOf('is-loading')!==-1 && !running)return;
  if(running){
    b.className='svc-btn svc-btn--toggle is-on';b.textContent='已就绪';b._running=true;b.onclick=b._doStop;
    b.onmouseenter=function(){this.textContent='关闭';};b.onmouseleave=function(){this.textContent='已就绪';};
  }else{
    b.className='svc-btn svc-btn--toggle is-off';b.textContent='已关闭';b._running=false;b.onclick=b._doStart;
    b.onmouseenter=function(){this.textContent='开启';};b.onmouseleave=function(){this.textContent='已关闭';};
  }
}
function closeServicesPanel(){var m=document.getElementById('servicesModal');if(m)m.style.display='none';}
(function(){var m=document.getElementById('servicesModal');if(m)m.addEventListener('click',function(e){if(e.target===m)closeServicesPanel();});})();

// ===== 工具库 =====
let allTools=[],allTags=[];

async function openToolsLibrary(){document.getElementById('toolsModal').style.display='flex';if(allTools.length===0){try{const r=await fetch('/api/tools'),d=await r.json();allTools=d.tools||[];allTags=d.tags||[];document.getElementById('toolsCount').textContent=`共 ${allTools.length} 个工具`;buildTagButtons();}catch(e){document.getElementById('toolsList').innerHTML='<div style="text-align:center;color:#e74c3c;padding:40px">加载失败</div>';return;}}renderToolsList('all');}
function buildTagButtons(){const c=document.getElementById('toolFilterBtns');c.innerHTML='<button class="tool-filter-btn active" data-tag="all" onclick="filterTools(\'all\')">全部</button>';for(const t of allTags){const b=document.createElement('button');b.className='tool-filter-btn';b.dataset.tag=t;b.setAttribute('onclick',`filterTools('${t}')`);b.textContent=t;c.appendChild(b);}}
function closeToolsLibrary(){document.getElementById('toolsModal').style.display='none';}
function filterTools(tag){document.querySelectorAll('.tool-filter-btn').forEach(b=>b.classList.toggle('active',b.dataset.tag===tag));renderToolsList(tag);}
async function toggleTool(tn){try{const r=await fetch('/api/tools/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:tn})}),d=await r.json();const t=allTools.find(x=>x.name===tn);if(t)t.enabled=d.enabled;const at=document.querySelector('.tool-filter-btn.active')?.dataset?.tag||'all';renderToolsList(at);}catch(e){console.error('Toggle tool failed:',e);}}
function renderToolsList(tag){const c=document.getElementById('toolsList'),f=tag==='all'?allTools:allTools.filter(t=>t.tag===tag);if(f.length===0){c.innerHTML='<div class="modal-empty">该分类下暂无工具</div>';return;}let h='';for(const t of f){const ph=t.parameters.length>0?t.parameters.map(p=>`<div class="tool-param"><code>${p.name}</code> <span>${p.type}</span>${p.required?'<span class="req">必填</span>':'<span class="opt">可选</span>'}${p.description?`<br><span style="opacity:.8">${p.description}</span>`:''}${p.enum?.length?`<br><span style="opacity:.75">可选值: ${p.enum.join(', ')}</span>`:''}</div>`).join(''):'<div class="tool-param" style="opacity:.7">无参数</div>';h+=`<div class="tool-card${t.enabled?'':' disabled'}" data-tag="${t.tag}"><div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;gap:8px"><div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap"><code class="tool-name">${t.name}</code><span class="tool-tag">${t.tag}</span><span class="tool-state ${t.enabled?'on':'off'}">${t.enabled?'已启用':'已禁用'}</span></div><div style="display:flex;align-items:center;gap:8px">${t.source?`<span class="tool-source" title="${t.source}">${t.source.split('/').pop()}</span>`:''}<button class="tool-toggle ${t.enabled?'disable':'enable'}" onclick="toggleTool('${t.name}')">${t.enabled?'禁用':'启用'}</button></div></div><div class="tool-desc">${t.description}</div>${ph}</div>`;}c.innerHTML=h;}
