/**
 * AI Agent 核心模块 —— WebSocket + 消息处理 + 渲染 + 状态 + 迁移 + 文件上传
 * 依赖：先于 sessions.js 和 panels.js 加载
 */

// ===== WebSocket 连接 =====
const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
const wsUrl = `${protocol}//${location.host}/ws`;
let ws = null;
let isAgentOnline = true;
let isMigrating = false;
let migrateTimer = null;
let reconnectTimer = null;

function connect() {
    if (ws && ws.readyState === WebSocket.OPEN) return;
    ws = new WebSocket(wsUrl);
    ws.onopen = () => {
        updateWsStatus('已连接', '#52C41A');
        ws.send(JSON.stringify({ type: 'register', client_type: 'pc' }));
        clearReconnect();
        setTimeout(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'comfyui_status' }));
            }
        }, 500);
    };
    ws.onmessage = (e) => handleMessage(JSON.parse(e.data));
    ws.onclose = () => {
        updateWsStatus('已断开，重连中...', '#FF4D4F');
        scheduleReconnect();
    };
    ws.onerror = () => updateWsStatus('连接错误', '#FF4D4F');
}

function scheduleReconnect() { clearReconnect(); reconnectTimer = setTimeout(connect, 3000); }
function clearReconnect() { if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; } }

// ===== 安全 WS 发送 =====
function wsSend(obj) {
    try { if (ws && ws.readyState === WebSocket.OPEN) { ws.send(JSON.stringify(obj)); return true; } }
    catch (e) { console.warn('WS 发送失败:', e); }
    return false;
}

async function refreshAfterChange(targetId) {
    const wsOk = wsSend({ type: 'switch_session', session_id: targetId });
    try {
        const r = await fetch('/api/sessions');
        const data = await r.json();
        renderSessionList(data.sessions || [], targetId);
        if (!wsOk) {
            const mr = await fetch('/api/sessions/' + targetId + '/messages');
            const md = await mr.json();
            loadHistory((md.messages || []).filter(m => m.role === 'user' || m.role === 'assistant'));
        }
    } catch (e) { console.error('刷新会话失败:', e); }
}

function updateWsStatus(text, color) {
    const el = document.getElementById('wsStatusText');
    if (el) { el.textContent = text; el.style.color = color; }
}

// ===== 消息处理 =====
let currentProcessGroup = null;
let currentSessionId = null;
let tempIdCounter = -1;
let streamingState = null;
let progressBars = {};

function handleMessage(msg) {
    switch (msg.type) {
        case 'status':
            updateStatus(msg['state.agent_location'] || msg.agent_location, msg.status);
            break;
        case 'history': loadHistory(msg.messages); break;
        case 'session_list': renderSessionList(msg.sessions, msg.current); break;
        case 'process': handleProcessStep(msg.step); break;
        case 'stream_start': handleStreamStart(); break;
        case 'stream_delta': handleStreamDelta(msg.delta); break;
        case 'stream_done': handleStreamDone(msg.content); break;
        case 'progress': handleProgress(msg); break;
        case 'response':
            currentProcessGroup = null;
            addMessage('agent', msg.content, null, null, msg.chunk_index, msg.chunk_total);
            checkMigrationComplete(msg.content);
            break;
        case 'migrate_data':
            loadHistory(msg.messages);
            ws.send(JSON.stringify({ type: 'migrate_ack', status: 'ok' }));
            break;
        case 'migrate_ack': break;
        case 'music_state': updateMusicBar(msg.result); break;
        case 'comfyui_status': updateComfyUIButton(msg.running); break;
        case 'comfyui_start_result':
            if (msg.success) pollComfyUIStatus();
            else { updateComfyUIButton(false); setElText('comfyui-status', msg.message); }
            break;
        case 'comfyui_restart_result':
            updateComfyUIButton(msg.success);
            if (!msg.success) setElText('comfyui-status', msg.message);
            break;

        case 'error': addMessage('system', msg.content); break;
    }
}

function handleProcessStep(step) {
    if (step.type === 'tool_result' && step.content) {
        if (step.content.includes('[EXPRESSION:')) {
            const m = step.content.match(/\[EXPRESSION:(\w+)\]/);
            if (m) switchSpineSkinDirect(m[1]);
        }
        if (step.content.includes('[MUSIC:')) updateMusicBar(step.content);
    }
    if (!currentProcessGroup) {
        if (step.type === 'tool_call' || step.type === 'tool_result') currentProcessGroup = createProcessGroup();
        else return;
    }
    addProcessStep(currentProcessGroup, step);
}

function createProcessGroup() {
    const container = document.getElementById('chatMessages');
    const welcome = container.querySelector('.welcome-message');
    if (welcome) welcome.remove();
    const group = document.createElement('div');
    group.className = 'process-group';
    const toggle = document.createElement('button');
    toggle.className = 'process-toggle';
    toggle.innerHTML = `<span class="toggle-icon">&#9654;</span><span>思考过程</span><span class="process-summary">正在思考...</span>`;
    toggle.addEventListener('click', () => group.classList.toggle('expanded'));
    const steps = document.createElement('div');
    steps.className = 'process-steps';
    group.appendChild(toggle);
    group.appendChild(steps);
    container.appendChild(group);
    scrollToBottom();
    return group;
}

function addProcessStep(group, step) {
    const steps = group.querySelector('.process-steps');
    const summary = group.querySelector('.process-summary');
    const stepEl = document.createElement('div');
    stepEl.className = 'process-step';
    let icon = '', label = '', cssClass = '';
    switch (step.type) {
        case 'thinking': icon = '&#9678;'; label = '思考中...'; cssClass = 'thinking'; summary.textContent = '正在思考...'; break;
        case 'tool_call':
            icon = '&#9881;'; label = `调用工具: <code>${escapeHtml(step.name)}</code>`;
            cssClass = 'tool-call'; summary.textContent = `调用工具: ${step.name}`;
            if (step.arguments && Object.keys(step.arguments).length > 0)
                label += `<pre>${escapeHtml(JSON.stringify(step.arguments, null, 2))}</pre>`;
            break;
        case 'tool_result':
            icon = '&#10003;'; label = `工具结果: ${escapeHtml(step.content)}`;
            cssClass = 'tool-result'; summary.textContent = `获取结果: ${step.name}`;
            break;
    }
    stepEl.className = `process-step ${cssClass}`;
    stepEl.innerHTML = `<span class="step-icon">${icon}</span><span class="step-content">${label}</span>`;
    steps.appendChild(stepEl);
    scrollToBottom();
}

function checkMigrationComplete(content) {
    if (isMigrating && (content.includes('迁移成功') || content.includes('已在'))) completeMigration();
}

// ===== 流式回复 =====
let streamTtsRef = null;
let ttsUserEnabled = false;

function detectTtsRef() {
    var msgs = document.querySelectorAll('.msg-system');
    for (var i = msgs.length-1; i >= 0; i--) {
        var m = msgs[i].textContent.match(/I:\/Agent\/data\/uploads\/[^\s]+\.(mp3|wav|m4a|flac)/i);
        if (m) return m[0];
    }
    return null;
}

function handleStreamStart() {
    if (streamingState) streamingState = null;
    currentProcessGroup = null;
    streamTtsRef = ttsUserEnabled ? detectTtsRef() : null;
    if (ttsUserEnabled) {
        fetch('/api/tts/detect-ref').then(r => r.json()).then(d => { if (d.ref) streamTtsRef = d.ref; }).catch(() => {});
    }
    var container = document.getElementById('chatMessages');
    var welcome = container.querySelector('.welcome-message');
    if (welcome) welcome.remove();
    streamingState = { row: null, textEl: null, buffer: '' };
}

function handleStreamDelta(delta) {
    if (!delta) return;
    if (!streamingState) handleStreamStart();
    streamingState.buffer += delta;
}

function handleStreamDone(content) {
    if (streamingState) streamingState = null;
    document.querySelectorAll('.stream-cursor').forEach(el => el.remove());
    currentProcessGroup = null;
    if (content) { var sentences = splitSentences(content); showSentencesWithTTS(sentences, content); checkMigrationComplete(content); }
    scrollToBottom();
}

function splitSentences(text) {
    text = text.replace(/\|\|\|/g, '\n\n');
    var chunks = [];
    var paragraphs = text.split(/\n\s*\n/);
    for (var i = 0; i < paragraphs.length; i++) {
        var para = paragraphs[i].trim();
        if (!para) continue;
        var subs = para.split(/(?<=[。！？?～…\n])/);
        for (var j = 0; j < subs.length; j++) {
            var s = subs[j].trim();
            if (!s) continue;
            if (s.length > 80) { var sub2 = s.split(/(?<=[，,；;])/); for (var k = 0; k < sub2.length; k++) { var x = sub2[k].trim(); if (x) chunks.push(x); } }
            else chunks.push(s);
        }
    }
    var merged = [];
    for (var m = 0; m < chunks.length; m++)
        if (merged.length && (merged[merged.length-1].length + chunks[m].length) < 30) merged[merged.length-1] += chunks[m];
        else if (chunks[m]) merged.push(chunks[m]);
    return merged.filter(c => c.length > 0);
}

function showSentencesWithTTS(sentences, fullContent) {
    var i = 0, rows = [];
    function next() {
        if (i >= sentences.length) {
            if (/\[(IMAGE|PAPER):/.test(fullContent)) { var lastRow = rows[rows.length-1]; if (lastRow) { var b = lastRow.querySelector('.msg-bubble'); if (b) b.innerHTML = formatMessageContent(fullContent); } }
            scrollToBottom();
            if (streamTtsRef) speakFullText(fullContent);
            return;
        }
        var text = sentences[i]; i++;
        addMessage('agent', text, null, null, 0, 1);
        var container = document.getElementById('chatMessages');
        var allRows = container.querySelectorAll('.msg-row.agent');
        var row = allRows[allRows.length-1];
        if (row) rows.push(row);
        scrollToBottom();
        setTimeout(next, 200);
    }
    next();
}

function speakFullText(text) {
    if (!text || !streamTtsRef) return;
    var cleanText = text.replace(/\[(IMAGE|PAPER|VIDEO):[^\]]+\]/g, '');
    fetch('/api/tts/speak', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({text:cleanText,lang:'zh',reference:streamTtsRef}) })
    .then(r => { if(!r.ok) throw new Error('TTS fail'); return r.blob(); })
    .then(blob => { var url=URL.createObjectURL(blob); var a=new Audio(url); a.onended=()=>URL.revokeObjectURL(url); a.onerror=()=>URL.revokeObjectURL(url); a.play(); })
    .catch(() => {});
}

function renderAgentReply(content) {
    if (content.includes('|||')) { var parts = content.split('|||').map(s => s.trim()).filter(Boolean); parts.forEach((p,i) => addMessage('agent', p, null, null, i, parts.length)); }
    else addMessage('agent', content);
}

// ===== 工具进度条 =====
function toolDisplayName(tool) {
    const map = { generate_image:'AI 绘画', generate_paper:'论文 / PDF', generate_ppt:'PPT 生成', generate_kimi_ppt:'PPT 生成', generate_presenton_ppt:'Presenton PPT' };
    return map[tool] || tool;
}

function handleProgress(p) {
    const tool = p.tool || 'task';
    const pct = Math.max(0, Math.min(100, Number(p.percent) || 0));
    const message = p.message || '';
    let wrap = progressBars[tool];
    if (!wrap) {
        if (pct >= 100) return;
        wrap = document.createElement('div');
        wrap.className = 'tool-progress';
        wrap.innerHTML = `<div class="tool-progress-head"><span class="tool-progress-name"></span><span class="tool-progress-pct"></span></div><div class="tool-progress-track"><div class="tool-progress-fill"></div></div><div class="tool-progress-msg"></div>`;
        document.getElementById('chatMessages').appendChild(wrap);
        progressBars[tool] = wrap;
    }
    wrap.querySelector('.tool-progress-name').textContent = toolDisplayName(tool);
    wrap.querySelector('.tool-progress-pct').textContent = Math.round(pct) + '%';
    wrap.querySelector('.tool-progress-fill').style.width = pct + '%';
    if (message) wrap.querySelector('.tool-progress-msg').textContent = message;
    scrollToBottom();
    if (pct >= 100) { wrap.classList.add('done'); setTimeout(() => { if (wrap.parentNode) wrap.parentNode.removeChild(wrap); if (progressBars[tool]===wrap) delete progressBars[tool]; }, 1200); }
}

// ===== 状态更新 =====
function updateStatus(location, status) {
    const els = { indicator: 'statusIndicator', statusText: 'statusText', avatar: 'agentAvatar', deviceText: 'agentDeviceText',
                   sendBtn: 'sendBtn', inputBox: 'inputBox', infoLocation: 'infoLocation', infoOnline: 'infoOnline', uploadBtn: 'uploadBtn' };
    const g = id => document.getElementById(id);
    const indicator = g(els.indicator), statusText = g(els.statusText), avatar = g(els.avatar);
    const deviceText = g(els.deviceText), sendBtn = g(els.sendBtn), inputBox = g(els.inputBox);
    const infoLocation = g(els.infoLocation), infoOnline = g(els.infoOnline), uploadBtn = g(els.uploadBtn);
    if (!indicator || !statusText || !deviceText || !sendBtn || !inputBox) return;
    indicator.className = 'status-indicator'; if(avatar) avatar.className = 'agent-avatar'; deviceText.className = 'agent-device';
    if (location === 'pc') {
        infoLocation.textContent = '电脑';
        if (status === 'online') { isAgentOnline=true; isMigrating=false; indicator.classList.add('online'); statusText.textContent='在线'; infoOnline.textContent='在线'; if(avatar) avatar.classList.remove('offline','migrating'); deviceText.textContent='当前在 电脑端'; sendBtn.disabled=false; inputBox.disabled=false; if(uploadBtn) uploadBtn.disabled=false; stopMigrationAnimation(); }
        else { isAgentOnline=false; indicator.classList.add('offline'); statusText.textContent='离线'; infoOnline.textContent='离线'; if(avatar) avatar.classList.add('offline'); deviceText.textContent='当前在 电脑端（离线）'; sendBtn.disabled=true; inputBox.disabled=true; if(uploadBtn) uploadBtn.disabled=true; }
    } else if (location === 'mobile') {
        infoLocation.textContent = '手机'; isAgentOnline=false; indicator.classList.add('offline'); statusText.textContent='已迁移'; infoOnline.textContent='离线（在手机）'; if(avatar) avatar.classList.add('offline'); deviceText.textContent='已迁移到 手机端'; sendBtn.disabled=true; inputBox.disabled=true; stopMigrationAnimation();
    } else if (location === 'migrating') {
        infoLocation.textContent = '迁移中...'; isMigrating=true; isAgentOnline=false; indicator.className='status-indicator migrating'; statusText.textContent='迁移中'; infoOnline.textContent='迁移中...'; if(avatar) avatar.classList.add('migrating'); deviceText.classList.add('migrating-text'); deviceText.textContent='正在迁移...'; sendBtn.disabled=true; inputBox.disabled=true; startMigrationAnimation();
    }
}

// ===== 迁移动画 =====
function startMigrationAnimation() {
    const pb = document.getElementById('migrateProgressBar'), pf = document.getElementById('migrateProgressFill'), pt = document.getElementById('migrateProgressText');
    pb.classList.add('active'); pf.style.width='0%'; pt.textContent='迁移准备中...';
    stopMigrationAnimation();
    let progress = 0;
    migrateTimer = setInterval(() => {
        progress += 2;
        if (progress >= 100) { progress=100; clearInterval(migrateTimer); migrateTimer=null; }
        pf.style.width = progress + '%';
        pt.textContent = progress<30?'打包会话数据...':progress<60?'传输到目标设备...':progress<90?'等待目标确认...':'即将完成...';
    }, 50);
}
function stopMigrationAnimation() { if (migrateTimer) { clearInterval(migrateTimer); migrateTimer=null; } document.getElementById('migrateProgressBar').classList.remove('active'); document.getElementById('migrateProgressFill').style.width='0%'; }
function completeMigration() { stopMigrationAnimation(); document.getElementById('migrateProgressFill').style.width='100%'; setTimeout(()=>{document.getElementById('migrateProgressBar').classList.remove('active');document.getElementById('migrateProgressFill').style.width='0%';},500); isMigrating=false; }

// ===== 历史消息加载 =====
function loadHistory(msgs) {
    const container = document.getElementById('chatMessages');
    container.innerHTML = '';
    if (!msgs || msgs.length === 0) { container.innerHTML = `<div class="welcome-message"><div class="welcome-icon">🤖</div><h3>欢迎使用 AI Agent</h3><p>Agent 当前在电脑端运行<br>输入消息开始对话</p></div>`; return; }
    for (const m of msgs) {
        if (m.role === 'user') addMessage('user', m.content, m.message_id, m.branches);
        else if (m.role === 'assistant' && m.content) {
            if (m.process_steps) { try { const steps = typeof m.process_steps==='string'?JSON.parse(m.process_steps):m.process_steps; renderHistoryProcessSteps(steps); } catch(e){} }
            var parts = splitSentences(m.content);
            if (parts.length <= 1) addMessage('agent', m.content, m.message_id);
            else { for (var p=0;p<parts.length;p++) addMessage('agent', parts[p], p===parts.length-1?m.message_id:null); }
        }
    }
    setTimeout(() => initBranchData(), 0);
    scrollToBottom();
}

function initBranchData() {
    document.querySelectorAll('.msg-row.user[data-branches]').forEach(userRow => {
        let sibling = userRow.nextElementSibling, aiRow = null;
        while (sibling) { if(sibling.classList.contains('msg-row')){if(sibling.classList.contains('agent'))aiRow=sibling;break;} sibling=sibling.nextElementSibling; }
        if (aiRow) { const aiBubble = aiRow.querySelector('.msg-bubble'); if (aiBubble) userRow.dataset.newContent = aiBubble.textContent; }
    });
}

function renderHistoryProcessSteps(steps) {
    const container = document.getElementById('chatMessages');
    const group = document.createElement('div');
    group.className = 'process-group';
    const toggle = document.createElement('button');
    toggle.className = 'process-toggle';
    toggle.innerHTML = `<span class="toggle-icon">&#9654;</span><span>思考过程</span><span class="process-summary">${formatSummary(steps)}</span>`;
    toggle.addEventListener('click', () => group.classList.toggle('expanded'));
    const stepsContainer = document.createElement('div');
    stepsContainer.className = 'process-steps';
    for (const step of steps) stepsContainer.appendChild(buildStepElement(step));
    group.appendChild(toggle); group.appendChild(stepsContainer); container.appendChild(group);
}

function formatSummary(steps) { const tc = steps.filter(s=>s.type==='tool_call'); return tc.length>0?`调用工具: ${tc.map(s=>s.name).join(', ')}`:'思考完成'; }
function buildStepElement(step) {
    const el = document.createElement('div');
    let icon='',label='',cssClass='';
    switch(step.type){
        case'thinking':icon='&#9678;';label='思考中...';cssClass='thinking';break;
        case'tool_call':icon='&#9881;';label=`调用工具: <code>${escapeHtml(step.name)}</code>`;cssClass='tool-call'; if(step.arguments&&Object.keys(step.arguments).length>0)label+=`<pre>${escapeHtml(JSON.stringify(step.arguments,null,2))}</pre>`;break;
        case'tool_result':icon='&#10003;';label=`工具结果: ${escapeHtml(step.content)}`;cssClass='tool-result';break;
    }
    el.className=`process-step ${cssClass}`; el.innerHTML=`<span class="step-icon">${icon}</span><span class="step-content">${label}</span>`; return el;
}

// ===== 消息渲染 =====
function addMessage(role, content, messageId, branches, chunkIndex, chunkTotal) {
    if (!content) return;
    if (role==='agent' && !chunkIndex) { document.querySelectorAll('.stream-cursor').forEach(el=>el.remove()); if(streamingState&&streamingState.row){streamingState.row.remove();streamingState=null;} }
    const container = document.getElementById('chatMessages');
    const welcome = container.querySelector('.welcome-message');
    if (welcome) welcome.remove();
    const msgId = messageId || (tempIdCounter--);
    const isTemp = !messageId;
    const isChunk = chunkTotal > 1;
    const isContinuation = isChunk && chunkIndex > 0;
    const row = document.createElement('div');
    row.className = `msg-row ${role}`;
    if (isContinuation) row.classList.add('chunk-continuation');
    row.dataset.messageId = msgId;
    if (role === 'system') { row.innerHTML = `<div class="msg-content"><div class="msg-bubble">${formatMessageContent(content)}</div></div>`; }
    else {
        const avatarEmoji = role==='user'?'👤':'🤖', label = role==='user'?'你':'Agent';
        const time = new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'});
        let menuHtml = '';
        if (role === 'user') {
            menuHtml = `<button class="msg-more" onclick="toggleMsgMenu(event,${msgId})" title="更多">⋮</button><div class="msg-menu" id="msgMenu-${msgId}"><button class="session-menu-item" onclick="msgCopy(event,${msgId})"><span class="menu-icon">📋</span> 复制</button><button class="session-menu-item" onclick="${isTemp?'alert(\'请刷新页面后再编辑\')':'msgEditUser(event,'+msgId+')'}"><span class="menu-icon">✏️</span> 编辑</button><button class="session-menu-item danger" onclick="${isTemp?'alert(\'请刷新页面后再删除\')':'msgDelete(event,'+msgId+')'}"><span class="menu-icon">🗑</span> 删除</button></div>`;
        } else {
            menuHtml = `<button class="msg-more" onclick="toggleMsgMenu(event,${msgId})" title="更多">⋮</button><div class="msg-menu" id="msgMenu-${msgId}"><button class="session-menu-item" onclick="msgCopy(event,${msgId})"><span class="menu-icon">📋</span> 复制</button><button class="session-menu-item danger" onclick="${isTemp?'alert(\'请刷新页面后再删除\')':'msgDelete(event,'+msgId+')'}"><span class="menu-icon">🗑</span> 删除</button></div>`;
        }
        let branchHtml = '';
        if (role==='user' && branches) { let bl=[]; try{bl=typeof branches==='string'?JSON.parse(branches):branches;}catch(e){} if(bl.length>0){row.dataset.branches=JSON.stringify(bl); branchHtml=`<div class="branch-nav"><button class="branch-arrow" onclick="switchBranch(event,${msgId},-1)">◀</button><span class="branch-label">分支 1/${bl.length+1}</span><button class="branch-arrow" onclick="switchBranch(event,${msgId},1)">▶</button></div>`;} }
        row.innerHTML = `<div class="msg-avatar">${avatarEmoji}</div><div class="msg-content"><div class="msg-label">${label}</div><div class="msg-bubble">${formatMessageContent(content)}</div><div class="msg-time">${time}</div>${branchHtml}</div>${menuHtml}`;
    }
    if (isContinuation) row.innerHTML = `<div class="msg-content chunk-bubble"><div class="msg-bubble">${formatMessageContent(content)}</div></div>`;
    container.appendChild(row);
    scrollToBottom();
}

function formatMessageContent(text) {
    const imgRegex = /\[IMAGE:([^\]]+)\]/g, paperRegex = /\[PAPER:([^\]]+)\]/g, videoRegex = /\[VIDEO:([^\]]+)\]/g;
    if (imgRegex.test(text) || paperRegex.test(text) || videoRegex.test(text)) {
        imgRegex.lastIndex=0; paperRegex.lastIndex=0; videoRegex.lastIndex=0;
        let result='', lastIdx=0, markers=[], match;
        while((match=imgRegex.exec(text))!==null) markers.push({idx:match.index,end:imgRegex.lastIndex,type:'image',url:match[1]});
        while((match=paperRegex.exec(text))!==null) markers.push({idx:match.index,end:paperRegex.lastIndex,type:'paper',url:match[1]});
        while((match=videoRegex.exec(text))!==null) markers.push({idx:match.index,end:videoRegex.lastIndex,type:'video',url:match[1]});
        markers.sort((a,b)=>a.idx-b.idx);
        const seenUrls = new Set(), deduped = [];
        for(const m of markers){ const k=m.type+':'+m.url; if(!seenUrls.has(k)){seenUrls.add(k);deduped.push(m);} }
        for(const m of deduped){ result+=renderMarkdown(text.slice(lastIdx,m.idx)); if(m.type==='image')result+=`<img src="${m.url}" alt="AI生成的图片" style="max-width:100%;border-radius:8px;cursor:pointer;margin:8px 0" onclick="window.open(this.src)" loading="lazy" />`; else if(m.type==='paper')result+=renderPaperEmbed(m.url); else if(m.type==='video')result+=`<video src="${m.url}" controls style="max-width:100%;max-height:480px;border-radius:8px;margin:8px 0;background:#000" preload="metadata"></video>`; lastIdx=m.end; }
        result+=renderMarkdown(text.slice(lastIdx)); return result;
    } return renderMarkdown(text);
}

function renderMarkdown(text) {
    let html = escapeHtml(text);
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    const _urls = [];
    html = html.replace(/(?<!href=")\bhttps?:\/\/[\w\-._~:/?#\[\]@!$&'()+,;=%]+/g, u => { const t=u.match(/[).,;:!?]+$/); if(t)u=u.slice(0,-t[0].length); return `\u0001URL${_urls.push(u)-1}\u0001`; });
    html = html.replace(/```(\w*)\n?([\s\S]*?)```/g,(_,lang,code)=>`<pre><code>${code.trim()}</code></pre>`);
    html = html.replace(/`([^`]+)`/g,'<code>$1</code>');
    html = html.replace(/\*\*\*(.+?)\*\*\*/g,'<strong><em>$1</em></strong>');
    html = html.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');
    html = html.replace(/__(.+?)__/g,'<strong>$1</strong>');
    html = html.replace(/\*([^*]+)\*/g,'<em>$1</em>');
    html = html.replace(/~~(.+?)~~/g,'<del>$1</del>');
    html = html.replace(/^### (.+)$/gm,'<h4>$1</h4>');
    html = html.replace(/^## (.+)$/gm,'<h3>$1</h3>');
    html = html.replace(/^# (.+)$/gm,'<h3>$1</h3>');
    html = html.replace(/((?:^&gt; .+\n?)+)/gm,m=>{const c=m.replace(/^&gt; /gm,'').trim();return`<blockquote>${c}</blockquote>`;});
    html = html.replace(/^(---|\*\*\*|___)$/gm,'<hr>');
    html = html.replace(/((?:^\d+\.\s+.+\n?)+)/gm,m=>{const i=m.trim().split('\n').map(l=>l.replace(/^\d+\.\s+/,'')).join('</li><li>');return`<ol><li>${i}</li></ol>`;});
    html = html.replace(/((?:^-\s+.+\n?)+)/gm,m=>{const i=m.trim().split('\n').map(l=>l.replace(/^-\s+/,'')).join('</li><li>');return`<ul><li>${i}</li></ul>`;});
    html = html.replace(/\n\n/g,'<br><br>'); html = html.replace(/\n/g,'<br>');
    html = html.replace(/\u0001URL(\d+)\u0001/g,(_,i)=>`<a href="${_urls[i]}" target="_blank" rel="noopener">${_urls[i]}</a>`);
    return html;
}

function renderPaperEmbed(pdfUrl) {
    const id = 'paper-' + Math.random().toString(36).substr(2,8), filename = pdfUrl.split('/').pop(), name = filename.replace(/\.(pdf|pptx)$/i,''), isPptx=/\.pptx$/i.test(filename), icon=isPptx?'📊':'📄', label=isPptx?'PPT 演示文稿':'论文文档', downloadLabel=isPptx?'⬇ 下载PPT':'⬇ 下载PDF', previewHint=isPptx?'点击后将自动转换为PDF并加载预览':'点击后将在下方加载PDF预览';
    return `<div class="paper-embed" style="margin:12px -8px;border:1px solid #e0e0e0;border-radius:8px;overflow:hidden;background:#fff;min-width:560px"><div class="paper-header" style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:#f5f5f5;border-bottom:1px solid #e0e0e0;flex-wrap:wrap;gap:4px"><span style="font-size:14px;font-weight:600">${icon} ${label}</span><div style="display:flex;flex-wrap:wrap;gap:4px"><button onclick="openPapersFolder()" style="font-size:13px;color:#4a90d9;background:none;border:none;cursor:pointer;text-decoration:none;white-space:nowrap">📁 打开文件夹</button>${isPptx?'':`<button onclick="editPaperContent('${name}')" style="font-size:13px;color:#4a90d9;background:none;border:none;cursor:pointer;text-decoration:none;white-space:nowrap">✏️ 修改文档</button>`}<a href="${pdfUrl}" target="_blank" style="font-size:13px;color:#4a90d9;text-decoration:none;white-space:nowrap">🔍 新窗口查看</a><a href="${pdfUrl}" download style="font-size:13px;color:#4a90d9;text-decoration:none;white-space:nowrap">${downloadLabel}</a></div></div><div id="${id}" style="padding:40px;text-align:center;background:#fafafa;cursor:pointer" onclick="loadPaperPreview('${id}','${pdfUrl}')"><div style="font-size:48px;margin-bottom:12px">${icon}</div><div style="font-size:15px;color:#4a90d9;font-weight:500">点击预览${isPptx?'PPT':'论文'}</div><div style="font-size:12px;color:#999;margin-top:4px">${previewHint}</div></div></div>`;
}

function loadPaperPreview(containerId, pdfUrl) { const c=document.getElementById(containerId); if(!c)return; c.style.padding='0';c.style.cursor='default';c.onclick=null; const fn=pdfUrl.split('/').pop(); if(/\.pptx$/i.test(fn)){ const u='/api/pptx-preview/'+encodeURIComponent(fn); c.innerHTML=`<div style="padding:40px;text-align:center;background:#fafafa;color:#999">⏳ 正在转换 PPT 为 PDF，请稍候...</div>`; const ifr=document.createElement('iframe');ifr.src=u;ifr.style.cssText='width:100%;height:600px;border:none;display:none';ifr.onload=()=>{c.innerHTML='';ifr.style.display='block';c.appendChild(ifr);};c.appendChild(ifr);return; } c.innerHTML=`<iframe src="${pdfUrl}" style="width:100%;height:600px;border:none;display:block" frameborder="0"></iframe>`; }
function openPapersFolder() { fetch('/api/open-papers-folder',{method:'POST'}).catch(()=>{}); }

// ===== 论文编辑 =====
let paperEditInfo = { name:'',title:'',format:'markdown' };
async function editPaperContent(name) {
    try{ const r=await fetch(`/api/paper-source?name=${encodeURIComponent(name)}`),d=await r.json(); if(d.error){alert('无法加载源文件：'+d.error);return;} paperEditInfo={name:d.name,title:d.title,format:d.format}; var dk='paper_draft_'+d.name, sv=localStorage.getItem(dk); function fb(){ g('paperEditTitle').value=d.title; g('paperEditContent').value=d.content; } function g(i){return document.getElementById(i);} if(sv){try{var dr=JSON.parse(sv);g('paperEditTitle').value=dr.title||d.title;g('paperEditContent').value=dr.content||d.content;}catch(e){fb();}}else fb(); var fl=g('paperEditFormat');fl.textContent=d.format==='latex'?'LaTeX':'Markdown';fl.style.background=d.format==='latex'?'#e8f5e9':'#e3f2fd';fl.style.color=d.format==='latex'?'#2e7d32':'#1565c0'; g('paperEditModal').style.display='flex'; startPaperAutoSave(); }catch(e){alert('加载失败：'+e.message);}
}
var _paperAutoSaveTimer = null;
function startPaperAutoSave(){clearInterval(_paperAutoSaveTimer);_paperAutoSaveTimer=setInterval(savePaperDraft,5000);}
function savePaperDraft(){if(!paperEditInfo.name)return;var t=document.getElementById('paperEditTitle').value.trim(),c=document.getElementById('paperEditContent').value.trim();if(!t&&!c)return;localStorage.setItem('paper_draft_'+paperEditInfo.name,JSON.stringify({title:t,content:c}));}
function closePaperEdit(){clearInterval(_paperAutoSaveTimer);savePaperDraft();document.getElementById('paperEditModal').style.display='none';}
async function regeneratePaper(){
    var t=document.getElementById('paperEditTitle').value.trim(),c=document.getElementById('paperEditContent').value.trim(); if(!t){alert('请输入标题');return;}
    var btn=document.getElementById('paperRegenerateBtn');btn.disabled=true;btn.textContent='正在生成...';
    try{var r=await fetch('/api/regenerate-paper',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:paperEditInfo.name,title:t,content:c,format:paperEditInfo.format})}),d=await r.json();
        if(d.ok){closePaperEdit();localStorage.removeItem('paper_draft_'+paperEditInfo.name);document.querySelectorAll('.paper-embed iframe').forEach(ifr=>{if(ifr.src.includes(paperEditInfo.name))ifr.src=ifr.src;});addMessage('system','✅ 论文已重新生成，刷新预览即可查看最新版本。');}
        else alert('生成失败：'+(d.error||'请重试'));
    }catch(e){alert('生成失败：'+e.message);} finally{btn.disabled=false;btn.textContent='重新生成';}
}

function escapeHtml(text) { const div = document.createElement('div'); div.textContent = text; return div.innerHTML; }
function addImageMessage(imgUrl, caption) {
    const container = document.getElementById('chatMessages');
    const welcome = container.querySelector('.welcome-message');
    if (welcome) welcome.remove();
    const row = document.createElement('div'); row.className = 'msg-row agent';
    const time = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    row.innerHTML = `<div class="msg-avatar">🤖</div><div class="msg-content"><div class="msg-label">Agent</div><div class="msg-bubble"><img src="${imgUrl}" alt="AI生成的图片" style="max-width:100%;border-radius:8px;cursor:pointer" onclick="window.open(this.src)" loading="lazy" />${caption?`<div style="margin-top:6px;font-size:13px;color:#666">${escapeHtml(caption)}</div>`:''}</div><div class="msg-time">${time}</div></div>`;
    container.appendChild(row);
    scrollToBottom();
}

function scrollToBottom() { const c = document.getElementById('chatMessages'); requestAnimationFrame(() => { c.scrollTop = c.scrollHeight; }); }

// ===== 文件上传 =====
async function onFileSelected(input) {
    const files = input.files; if (!files.length) return;
    for (const file of files) {
        const formData = new FormData(); formData.append('file', file);
        try {
            const resp = await fetch('/api/upload', { method: 'POST', body: formData }), data = await resp.json();
            if (data.ok) {
                const sizeStr = data.size<1024?`${data.size}B`:data.size<1048576?`${(data.size/1024).toFixed(1)}KB`:`${(data.size/1048576).toFixed(1)}MB`;
                addMessage('system', `📎 已上传：${data.filename}（${sizeStr}）\n绝对路径：I:/Agent/data/${data.path}`);
                wsSend({ type: 'chat', content: `📎 文件已上传：${data.filename}\n绝对路径：I:/Agent/data/${data.path}` });
            } else addMessage('system', `上传失败：${data.error}`);
        } catch (e) { addMessage('system', `上传失败：${e.message}`); }
    }
    input.value = '';
}

// ===== 发送消息 =====
function sendMessage() {
    const input = document.getElementById('inputBox'); const text = input.value.trim();
    if (!text || !isAgentOnline || isMigrating) return;
    if (!wsSend({ type: 'chat', content: text })) { addMessage('system', '⚠️ 连接已断开，正在重连，请稍后重试'); return; }
    addMessage('user', text); input.value = ''; input.style.height = 'auto'; input.focus();
}

// ===== 新建会话 =====
function newSession() {
    fetch('/api/sessions', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({device:'电脑'}) })
    .then(r=>r.json()).then(data=>refreshAfterChange(data.session_id)).catch(err=>console.error('创建会话失败:',err));
}

// ===== DOM 辅助 =====
function setElText(id, text) { var el = document.getElementById(id); if(el) el.textContent = text; }
