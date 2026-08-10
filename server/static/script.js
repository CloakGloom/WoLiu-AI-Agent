/**
 * AI Agent 跨设备漫游系统 - WebSocket 客户端脚本
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
        // 连接后检查 ComfyUI 状态 & 绘画模型
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

function scheduleReconnect() {
    clearReconnect();
    reconnectTimer = setTimeout(connect, 3000);
}
function clearReconnect() {
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
}

// ===== 安全 WS 发送与 HTTP 降级刷新 =====
// WS 断开时 ws.send 会抛 InvalidStateError，导致后续 UI 刷新逻辑中断（如删除会话后列表不刷新）
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

// 会话变更后的刷新：WS 推历史+会话列表（快速），同时 HTTP 兜底确保可靠性
async function refreshAfterChange(targetId) {
    // 先尝试 WS 通道（switch_session 会推 history + session_list）
    const wsOk = wsSend({ type: 'switch_session', session_id: targetId });
    // HTTP 兜底：无论 WS 是否成功，都拉一遍会话列表保证 UI 一定更新
    try {
        const r = await fetch('/api/sessions');
        const data = await r.json();
        renderSessionList(data.sessions || [], targetId);
        // WS 不可用时才通过 HTTP 加载历史（WS 可用时后端已推送）
        if (!wsOk) {
            const mr = await fetch('/api/sessions/' + targetId + '/messages');
            const md = await mr.json();
            loadHistory((md.messages || []).filter(m => m.role === 'user' || m.role === 'assistant'));
        }
    } catch (e) {
        console.error('刷新会话失败:', e);
    }
}
function updateWsStatus(text, color) {
    const el = document.getElementById('wsStatusText');
    el.textContent = text;
    el.style.color = color;
}

// ===== 消息处理 =====
let currentProcessGroup = null;   // 当前正在构建的过程组 DOM
let currentSessionId = null;      // 当前活跃会话 ID
let tempIdCounter = -1;            // 临时消息 ID（负数，避免与 DB 正数 ID 冲突）
let streamingState = null;         // 流式回复状态 {row, textEl, buffer}
let progressBars = {};             // 工具进度条 {tool: element}

function handleMessage(msg) {
    switch (msg.type) {
        case 'status':
            updateStatus(msg['state.agent_location'] || msg.agent_location, msg.status);
            break;
        case 'history':
            loadHistory(msg.messages);
            break;
        case 'session_list':
            renderSessionList(msg.sessions, msg.current);
            break;
        case 'process':
            handleProcessStep(msg.step);
            break;
        case 'stream_start':
            handleStreamStart();
            break;
        case 'stream_delta':
            handleStreamDelta(msg.delta);
            break;
        case 'stream_done':
            handleStreamDone(msg.content);
            break;
        case 'progress':
            handleProgress(msg);
            break;
        case 'response':
            currentProcessGroup = null;
            addMessage('agent', msg.content, null, null, msg.chunk_index, msg.chunk_total);
            checkMigrationComplete(msg.content);
            break;
        case 'migrate_data':
            loadHistory(msg.messages);
            ws.send(JSON.stringify({ type: 'migrate_ack', status: 'ok' }));
            break;
        case 'migrate_ack':
            break;
        case 'music_state':
            updateMusicBar(msg.result);
            break;
        case 'comfyui_status':
            updateComfyUIButton(msg.running);
            break;
        case 'comfyui_start_result':
            if (msg.success) {
                // 不立即显示已就绪，让 polling 确认真正在线后再改
                pollComfyUIStatus();
            } else {
                updateComfyUIButton(false);
                document.getElementById('comfyui-status').textContent = msg.message;
            }
            break;

        case 'personality_state_result':
            if (typeof renderPersonalityState === 'function') {
                renderPersonalityState(msg);
            }
            break;
        case 'personality_list_result':
        case 'personality_switch_result':
        case 'comfyui_restart_result':
            if (msg.success) {
                updateComfyUIButton(true);
            } else {
                updateComfyUIButton(false);
                document.getElementById('comfyui-status').textContent = msg.message;
            }
            break;

        case 'error':
            addMessage('system', msg.content);
            break;
    }
}

function handleProcessStep(step) {
    // 拦截表情切换指令
    if (step.type === 'tool_result' && step.content && step.content.includes('[EXPRESSION:')) {
        const match = step.content.match(/\[EXPRESSION:(\w+)\]/);
        if (match) {
            switchSpineSkinDirect(match[1]);
        }
    }
    // 拦截音乐播放状态更新
    if (step.type === 'tool_result' && step.content && step.content.includes('[MUSIC:')) {
        updateMusicBar(step.content);
    }
    // 只在实际调用工具时才创建思考过程组
    if (!currentProcessGroup) {
        if (step.type === 'tool_call' || step.type === 'tool_result') {
            currentProcessGroup = createProcessGroup();
        } else {
            return; // thinking 步骤不显示，等真正调用工具再说
        }
    }
    addProcessStep(currentProcessGroup, step);
}

function createProcessGroup() {
    const container = document.getElementById('chatMessages');
    const welcome = container.querySelector('.welcome-message');
    if (welcome) welcome.remove();

    const group = document.createElement('div');
    group.className = 'process-group';

    // 折叠头部
    const toggle = document.createElement('button');
    toggle.className = 'process-toggle';
    toggle.innerHTML = `
        <span class="toggle-icon"><i class="fas fa-caret-right"></i></span>
        <span>思考过程</span>
        <span class="process-summary">正在思考...</span>
    `;
    toggle.addEventListener('click', () => {
        group.classList.toggle('expanded');
    });

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

    let icon = '';
    let label = '';
    let cssClass = '';

    switch (step.type) {
        case 'thinking':
            icon = '&#9678;';
            label = '思考中...';
            cssClass = 'thinking';
            summary.textContent = '正在思考...';
            break;
        case 'tool_call':
            icon = '&#9881;';
            label = `调用工具: <code>${escapeHtml(step.name)}</code>`;
            cssClass = 'tool-call';
            summary.textContent = `调用工具: ${step.name}`;
            if (step.arguments && Object.keys(step.arguments).length > 0) {
                label += `<pre>${escapeHtml(JSON.stringify(step.arguments, null, 2))}</pre>`;
            }
            break;
        case 'tool_result':
            icon = '&#10003;';
            label = `工具结果: ${escapeHtml(step.content)}`;
            cssClass = 'tool-result';
            summary.textContent = `获取结果: ${step.name}`;
            break;
    }

    stepEl.className = `process-step ${cssClass}`;
    stepEl.innerHTML = `
        <span class="step-icon">${icon}</span>
        <span class="step-content">${label}</span>
    `;
    steps.appendChild(stepEl);
    scrollToBottom();
}

function checkMigrationComplete(content) {
    if (isMigrating) {
        if (content.includes('迁移成功') || content.includes('已在')) {
            completeMigration();
        }
    }
}

// ===== 流式回复渲染 =====
let streamTtsRef = null;
let ttsUserEnabled = false;  // 只有用户在设置中开启后才为 true

function detectTtsRef() {
    // 先看系统消息里有没有已上传的音频引用
    var msgs = document.querySelectorAll('.msg-system');
    for (var i = msgs.length-1; i >= 0; i--) {
        var m = msgs[i].textContent.match(/I:\/Agent\/data\/uploads\/[^\s]+\.(mp3|wav|m4a|flac)/i);
        if (m) { return m[0]; }
    }
    return null;
}

function handleStreamStart() {
    if (streamingState) { streamingState = null; }
    currentProcessGroup = null;
    streamTtsRef = ttsUserEnabled ? detectTtsRef() : null;
    if (ttsUserEnabled) {
        fetch('/api/tts/detect-ref').then(function(r) { return r.json(); }).then(function(d) {
            if (d.ref) streamTtsRef = d.ref;
        }).catch(function() {});
    }
    var container = document.getElementById('chatMessages');
    var welcome = container.querySelector('.welcome-message');
    if (welcome) welcome.remove();
    // 不创建任何可见行，只记录缓冲——等 stream_done 后一次性渲染
    streamingState = { row: null, textEl: null, buffer: '' };
}

function handleStreamDelta(delta) {
    if (!delta) return;
    if (!streamingState) handleStreamStart();
    streamingState.buffer += delta;
}

function handleStreamDone(content) {
    if (streamingState) { streamingState = null; }
    document.querySelectorAll('.stream-cursor').forEach(function(el) { el.remove(); });
    currentProcessGroup = null;
    if (content) {
        var sentences = splitSentences(content);
        showSentencesWithTTS(sentences, content);
        checkMigrationComplete(content);
    }
    scrollToBottom();
}

// ===== 逐句 TTS 朗读 + 同步展示 =====

function splitSentences(text) {
    // 与 server _send_chunked_response 一致的分句逻辑
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
            if (s.length > 80) {
                var sub2 = s.split(/(?<=[，,；;])/);
                for (var k = 0; k < sub2.length; k++) {
                    var x = sub2[k].trim();
                    if (x) chunks.push(x);
                }
            } else {
                chunks.push(s);
            }
        }
    }
    // 合并过短的相邻片段
    var merged = [];
    for (var m = 0; m < chunks.length; m++) {
        if (merged.length && (merged[merged.length-1].length + chunks[m].length) < 30) {
            merged[merged.length-1] += chunks[m];
        } else if (chunks[m]) {
            merged.push(chunks[m]);
        }
    }
    return merged.filter(function(c) { return c.length > 0; });
}

function showSentencesWithTTS(sentences, fullContent) {
    var i = 0;
    var rows = [];

    function next() {
        if (i >= sentences.length) {
            // 全部句子显示完后，重新渲染完整内容（支持 IMAGE/PAPER 标记）
            if (/\[(IMAGE|PAPER|VIDEO):/.test(fullContent)) {
                var lastRow = rows[rows.length - 1];
                if (lastRow) {
                    var bubble = lastRow.querySelector('.msg-bubble');
                    if (bubble) bubble.innerHTML = formatMessageContent(fullContent);
                }
            }
            scrollToBottom();
            // 所有文本一次性发送给 TTS
            if (streamTtsRef) speakFullText(fullContent);
            return;
        }
        var text = sentences[i];
        i++;
        addMessage('agent', text, null, null, 0, 1);
        var container = document.getElementById('chatMessages');
        var allRows = container.querySelectorAll('.msg-row.agent');
        var row = allRows[allRows.length - 1];
        if (row) rows.push(row);
        scrollToBottom();
        setTimeout(next, 200);
    }
    next();
}

function speakFullText(text) {
    if (!text || !streamTtsRef) return;
    var cleanText = text.replace(/\[(IMAGE|PAPER|VIDEO):[^\]]+\]/g, '');
    fetch('/api/tts/speak', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: cleanText, lang: 'zh', reference: streamTtsRef })
    }).then(function(r) {
        if (!r.ok) throw new Error('TTS fail');
        return r.blob();
    }).then(function(blob) {
        var url = URL.createObjectURL(blob);
        var a = new Audio(url);
        a.onended = function() { URL.revokeObjectURL(url); };
        a.onerror = function() { URL.revokeObjectURL(url); };
        a.play();
    }).catch(function() {});
}

// 按 ||| 分隔符将回复拆成多条自然消息（保留图片/论文标记渲染）
function renderAgentReply(content) {
    if (content.includes('|||')) {
        const parts = content.split('|||').map(s => s.trim()).filter(Boolean);
        parts.forEach((part, i) => addMessage('agent', part, null, null, i, parts.length));
    } else {
        addMessage('agent', content);
    }
}

// ===== 工具进度条 =====
function toolDisplayName(tool) {
    const map = {
        generate_image: 'AI 绘画',
        generate_paper: '论文 / PDF',
        generate_ppt: 'PPT 生成',
        generate_kimi_ppt: 'PPT 生成',
        generate_presenton_ppt: 'Presenton PPT'
    };
    return map[tool] || tool;
}

function handleProgress(p) {
    const tool = p.tool || 'task';
    const pct = Math.max(0, Math.min(100, Number(p.percent) || 0));
    const message = p.message || '';

    let wrap = progressBars[tool];
    if (!wrap) {
        // 已完成事件且无进行中进度条：无需创建，避免普通工具闪现
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
        const container = document.getElementById('chatMessages');
        container.appendChild(wrap);
        progressBars[tool] = wrap;
    }

    wrap.querySelector('.tool-progress-name').textContent = toolDisplayName(tool);
    wrap.querySelector('.tool-progress-pct').textContent = Math.round(pct) + '%';
    wrap.querySelector('.tool-progress-fill').style.width = pct + '%';
    if (message) wrap.querySelector('.tool-progress-msg').textContent = message;
    scrollToBottom();

    if (pct >= 100) {
        wrap.classList.add('done');
        setTimeout(() => {
            if (wrap.parentNode) wrap.parentNode.removeChild(wrap);
            if (progressBars[tool] === wrap) delete progressBars[tool];
        }, 1200);
    }
}

// ===== 状态更新 =====
function updateStatus(location, status) {
    console.log('updateStatus called:', { location, status });
    
    const indicator = document.getElementById('statusIndicator');
    const statusText = document.getElementById('statusText');
    const avatar = document.getElementById('agentAvatar');
    const deviceText = document.getElementById('agentDeviceText');
    const sendBtn = document.getElementById('sendBtn');
    const inputBox = document.getElementById('inputBox');
    const infoLocation = document.getElementById('infoLocation');
    const infoOnline = document.getElementById('infoOnline');
    const uploadBtn = document.getElementById('uploadBtn');

    console.log('DOM elements:', { indicator, statusText, avatar, deviceText, sendBtn, inputBox });

    if (!indicator || !statusText || !deviceText || !sendBtn || !inputBox) {
        console.error('Some DOM elements not found');
        return;
    }

    indicator.className = 'status-indicator';
    if (avatar) avatar.className = 'agent-avatar';
    deviceText.className = 'agent-device';

    if (location === 'pc') {
        infoLocation.textContent = '电脑';
        if (status === 'online') {
            console.log('Setting inputBox to enabled');
            isAgentOnline = true;
            isMigrating = false;
            indicator.classList.add('online');
            statusText.textContent = '在线';
            infoOnline.textContent = '在线';
            if (avatar) avatar.classList.remove('offline', 'migrating');
            deviceText.textContent = '当前在 电脑端';
            sendBtn.disabled = false;
            inputBox.disabled = false;
            if (uploadBtn) uploadBtn.disabled = false;
            stopMigrationAnimation();
        } else {
            isAgentOnline = false;
            indicator.classList.add('offline');
            statusText.textContent = '离线';
            infoOnline.textContent = '离线';
            if (avatar) avatar.classList.add('offline');
            deviceText.textContent = '当前在 电脑端（离线）';
            sendBtn.disabled = true;
            inputBox.disabled = true;
            if (uploadBtn) uploadBtn.disabled = true;
        }
    } else if (location === 'mobile') {
        infoLocation.textContent = '手机';
        isAgentOnline = false;
        indicator.classList.add('offline');
        statusText.textContent = '已迁移';
        infoOnline.textContent = '离线（在手机）';
        if (avatar) avatar.classList.add('offline');
        deviceText.textContent = '已迁移到 手机端';
        sendBtn.disabled = true;
        inputBox.disabled = true;
        stopMigrationAnimation();
    } else if (location === 'migrating') {
        infoLocation.textContent = '迁移中...';
        isMigrating = true;
        isAgentOnline = false;
        indicator.className = 'status-indicator migrating';
        statusText.textContent = '迁移中';
        infoOnline.textContent = '迁移中...';
        if (avatar) avatar.classList.add('migrating');
        deviceText.classList.add('migrating-text');
        deviceText.textContent = '正在迁移...';
        sendBtn.disabled = true;
        inputBox.disabled = true;
        startMigrationAnimation();
    }
}

// ===== 迁移动画 =====
function startMigrationAnimation() {
    const progressBar = document.getElementById('migrateProgressBar');
    const progressFill = document.getElementById('migrateProgressFill');
    const progressText = document.getElementById('migrateProgressText');

    progressBar.classList.add('active');
    progressFill.style.width = '0%';
    progressText.textContent = '迁移准备中...';

    let progress = 0;
    const totalDuration = 5000;
    const interval = 50;

    stopMigrationAnimation();

    migrateTimer = setInterval(() => {
        progress += (interval / totalDuration) * 100;
        if (progress >= 100) {
            progress = 100;
            clearInterval(migrateTimer);
            migrateTimer = null;
        }
        progressFill.style.width = progress + '%';

        if (progress < 30) {
            progressText.textContent = '打包会话数据...';
        } else if (progress < 60) {
            progressText.textContent = '传输到目标设备...';
        } else if (progress < 90) {
            progressText.textContent = '等待目标确认...';
        } else {
            progressText.textContent = '即将完成...';
        }
    }, interval);
}

function stopMigrationAnimation() {
    if (migrateTimer) { clearInterval(migrateTimer); migrateTimer = null; }
    const progressBar = document.getElementById('migrateProgressBar');
    progressBar.classList.remove('active');
    document.getElementById('migrateProgressFill').style.width = '0%';
}

function completeMigration() {
    stopMigrationAnimation();
    const progressFill = document.getElementById('migrateProgressFill');
    progressFill.style.width = '100%';
    setTimeout(() => {
        document.getElementById('migrateProgressBar').classList.remove('active');
        progressFill.style.width = '0%';
    }, 500);
    isMigrating = false;
}

// ===== 历史消息加载 =====
function loadHistory(msgs) {
    const container = document.getElementById('chatMessages');
    container.innerHTML = '';
    if (!msgs || msgs.length === 0) {
        container.innerHTML = `
            <div class="welcome-message">
                <div class="welcome-icon"><i class="fas fa-robot"></i></div>
                <h3>欢迎使用 AI Agent</h3>
                <p>Agent 当前在电脑端运行<br>输入消息开始对话</p>
            </div>`;
        return;
    }
    for (const m of msgs) {
        if (m.role === 'user') {
            addMessage('user', m.content, m.message_id, m.branches);
        } else if (m.role === 'assistant' && m.content) {
            if (m.process_steps) {
                try {
                    const steps = typeof m.process_steps === 'string'
                        ? JSON.parse(m.process_steps)
                        : m.process_steps;
                    renderHistoryProcessSteps(steps);
                } catch (e) {}
            }
            // 按句子拆分，每条独立气泡（message_id 只给最后一句）
            var parts = splitSentences(m.content);
            if (parts.length <= 1) {
                addMessage('agent', m.content, m.message_id);
            } else {
                for (var p = 0; p < parts.length; p++) {
                    var mid = (p === parts.length - 1) ? m.message_id : null;
                    addMessage('agent', parts[p], mid);
                }
            }
        }
    }
    // 初始化分支数据：延迟执行确保 DOM 已更新
    setTimeout(() => {
        initBranchData();
    }, 0);
    scrollToBottom();
}

function initBranchData() {
    // 遍历所有有分支的用户消息，保存其后的AI回复（跳过 process-group）
    document.querySelectorAll('.msg-row.user[data-branches]').forEach(userRow => {
        let sibling = userRow.nextElementSibling;
        let aiRow = null;
        while (sibling) {
            if (sibling.classList.contains('msg-row')) {
                if (sibling.classList.contains('agent')) aiRow = sibling;
                break;
            }
            sibling = sibling.nextElementSibling;
        }
        if (aiRow) {
            const aiBubble = aiRow.querySelector('.msg-bubble');
            if (aiBubble) {
                userRow.dataset.newContent = aiBubble.textContent;
                console.log('初始化 newContent:', aiBubble.textContent.substring(0, 50));
            } else {
                console.warn('找不到 AI 消息的 bubble');
            }
        } else {
            console.warn('找不到 AI 消息行');
        }
    });
}

function renderHistoryProcessSteps(steps) {
    const container = document.getElementById('chatMessages');
    const group = document.createElement('div');
    group.className = 'process-group';

    const toggle = document.createElement('button');
    toggle.className = 'process-toggle';
    toggle.innerHTML = `
        <span class="toggle-icon"><i class="fas fa-caret-right"></i></span>
        <span>思考过程</span>
        <span class="process-summary">${formatSummary(steps)}</span>
    `;
    toggle.addEventListener('click', () => {
        group.classList.toggle('expanded');
    });

    const stepsContainer = document.createElement('div');
    stepsContainer.className = 'process-steps';

    for (const step of steps) {
        const stepEl = buildStepElement(step);
        stepsContainer.appendChild(stepEl);
    }

    group.appendChild(toggle);
    group.appendChild(stepsContainer);
    container.appendChild(group);
}

function formatSummary(steps) {
    const toolCalls = steps.filter(s => s.type === 'tool_call');
    if (toolCalls.length > 0) {
        return `调用工具: ${toolCalls.map(s => s.name).join(', ')}`;
    }
    return '思考完成';
}

function buildStepElement(step) {
    const stepEl = document.createElement('div');
    let icon = '', label = '', cssClass = '';

    switch (step.type) {
        case 'thinking':
            icon = '&#9678;'; label = '思考中...'; cssClass = 'thinking';
            break;
        case 'tool_call':
            icon = '&#9881;';
            label = `调用工具: <code>${escapeHtml(step.name)}</code>`;
            cssClass = 'tool-call';
            if (step.arguments && Object.keys(step.arguments).length > 0) {
                label += `<pre>${escapeHtml(JSON.stringify(step.arguments, null, 2))}</pre>`;
            }
            break;
        case 'tool_result':
            icon = '&#10003;';
            label = `工具结果: ${escapeHtml(step.content)}`;
            cssClass = 'tool-result';
            break;
    }

    stepEl.className = `process-step ${cssClass}`;
    stepEl.innerHTML = `
        <span class="step-icon">${icon}</span>
        <span class="step-content">${label}</span>
    `;
    return stepEl;
}

// ===== 消息渲染 =====
function addMessage(role, content, messageId, branches, chunkIndex, chunkTotal) {
    if (!content) return;

    // 当添加新的完整 agent 消息时，清理所有残留的流式光标
    if (role === 'agent' && !chunkIndex) {
        document.querySelectorAll('.stream-cursor').forEach(function(el) { el.remove(); });
        if (streamingState && streamingState.row) {
            streamingState.row.remove();
            streamingState = null;
        }
    }

    const container = document.getElementById('chatMessages');
    const welcome = container.querySelector('.welcome-message');
    if (welcome) welcome.remove();

    // 如果没有 ID，分配临时 ID
    const msgId = messageId || (tempIdCounter--);
    const isTemp = !messageId;  // 是否是临时消息
    const isChunk = chunkTotal > 1;          // 是否为分块消息
    const isContinuation = isChunk && chunkIndex > 0;  // 是否为后续分块（不显示头像）

    const row = document.createElement('div');
    row.className = `msg-row ${role}`;
    if (isContinuation) row.classList.add('chunk-continuation');
    row.dataset.messageId = msgId;

    if (role === 'system') {
        row.innerHTML = `
            <div class="msg-content">
                <div class="msg-bubble">${formatMessageContent(content)}</div>
            </div>`;
    } else {
        const avatarEmoji = role === 'user' ? '<i class="fas fa-user"></i>' : '<i class="fas fa-robot"></i>';
        const label = role === 'user' ? '你' : 'Agent';
        const time = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });

        // 根据角色构建不同菜单
        let menuHtml = '';
        if (role === 'user') {
            menuHtml = `
                <button class="msg-more" onclick="toggleMsgMenu(event, ${msgId})" title="更多"><i class="fas fa-ellipsis-vertical"></i></button>
                <div class="msg-menu" id="msgMenu-${msgId}">
                    <button class="session-menu-item" onclick="msgCopy(event, ${msgId})">
                        <span class="menu-icon"><i class="fas fa-clipboard"></i></span> 复制
                    </button>
                    <button class="session-menu-item" onclick="${isTemp ? 'alert(\'请刷新页面后再编辑\')' : 'msgEditUser(event, ' + msgId + ')'}">
                        <span class="menu-icon"><i class="fas fa-pen-to-square"></i></span> 编辑
                    </button>
                    <button class="session-menu-item danger" onclick="${isTemp ? 'alert(\'请刷新页面后再删除\')' : 'msgDelete(event, ' + msgId + ')'}">
                        <span class="menu-icon"><i class="fas fa-trash-can"></i></span> 删除
                    </button>
                </div>`;
        } else {
            menuHtml = `
                <button class="msg-more" onclick="toggleMsgMenu(event, ${msgId})" title="更多"><i class="fas fa-ellipsis-vertical"></i></button>
                <div class="msg-menu" id="msgMenu-${msgId}">
                    <button class="session-menu-item" onclick="msgCopy(event, ${msgId})">
                        <span class="menu-icon"><i class="fas fa-clipboard"></i></span> 复制
                    </button>
                    <button class="session-menu-item danger" onclick="${isTemp ? 'alert(\'请刷新页面后再删除\')' : 'msgDelete(event, ' + msgId + ')'}">
                        <span class="menu-icon"><i class="fas fa-trash-can"></i></span> 删除
                    </button>
                </div>`;
        }

        // 分支切换箭头
        let branchHtml = '';
        if (role === 'user' && branches) {
            let branchList = [];
            try {
                branchList = typeof branches === 'string' ? JSON.parse(branches) : branches;
            } catch (e) {}
            if (branchList.length > 0) {
                row.dataset.branches = JSON.stringify(branchList);
                branchHtml = `
                    <div class="branch-nav">
                        <button class="branch-arrow" onclick="switchBranch(event, ${msgId}, -1)" title="上一个分支"><i class="fas fa-chevron-left"></i></button>
                        <span class="branch-label">分支 1/${branchList.length + 1}</span>
                        <button class="branch-arrow" onclick="switchBranch(event, ${msgId}, 1)" title="下一个分支"><i class="fas fa-chevron-right"></i></button>
                    </div>`;
            }
        }

        row.innerHTML = `
            <div class="msg-avatar">${avatarEmoji}</div>
            <div class="msg-content">
                <div class="msg-label">${label}</div>
                <div class="msg-bubble">${formatMessageContent(content)}</div>
                <div class="msg-time">${time}</div>
                ${branchHtml}
            </div>
            ${menuHtml}`;
    }

    // 分块续接消息：去除头像、标签、时间，只保留气泡
    if (isContinuation) {
        row.innerHTML = `
            <div class="msg-content chunk-bubble">
                <div class="msg-bubble">${formatMessageContent(content)}</div>
            </div>`;
    }

    container.appendChild(row);
    scrollToBottom();
}

function formatMessageContent(text) {
    // 检测 [IMAGE:url] 标记，渲染为真实图片
    const imgRegex = /\[IMAGE:([^\]]+)\]/g;
    // 检测 [PAPER:url] 标记，渲染为内嵌PDF
    const paperRegex = /\[PAPER:([^\]]+)\]/g;
    // 检测 [VIDEO:url] 标记，渲染为视频播放器
    const videoRegex = /\[VIDEO:([^\]]+)\]/g;

    let result;
    if (imgRegex.test(text) || paperRegex.test(text) || videoRegex.test(text)) {
        imgRegex.lastIndex = 0;
        paperRegex.lastIndex = 0;
        videoRegex.lastIndex = 0;
        result = '';
        let lastIdx = 0;

        const markers = [];
        let match;
        while ((match = imgRegex.exec(text)) !== null) {
            markers.push({ idx: match.index, end: imgRegex.lastIndex, type: 'image', url: match[1] });
        }
        while ((match = paperRegex.exec(text)) !== null) {
            markers.push({ idx: match.index, end: paperRegex.lastIndex, type: 'paper', url: match[1] });
        }
        while ((match = videoRegex.exec(text)) !== null) {
            markers.push({ idx: match.index, end: videoRegex.lastIndex, type: 'video', url: match[1] });
        }
        markers.sort((a, b) => a.idx - b.idx);

        // 去重：同一个 URL 只渲染一次
        const seenUrls = new Set();
        const deduped = [];
        for (const m of markers) {
            const key = m.type + ':' + m.url;
            if (!seenUrls.has(key)) {
                seenUrls.add(key);
                deduped.push(m);
            }
        }

        for (const m of deduped) {
            result += renderMarkdown(text.slice(lastIdx, m.idx));
            if (m.type === 'image') {
                result += `<img src="${m.url}" alt="AI生成的图片" style="max-width:100%;border-radius:8px;cursor:pointer;margin:8px 0" onclick="window.open(this.src)" loading="lazy" />`;
            } else if (m.type === 'paper') {
                result += renderPaperEmbed(m.url);
            } else if (m.type === 'video') {
                result += `<video src="${m.url}" controls style="max-width:100%;max-height:480px;border-radius:8px;margin:8px 0;background:#000" preload="metadata"></video>`;
            }
            lastIdx = m.end;
        }
        result += renderMarkdown(text.slice(lastIdx));
    } else {
        result = renderMarkdown(text);
    }
    return result;
}

function renderMarkdown(text) {
    // 先转义 HTML，再转换 Markdown 语法
    let html = escapeHtml(text);

    // 0a. 链接 [text](url) —— 提前处理，避免 URL 被裸 URL 规则误吞
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

    // 0b. 保护裸 URL（http/https，排除已在 href="..." 中的），先转为占位符，最后渲染为超链接
    const _urls = [];
    html = html.replace(/(?<!href=")\bhttps?:\/\/[\w\-._~:/?#\[\]@!$&'()+,;=%]+/g, (u) => {
        const trailing = u.match(/[).,;:!?]+$/);
        if (trailing) u = u.slice(0, -trailing[0].length);
        return `\u0001URL${_urls.push(u) - 1}\u0001`;
    });

    // 1. 代码块 ```...```（多行）—— 最先处理，避免内部语法被误解析
    html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
        return `<pre><code>${code.trim()}</code></pre>`;
    });

    // 2. 行内代码 `...`
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // 3. 粗体+斜体 ***...***
    html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');

    // 4. 粗体 **...** 和 __...__
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/__(.+?)__/g, '<strong>$1</strong>');

    // 5. 斜体 *...*
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');

    // 6. 删除线 ~~...~~
    html = html.replace(/~~(.+?)~~/g, '<del>$1</del>');

    // 7. 标题 # / ## / ###
    html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^# (.+)$/gm, '<h3>$1</h3>');

    // 9. 引用 > ...（连续行合并为一个 blockquote）
    html = html.replace(/((?:^&gt; .+\n?)+)/gm, (match) => {
        const content = match.replace(/^&gt; /gm, '').trim();
        return `<blockquote>${content}</blockquote>`;
    });

    // 10. 水平分割线 --- / *** / ___（单独一行）
    html = html.replace(/^(---|\*\*\*|___)$/gm, '<hr>');

    // 11. 有序列表（连续的数字. 开头行）
    html = html.replace(/((?:^\d+\.\s+.+\n?)+)/gm, (match) => {
        const items = match.trim().split('\n').map(line =>
            line.replace(/^\d+\.\s+/, '')
        ).join('</li><li>');
        return `<ol><li>${items}</li></ol>`;
    });

    // 12. 无序列表（连续的 - 开头行）
    html = html.replace(/((?:^-\s+.+\n?)+)/gm, (match) => {
        const items = match.trim().split('\n').map(line =>
            line.replace(/^-\s+/, '')
        ).join('</li><li>');
        return `<ul><li>${items}</li></ul>`;
    });

    // 13. 双换行 → 段落分隔
    html = html.replace(/\n\n/g, '<br><br>');
    // 14. 单换行
    html = html.replace(/\n/g, '<br>');

    // 15. 还原裸 URL 为可点击超链接
    html = html.replace(/\u0001URL(\d+)\u0001/g, (_, i) =>
        `<a href="${_urls[i]}" target="_blank" rel="noopener">${_urls[i]}</a>`);

    return html;
}

function renderPaperEmbed(pdfUrl) {
    const id = 'paper-' + Math.random().toString(36).substr(2, 8);
    const filename = pdfUrl.split('/').pop();
    const name = filename.replace(/\.(pdf|pptx)$/i, '');
    const isPptx = /\.pptx$/i.test(filename);
    const icon = isPptx ? '<i class="fas fa-file-powerpoint"></i>' : '<i class="fas fa-file-pdf"></i>';
    const label = isPptx ? 'PPT 演示文稿' : '论文文档';
    const downloadLabel = isPptx ? '<i class="fas fa-download"></i> 下载PPT' : '<i class="fas fa-download"></i> 下载PDF';
    const previewHint = isPptx ? '点击后将自动转换为PDF并加载预览' : '点击后将在下方加载PDF预览';
    return `
        <div class="paper-embed" style="margin:12px -8px;border:1px solid #e0e0e0;border-radius:8px;overflow:hidden;background:#fff;min-width:560px">
            <div class="paper-header" style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:#f5f5f5;border-bottom:1px solid #e0e0e0;flex-wrap:wrap;gap:4px">
                <span style="font-size:14px;font-weight:600">${icon} ${label}</span>
                <div style="display:flex;flex-wrap:wrap;gap:4px">
                    <button onclick="openPapersFolder()" style="font-size:13px;color:#4a90d9;background:none;border:none;cursor:pointer;text-decoration:none;white-space:nowrap"><i class="fas fa-folder-open"></i> 打开文件夹</button>
                    ${isPptx ? '' : `<button onclick="editPaperContent('${name}')" style="font-size:13px;color:#4a90d9;background:none;border:none;cursor:pointer;text-decoration:none;white-space:nowrap"><i class="fas fa-pen-to-square"></i> 修改文档</button>`}
                    <a href="${pdfUrl}" target="_blank" style="font-size:13px;color:#4a90d9;text-decoration:none;white-space:nowrap"><i class="fas fa-magnifying-glass"></i> 新窗口查看</a>
                    <a href="${pdfUrl}" download style="font-size:13px;color:#4a90d9;text-decoration:none;white-space:nowrap">${downloadLabel}</a>
                </div>
            </div>
            <div id="${id}" style="padding:40px;text-align:center;background:#fafafa;cursor:pointer" onclick="loadPaperPreview('${id}', '${pdfUrl}')">
                <div style="font-size:48px;margin-bottom:12px">${icon}</div>
                <div style="font-size:15px;color:#4a90d9;font-weight:500">点击预览${isPptx ? 'PPT' : '论文'}</div>
                <div style="font-size:12px;color:#999;margin-top:4px">${previewHint}</div>
            </div>
        </div>`;
}

function loadPaperPreview(containerId, pdfUrl) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.style.padding = '0';
    container.style.cursor = 'default';
    container.onclick = null;

    // PPTX 文件：先转 PDF 再预览
    const filename = pdfUrl.split('/').pop();
    let previewUrl = pdfUrl;
    if (/\.pptx$/i.test(filename)) {
        previewUrl = '/api/pptx-preview/' + encodeURIComponent(filename);
        container.innerHTML = `<div style="padding:40px;text-align:center;background:#fafafa;color:#999"><i class="fas fa-hourglass-half"></i> 正在转换 PPT 为 PDF，请稍候...</div>`;
        const iframe = document.createElement('iframe');
        iframe.src = previewUrl;
        iframe.style.cssText = 'width:100%;height:600px;border:none;display:none';
        iframe.onload = function() {
            container.innerHTML = '';
            iframe.style.display = 'block';
            container.appendChild(iframe);
        };
        container.appendChild(iframe);
        return;
    }

    container.innerHTML = `<iframe src="${previewUrl}" style="width:100%;height:600px;border:none;display:block" frameborder="0"></iframe>`;
}

function openPapersFolder() {
    fetch('/api/open-papers-folder', { method: 'POST' }).catch(() => {});
}

// ===== 论文编辑 =====
let paperEditInfo = { name: '', title: '', format: 'markdown' };

async function editPaperContent(name) {
    try {
        const resp = await fetch(`/api/paper-source?name=${encodeURIComponent(name)}`);
        const data = await resp.json();
        if (data.error) {
            alert('无法加载源文件：' + data.error);
            return;
        }
        paperEditInfo = { name: data.name, title: data.title, format: data.format };
        // 优先恢复本地草稿（未保存的编辑）
        var draftKey = 'paper_draft_' + data.name;
        var saved = localStorage.getItem(draftKey);
        if (saved) {
            try {
                var draft = JSON.parse(saved);
                document.getElementById('paperEditTitle').value = draft.title || data.title;
                document.getElementById('paperEditContent').value = draft.content || data.content;
            } catch(e) { fallback(); }
        } else {
            fallback();
        }
        function fallback() {
            document.getElementById('paperEditTitle').value = data.title;
            document.getElementById('paperEditContent').value = data.content;
        }
        var fmtLabel = document.getElementById('paperEditFormat');
        fmtLabel.textContent = data.format === 'latex' ? 'LaTeX' : 'Markdown';
        fmtLabel.style.background = data.format === 'latex' ? '#e8f5e9' : '#e3f2fd';
        fmtLabel.style.color = data.format === 'latex' ? '#2e7d32' : '#1565c0';
        document.getElementById('paperEditModal').style.display = 'flex';
        // 自动定时保存草稿
        startPaperAutoSave();
    } catch (e) {
        alert('加载失败：' + e.message);
    }
}

var _paperAutoSaveTimer = null;
function startPaperAutoSave() {
    clearInterval(_paperAutoSaveTimer);
    _paperAutoSaveTimer = setInterval(savePaperDraft, 5000);
}
function savePaperDraft() {
    if (!paperEditInfo.name) return;
    var title = document.getElementById('paperEditTitle').value.trim();
    var content = document.getElementById('paperEditContent').value.trim();
    if (!title && !content) return;
    localStorage.setItem('paper_draft_' + paperEditInfo.name, JSON.stringify({title: title, content: content}));
}

function closePaperEdit() {
    clearInterval(_paperAutoSaveTimer);
    savePaperDraft();
    document.getElementById('paperEditModal').style.display = 'none';
}

async function regeneratePaper() {
    const title = document.getElementById('paperEditTitle').value.trim();
    const content = document.getElementById('paperEditContent').value.trim();
    if (!title) { alert('请输入标题'); return; }

    const btn = document.getElementById('paperRegenerateBtn');
    btn.disabled = true;
    btn.textContent = '正在生成...';

    try {
        const resp = await fetch('/api/regenerate-paper', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: paperEditInfo.name,
                title: title,
                content: content,
                format: paperEditInfo.format
            })
        });
        const data = await resp.json();
        if (data.ok) {
            closePaperEdit();
            localStorage.removeItem('paper_draft_' + paperEditInfo.name);
            const embeds = document.querySelectorAll('.paper-embed');
            for (const embed of embeds) {
                const iframe = embed.querySelector('iframe');
                if (iframe && iframe.src.includes(paperEditInfo.name)) {
                    iframe.src = iframe.src;
                }
            }
            addMessage('system', '<i class="fas fa-circle-check"></i> 论文已重新生成，刷新预览即可查看最新版本。');
        } else {
            alert('生成失败：' + (data.error || '请重试'));
        }
    } catch (e) {
        alert('生成失败：' + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = '重新生成';
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function addImageMessage(imgUrl, caption) {
    const container = document.getElementById('chatMessages');
    const welcome = container.querySelector('.welcome-message');
    if (welcome) welcome.remove();

    const row = document.createElement('div');
    row.className = 'msg-row agent';
    const time = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });

    row.innerHTML = `
        <div class="msg-avatar"><i class="fas fa-robot"></i></div>
        <div class="msg-content">
            <div class="msg-label">Agent</div>
            <div class="msg-bubble">
                <img src="${imgUrl}" alt="AI生成的图片" style="max-width:100%;border-radius:8px;cursor:pointer" onclick="window.open(this.src)" loading="lazy" />
                ${caption ? `<div style="margin-top:6px;font-size:13px;color:#666">${escapeHtml(caption)}</div>` : ''}
            </div>
            <div class="msg-time">${time}</div>
        </div>`;
    container.appendChild(row);
    scrollToBottom();
}

function scrollToBottom() {
    const container = document.getElementById('chatMessages');
    requestAnimationFrame(() => { container.scrollTop = container.scrollHeight; });
}

// ===== 文件上传 =====
async function onFileSelected(input) {
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
                addMessage('system', `<i class="fas fa-paperclip"></i> 已上传：${data.filename}（${sizeStr}）\n绝对路径：I:/Agent/data/${data.path}`);
                // 同步通知 Agent
                wsSend({ type: 'chat', content: `<i class="fas fa-paperclip"></i> 文件已上传：${data.filename}\n绝对路径：I:/Agent/data/${data.path}` });
            } else {
                addMessage('system', `上传失败：${data.error}`);
            }
        } catch (e) {
            addMessage('system', `上传失败：${e.message}`);
        }
    }
    input.value = '';
}

// ===== 发送消息 =====
function sendMessage() {
    const input = document.getElementById('inputBox');
    const text = input.value.trim();
    if (!text || !isAgentOnline || isMigrating) return;
    if (!wsSend({ type: 'chat', content: text })) {
        addMessage('system', '<i class="fas fa-triangle-exclamation"></i> 连接已断开，正在重连，请稍后重试');
        return;
    }
    addMessage('user', text);
    input.value = '';
    input.style.height = 'auto';
    input.focus();
}

// ===== 新建会话 =====
function newSession() {
    fetch('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device: '电脑' })
    })
    .then(r => r.json())
    .then(data => {
        // 切换到新会话（WS 不可用时降级 HTTP 刷新）
        refreshAfterChange(data.session_id);
    })
    .catch(err => console.error('创建会话失败:', err));
}

// ===== 会话列表渲染 =====
let selectMode = false;
let selectedSessions = new Set();
let sessionDataMap = {};  // 缓存会话完整数据（用于详情弹窗）

function renderSessionList(sessions, current) {
    currentSessionId = current;
    document.getElementById('infoSession').textContent = current || '';
    const list = document.getElementById('sessionList');
    list.innerHTML = '';

    if (!sessions || sessions.length === 0) {
        list.innerHTML = '<div style="padding:12px;color:#999;font-size:12px;">暂无会话</div>';
        exitSelectMode();
        return;
    }

    // 更新选择模式状态
    if (selectMode) {
        list.classList.add('select-mode');
    } else {
        list.classList.remove('select-mode');
    }

    for (const s of sessions) {
        sessionDataMap[s.session_id] = s;  // 缓存完整数据
        const isActive = s.session_id === current;
        const isPinned = s.pinned === 1;
        const isChecked = selectedSessions.has(s.session_id);
        const displayTitle = s.title || s.session_id.substring(0, 8) + '...';

        const item = document.createElement('div');
        item.className = 'session-item' + (isActive ? ' active' : '') + (isPinned ? ' pinned' : '') + (isChecked ? ' checked' : '');
        item.style.position = 'relative';
        item.dataset.sessionId = s.session_id;
        item.innerHTML = `
            <span class="session-check" onclick="toggleSessionCheck(event, '${s.session_id}')"></span>
            <span class="pin-icon" title="已置顶"><i class="fas fa-thumbtack"></i></span>
            <div class="session-icon"><i class="fas fa-comment-dots"></i></div>
            <div class="session-info">
                <div class="session-title">${escapeHtml(displayTitle)}</div>
                <div class="session-meta">${s.message_count || 0} 条消息</div>
            </div>
            <button class="session-more" onclick="toggleSessionMenu(event, '${s.session_id}')" title="更多"><i class="fas fa-ellipsis-vertical"></i></button>
            <div class="session-menu" id="menu-${s.session_id}">
                <button class="session-menu-item" onclick="sessionDetail(event, '${s.session_id}')">
                    <span class="menu-icon"><i class="fas fa-circle-info"></i></span> 详情
                </button>
                <button class="session-menu-item" onclick="sessionRename(event, '${s.session_id}', '${escapeHtml(s.title || s.session_id).replace(/'/g, "\\'")}')">
                    <span class="menu-icon"><i class="fas fa-pen-to-square"></i></span> 改名
                </button>
                <button class="session-menu-item" onclick="sessionPin(event, '${s.session_id}', ${isPinned ? 'false' : 'true'})">
                    <span class="menu-icon"><i class="fas fa-thumbtack"></i></span> ${isPinned ? '取消置顶' : '置顶'}
                </button>
                <button class="session-menu-item" onclick="sessionDuplicate(event, '${s.session_id}')">
                    <span class="menu-icon"><i class="fas fa-clipboard"></i></span> 复制对话
                </button>
                <button class="session-menu-item danger" onclick="sessionDelete(event, '${s.session_id}')">
                    <span class="menu-icon"><i class="fas fa-trash-can"></i></span> 删除
                </button>
            </div>
        `;
        if (!isActive && !selectMode) {
            item.style.cursor = 'pointer';
        }
        item.addEventListener('click', (e) => {
            if (e.target.closest('.session-more') || e.target.closest('.session-menu')) return;
            if (selectMode) {
                toggleSessionCheck(e, s.session_id);
            } else if (!isActive) {
                switchSession(s.session_id);
            }
        });
        list.appendChild(item);
    }

    updateBatchBar();
}

function switchSession(sessionId) {
    closeAllMenus();
    wsSend({ type: 'switch_session', session_id: sessionId });
}

// ===== 会话菜单操作 =====
function toggleSessionMenu(e, sessionId) {
    e.stopPropagation();
    const menu = document.getElementById('menu-' + sessionId);
    if (!menu) return;
    const isOpen = menu.classList.contains('show');
    closeAllMenus();
    if (!isOpen) {
        menu.classList.add('show');
    }
}

function closeAllMenus() {
    document.querySelectorAll('.session-menu.show').forEach(m => m.classList.remove('show'));
}

function sessionDelete(e, sessionId) {
    e.stopPropagation();
    closeAllMenus();
    if (!confirm('确定要删除这个会话吗？所有聊天记录将被永久删除。')) return;
    console.log('[sessionDelete] 开始删除:', sessionId);
    fetch('/api/sessions/' + sessionId, { method: 'DELETE' })
    .then(r => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
    })
    .then(data => {
        console.log('[sessionDelete] 删除成功，返回数据:', data);
        // 后端已直接返回最新会话列表，直接渲染
        if (data.sessions) {
            renderSessionList(data.sessions, data.new_current || data.session_id);
        }
        // WS 通道也在后台刷新历史
        const targetId = data.new_current || data.session_id;
        wsSend({ type: 'switch_session', session_id: targetId });
    })
    .catch(err => {
        console.error('删除会话失败:', err);
        alert('删除会话失败，请稍后重试');
    });
}

function sessionPin(e, sessionId, pinned) {
    e.stopPropagation();
    closeAllMenus();
    fetch('/api/sessions/' + sessionId + '/pin', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pinned: pinned })
    })
    .then(() => {
        // 刷新会话列表（WS 不可用时降级 HTTP）
        refreshAfterChange(currentSessionId);
    })
    .catch(err => console.error('置顶操作失败:', err));
}

function sessionRename(e, sessionId, currentTitle) {
    e.stopPropagation();
    closeAllMenus();
    showRenameDialog(sessionId, currentTitle);
}

function sessionDetail(e, sessionId) {
    e.stopPropagation();
    closeAllMenus();
    const s = sessionDataMap[sessionId] || {};
    const title = s.title || s.session_id || '未知';
    const created = s.created_at ? new Date(s.created_at + 'Z').toLocaleString('zh-CN') : '未知';
    const updated = s.updated_at ? new Date(s.updated_at + 'Z').toLocaleString('zh-CN') : '未知';
    const count = s.message_count || 0;
    const device = s.device || '未知';
    const pinned = s.pinned ? '是' : '否';

    const overlay = document.createElement('div');
    overlay.className = 'rename-overlay';
    overlay.onclick = (ev) => { if (ev.target === overlay) overlay.remove(); };
    overlay.innerHTML = `
        <div class="rename-dialog" style="min-width:320px;">
            <h4>会话详情</h4>
            <div class="detail-grid">
                <div class="detail-row"><span class="detail-label">名称</span><span class="detail-value">${escapeHtml(title)}</span></div>
                <div class="detail-row"><span class="detail-label">ID</span><span class="detail-value mono">${escapeHtml(sessionId)}</span></div>
                <div class="detail-row"><span class="detail-label">消息数</span><span class="detail-value">${count} 条</span></div>
                <div class="detail-row"><span class="detail-label">设备</span><span class="detail-value">${escapeHtml(device)}</span></div>
                <div class="detail-row"><span class="detail-label">置顶</span><span class="detail-value">${pinned}</span></div>
                <div class="detail-row"><span class="detail-label">创建时间</span><span class="detail-value">${created}</span></div>
                <div class="detail-row"><span class="detail-label">最后活跃</span><span class="detail-value">${updated}</span></div>
            </div>
            <div style="margin-top:12px;text-align:right;">
                <button class="btn-cancel" onclick="this.closest('.rename-overlay').remove()">关闭</button>
            </div>
        </div>`;
    document.body.appendChild(overlay);
}

function sessionDuplicate(e, sessionId) {
    e.stopPropagation();
    closeAllMenus();
    fetch('/api/sessions/' + sessionId + '/duplicate', { method: 'POST' })
    .then(r => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
    })
    .then(() => {
        refreshAfterChange(currentSessionId);
    })
    .catch(err => console.error('复制会话失败:', err));
}

function showRenameDialog(sessionId, currentTitle) {
    // 移除已有弹窗
    const existing = document.querySelector('.rename-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.className = 'rename-overlay';
    overlay.innerHTML = `
        <div class="rename-dialog">
            <h4>重命名会话</h4>
            <input type="text" id="renameInput" value="${escapeHtml(currentTitle)}" placeholder="输入会话名称" maxlength="30">
            <div class="rename-actions">
                <button class="btn-cancel" onclick="this.closest('.rename-overlay').remove()">取消</button>
                <button class="btn-ok" onclick="doRename('${sessionId}')">确定</button>
            </div>
        </div>
    `;
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.remove();
    });
    document.body.appendChild(overlay);

    // 聚焦输入框
    setTimeout(() => {
        const input = document.getElementById('renameInput');
        if (input) { input.focus(); input.select(); }
    }, 50);
}

function doRename(sessionId) {
    const input = document.getElementById('renameInput');
    const title = input ? input.value.trim() : '';
    document.querySelector('.rename-overlay').remove();
    if (!title) return;
    fetch('/api/sessions/' + sessionId + '/rename', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title })
    })
    .then(() => {
        refreshAfterChange(currentSessionId);
    })
    .catch(err => console.error('重命名失败:', err));
}

// 点击页面其他地方关闭菜单
document.addEventListener('click', (e) => {
    if (!e.target.closest('.session-more') && !e.target.closest('.session-menu')
        && !e.target.closest('.msg-more') && !e.target.closest('.msg-menu')) {
        closeAllMenus();
        closeAllMsgMenus();
    }
});

// ===== 消息菜单操作 =====
function toggleMsgMenu(e, messageId) {
    e.stopPropagation();
    const menu = document.getElementById('msgMenu-' + messageId);
    if (!menu) return;
    const isOpen = menu.classList.contains('show');
    closeAllMsgMenus();
    if (!isOpen) {
        menu.classList.add('show');
    }
}

function closeAllMsgMenus() {
    document.querySelectorAll('.msg-menu.show').forEach(m => m.classList.remove('show'));
}

function msgCopy(e, messageId) {
    e.stopPropagation();
    closeAllMsgMenus();
    if (!messageId) return;
    const row = document.querySelector(`.msg-row[data-message-id="${messageId}"]`);
    if (!row) return;
    const bubble = row.querySelector('.msg-bubble');
    if (!bubble) return;
    navigator.clipboard.writeText(bubble.textContent).then(() => {
        // 短暂提示
        const orig = bubble.style.background;
        bubble.style.background = '#E6F7FF';
        setTimeout(() => { bubble.style.background = orig; }, 500);
    }).catch(() => {});
}

function msgEditUser(e, messageId) {
    e.stopPropagation();
    closeAllMsgMenus();
    if (!messageId) return;
    const row = document.querySelector(`.msg-row[data-message-id="${messageId}"]`);
    if (!row) return;
    const bubble = row.querySelector('.msg-bubble');
    if (!bubble) return;
    const currentText = bubble.textContent;

    const newText = prompt('编辑消息（AI 将重新回复）：', currentText);
    if (newText === null || newText === currentText) return;

    // 立即更新显示
    bubble.textContent = newText;
    bubble.style.opacity = '1';

    // 找到旧的 AI 回复，移除并标记位置
    var oldAiRow = null;
    var next = row.nextElementSibling;
    while (next) {
        if (next.classList.contains('msg-row') && next.classList.contains('agent')) {
            oldAiRow = next;
            break;
        }
        if (next.classList.contains('process-group')) {
            next = next.nextElementSibling;
            continue;
        }
        break;
    }
    if (oldAiRow) {
        oldAiRow.querySelector('.msg-bubble').textContent = '正在重新生成...';
        oldAiRow.style.opacity = '0.6';
    }

    // 触发后端重新生成
    fetch('/api/messages/' + messageId, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: newText, rerun: true })
    })
    .then(r => r.json())
    .then(data => {
        if (data.reply) {
            // 直接渲染新回复（不刷新整个页面）
            var oldRow = document.querySelector('.msg-row.agent[data-old-branch="' + messageId + '"]');
            if (oldRow) oldRow.remove();
            var userRow = document.querySelector(`.msg-row[data-message-id="${messageId}"]`);
            // 用新内容替换旧 AI 回复
            if (oldAiRow && oldAiRow.parentNode) {
                oldAiRow.querySelector('.msg-bubble').textContent = data.reply;
                oldAiRow.style.opacity = '1';
                oldAiRow.setAttribute('data-old-branch', messageId);
            }
            // 更新分支数据
            updateBranchNav(messageId);
        } else {
            // 流式生成完成但没有直接返回内容，刷新
            refreshAfterChange(currentSessionId);
        }
    })
    .catch(() => {
        bubble.textContent = currentText;
        if (oldAiRow) oldAiRow.style.opacity = '1';
    });
}

function updateBranchNav(userMessageId) {
    fetch('/api/messages/' + userMessageId + '/branches')
        .then(r => r.json())
        .then(branches => {
            var row = document.querySelector(`.msg-row[data-message-id="${userMessageId}"]`);
            if (!row) return;
            if (branches.length > 0) {
                row.dataset.branches = JSON.stringify(branches);
                row.dataset.branchIdx = '0';
                var nav = row.querySelector('.branch-nav');
                var label = row.querySelector('.branch-label');
                if (!nav) {
                    var html = `<div class="branch-nav">
                        <button class="branch-arrow" onclick="switchBranch(event, ${userMessageId}, -1)"><i class="fas fa-chevron-left"></i></button>
                        <span class="branch-label">分支 1/${branches.length + 1}</span>
                        <button class="branch-arrow" onclick="switchBranch(event, ${userMessageId}, 1)"><i class="fas fa-chevron-right"></i></button>
                    </div>`;
                    row.querySelector('.msg-footer')?.insertAdjacentHTML('afterbegin', html);
                } else if (label) {
                    label.textContent = `分支 1/${branches.length + 1}`;
                }
            }
        }).catch(function() {});
}

function msgDelete(e, messageId) {
    e.stopPropagation();
    closeAllMsgMenus();
    if (!messageId) return;
    if (!confirm('确定要删除这条消息吗？')) return;

    fetch('/api/messages/' + messageId, { method: 'DELETE' })
    .then(() => {
        const row = document.querySelector(`.msg-row[data-message-id="${messageId}"]`);
        if (row) {
            const prev = row.previousElementSibling;
            if (prev && prev.classList.contains('process-group')) {
                prev.remove();
            }
            row.remove();
        }
    });
}

// ===== 分支切换 =====
function switchBranch(e, userMessageId, direction) {
    e.stopPropagation();
    const userRow = document.querySelector(`.msg-row[data-message-id="${userMessageId}"]`);
    if (!userRow) return;

    // 跳过 process-group，找到 AI 回复行
    let aiRow = userRow.nextElementSibling;
    while (aiRow) {
        if (aiRow.classList.contains('process-group')) { aiRow = aiRow.nextElementSibling; continue; }
        if (aiRow.classList.contains('msg-row') && aiRow.classList.contains('agent')) break;
        aiRow = aiRow.nextElementSibling;
    }
    if (!aiRow) return;
    const aiBubble = aiRow.querySelector('.msg-bubble');
    if (!aiBubble) return;

    const branchLabel = userRow.querySelector('.branch-label');

    // 优先从 API 获取最新分支数据
    function doSwitch(branches) {
        if (!branches || branches.length === 0) return;
        var currentIdx = parseInt(userRow.dataset.branchIdx) || 0;
        var newIdx = currentIdx + direction;
        if (newIdx < 0) newIdx = branches.length;
        if (newIdx > branches.length) newIdx = 0;

        // 分支列表: [旧回复1, 旧回复2, ...] / 活跃 = index 0
        if (currentIdx === 0 && newIdx > 0) {
            // 离开活跃分支 → 记录当前内容
            userRow.dataset.latestReply = aiBubble.innerHTML;
        }
        if (newIdx === 0) {
            // 切回活跃分支
            aiBubble.innerHTML = userRow.dataset.latestReply || aiBubble.innerHTML;
        } else {
            var branch = branches[newIdx - 1];
            // 分支里同时可能存了用户编辑后的消息
            if (branch.user_content) userRow.querySelector('.msg-bubble').textContent = branch.user_content;
            aiBubble.innerHTML = branch.content || '';
        }
        userRow.dataset.branchIdx = newIdx;
        if (branchLabel) {
            branchLabel.textContent = '分支 ' + (newIdx + 1) + '/' + (branches.length + 1);
        }
    }

    // 尝试从 DOM 获取
    try {
        var raw = userRow.dataset.branches;
        var branches = raw ? JSON.parse(raw) : [];
        if (branches.length > 0) { doSwitch(branches); return; }
    } catch (_) {}

    // DOM 里没有就从 API 拉
    fetch('/api/messages/' + userMessageId + '/branches')
        .then(r => r.json()).then(function(branches) {
            userRow.dataset.branches = JSON.stringify(branches);
            doSwitch(branches);
        }).catch(function() {});
}

// ===== 批量选择 =====
function toggleSelectMode() {
    selectMode = !selectMode;
    if (!selectMode) {
        selectedSessions.clear();
    }
    // 刷新列表以显示/隐藏复选框
    refreshAfterChange(currentSessionId);
}

function exitSelectMode() {
    selectMode = false;
    selectedSessions.clear();
    updateBatchBar();
}

function toggleSessionCheck(e, sessionId) {
    e.stopPropagation();
    if (selectedSessions.has(sessionId)) {
        selectedSessions.delete(sessionId);
    } else {
        selectedSessions.add(sessionId);
    }
    // 更新 UI
    const item = document.querySelector(`.session-item[data-session-id="${sessionId}"]`);
    if (item) {
        item.classList.toggle('checked', selectedSessions.has(sessionId));
    }
    updateBatchBar();
}

function toggleSelectAll() {
    const items = document.querySelectorAll('#sessionList .session-item');
    if (selectedSessions.size === items.length) {
        // 取消全选
        selectedSessions.clear();
        items.forEach(el => el.classList.remove('checked'));
    } else {
        // 全选
        items.forEach(el => {
            const sid = el.dataset.sessionId;
            if (sid) selectedSessions.add(sid);
            el.classList.add('checked');
        });
    }
    updateBatchBar();
}

function updateBatchBar() {
    const bar = document.getElementById('batchBar');
    const count = selectedSessions.size;
    const btn = document.getElementById('batchDeleteBtn');
    const countEl = document.getElementById('batchCount');

    if (selectMode) {
        bar.classList.add('show');
        countEl.textContent = `已选 ${count} 项`;
        btn.disabled = count === 0;
    } else {
        bar.classList.remove('show');
    }
}

function batchDelete() {
    if (selectedSessions.size === 0) return;
    if (!confirm(`确定要删除选中的 ${selectedSessions.size} 个会话吗？所有聊天记录将被永久删除。`)) return;

    const ids = Array.from(selectedSessions);
    console.log('[batchDelete] 开始批量删除:', ids);
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
        console.log('[batchDelete] 删除成功，返回数据:', data);
        selectedSessions.clear();
        exitSelectMode();
        // 后端直接返回最新会话列表，直接渲染
        if (data.sessions) {
            renderSessionList(data.sessions, data.new_current || currentSessionId);
        }
        // WS 后台刷新历史
        const targetId = data.new_current || currentSessionId;
        wsSend({ type: 'switch_session', session_id: targetId });
    })
    .catch(err => {
        console.error('批量删除失败:', err);
        alert('批量删除失败，请稍后重试');
    });
}

// ===== 清空聊天记录 =====
function clearChat() {
    if (!confirm('确定要清空当前会话的所有聊天记录吗？')) return;
    fetch('/api/sessions/current/messages', { method: 'DELETE' })
    .then(r => r.json())
    .then(data => {
        const container = document.getElementById('chatMessages');
        container.innerHTML = `
            <div class="welcome-message">
                <div class="welcome-icon"><i class="fas fa-robot"></i></div>
                <h3>聊天记录已清空</h3>
                <p>输入消息开始新对话</p>
            </div>`;
        currentProcessGroup = null;
    })
    .catch(err => console.error('清空失败:', err));
}

// ===== 输入框事件 =====
const inputBox = document.getElementById('inputBox');
inputBox.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});
inputBox.addEventListener('input', () => {
    inputBox.style.height = 'auto';
    inputBox.style.height = Math.min(inputBox.scrollHeight, 120) + 'px';
});

// ===== Spine 2D 动画初始化 =====
let spinePlayer = null;
let spineReady = false;
let pendingSkin = null;

function initSpineAnimation() {
    const container = document.getElementById('spinePlayer');
    if (!container) return;
    
    function doInit() {
        try {
            spinePlayer = new spine.SpinePlayer(container, {
                jsonUrl: '/static/spine/character.json',
                atlasUrl: '/static/spine/character.atlas',
                skin: 'default',
                animation: 'blink',
                premultipliedAlpha: false,
                alpha: true,
                backgroundColor: '#00000000',
                showControls: false,
                success: (player) => {
                    console.log('Spine 动画加载成功');
                    spinePlayer = player;
                    spineReady = true;
                    // 应用待切换的表情
                    if (pendingSkin) {
                        console.log('Spine skin: 应用待切换表情 ->', pendingSkin);
                        switchSpineSkinDirect(pendingSkin);
                        pendingSkin = null;
                    }
                },
                error: (_player, error) => {
                    console.error('Spine 动画加载失败:', error);
                    fallbackAvatar();
                }
            });
        } catch (e) {
            console.error('Spine 初始化失败:', e);
            fallbackAvatar();
        }
    }

    function fallbackAvatar() {
        const spineContainer = document.getElementById('spineContainer');
        if (spineContainer) {
            spineContainer.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:48px;"><i class="fas fa-robot"></i></div>';
        }
    }

    // 如果 spine 已加载，直接初始化；否则动态加载本地脚本
    if (typeof spine !== 'undefined' && spine.SpinePlayer) {
        doInit();
    } else {
        const script = document.createElement('script');
        script.src = '/static/spine-player.js';
        script.onload = doInit;
        script.onerror = () => {
            console.warn('Spine 运行时加载失败');
            fallbackAvatar();
        };
        document.head.appendChild(script);
    }
}

// 直接切换表情（通过附件切换 mouth 实现，由 AI 工具 set_expression 调用）
function switchSpineSkinDirect(skin) {
    if (!['default', 'happy', 'unhappy'].includes(skin)) {
        console.warn('Spine skin: 未知表情 ->', skin);
        return;
    }
    if (!spineReady || !spinePlayer || !spinePlayer.skeleton) {
        console.warn('Spine skin: 动画未就绪，暂存表情 ->', skin);
        pendingSkin = skin;
        return;
    }
    console.log('Spine skin: 切换表情 ->', skin);
    try {
        const skel = spinePlayer.skeleton;
        // 角色没有 happy/unhappy 皮肤，改用 mouth 附件切换表情
        const mouthMap = {
            'default': 'mouth_smile',
            'happy': 'mouth_open',
            'unhappy': 'mouth_unhappy'
        };
        skel.setAttachment('mouth', mouthMap[skin]);
        // 同时切换眼睛附件（如果有的话）
        const eyeMap = {
            'default': 'eye_socket_left',
            'happy': 'eye_socket_left',
            'unhappy': 'eye_socket_left'
        };
        // 只更新 mouth，eye 保持默认
        skel.setSlotsToSetupPose();
    } catch (e) {
        console.warn('切换表情失败:', e);
    }
}

// ===== 启动 =====
connect();
// 等待 DOM 加载完成后初始化 Spine 动画
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSpineAnimation);
} else {
    initSpineAnimation();
}

// 安全兜底：如果 3 秒后输入框仍被禁用，强制启用
setTimeout(() => {
    const inputBox = document.getElementById('inputBox');
    const sendBtn = document.getElementById('sendBtn');
    const uploadBtn = document.getElementById('uploadBtn');
    if (inputBox && inputBox.disabled) {
        console.warn('输入框被强制启用（状态消息未收到）');
        inputBox.disabled = false;
        if (sendBtn) sendBtn.disabled = false;
        if (uploadBtn) uploadBtn.disabled = false;
    }
}, 3000);

// ===== 音乐播放条 =====
let musicBarVisible = false;
let musicBarPlaying = false;
let musicBarPosition = 0;
let musicBarDuration = 0;
let musicBarPollTimer = null;
let musicBarSeeking = false; // 正在拖动时不轮询，避免冲突

function updateMusicBar(content) {
    const bar = document.getElementById('musicBar');
    if (!bar) return;
    
    // 解析 [MUSIC:status|title|progress|position|duration]
    const match = content.match(/\[MUSIC:(\w+)(?:\|([^|]*))?(?:\|([^|]*))?(?:\|([^|]*))?(?:\|([^|\]]*))?\]/);
    if (!match) return;
    
    const status = match[1];
    const title = match[2] || '';
    const pos = parseFloat(match[4]) || 0;
    const dur = parseFloat(match[5]) || 0;
    
    if (status === 'playing') {
        musicBarVisible = true;
        musicBarPlaying = true;
        musicBarPosition = pos;
        musicBarDuration = dur;
        bar.style.display = 'flex';
        bar.classList.remove('paused');
        bar.classList.remove('stopped');
        document.getElementById('musicBarTitle').textContent = title || '正在播放...';
        document.getElementById('musicBtnPlay').innerHTML = '&#10074;&#10074;';
        document.getElementById('musicBtnPlay').title = '暂停';
        updateProgressBar(pos, dur);
        startMusicPolling();
    } else if (status === 'paused') {
        musicBarVisible = true;
        musicBarPlaying = false;
        musicBarPosition = pos || musicBarPosition;
        musicBarDuration = dur || musicBarDuration;
        bar.style.display = 'flex';
        bar.classList.add('paused');
        bar.classList.remove('stopped');
        document.getElementById('musicBarTitle').textContent = title || '已暂停';
        document.getElementById('musicBtnPlay').innerHTML = '&#9654;';
        document.getElementById('musicBtnPlay').title = '播放';
        updateProgressBar(musicBarPosition, musicBarDuration);
        stopMusicPolling();
    } else if (status === 'stopped') {
        // 不再直接隐藏，显示"播放结束"状态，让用户手动关闭
        musicBarVisible = true;
        musicBarPlaying = false;
        bar.style.display = 'flex';
        bar.classList.add('paused');
        bar.classList.add('stopped');
        document.getElementById('musicBarTitle').textContent = '播放结束';
        document.getElementById('musicBtnPlay').innerHTML = '&#9654;';
        document.getElementById('musicBtnPlay').title = '重新播放';
        document.getElementById('musicBarTime').textContent = '0:00';
        document.getElementById('musicBarDuration').textContent = '0:00';
        document.getElementById('musicBarSlider').value = 0;
        stopMusicPolling();
    }
}

function updateProgressBar(pos, dur) {
    const slider = document.getElementById('musicBarSlider');
    const timeEl = document.getElementById('musicBarTime');
    const durEl = document.getElementById('musicBarDuration');
    if (!slider) return;
    
    const pct = dur > 0 ? (pos / dur) * 100 : 0;
    if (!musicBarSeeking) {
        slider.value = pct;
    }
    timeEl.textContent = formatTime(pos);
    durEl.textContent = formatTime(dur);
}

function formatTime(seconds) {
    const s = Math.max(0, Math.floor(seconds || 0));
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec.toString().padStart(2, '0')}`;
}

function startMusicPolling() {
    stopMusicPolling();
    musicBarPollTimer = setInterval(() => {
        if (!musicBarPlaying || musicBarSeeking) return;
        musicBarAction('status');
    }, 2000);
}

function stopMusicPolling() {
    if (musicBarPollTimer) {
        clearInterval(musicBarPollTimer);
        musicBarPollTimer = null;
    }
}

function onMusicSeek(pct) {
    musicBarSeeking = true;
    const dur = musicBarDuration || 0;
    const pos = (pct / 100) * dur;
    document.getElementById('musicBarTime').textContent = formatTime(pos);
}

function onMusicSeekEnd() {
    const slider = document.getElementById('musicBarSlider');
    if (!slider || !musicBarDuration) {
        musicBarSeeking = false;
        return;
    }
    const pct = parseFloat(slider.value);
    const seekSeconds = Math.round((pct / 100) * musicBarDuration);
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'music_control', action: 'seek', seek_seconds: seekSeconds }));
    }
    musicBarSeeking = false;
}

function toggleMusicPlay() {
    if (musicBarPlaying) {
        musicBarAction('pause');
    } else {
        musicBarAction('resume');
    }
}

function musicBarAction(action) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'music_control', action: action }));
    }
}

function closeMusicBar() {
    const bar = document.getElementById('musicBar');
    if (bar) {
        bar.style.display = 'none';
        musicBarVisible = false;
        musicBarPlaying = false;
        stopMusicPolling();
    }
}

// ===== 自启动管理 =====
function toggleAutostart(service) {
    fetch('/api/autostart/' + service, { method: 'POST' })
        .then(r => r.json())
        .then(data => updateAutostartBtn(service, data.enabled))
        .catch(() => {});
}
function updateAutostartBtn(service, enabled) {
    var btn = document.getElementById('as-' + service);
    if (!btn) return;
    btn.className = 'svc-btn svc-btn--auto' + (enabled ? ' is-on' : '');
    btn.textContent = enabled ? '已自启' : '自启动';
}
function loadAutostartConfig() {
    fetch('/api/autostart').then(r => r.json()).then(cfg => {
        for (var k in cfg) updateAutostartBtn(k, cfg[k]);
    }).catch(() => {});
}
setTimeout(loadAutostartConfig, 1500);

// ===== 释放 GPU 显存 =====
function releaseGPU() {
    var btn = document.getElementById('gpu-release-btn');
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = '释放中...';
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'gpu_release' }));
        updateComfyUIButton(false);
        setTimeout(function() {
            btn.disabled = false;
            btn.textContent = '释放 GPU 显存';
        }, 3000);
    }
}

// ===== 退出程序 =====
function quitApp() {
    if (!confirm('确定退出程序？\n\n点击"确定"后会询问是否保留后台服务。')) return;
    var keep = [];
    if (confirm('保留 ComfyUI（AI绘画/视频）后台运行？\n点"确定"保留，点"取消"关闭')) keep.push('comfyui');

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'shutdown', keep_services: keep }));
    }
    setTimeout(function() { window.close(); }, 500);
}

// ===== ComfyUI 绘画按钮 =====
let comfyuiPollTimer = null;
let comfyuiStarting = false;  // 启动中标志，防止 polling 把状态改回"已关闭"

function updateComfyUIButton(running) {
    const btn = document.getElementById('comfyui-btn');
    const status = document.getElementById('comfyui-status');
    if (!btn || !status) return;

    if (running) {
        btn.className = 'svc-btn svc-btn--toggle is-on';
        btn.textContent = '已就绪';
        btn.title = '点击关闭 ComfyUI';
        btn.onclick = stopComfyUI;
        btn.onmouseenter = function() { this.textContent = '关闭'; };
        btn.onmouseleave = function() { this.textContent = '已就绪'; };
        status.textContent = '绘画功能可用';
        clearInterval(comfyuiPollTimer);
        comfyuiPollTimer = null;
        comfyuiStarting = false;
    } else {
        // 启动中不切换到"已关闭"
        if (comfyuiStarting) return;
        btn.className = 'svc-btn svc-btn--toggle is-off';
        btn.textContent = '已关闭';
        btn.title = '点击开启 ComfyUI';
        btn.onclick = toggleComfyUI;
        btn.onmouseenter = function() { this.textContent = '开启'; };
        btn.onmouseleave = function() { this.textContent = '已关闭'; };
        status.textContent = '点击按钮开启';
    }
}

function stopComfyUI() {
    var btn = document.getElementById('comfyui-btn'), st = document.getElementById('comfyui-status');
    if (!btn) return;
    // 关闭中过渡态
    btn.className = 'svc-btn svc-btn--toggle is-loading'; btn.textContent = '关闭中...';
    btn.onclick = null; btn.onmouseenter = null; btn.onmouseleave = null;
    if(st) st.textContent = '正在关闭...';
    if(ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({type:'comfyui_stop'}));
    // 2秒后确认已关闭（给进程 kill 时间）
    setTimeout(function(){
        btn.className = 'svc-btn svc-btn--toggle is-off'; btn.textContent = '已关闭';
        btn.onclick = toggleComfyUI;
        btn.onmouseenter = function() { this.textContent = '开启'; };
        btn.onmouseleave = function() { this.textContent = '已关闭'; };
        if(st) st.textContent = '已关闭';
    }, 2000);
}

function toggleComfyUI() {
    const btn = document.getElementById('comfyui-btn');
    const status = document.getElementById('comfyui-status');
    if (!btn || !status) return;

    comfyuiStarting = true;
    btn.className = 'svc-btn svc-btn--toggle is-loading';
    btn.textContent = '启动中...';
    btn.title = '';
    btn.onclick = null;
    btn.onmouseenter = null;
    btn.onmouseleave = null;
    status.textContent = '正在启动 ComfyUI...';

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'comfyui_start' }));
    }
}

function restartComfyUI() {
    console.log('[restartComfyUI] 被调用');
    const btn = document.getElementById('comfyui-btn');
    const status = document.getElementById('comfyui-status');
    if (!btn || !status) {
        console.error('[restartComfyUI] 找不到按钮或状态元素');
        return;
    }

    console.log('[restartComfyUI] 设置加载状态，发送 comfyui_restart');
    btn.className = 'svc-btn svc-btn--toggle is-loading';
    btn.textContent = '重启中...';
    btn.title = '';
    btn.onclick = null;
    btn.onmouseenter = null;
    btn.onmouseleave = null;
    status.textContent = '正在重启 ComfyUI...';

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'comfyui_restart' }));
    } else {
        console.warn('[restartComfyUI] WebSocket 未连接，readyState=' + (ws ? ws.readyState : 'null'));
    }
}

function pollComfyUIStatus() {
    clearInterval(comfyuiPollTimer);
    let attempts = 0;
    comfyuiPollTimer = setInterval(() => {
        attempts++;
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'comfyui_status' }));
        }
        if (attempts >= 60) {
            clearInterval(comfyuiPollTimer);
            comfyuiPollTimer = null;
            comfyuiStarting = false;
            updateComfyUIButton(false);
            const status = document.getElementById('comfyui-status');
            if (status) status.textContent = '启动超时，请检查 ComfyUI';
        }
    }, 2000);
}


// ===== 服务管理面板 =====
function openServicesPanel() {
    var modal = document.getElementById('servicesModal');
    if (modal) modal.style.display = 'flex';
}

function closeServicesPanel() {
    var modal = document.getElementById('servicesModal');
    if (modal) modal.style.display = 'none';
}

// 点击模态背景关闭
(function() {
    var modal = document.getElementById('servicesModal');
    if (modal) {
        modal.addEventListener('click', function(e) {
            if (e.target === modal) closeServicesPanel();
        });
    }
})();

// ===== 工具库 =====
let allTools = [];
let allTags = [];

async function openToolsLibrary() {
    document.getElementById('toolsModal').style.display = 'flex';
    if (allTools.length === 0) {
        try {
            const resp = await fetch('/api/tools');
            const data = await resp.json();
            allTools = data.tools || [];
            allTags = data.tags || [];
            document.getElementById('toolsCount').textContent = `共 ${allTools.length} 个工具`;
            buildTagButtons();
        } catch (e) {
            document.getElementById('toolsList').innerHTML = '<div style="text-align:center;color:#e74c3c;padding:40px">加载失败</div>';
            return;
        }
    }
    renderToolsList('all');
}

function buildTagButtons() {
    const container = document.getElementById('toolFilterBtns');
    // 保留"全部"按钮，追加标签按钮
    container.innerHTML = '<button class="tool-filter-btn active" data-tag="all" onclick="filterTools(\'all\')">全部</button>';
    for (const tag of allTags) {
        const btn = document.createElement('button');
        btn.className = 'tool-filter-btn';
        btn.dataset.tag = tag;
        btn.setAttribute('onclick', `filterTools('${tag}')`);
        btn.textContent = tag;
        container.appendChild(btn);
    }
}

function closeToolsLibrary() {
    document.getElementById('toolsModal').style.display = 'none';
}

function filterTools(tag) {
    document.querySelectorAll('.tool-filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tag === tag);
    });
    renderToolsList(tag);
}

async function toggleTool(toolName) {
    try {
        const resp = await fetch('/api/tools/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: toolName })
        });
        const result = await resp.json();
        // 更新本地状态
        const tool = allTools.find(t => t.name === toolName);
        if (tool) tool.enabled = result.enabled;
        // 重新渲染
        const activeTag = document.querySelector('.tool-filter-btn.active')?.dataset?.tag || 'all';
        renderToolsList(activeTag);
    } catch (e) {
        console.error('Toggle tool failed:', e);
    }
}

function renderToolsList(tag) {
    const container = document.getElementById('toolsList');
    const filtered = tag === 'all' ? allTools : allTools.filter(t => t.tag === tag);

    if (filtered.length === 0) {
        container.innerHTML = '<div class="modal-empty">该分类下暂无工具</div>';
        return;
    }

    let html = '';
    for (const tool of filtered) {
        const paramsHtml = tool.parameters.length > 0
            ? tool.parameters.map(p => {
                const badge = p.required
                    ? '<span class="req">必填</span>'
                    : '<span class="opt">可选</span>';
                const enumInfo = p.enum && p.enum.length
                    ? '<br><span style="opacity:.75">可选值: ' + p.enum.join(', ') + '</span>'
                    : '';
                return '<div class="tool-param">' +
                    '<code>' + p.name + '</code> ' +
                    '<span>' + p.type + '</span>' + badge +
                    (p.description ? '<br><span style="opacity:.8">' + p.description + '</span>' : '') + enumInfo +
                    '</div>';
            }).join('')
            : '<div class="tool-param" style="opacity:.7">无参数</div>';

        const enabledText = tool.enabled ? '已启用' : '已禁用';
        const toggleLabel = tool.enabled ? '禁用' : '启用';
        const toggleCls = tool.enabled ? 'disable' : 'enable';

        html += '<div class="tool-card' + (tool.enabled ? '' : ' disabled') + '" data-tag="' + tool.tag + '">' +
            '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;gap:8px">' +
            '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">' +
            '<code class="tool-name">' + tool.name + '</code>' +
            '<span class="tool-tag">' + tool.tag + '</span>' +
            '<span class="tool-state ' + (tool.enabled ? 'on' : 'off') + '">' + enabledText + '</span>' +
            '</div>' +
            '<div style="display:flex;align-items:center;gap:8px">' +
            (tool.source ? '<span class="tool-source" title="' + tool.source + '">' + tool.source.split('/').pop() + '</span>' : '') +
            '<button class="tool-toggle ' + toggleCls + '" onclick="toggleTool(\'' + tool.name + '\')">' + toggleLabel + '</button>' +
            '</div>' +
            '</div>' +
            '<div class="tool-desc">' + tool.description + '</div>' +
            paramsHtml +
            '</div>';
    }
    container.innerHTML = html;
}