/**
 * AI Agent 手机端 - 完整功能脚本
 */

// ===== WebSocket =====
const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
const wsUrl = `${protocol}//${location.host}/ws`;
let ws = null;
let isAgentOnline = true;
let isMigrating = false;
let reconnectTimer = null;
let currentSessionId = null;
let currentProcessGroup = null;
let tempIdCounter = -1;
let sessionDataMap = {};
let streamingState = null;   // 流式回复状态 {row, textEl, buffer}
let progressBars = {};       // 工具进度条 {tool: element}

function connect() {
    if (ws && ws.readyState === WebSocket.OPEN) return;
    ws = new WebSocket(wsUrl);
    ws.onopen = () => {
        updateMobileStatus('online');
        ws.send(JSON.stringify({ type: 'register', client_type: 'mobile' }));
        clearReconnect();
        setTimeout(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'comfyui_status' }));
            }
        }, 500);
    };
    ws.onmessage = (e) => handleMobileMessage(JSON.parse(e.data));
    ws.onclose = () => {
        updateMobileStatus('offline');
        scheduleReconnect();
    };
    ws.onerror = () => updateMobileStatus('offline');
}

function scheduleReconnect() {
    clearReconnect();
    reconnectTimer = setTimeout(connect, 3000);
}
function clearReconnect() {
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
}

// ===== 安全 WS 发送与 HTTP 降级刷新 =====
// WS 断开时 ws.send 会抛 InvalidStateError，导致删除会话后列表不刷新
function wsSend(obj) {
    try {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(obj));
            return true;
        }
    } catch (e) {
        console.warn('WS 发送失败:', e);
    }
    return false;
}

// 会话变更后的刷新：优先走 WS，WS 不可用时降级为 HTTP 拉取
async function mobileRefreshAfterChange(targetId) {
    if (wsSend({ type: 'switch_session', session_id: targetId })) return;
    try {
        const r = await fetch('/api/sessions');
        const data = await r.json();
        renderMobileSessionList(data.sessions || [], targetId);
        const mr = await fetch('/api/sessions/' + targetId + '/messages');
        const md = await mr.json();
        loadMobileHistory((md.messages || []).filter(m => m.role === 'user' || m.role === 'assistant'));
    } catch (e) {
        console.error('刷新会话失败:', e);
    }
}

function updateMobileStatus(state) {
    const dot = document.getElementById('mobileStatusDot');
    const input = document.getElementById('mobileInput');
    const sendBtn = document.getElementById('mobileSendBtn');
    const uploadBtn = document.getElementById('mobileUploadBtn');
    const cameraBtn = document.getElementById('mobileCameraBtn');
    dot.className = 'status-dot';
    if (state === 'online') {
        isAgentOnline = true;
        dot.classList.add('online');
        dot.title = '在线';
        input.disabled = false;
        sendBtn.disabled = false;
        if (uploadBtn) uploadBtn.disabled = false;
        if (cameraBtn) cameraBtn.disabled = false;
    } else if (state === 'offline') {
        isAgentOnline = false;
        dot.classList.add('offline');
        dot.title = '离线';
        input.disabled = true;
        sendBtn.disabled = true;
        if (uploadBtn) uploadBtn.disabled = true;
        if (cameraBtn) cameraBtn.disabled = true;
    } else if (state === 'migrating') {
        isAgentOnline = false;
        isMigrating = true;
        dot.classList.add('migrating');
        dot.title = '迁移中';
        input.disabled = true;
        sendBtn.disabled = true;
        if (uploadBtn) uploadBtn.disabled = true;
        if (cameraBtn) cameraBtn.disabled = true;
    }
}

// ===== 消息处理 =====
function handleMobileMessage(msg) {
    switch (msg.type) {
        case 'status':
            updateMobileLocation(msg.agent_location, msg.status);
            break;
        case 'history':
            loadMobileHistory(msg.messages);
            break;
        case 'session_list':
            renderMobileSessionList(msg.sessions, msg.current);
            break;
        case 'process':
            handleMobileProcess(msg.step);
            break;
        case 'stream_start':
            handleMobileStreamStart();
            break;
        case 'stream_delta':
            handleMobileStreamDelta(msg.delta);
            break;
        case 'stream_done':
            handleMobileStreamDone(msg.content);
            break;
        case 'progress':
            handleMobileProgress(msg);
            break;
        case 'response':
            currentProcessGroup = null;
            addMobileMessage('agent', msg.content);
            break;
        case 'error':
            addMobileMessage('system', msg.content);
            break;
        case 'music_state':
            updateMobileMusicBar(msg.result);
            break;
        case 'migrate_data':
            loadMobileHistory(msg.messages);
            ws.send(JSON.stringify({ type: 'migrate_ack', status: 'ok' }));
            break;
        case 'comfyui_status':
            updateMobileComfyUIButton(msg.running);
            break;
        case 'comfyui_start_result':
            if (msg.success) {
                updateMobileComfyUIButton(true);
                pollMobileComfyUIStatus();
            } else {
                updateMobileComfyUIButton(false);
                const st = document.getElementById('comfyui-status');
                if (st) st.textContent = msg.message;
            }
            break;
        case 'comfyui_restart_result':
            if (msg.success) {
                updateMobileComfyUIButton(true);
            } else {
                updateMobileComfyUIButton(false);
                const st2 = document.getElementById('comfyui-status');
                if (st2) st2.textContent = msg.message;
            }
            break;
    }
}

// ===== 状态更新 =====
function updateMobileLocation(location, status) {
    const progress = document.getElementById('mobileProgress');
    const fill = document.getElementById('mobileProgressFill');
    const title = document.getElementById('mobileTitle');
    const infoLocation = document.getElementById('infoLocation');
    const infoOnline = document.getElementById('infoOnline');
    const infoSession = document.getElementById('infoSession');
    const deviceText = document.getElementById('agentDeviceText');

    if (infoLocation) infoLocation.textContent = location === 'pc' ? '电脑' : (location === 'mobile' ? '手机' : '迁移中...');
    if (infoOnline) infoOnline.textContent = status === 'online' ? '在线' : (location === 'migrating' ? '迁移中...' : '离线');
    if (infoSession) infoSession.textContent = currentSessionId || '-';

    if (location === 'pc') {
        progress.style.display = 'none';
        if (status === 'online') {
            isAgentOnline = true; isMigrating = false;
            updateMobileStatus('online');
            title.textContent = 'AI Agent · 电脑端';
            if (deviceText) deviceText.textContent = '当前在 电脑端';
        } else {
            updateMobileStatus('offline');
            title.textContent = 'AI Agent · 离线';
            if (deviceText) deviceText.textContent = '当前在 电脑端（离线）';
        }
    } else if (location === 'mobile') {
        progress.style.display = 'none';
        isAgentOnline = true; isMigrating = false;
        updateMobileStatus('online');
        title.textContent = 'AI Agent · 手机端';
        if (deviceText) deviceText.textContent = '已迁移到 手机端';
        document.getElementById('mobileStatusDot').className = 'status-dot';
        document.getElementById('mobileStatusDot').title = '已在本机';
    } else if (location === 'migrating') {
        progress.style.display = 'block';
        fill.style.width = '0%';
        updateMobileStatus('migrating');
        title.textContent = '正在迁移...';
        if (deviceText) deviceText.textContent = '正在迁移...';
        let p = 0;
        const timer = setInterval(() => {
            p += 2;
            if (p >= 100) { p = 100; clearInterval(timer); }
            fill.style.width = p + '%';
        }, 80);
    }
}

// ===== 历史加载 =====
function loadMobileHistory(msgs) {
    const container = document.getElementById('mobileChat');
    container.innerHTML = '';
    if (!msgs || msgs.length === 0) {
        container.innerHTML = `
            <div class="welcome">
                <div class="welcome-icon">🤖</div>
                <h3>欢迎使用 AI Agent</h3>
                <p>输入消息开始对话</p>
            </div>`;
        return;
    }
    for (const m of msgs) {
        if (m.role === 'user') {
            addMobileMessage('user', m.content, m.message_id, m.branches);
        } else if (m.role === 'assistant' && m.content) {
            if (m.process_steps) {
                try {
                    const steps = typeof m.process_steps === 'string'
                        ? JSON.parse(m.process_steps)
                        : m.process_steps;
                    renderMobileHistorySteps(steps);
                } catch (e) {}
            }
            addMobileMessage('agent', m.content, m.message_id);
        }
    }
    scrollMobileBottom();
}

function renderMobileHistorySteps(steps) {
    const container = document.getElementById('mobileChat');
    const group = document.createElement('div');
    group.className = 'process-group';
    const toggle = document.createElement('button');
    toggle.className = 'process-toggle';
    toggle.innerHTML = `<span class="toggle-icon">▶</span><span>思考过程</span><span class="process-summary">${formatMobileSummary(steps)}</span>`;
    toggle.addEventListener('click', () => group.classList.toggle('expanded'));
    const stepsDiv = document.createElement('div');
    stepsDiv.className = 'process-steps';
    for (const step of steps) {
        const el = buildMobileStepElement(step);
        stepsDiv.appendChild(el);
    }
    group.appendChild(toggle);
    group.appendChild(stepsDiv);
    container.appendChild(group);
}

function formatMobileSummary(steps) {
    const toolCalls = steps.filter(s => s.type === 'tool_call');
    if (toolCalls.length > 0) return `调用: ${toolCalls.map(s => s.name).join(', ')}`;
    return '思考完成';
}

function buildMobileStepElement(step) {
    const el = document.createElement('div');
    let icon = '', label = '', cssClass = '';
    switch (step.type) {
        case 'thinking': icon = '◈'; label = '思考中...'; cssClass = 'thinking'; break;
        case 'tool_call':
            icon = '⚙';
            label = `调用: <code>${escapeHtml(step.name)}</code>`;
            cssClass = 'tool-call';
            if (step.arguments && Object.keys(step.arguments).length > 0) {
                label += `<pre>${escapeHtml(JSON.stringify(step.arguments, null, 2))}</pre>`;
            }
            break;
        case 'tool_result':
            icon = '✓'; label = `结果: ${escapeHtml(step.content)}`; cssClass = 'tool-result'; break;
    }
    el.className = `process-step ${cssClass}`;
    el.innerHTML = `<span class="step-icon">${icon}</span><span class="step-content">${label}</span>`;
    return el;
}

// ===== 消息渲染 =====
function addMobileMessage(role, content, messageId, branches) {
    if (!content) return;
    const container = document.getElementById('mobileChat');
    const welcome = container.querySelector('.welcome');
    if (welcome) welcome.remove();

    const msgId = messageId || (tempIdCounter--);
    const isTemp = !messageId;
    const row = document.createElement('div');
    row.className = `msg-row ${role}`;
    row.dataset.messageId = msgId;

    if (role === 'system') {
        row.innerHTML = `<div class="msg-bubble">${formatMobileContent(content)}</div>`;
    } else {
        const avatarEmoji = role === 'user' ? '👤' : '🤖';
        const time = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });

        let menuHtml = '';
        if (role === 'user') {
            menuHtml = `
                <div class="msg-actions">
                    <button onclick="mobileMsgCopy(event, ${msgId})">复制</button>
                    <button onclick="${isTemp ? 'alert(\'请刷新页面后再编辑\')' : 'mobileMsgEdit(event, ' + msgId + ')'}">编辑</button>
                    <button onclick="${isTemp ? 'alert(\'请刷新页面后再删除\')' : 'mobileMsgDelete(event, ' + msgId + ')'}">删除</button>
                </div>`;
        } else {
            menuHtml = `
                <div class="msg-actions">
                    <button onclick="mobileMsgCopy(event, ${msgId})">复制</button>
                    <button onclick="${isTemp ? 'alert(\'请刷新页面后再删除\')' : 'mobileMsgDelete(event, ' + msgId + ')'}">删除</button>
                </div>`;
        }

        let branchHtml = '';
        if (role === 'user' && branches) {
            let branchList = [];
            try { branchList = typeof branches === 'string' ? JSON.parse(branches) : branches; } catch (e) {}
            if (branchList.length > 0) {
                row.dataset.branches = JSON.stringify(branchList);
                branchHtml = `
                    <div class="branch-nav" style="display:flex;align-items:center;gap:4px;font-size:10px;margin-top:2px">
                        <button onclick="mobileSwitchBranch(event, ${msgId}, -1)" style="background:none;border:1px solid #d0d0d0;border-radius:4px;padding:1px 6px;font-size:10px;cursor:pointer">◀</button>
                        <span class="branch-label">分支 1/${branchList.length + 1}</span>
                        <button onclick="mobileSwitchBranch(event, ${msgId}, 1)" style="background:none;border:1px solid #d0d0d0;border-radius:4px;padding:1px 6px;font-size:10px;cursor:pointer">▶</button>
                    </div>`;
            }
        }

        row.innerHTML = `
            <div class="msg-avatar">${avatarEmoji}</div>
            <div class="msg-content">
                <div class="msg-bubble">${formatMobileContent(content)}</div>
                <div class="msg-time">${time}</div>
                ${branchHtml}
                ${menuHtml}
            </div>`;
    }
    container.appendChild(row);
    scrollMobileBottom();
}

// ===== 流式回复渲染（手机端） =====
function handleMobileStreamStart() {
    currentProcessGroup = null;
    const container = document.getElementById('mobileChat');
    const welcome = container.querySelector('.welcome');
    if (welcome) welcome.remove();

    const row = document.createElement('div');
    row.className = 'msg-row agent';
    row.innerHTML = `
        <div class="msg-avatar">🤖</div>
        <div class="msg-content">
            <div class="msg-bubble streaming-bubble"><span class="stream-text"></span><span class="stream-cursor"></span></div>
        </div>`;
    container.appendChild(row);
    streamingState = { row: row, textEl: row.querySelector('.stream-text'), buffer: '' };
    scrollMobileBottom();
}

function handleMobileStreamDelta(delta) {
    if (!delta) return;
    if (!streamingState) handleMobileStreamStart();
    streamingState.buffer += delta;
    streamingState.textEl.textContent = streamingState.buffer.split('|||').join('\n');
    scrollMobileBottom();
}

function handleMobileStreamDone(content) {
    if (streamingState) {
        streamingState.row.remove();
        streamingState = null;
    }
    currentProcessGroup = null;
    if (content) renderMobileAgentReply(content);
    scrollMobileBottom();
}

// 按 ||| 分隔符将回复拆成多条自然消息
function renderMobileAgentReply(content) {
    if (content.includes('|||')) {
        content.split('|||').map(s => s.trim()).filter(Boolean)
            .forEach(part => addMobileMessage('agent', part));
    } else {
        addMobileMessage('agent', content);
    }
}

// ===== 工具进度条（手机端） =====
function mobileToolDisplayName(tool) {
    const map = {
        generate_image: 'AI 绘画',
        generate_paper: '论文 / PDF',
        generate_ppt: 'PPT 生成',
        generate_kimi_ppt: 'PPT 生成',
        generate_presenton_ppt: 'Presenton PPT'
    };
    return map[tool] || tool;
}

function handleMobileProgress(p) {
    const tool = p.tool || 'task';
    const pct = Math.max(0, Math.min(100, Number(p.percent) || 0));
    const message = p.message || '';

    let wrap = progressBars[tool];
    if (!wrap) {
        if (pct >= 100) return;
        wrap = document.createElement('div');
        wrap.className = 'tool-progress';
        wrap.innerHTML = `
            <div class="tool-progress-head">
                <span class="tool-progress-name"></span>
                <span class="tool-progress-pct"></span>
            </div>
            <div class="tool-progress-track"><div class="tool-progress-fill"></div></div>
            <div class="tool-progress-msg"></div>`;
        document.getElementById('mobileChat').appendChild(wrap);
        progressBars[tool] = wrap;
    }

    wrap.querySelector('.tool-progress-name').textContent = mobileToolDisplayName(tool);
    wrap.querySelector('.tool-progress-pct').textContent = Math.round(pct) + '%';
    wrap.querySelector('.tool-progress-fill').style.width = pct + '%';
    if (message) wrap.querySelector('.tool-progress-msg').textContent = message;
    scrollMobileBottom();

    if (pct >= 100) {
        wrap.classList.add('done');
        setTimeout(() => {
            if (wrap.parentNode) wrap.parentNode.removeChild(wrap);
            if (progressBars[tool] === wrap) delete progressBars[tool];
        }, 1200);
    }
}

function formatMobileContent(text) {
    const imgRegex = /\[IMAGE:([^\]]+)\]/g;
    const paperRegex = /\[PAPER:([^\]]+)\]/g;

    let result;
    if (imgRegex.test(text) || paperRegex.test(text)) {
        imgRegex.lastIndex = 0; paperRegex.lastIndex = 0;
        result = ''; let lastIdx = 0;
        const markers = [];
        let match;
        while ((match = imgRegex.exec(text)) !== null) {
            markers.push({ idx: match.index, end: imgRegex.lastIndex, type: 'image', url: match[1] });
        }
        while ((match = paperRegex.exec(text)) !== null) {
            markers.push({ idx: match.index, end: paperRegex.lastIndex, type: 'paper', url: match[1] });
        }
        markers.sort((a, b) => a.idx - b.idx);
        for (const m of markers) {
            result += renderMobileMarkdown(text.slice(lastIdx, m.idx));
            if (m.type === 'image') {
                result += `<img src="${m.url}" alt="AI图片" style="max-width:100%;border-radius:8px;margin:6px 0" loading="lazy" onclick="window.open(this.src)" />`;
            } else if (m.type === 'paper') {
                result += renderMobilePaper(m.url);
            }
            lastIdx = m.end;
        }
        result += renderMobileMarkdown(text.slice(lastIdx));
    } else {
        result = renderMobileMarkdown(text);
    }
    return result;
}

function renderMobileMarkdown(text) {
    let html = escapeHtml(text);

    // 链接 [text](url) —— 提前处理，避免 URL 被裸 URL 规则误吞
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

    // 保护裸 URL（http/https，排除已在 href="..." 中的），先转为占位符，最后渲染为超链接
    const _urls = [];
    html = html.replace(/(?<!href=")\bhttps?:\/\/[\w\-._~:/?#\[\]@!$&'()*+,;=%]+/g, (u) => {
        const trailing = u.match(/[).,;:!?]+$/);
        if (trailing) u = u.slice(0, -trailing[0].length);
        return `\u0001URL${_urls.push(u) - 1}\u0001`;
    });

    html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
        return `<pre><code>${code.trim()}</code></pre>`;
    });
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/__(.+?)__/g, '<strong>$1</strong>');
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    html = html.replace(/~~(.+?)~~/g, '<del>$1</del>');
    html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^# (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/((?:^&gt; .+\n?)+)/gm, (match) => {
        const content = match.replace(/^&gt; /gm, '').trim();
        return `<blockquote>${content}</blockquote>`;
    });
    html = html.replace(/^(---|\*\*\*|___)$/gm, '<hr>');
    html = html.replace(/((?:^\d+\.\s+.+\n?)+)/gm, (match) => {
        const items = match.trim().split('\n').map(line =>
            line.replace(/^\d+\.\s+/, '')
        ).join('</li><li>');
        return `<ol><li>${items}</li></ol>`;
    });
    html = html.replace(/((?:^-\s+.+\n?)+)/gm, (match) => {
        const items = match.trim().split('\n').map(line =>
            line.replace(/^-\s+/, '')
        ).join('</li><li>');
        return `<ul><li>${items}</li></ul>`;
    });
    html = html.replace(/\n\n/g, '<br><br>');
    html = html.replace(/\n/g, '<br>');
    // 还原裸 URL 为可点击超链接
    html = html.replace(/\u0001URL(\d+)\u0001/g, (_, i) =>
        `<a href="${_urls[i]}" target="_blank" rel="noopener">${_urls[i]}</a>`);
    return html;
}

function renderMobilePaper(pdfUrl) {
    const id = 'mpaper-' + Math.random().toString(36).substr(2, 8);
    const name = pdfUrl.split('/').pop().replace('.pdf', '');
    return `
        <div class="paper-embed">
            <div class="paper-header">
                <span>📄 论文文档</span>
                <div>
                    <button onclick="openPapersFolder()" style="font-size:11px;color:#4a90d9;background:none;border:none;cursor:pointer;margin-right:8px">📁 文件夹</button>
                    <button onclick="editPaperContent('${name}')" style="font-size:11px;color:#4a90d9;background:none;border:none;cursor:pointer;margin-right:8px">✏️ 修改</button>
                    <a href="${pdfUrl}" target="_blank" style="font-size:11px;color:#4a90d9;margin-right:8px">查看</a>
                    <a href="${pdfUrl}" download style="font-size:11px;color:#4a90d9">下载</a>
                </div>
            </div>
            <div id="${id}" style="padding:20px;text-align:center;background:#fafafa;cursor:pointer" onclick="loadMobilePaperPreview('${id}', '${pdfUrl}')">
                <div style="font-size:32px;margin-bottom:8px">📄</div>
                <div style="font-size:13px;color:#4a90d9">点击预览论文</div>
            </div>
        </div>`;
}

function loadMobilePaperPreview(containerId, pdfUrl) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.style.padding = '0';
    container.style.cursor = 'default';
    container.onclick = null;
    container.innerHTML = `<iframe src="${pdfUrl}" style="width:100%;height:400px;border:none;display:block" frameborder="0"></iframe>`;
}

function openPapersFolder() {
    fetch('/api/open-papers-folder', { method: 'POST' }).catch(() => {});
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ===== 过程步骤 =====
function handleMobileProcess(step) {
    if (step.type === 'tool_result' && step.content && step.content.includes('[EXPRESSION:')) {
        const match = step.content.match(/\[EXPRESSION:(\w+)\]/);
        if (match) switchMobileSpineSkin(match[1]);
        return;
    }
    if (step.type === 'tool_result' && step.content && step.content.includes('[MUSIC:')) {
        updateMobileMusicBar(step.content);
    }
    if (!currentProcessGroup) {
        currentProcessGroup = createMobileProcessGroup();
    }
    addMobileProcessStep(currentProcessGroup, step);
}

function createMobileProcessGroup() {
    const container = document.getElementById('mobileChat');
    const welcome = container.querySelector('.welcome');
    if (welcome) welcome.remove();
    const group = document.createElement('div');
    group.className = 'process-group';
    const toggle = document.createElement('button');
    toggle.className = 'process-toggle';
    toggle.innerHTML = `<span class="toggle-icon">▶</span><span>思考过程</span><span class="process-summary">正在思考...</span>`;
    toggle.addEventListener('click', () => group.classList.toggle('expanded'));
    const steps = document.createElement('div');
    steps.className = 'process-steps';
    group.appendChild(toggle);
    group.appendChild(steps);
    container.appendChild(group);
    scrollMobileBottom();
    return group;
}

function addMobileProcessStep(group, step) {
    const steps = group.querySelector('.process-steps');
    const summary = group.querySelector('.process-summary');
    let icon = '', label = '', cssClass = '';
    switch (step.type) {
        case 'thinking': icon = '◈'; label = '思考中...'; cssClass = 'thinking'; summary.textContent = '正在思考...'; break;
        case 'tool_call':
            icon = '⚙'; label = `调用: <code>${escapeHtml(step.name)}</code>`; cssClass = 'tool-call';
            summary.textContent = `调用: ${step.name}`;
            if (step.arguments && Object.keys(step.arguments).length > 0) {
                label += `<pre>${escapeHtml(JSON.stringify(step.arguments, null, 2))}</pre>`;
            }
            break;
        case 'tool_result':
            icon = '✓'; label = `结果: ${escapeHtml(step.content)}`; cssClass = 'tool-result';
            summary.textContent = `获取结果: ${step.name}`;
            break;
    }
    const el = document.createElement('div');
    el.className = `process-step ${cssClass}`;
    el.innerHTML = `<span class="step-icon">${icon}</span><span class="step-content">${label}</span>`;
    steps.appendChild(el);
    scrollMobileBottom();
}

// ===== 消息操作 =====
function mobileMsgCopy(e, messageId) {
    e.stopPropagation();
    const row = document.querySelector(`.msg-row[data-message-id="${messageId}"]`);
    if (!row) return;
    const bubble = row.querySelector('.msg-bubble');
    if (!bubble) return;
    navigator.clipboard.writeText(bubble.textContent).catch(() => {});
    const orig = bubble.style.background;
    bubble.style.background = '#E6F7FF';
    setTimeout(() => { bubble.style.background = orig; }, 500);
}

function mobileMsgEdit(e, messageId) {
    e.stopPropagation();
    const row = document.querySelector(`.msg-row[data-message-id="${messageId}"]`);
    if (!row) return;
    const bubble = row.querySelector('.msg-bubble');
    if (!bubble) return;
    const currentText = bubble.textContent;

    const overlay = document.createElement('div');
    overlay.className = 'edit-modal-overlay';
    overlay.innerHTML = `
        <div class="edit-modal">
            <div class="edit-modal-header">
                <h3>编辑消息</h3>
                <button onclick="this.closest('.edit-modal-overlay').remove()" style="font-size:20px;background:none;border:none;cursor:pointer;color:#999">&times;</button>
            </div>
            <div class="edit-modal-body">
                <textarea id="mobileEditInput">${escapeHtml(currentText)}</textarea>
            </div>
            <div class="edit-modal-footer">
                <button onclick="this.closest('.edit-modal-overlay').remove()" style="background:#fff;border:1px solid #d0d0d0">取消</button>
                <button onclick="doMobileEdit(${messageId}, this)" style="background:#4a90d9;color:#fff;border:none">确定</button>
            </div>
        </div>`;
    document.body.appendChild(overlay);
    setTimeout(() => {
        const input = document.getElementById('mobileEditInput');
        if (input) { input.focus(); input.select(); }
    }, 50);
}

function doMobileEdit(messageId, btn) {
    const input = document.getElementById('mobileEditInput');
    const newText = input ? input.value.trim() : '';
    btn.closest('.edit-modal-overlay').remove();
    if (!newText) return;

    const row = document.querySelector(`.msg-row[data-message-id="${messageId}"]`);
    if (!row) return;
    const bubble = row.querySelector('.msg-bubble');
    if (bubble) {
        bubble.textContent = newText;
        bubble.style.opacity = '0.6';
    }

    fetch('/api/messages/' + messageId, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: newText, rerun: true })
    })
    .then(r => r.json())
    .then(data => {
        if (bubble) { bubble.textContent = newText; bubble.style.opacity = '1'; }
        let next = row.nextElementSibling;
        while (next) {
            const toRemove = next;
            next = next.nextElementSibling;
            if (toRemove.classList.contains('msg-row') && toRemove.classList.contains('agent')) {
                toRemove.remove();
                break;
            }
            toRemove.remove();
        }
        if (data.reply) addMobileMessage('agent', data.reply);
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'switch_session', session_id: currentSessionId }));
        }
    })
    .catch(() => { if (bubble) { bubble.textContent = newText; bubble.style.opacity = '1'; } });
}

function mobileMsgDelete(e, messageId) {
    e.stopPropagation();
    if (!confirm('确定要删除这条消息吗？')) return;
    fetch('/api/messages/' + messageId, { method: 'DELETE' })
    .then(() => {
        const row = document.querySelector(`.msg-row[data-message-id="${messageId}"]`);
        if (row) {
            const prev = row.previousElementSibling;
            if (prev && prev.classList.contains('process-group')) prev.remove();
            row.remove();
        }
    });
}

// ===== 分支切换 =====
function mobileSwitchBranch(e, userMessageId, direction) {
    e.stopPropagation();
    const userRow = document.querySelector(`.msg-row[data-message-id="${userMessageId}"]`);
    if (!userRow) return;
    let aiRow = userRow.nextElementSibling;
    while (aiRow && !aiRow.classList.contains('msg-row')) aiRow = aiRow.nextElementSibling;
    if (!aiRow || !aiRow.classList.contains('agent')) return;
    const aiBubble = aiRow.querySelector('.msg-bubble');
    if (!aiBubble) return;
    const branchLabel = userRow.querySelector('.branch-label');
    let branches = [];
    try { branches = JSON.parse(userRow.dataset.branches || '[]'); } catch (e) {}
    if (branches.length === 0) return;
    let currentIdx = parseInt(userRow.dataset.branchIdx) || 0;
    let newIdx = currentIdx + direction;
    if (newIdx < 0) newIdx = branches.length;
    if (newIdx > branches.length) newIdx = 0;
    if (currentIdx === 0) userRow.dataset.newContent = aiBubble.textContent;
    if (newIdx === 0) {
        aiBubble.textContent = userRow.dataset.newContent || aiBubble.textContent;
    } else {
        const branch = branches[newIdx - 1];
        if (branch && branch.content) aiBubble.textContent = branch.content;
    }
    userRow.dataset.branchIdx = newIdx;
    if (branchLabel) branchLabel.textContent = `分支 ${newIdx + 1}/${branches.length + 1}`;
}

// ===== 会话列表 =====
let selectMode = false;
let selectedSessions = new Set();

function renderMobileSessionList(sessions, current) {
    currentSessionId = current;
    const infoSession = document.getElementById('infoSession');
    if (infoSession) infoSession.textContent = current || '';
    const list = document.getElementById('mobileSessionList');
    list.innerHTML = '';

    if (!sessions || sessions.length === 0) {
        list.innerHTML = '<div style="padding:16px;color:#999;font-size:12px;text-align:center">暂无会话</div>';
        exitMobileSelectMode();
        return;
    }

    if (selectMode) {
        list.classList.add('select-mode');
    } else {
        list.classList.remove('select-mode');
    }

    for (const s of sessions) {
        sessionDataMap[s.session_id] = s;
        const isActive = s.session_id === current;
        const isChecked = selectedSessions.has(s.session_id);
        const isPinned = s.pinned === 1;
        const displayTitle = s.title || s.session_id.substring(0, 8) + '...';

        const item = document.createElement('div');
        item.className = 'session-item' + (isActive ? ' active' : '') + (isChecked ? ' selected' : '') + (isPinned ? ' pinned' : '');
        item.dataset.sessionId = s.session_id;
        item.innerHTML = `
            <span class="sess-check">✓</span>
            <span class="sess-icon">💬</span>
            <div class="sess-info">
                <div class="sess-title">${escapeHtml(displayTitle)}</div>
                <div class="sess-meta">${s.message_count || 0} 条消息</div>
            </div>
            <button class="sess-more" onclick="toggleMobileSessionMenu(event, '${s.session_id}')">⋮</button>
            <div class="sess-menu" id="smenu-${s.session_id}">
                <button class="sess-menu-item" onclick="mobileSessionRename(event, '${s.session_id}')">✏️ 改名</button>
                <button class="sess-menu-item" onclick="mobileSessionPin(event, '${s.session_id}', ${isPinned ? 'false' : 'true'})">${isPinned ? '📌 取消置顶' : '📍 置顶'}</button>
                <button class="sess-menu-item danger" onclick="mobileSessionDelete(event, '${s.session_id}')">🗑 删除</button>
            </div>`;
        item.addEventListener('click', (e) => {
            if (e.target.closest('.sess-more') || e.target.closest('.sess-menu')) return;
            if (selectMode) {
                toggleMobileSessionCheck(e, s.session_id);
            } else if (!isActive) {
                switchMobileSession(s.session_id);
                toggleDrawer();
            }
        });
        list.appendChild(item);
    }
    updateMobileBatchBar();
}

// ===== 单会话菜单操作 =====
function toggleMobileSessionMenu(e, sessionId) {
    e.stopPropagation();
    const menu = document.getElementById('smenu-' + sessionId);
    if (!menu) return;
    const isOpen = menu.classList.contains('show');
    closeMobileSessionMenus();
    if (!isOpen) menu.classList.add('show');
}

function closeMobileSessionMenus() {
    document.querySelectorAll('.sess-menu.show').forEach(m => m.classList.remove('show'));
}

// 点击菜单外区域关闭会话菜单
document.addEventListener('click', (e) => {
    if (!e.target.closest('.sess-more') && !e.target.closest('.sess-menu')) {
        closeMobileSessionMenus();
    }
});

function mobileSessionDelete(e, sessionId) {
    e.stopPropagation();
    closeMobileSessionMenus();
    if (!confirm('确定要删除这个会话吗？所有聊天记录将被永久删除。')) return;
    fetch('/api/sessions/' + sessionId, { method: 'DELETE' })
    .then(r => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
    })
    .then(data => {
        mobileRefreshAfterChange(data.new_current || data.session_id);
    })
    .catch(err => {
        console.error('删除会话失败:', err);
        alert('删除会话失败，请稍后重试');
    });
}

function mobileSessionPin(e, sessionId, pinned) {
    e.stopPropagation();
    closeMobileSessionMenus();
    fetch('/api/sessions/' + sessionId + '/pin', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pinned: pinned })
    })
    .then(() => mobileRefreshAfterChange(currentSessionId))
    .catch(err => console.error('置顶操作失败:', err));
}

function mobileSessionRename(e, sessionId) {
    e.stopPropagation();
    closeMobileSessionMenus();
    const s = sessionDataMap[sessionId] || {};
    const title = prompt('输入新的会话名称：', s.title || '');
    if (!title || !title.trim()) return;
    fetch('/api/sessions/' + sessionId + '/rename', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title.trim() })
    })
    .then(() => mobileRefreshAfterChange(currentSessionId))
    .catch(err => console.error('重命名失败:', err));
}

function switchMobileSession(sessionId) {
    wsSend({ type: 'switch_session', session_id: sessionId });
}

function mobileNewSession() {
    fetch('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device: '手机' })
    })
    .then(r => r.json())
    .then(data => {
        mobileRefreshAfterChange(data.session_id);
        toggleDrawer();
    })
    .catch(err => console.error('创建会话失败:', err));
}

// ===== 批量选择 =====
function toggleSelectMode() {
    selectMode = !selectMode;
    if (!selectMode) selectedSessions.clear();
    mobileRefreshAfterChange(currentSessionId);
}

function exitMobileSelectMode() {
    selectMode = false;
    selectedSessions.clear();
    updateMobileBatchBar();
}

function toggleMobileSessionCheck(e, sessionId) {
    e.stopPropagation();
    if (selectedSessions.has(sessionId)) {
        selectedSessions.delete(sessionId);
    } else {
        selectedSessions.add(sessionId);
    }
    const item = document.querySelector(`.session-item[data-session-id="${sessionId}"]`);
    if (item) item.classList.toggle('selected', selectedSessions.has(sessionId));
    updateMobileBatchBar();
}

function toggleSelectAll() {
    const items = document.querySelectorAll('#mobileSessionList .session-item');
    if (selectedSessions.size === items.length) {
        selectedSessions.clear();
        items.forEach(el => el.classList.remove('selected'));
    } else {
        items.forEach(el => {
            const sid = el.dataset.sessionId;
            if (sid) selectedSessions.add(sid);
            el.classList.add('selected');
        });
    }
    updateMobileBatchBar();
}

function updateMobileBatchBar() {
    const bar = document.getElementById('mobileBatchBar');
    const count = selectedSessions.size;
    const btn = document.getElementById('mobileBatchDeleteBtn');
    const countEl = document.getElementById('mobileBatchCount');
    if (selectMode) {
        bar.classList.add('show');
        if (countEl) countEl.textContent = `已选 ${count} 项`;
        if (btn) btn.disabled = count === 0;
    } else {
        bar.classList.remove('show');
    }
}

function batchDelete() {
    if (selectedSessions.size === 0) return;
    if (!confirm(`确定要删除选中的 ${selectedSessions.size} 个会话吗？`)) return;
    const ids = Array.from(selectedSessions);
    fetch('/api/sessions/batch', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_ids: ids })
    })
    .then(r => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
    })
    .then(data => {
        selectedSessions.clear();
        exitMobileSelectMode();
        mobileRefreshAfterChange(data.new_current || currentSessionId);
    })
    .catch(err => {
        console.error('批量删除失败:', err);
        alert('批量删除失败，请稍后重试');
    });
}

// ===== 清空聊天 =====
function clearMobileChat() {
    if (!confirm('确定要清空当前会话的所有聊天记录吗？')) return;
    fetch('/api/sessions/current/messages', { method: 'DELETE' })
    .then(r => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
    })
    .then(() => {
        document.getElementById('mobileChat').innerHTML = `
            <div class="welcome">
                <div class="welcome-icon">🤖</div>
                <h3>聊天记录已清空</h3>
                <p>输入消息开始新对话</p>
            </div>`;
        currentProcessGroup = null;
    });
}

// ===== 抽屉 =====
function toggleDrawer() {
    document.getElementById('sessionDrawer').classList.toggle('open');
    document.getElementById('drawerOverlay').classList.toggle('show');
}

// ===== 系统状态面板 =====
function toggleStatusPanel() {
    document.getElementById('statusPanel').classList.toggle('show');
}

// ===== 角色展示 =====
function toggleCharacter() {
    const char = document.getElementById('mobileCharacter');
    const collapsed = document.getElementById('characterCollapsed');
    if (char.style.display === 'none') {
        char.style.display = 'flex';
        collapsed.style.display = 'none';
    } else {
        char.style.display = 'none';
        collapsed.style.display = 'block';
    }
}

// ===== 发送消息 =====
function mobileSend() {
    const input = document.getElementById('mobileInput');
    const text = input.value.trim();
    if (!text || !isAgentOnline || isMigrating) return;
    if (!wsSend({ type: 'chat', content: text })) {
        addMobileMessage('system', '⚠️ 连接已断开，正在重连，请稍后重试');
        return;
    }
    addMobileMessage('user', text);
    input.value = '';
    input.style.height = 'auto';
    input.focus();
}

// ===== 文件上传 =====
async function onMobileFileSelected(input) {
    const files = input.files;
    if (!files.length) return;
    for (const file of files) {
        const formData = new FormData();
        formData.append('file', file);
        try {
            const resp = await fetch('/api/upload', { method: 'POST', body: formData });
            const data = await resp.json();
            if (data.ok) {
                const sizeStr = data.size < 1024 ? `${data.size}B`
                    : data.size < 1024 * 1024 ? `${(data.size / 1024).toFixed(1)}KB`
                    : `${(data.size / (1024 * 1024)).toFixed(1)}MB`;
                addMobileMessage('system', `📎 已上传：${data.filename}（${sizeStr}）\n路径：${data.path}`);
            } else {
                addMobileMessage('system', `上传失败：${data.error}`);
            }
        } catch (e) {
            addMobileMessage('system', `上传失败：${e.message}`);
        }
    }
    input.value = '';
}

// ===== 摄像头拍照（使用 getUserMedia，避免页面被杀） =====
let cameraStream = null;
let cameraFacingMode = 'environment';  // 'environment' = 后置, 'user' = 前置

async function openMobileCamera() {
    try {
        // 先关闭之前的流
        if (cameraStream) {
            cameraStream.getTracks().forEach(t => t.stop());
            cameraStream = null;
        }

        const video = document.getElementById('cameraPreview');
        const modal = document.getElementById('cameraModal');
        modal.style.display = 'flex';

        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: cameraFacingMode, width: { ideal: 1280 }, height: { ideal: 720 } },
            audio: false
        });
        video.srcObject = cameraStream;
        await video.play();
    } catch (e) {
        // 降级：使用原生相机
        fallbackToNativeCamera();
    }
}

function closeCamera() {
    if (cameraStream) {
        cameraStream.getTracks().forEach(t => t.stop());
        cameraStream = null;
    }
    document.getElementById('cameraModal').style.display = 'none';
}

function switchCamera() {
    cameraFacingMode = cameraFacingMode === 'environment' ? 'user' : 'environment';
    if (cameraStream) {
        cameraStream.getTracks().forEach(t => t.stop());
        cameraStream = null;
    }
    navigator.mediaDevices.getUserMedia({
        video: { facingMode: cameraFacingMode, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false
    }).then(stream => {
        cameraStream = stream;
        document.getElementById('cameraPreview').srcObject = stream;
    }).catch(() => {});
}

function capturePhoto() {
    const video = document.getElementById('cameraPreview');
    const canvas = document.getElementById('cameraCanvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0);
    canvas.toBlob(async (blob) => {
        closeCamera();
        if (!blob) return;

        // 显示本地预览
        const localUrl = URL.createObjectURL(blob);
        addMobilePhotoMessage('user', localUrl);

        // 上传到服务器
        const formData = new FormData();
        formData.append('file', blob, 'photo.jpg');
        try {
            const resp = await fetch('/api/upload', { method: 'POST', body: formData });
            const data = await resp.json();
            if (data.ok) {
                const lastImg = document.querySelector('#mobileChat .msg-row.user .msg-bubble img.photo-preview');
                if (lastImg) {
                    lastImg.src = data.url;
                    lastImg.classList.remove('photo-preview');
                }
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'chat', content: `请分析这张图片：${data.url}` }));
                }
            } else {
                addMobileMessage('system', `拍照上传失败：${data.error}`);
            }
        } catch (e) {
            addMobileMessage('system', `拍照上传失败：${e.message}`);
        }
    }, 'image/jpeg', 0.9);
}

function fallbackToNativeCamera() {
    document.getElementById('cameraModal').style.display = 'none';
    document.getElementById('mobileCameraInput').click();
}

function addMobilePhotoMessage(role, localUrl) {
    const container = document.getElementById('mobileChat');
    const welcome = container.querySelector('.welcome');
    if (welcome) welcome.remove();

    const time = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    const row = document.createElement('div');
    row.className = `msg-row ${role}`;
    row.innerHTML = `
        <div class="msg-avatar">👤</div>
        <div class="msg-content">
            <div class="msg-bubble">
                <img src="${localUrl}" class="photo-preview" alt="拍照" style="max-width:100%;border-radius:8px" />
            </div>
            <div class="msg-time">${time}</div>
        </div>`;
    container.appendChild(row);
    scrollMobileBottom();
}

// ===== 音乐条 =====
let mobileMusicBarPlaying = false;
let mobileMusicBarPosition = 0;
let mobileMusicBarDuration = 0;
let mobileMusicBarPollTimer = null;
let mobileMusicBarSeeking = false;

function updateMobileMusicBar(content) {
    const bar = document.getElementById('mobileMusicBar');
    if (!bar) return;

    const match = content.match(/\[MUSIC:(\w+)(?:\|([^|]*))?(?:\|([^|]*))?(?:\|([^|]*))?(?:\|([^|\]]*))?\]/);
    if (!match) return;

    const status = match[1];
    const title = match[2] || '';
    const pos = parseFloat(match[4]) || 0;
    const dur = parseFloat(match[5]) || 0;

    if (status === 'playing') {
        mobileMusicBarPlaying = true;
        mobileMusicBarPosition = pos;
        mobileMusicBarDuration = dur;
        bar.classList.add('show');
        document.getElementById('mobileMusicTitle').textContent = title || '正在播放...';
        document.getElementById('mobileMusicBtnPlay').textContent = '⏸';
        document.getElementById('mobileMusicBtnPlay').title = '暂停';
        updateMobileProgressBar(pos, dur);
        startMobileMusicPolling();
    } else if (status === 'paused') {
        mobileMusicBarPlaying = false;
        mobileMusicBarPosition = pos || mobileMusicBarPosition;
        mobileMusicBarDuration = dur || mobileMusicBarDuration;
        bar.classList.add('show');
        document.getElementById('mobileMusicTitle').textContent = title || '已暂停';
        document.getElementById('mobileMusicBtnPlay').textContent = '▶';
        document.getElementById('mobileMusicBtnPlay').title = '播放';
        updateMobileProgressBar(mobileMusicBarPosition, mobileMusicBarDuration);
        stopMobileMusicPolling();
    } else if (status === 'stopped') {
        closeMobileMusicBar();
    }
}

function updateMobileProgressBar(pos, dur) {
    const slider = document.getElementById('mobileMusicSlider');
    const timeEl = document.getElementById('mobileMusicTime');
    const durEl = document.getElementById('mobileMusicDuration');
    if (!slider) return;
    const pct = dur > 0 ? (pos / dur) * 100 : 0;
    if (!mobileMusicBarSeeking) slider.value = pct;
    timeEl.textContent = formatMobileTime(pos);
    durEl.textContent = formatMobileTime(dur);
}

function formatMobileTime(seconds) {
    const s = Math.max(0, Math.floor(seconds || 0));
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec.toString().padStart(2, '0')}`;
}

function startMobileMusicPolling() {
    stopMobileMusicPolling();
    mobileMusicBarPollTimer = setInterval(() => {
        if (!mobileMusicBarPlaying || mobileMusicBarSeeking) return;
        mobileMusicAction('status');
    }, 2000);
}

function stopMobileMusicPolling() {
    if (mobileMusicBarPollTimer) { clearInterval(mobileMusicBarPollTimer); mobileMusicBarPollTimer = null; }
}

function onMobileMusicSeek(pct) {
    mobileMusicBarSeeking = true;
    const dur = mobileMusicBarDuration || 0;
    const pos = (pct / 100) * dur;
    document.getElementById('mobileMusicTime').textContent = formatMobileTime(pos);
}

function onMobileMusicSeekEnd() {
    const slider = document.getElementById('mobileMusicSlider');
    if (!slider || !mobileMusicBarDuration) { mobileMusicBarSeeking = false; return; }
    const pct = parseFloat(slider.value);
    const seekSeconds = Math.round((pct / 100) * mobileMusicBarDuration);
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'music_control', action: 'seek', seek_seconds: seekSeconds }));
    }
    mobileMusicBarSeeking = false;
}

function toggleMobileMusicPlay() {
    if (mobileMusicBarPlaying) {
        mobileMusicAction('pause');
    } else {
        mobileMusicAction('resume');
    }
}

function mobileMusicAction(action) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'music_control', action: action }));
    }
}

function closeMobileMusicBar() {
    const bar = document.getElementById('mobileMusicBar');
    if (bar) {
        bar.classList.remove('show');
        mobileMusicBarPlaying = false;
        stopMobileMusicPolling();
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'music_control', action: 'stop' }));
    }
}

// ===== ComfyUI 绘画 =====
let mobileComfyuiPollTimer = null;

function updateMobileComfyUIButton(running) {
    const btn = document.getElementById('comfyui-btn');
    const status = document.getElementById('comfyui-status');
    if (!btn || !status) return;

    if (running) {
        btn.className = 'quick-btn on';
        btn.title = '点击重启 ComfyUI';
        btn.onclick = restartComfyUI;
        status.textContent = '已就绪';
        clearInterval(mobileComfyuiPollTimer);
        mobileComfyuiPollTimer = null;
    } else {
        btn.className = 'quick-btn off';
        btn.title = '首次启动需等待约1-2分钟';
        btn.onclick = toggleComfyUI;
        status.textContent = '未启动';
    }
}

function toggleComfyUI() {
    const btn = document.getElementById('comfyui-btn');
    const status = document.getElementById('comfyui-status');
    if (!btn || !status) return;

    btn.className = 'quick-btn';
    btn.style.borderColor = '#FAAD14';
    btn.style.color = '#FAAD14';
    btn.style.background = '#FFFBE6';
    btn.title = '';
    btn.onclick = null;
    status.textContent = '正在启动...';

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'comfyui_start' }));
    }
}

function restartComfyUI() {
    const btn = document.getElementById('comfyui-btn');
    const status = document.getElementById('comfyui-status');
    if (!btn || !status) return;

    btn.className = 'quick-btn';
    btn.style.borderColor = '#FAAD14';
    btn.style.color = '#FAAD14';
    btn.style.background = '#FFFBE6';
    btn.title = '';
    btn.onclick = null;
    status.textContent = '正在重启...';

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'comfyui_restart' }));
    }
}

function pollMobileComfyUIStatus() {
    clearInterval(mobileComfyuiPollTimer);
    let attempts = 0;
    mobileComfyuiPollTimer = setInterval(() => {
        attempts++;
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'comfyui_status' }));
        }
        if (attempts >= 60) {
            clearInterval(mobileComfyuiPollTimer);
            mobileComfyuiPollTimer = null;
            updateMobileComfyUIButton(false);
            const st = document.getElementById('comfyui-status');
            if (st) st.textContent = '启动超时';
        }
    }, 2000);
}

// ===== 工具库 =====
let allTools = [];

async function openToolsLibrary() {
    document.getElementById('toolsModal').style.display = 'flex';
    if (allTools.length === 0) {
        try {
            const resp = await fetch('/api/tools');
            const data = await resp.json();
            allTools = data.tools || [];
            document.getElementById('toolsCount').textContent = `共 ${allTools.length} 个工具`;
        } catch (e) {
            document.getElementById('toolsList').innerHTML = '<div style="text-align:center;color:#e74c3c;padding:40px">加载失败</div>';
            return;
        }
    }
    renderMobileToolsList('all');
}

function closeToolsLibrary() {
    document.getElementById('toolsModal').style.display = 'none';
}

function filterTools(cat) {
    document.querySelectorAll('.tool-filter-btn').forEach(btn => {
        if (btn.dataset.cat === cat) {
            btn.style.background = '#4a90d9'; btn.style.color = '#fff'; btn.style.borderColor = '#4a90d9';
        } else {
            btn.style.background = '#fff'; btn.style.color = '#666'; btn.style.borderColor = '#d0d0d0';
        }
    });
    renderMobileToolsList(cat);
}

function renderMobileToolsList(cat) {
    const container = document.getElementById('toolsList');
    const filtered = cat === 'all' ? allTools : allTools.filter(t => t.category === cat);
    if (filtered.length === 0) {
        container.innerHTML = '<div style="text-align:center;color:#999;padding:40px">该分类下暂无工具</div>';
        return;
    }
    const catLabel = { builtin: '内置', hardware: '硬件', custom: '自定义', ai_custom: 'AI自定义' };
    let html = '';
    for (const tool of filtered) {
        const paramsHtml = tool.parameters.length > 0
            ? tool.parameters.map(p => {
                const badge = p.required
                    ? '<span style="font-size:10px;color:#e74c3c;background:#fdecea;padding:1px 5px;border-radius:3px;margin-left:4px">必填</span>'
                    : '<span style="font-size:10px;color:#999;background:#f5f5f5;padding:1px 5px;border-radius:3px;margin-left:4px">可选</span>';
                const enumInfo = p.enum && p.enum.length
                    ? '<br><span style="font-size:10px;color:#888">可选值: ' + p.enum.join(', ') + '</span>'
                    : '';
                return '<div style="margin:2px 0;font-size:11px;color:#555">' +
                    '<code style="background:#f0f0f0;padding:1px 4px;border-radius:2px">' + p.name + '</code> ' +
                    '<span style="color:#888">' + p.type + '</span>' + badge +
                    (p.description ? '<br><span style="color:#777">' + p.description + '</span>' : '') + enumInfo +
                    '</div>';
            }).join('')
            : '<div style="font-size:11px;color:#999">无参数</div>';
        html += '<div class="tool-item">' +
            '<div class="tool-name">' + tool.name +
            '<span class="tool-cat">' + (catLabel[tool.category] || tool.category) + '</span>' +
            '</div>' +
            '<div class="tool-desc">' + tool.description + '</div>' +
            paramsHtml +
            '</div>';
    }
    container.innerHTML = html;
}

// ===== 论文编辑 =====
let paperEditInfo = { name: '', title: '', format: 'markdown' };

async function editPaperContent(name) {
    try {
        const resp = await fetch(`/api/paper-source?name=${encodeURIComponent(name)}`);
        const data = await resp.json();
        if (data.error) { alert('无法加载源文件：' + data.error); return; }
        paperEditInfo = { name: data.name, title: data.title, format: data.format };
        document.getElementById('paperEditTitle').value = data.title;
        document.getElementById('paperEditContent').value = data.content;
        const fmtLabel = document.getElementById('paperEditFormat');
        fmtLabel.textContent = data.format === 'latex' ? 'LaTeX' : 'Markdown';
        fmtLabel.style.background = data.format === 'latex' ? '#e8f5e9' : '#e3f2fd';
        fmtLabel.style.color = data.format === 'latex' ? '#2e7d32' : '#1565c0';
        document.getElementById('paperEditModal').style.display = 'flex';
    } catch (e) { alert('加载失败：' + e.message); }
}

function closePaperEdit() {
    document.getElementById('paperEditModal').style.display = 'none';
}

async function regeneratePaper() {
    const title = document.getElementById('paperEditTitle').value.trim();
    const content = document.getElementById('paperEditContent').value.trim();
    if (!title) { alert('请输入标题'); return; }
    const btn = document.getElementById('paperRegenerateBtn');
    btn.disabled = true; btn.textContent = '正在生成...';
    try {
        const resp = await fetch('/api/regenerate-paper', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: paperEditInfo.name, title: title, content: content, format: paperEditInfo.format })
        });
        const data = await resp.json();
        if (data.ok) {
            closePaperEdit();
            addMobileMessage('system', '✅ 论文已重新生成，刷新预览即可查看最新版本。');
        } else {
            alert('生成失败：' + (data.error || '请重试'));
        }
    } catch (e) { alert('生成失败：' + e.message); }
    finally { btn.disabled = false; btn.textContent = '重新生成'; }
}

// ===== Spine 2D 动画 =====
let mobileSpinePlayer = null;
let mobileSpineReady = false;
let mobilePendingSkin = null;

function initMobileSpineAnimation() {
    const container = document.getElementById('spinePlayer');
    if (!container) return;

    function doInit() {
        try {
            mobileSpinePlayer = new spine.SpinePlayer(container, {
                jsonUrl: '/static/spine/character.json',
                atlasUrl: '/static/spine/character.atlas',
                skin: 'default',
                animation: 'blink',
                premultipliedAlpha: false,
                alpha: true,
                backgroundColor: '#00000000',
                showControls: false,
                success: (player) => {
                    mobileSpinePlayer = player;
                    mobileSpineReady = true;
                    if (mobilePendingSkin) {
                        switchMobileSpineSkin(mobilePendingSkin);
                        mobilePendingSkin = null;
                    }
                },
                error: () => { mobileFallbackAvatar(); }
            });
        } catch (e) { mobileFallbackAvatar(); }
    }

    function mobileFallbackAvatar() {
        const spineContainer = document.getElementById('spineContainer');
        if (spineContainer) {
            spineContainer.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:36px;">🤖</div>';
        }
    }

    if (typeof spine !== 'undefined' && spine.SpinePlayer) {
        doInit();
    } else {
        const script = document.createElement('script');
        script.src = '/static/spine-player.js';
        script.onload = doInit;
        script.onerror = () => mobileFallbackAvatar();
        document.head.appendChild(script);
    }
}

function switchMobileSpineSkin(skin) {
    if (!['default', 'happy', 'unhappy'].includes(skin)) return;
    if (!mobileSpineReady || !mobileSpinePlayer || !mobileSpinePlayer.skeleton) {
        mobilePendingSkin = skin;
        return;
    }
    try {
        const skel = mobileSpinePlayer.skeleton;
        const mouthMap = { 'default': 'mouth_smile', 'happy': 'mouth_open', 'unhappy': 'mouth_unhappy' };
        skel.setAttachment('mouth', mouthMap[skin]);
        skel.setSlotsToSetupPose();
    } catch (e) {}
}

// ===== 滚动 =====
function scrollMobileBottom() {
    const container = document.getElementById('mobileChat');
    requestAnimationFrame(() => { container.scrollTop = container.scrollHeight; });
}

// ===== 输入框 =====
const mobileInput = document.getElementById('mobileInput');
mobileInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        mobileSend();
    }
});
mobileInput.addEventListener('input', () => {
    mobileInput.style.height = 'auto';
    mobileInput.style.height = Math.min(mobileInput.scrollHeight, 100) + 'px';
});

// ===== 启动 =====
connect();
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMobileSpineAnimation);
} else {
    initMobileSpineAnimation();
}

// 安全兜底
setTimeout(() => {
    const input = document.getElementById('mobileInput');
    const sendBtn = document.getElementById('mobileSendBtn');
    const uploadBtn = document.getElementById('mobileUploadBtn');
    const cameraBtn = document.getElementById('mobileCameraBtn');
    if (input && input.disabled) {
        input.disabled = false;
        if (sendBtn) sendBtn.disabled = false;
        if (uploadBtn) uploadBtn.disabled = false;
        if (cameraBtn) cameraBtn.disabled = false;
    }
}, 3000);

// 点击外部关闭面板和菜单
document.addEventListener('click', (e) => {
    const panel = document.getElementById('statusPanel');
    if (panel && panel.classList.contains('show') && !e.target.closest('#mobileStatusBtn') && !e.target.closest('#statusPanel')) {
        panel.classList.remove('show');
    }
});

// ===== 服务管理面板 =====
function openServicesPanel() {
    var modal = document.getElementById('servicesModal');
    if (modal) modal.style.display = 'flex';
}

function closeServicesPanel() {
    var modal = document.getElementById('servicesModal');
    if (modal) modal.style.display = 'none';
}

(function() {
    var modal = document.getElementById('servicesModal');
    if (modal) {
        modal.addEventListener('click', function(e) {
            if (e.target === modal) closeServicesPanel();
        });
    }
})();

// ===== 记忆管理 =====
var _toastTimer=null;
function showToast(msg){
  var t=document.getElementById('toast');clearTimeout(_toastTimer);
  t.textContent=msg;t.classList.add('show');
  _toastTimer=setTimeout(function(){t.classList.remove('show')},1500);
}
var _memItems=[];_memSelected=new Set();_memAll=[];
function openMemoryManager(){
  var m=document.getElementById('memoryModal');
  if(m)m.style.display='flex';
  loadMemStats();loadMemAll();
}
function closeMemoryManager(){
  var m=document.getElementById('memoryModal');
  if(m)m.style.display='none';
}

async function loadMemStats(){
  try{var r=await fetch('/api/memory/stats');var d=await r.json();document.getElementById('memTotal').textContent=d.total+' 条';}catch(e){}
}

async function loadMemAll(){
  _memSelected.clear();updateDelBtn();document.getElementById('memSelectAllBtn').textContent='全选';
  document.getElementById('memSearchInput').value='';document.getElementById('memSearchHint').textContent='';
  try{
    var r=await fetch('/api/memory/list?limit=200');var d=await r.json();
    _memAll=d.memories||[];_memItems=_memAll;
    renderMemList();
  }catch(e){document.getElementById('memDeleteList').innerHTML='<div style="text-align:center;color:#999;padding:30px">加载失败</div>'}
}

function renderMemList(){
  var el=document.getElementById('memDeleteList');var items=_memItems;
  if(!items.length){el.innerHTML='<div style="text-align:center;color:#999;padding:30px">'+(document.getElementById('memSearchInput').value?'无匹配':'暂无记忆')+'</div>';return}
  el.innerHTML=items.map(function(m,i){
    var txt=m.document||'';var preview=txt.length>80?txt.substring(0,80)+'...':txt;
    var sel=_memSelected.has(i);
    return '<label id="memDelLabel'+i+'" style="display:flex;align-items:flex-start;gap:6px;padding:8px;margin-bottom:4px;border:1px solid '+(sel?'#ef4444':'#f0f0f0')+';border-radius:6px;font-size:12px"><input type="checkbox" data-idx="'+i+'" data-id="'+m.id+'" onchange="memToggleItem(this)"'+(sel?' checked':'')+' style="margin-top:2px"><div style="flex:1"><div style="color:#999;font-size:10px">#'+(i+1)+' | '+(m.session_id||'?')+'</div><div>'+preview.replace(/</g,'&lt;')+'</div></div></label>';
  }).join('');
}

function memSearch(){
  var q=document.getElementById('memSearchInput').value.trim().toLowerCase();
  if(!q){_memItems=_memAll;document.getElementById('memSearchHint').textContent=''}
  else{
    _memItems=_memAll.filter(function(m){return (m.document||'').toLowerCase().indexOf(q)>-1;});
    document.getElementById('memSearchHint').textContent='匹配'+_memItems.length+'条';
  }
  _memSelected.clear();updateDelBtn();document.getElementById('memSelectAllBtn').textContent='全选';
  renderMemList();
}

function memToggleItem(cb){
  var idx=parseInt(cb.dataset.idx);var label=document.getElementById('memDelLabel'+idx);
  if(cb.checked){_memSelected.add(idx);if(label)label.style.borderColor='#ef4444'}
  else{_memSelected.delete(idx);if(label)label.style.borderColor='#f0f0f0'}
  updateDelBtn();
}
function memToggleSelectAll(){
  if(!_memItems.length)return;
  var all=document.getElementById('memSelectAllBtn');
  var allSelected=_memSelected.size===_memItems.length;
  var cbs=document.querySelectorAll('#memDeleteList input[type=checkbox]');
  cbs.forEach(function(cb){cb.checked=!allSelected;memToggleItem(cb)});
  all.textContent=allSelected?'全选':'取消全选';
}
function updateDelBtn(){
  var btn=document.getElementById('memDeleteBtn');
  btn.disabled=_memSelected.size===0;
  btn.textContent='删除'+( _memSelected.size?'('+_memSelected.size+')':'');
}
async function memDeleteSelected(){
  if(_memSelected.size===0)return;
  var ids=[];_memSelected.forEach(function(i){ids.push(_memItems[i].id)});
  if(!confirm('确定删除'+ids.length+'条？'))return;
  var ok=0;
  for(var i=0;i<ids.length;i++){try{await fetch('/api/memory/'+encodeURIComponent(ids[i]),{method:'DELETE'});ok++}catch(e){}}
  showToast('已删除'+ok+'/'+ids.length+'条');
  loadMemAll();
}
(function(){
  var m=document.getElementById('memoryModal');
  if(m)m.addEventListener('click',function(e){if(e.target===m)closeMemoryManager()});
})();