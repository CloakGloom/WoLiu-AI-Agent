/**
 * AI Agent 会话管理模块 —— 会话列表渲染、CRUD、批量选择、消息菜单
 * 依赖：core.js（全局变量 ws, currentSessionId, escapeHtml, refreshAfterChange 等）
 */

// ===== 会话列表渲染 =====
let selectMode = false;
let selectedSessions = new Set();
let sessionDataMap = {};

function renderSessionList(sessions, current) {
    currentSessionId = current;
    setElText('infoSession', current || '');
    const list = document.getElementById('sessionList');
    list.innerHTML = '';
    if (!sessions || sessions.length === 0) { list.innerHTML = '<div style="padding:12px;color:#999;font-size:12px;">暂无会话</div>'; exitSelectMode(); return; }
    if (selectMode) list.classList.add('select-mode'); else list.classList.remove('select-mode');

    for (const s of sessions) {
        sessionDataMap[s.session_id] = s;
        const isActive = s.session_id === current, isPinned = s.pinned === 1, isChecked = selectedSessions.has(s.session_id);
        const displayTitle = s.title || s.session_id.substring(0, 8) + '...';
        const item = document.createElement('div');
        item.className = 'session-item' + (isActive?' active':'') + (isPinned?' pinned':'') + (isChecked?' checked':'');
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
                <button class="session-menu-item" onclick="sessionDetail(event, '${s.session_id}')"><span class="menu-icon"><i class="fas fa-circle-info"></i></span> 详情</button>
                <button class="session-menu-item" onclick="sessionRename(event, '${s.session_id}', '${escapeHtml(s.title || s.session_id).replace(/'/g, "\\'")}')"><span class="menu-icon"><i class="fas fa-pen-to-square"></i></span> 改名</button>
                <button class="session-menu-item" onclick="sessionPin(event, '${s.session_id}', ${isPinned?'false':'true'})"><span class="menu-icon"><i class="fas fa-thumbtack"></i></span> ${isPinned?'取消置顶':'置顶'}</button>
                <button class="session-menu-item" onclick="sessionDuplicate(event, '${s.session_id}')"><span class="menu-icon"><i class="fas fa-clipboard"></i></span> 复制对话</button>
                <button class="session-menu-item danger" onclick="sessionDelete(event, '${s.session_id}')"><span class="menu-icon"><i class="fas fa-trash-can"></i></span> 删除</button>
            </div>`;
        if (!isActive && !selectMode) item.style.cursor = 'pointer';
        item.addEventListener('click', (e) => {
            if (e.target.closest('.session-more') || e.target.closest('.session-menu')) return;
            if (selectMode) toggleSessionCheck(e, s.session_id);
            else if (!isActive) switchSession(s.session_id);
        });
        list.appendChild(item);
    }
    updateBatchBar();
}

function switchSession(sessionId) { closeAllMenus(); wsSend({ type: 'switch_session', session_id: sessionId }); }

// ===== 会话菜单 =====
function toggleSessionMenu(e, sessionId) { e.stopPropagation(); const menu=document.getElementById('menu-'+sessionId); if(!menu)return; const isOpen=menu.classList.contains('show'); closeAllMenus(); if(!isOpen)menu.classList.add('show'); }
function closeAllMenus() { document.querySelectorAll('.session-menu.show').forEach(m=>m.classList.remove('show')); }

function sessionDelete(e, sessionId) {
    e.stopPropagation(); closeAllMenus();
    if (!confirm('确定要删除这个会话吗？所有聊天记录将被永久删除。')) return;
    console.log('[sessionDelete] 开始删除:', sessionId);
    fetch('/api/sessions/' + sessionId, { method: 'DELETE' })
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(data => {
        if (data.sessions) renderSessionList(data.sessions, data.new_current || data.session_id);
        wsSend({ type: 'switch_session', session_id: data.new_current || data.session_id });
    })
    .catch(err => { console.error('删除会话失败:', err); alert('删除会话失败，请稍后重试'); });
}

function sessionPin(e, sessionId, pinned) { e.stopPropagation(); closeAllMenus(); fetch('/api/sessions/'+sessionId+'/pin',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({pinned})}).then(()=>refreshAfterChange(currentSessionId)).catch(err=>console.error('置顶操作失败:',err)); }
function sessionRename(e, sessionId, currentTitle) { e.stopPropagation(); closeAllMenus(); showRenameDialog(sessionId, currentTitle); }

function sessionDetail(e, sessionId) {
    e.stopPropagation(); closeAllMenus();
    const s = sessionDataMap[sessionId] || {};
    const title = s.title || s.session_id || '未知', created = s.created_at?new Date(s.created_at+'Z').toLocaleString('zh-CN'):'未知', updated = s.updated_at?new Date(s.updated_at+'Z').toLocaleString('zh-CN'):'未知', count = s.message_count||0, device = s.device||'未知', pinned = s.pinned?'是':'否';
    const overlay = document.createElement('div');
    overlay.className = 'rename-overlay';
    overlay.onclick = (ev) => { if (ev.target === overlay) overlay.remove(); };
    overlay.innerHTML = `<div class="rename-dialog" style="min-width:320px;"><h4>会话详情</h4><div class="detail-grid"><div class="detail-row"><span class="detail-label">名称</span><span class="detail-value">${escapeHtml(title)}</span></div><div class="detail-row"><span class="detail-label">ID</span><span class="detail-value mono">${escapeHtml(sessionId)}</span></div><div class="detail-row"><span class="detail-label">消息数</span><span class="detail-value">${count} 条</span></div><div class="detail-row"><span class="detail-label">设备</span><span class="detail-value">${escapeHtml(device)}</span></div><div class="detail-row"><span class="detail-label">置顶</span><span class="detail-value">${pinned}</span></div><div class="detail-row"><span class="detail-label">创建时间</span><span class="detail-value">${created}</span></div><div class="detail-row"><span class="detail-label">最后活跃</span><span class="detail-value">${updated}</span></div></div><div style="margin-top:12px;text-align:right;"><button class="btn-cancel" onclick="this.closest('.rename-overlay').remove()">关闭</button></div></div>`;
    document.body.appendChild(overlay);
}

function sessionDuplicate(e, sessionId) { e.stopPropagation(); closeAllMenus(); fetch('/api/sessions/'+sessionId+'/duplicate',{method:'POST'}).then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json();}).then(()=>refreshAfterChange(currentSessionId)).catch(err=>console.error('复制会话失败:',err)); }

function showRenameDialog(sessionId, currentTitle) {
    const existing = document.querySelector('.rename-overlay'); if (existing) existing.remove();
    const overlay = document.createElement('div');
    overlay.className = 'rename-overlay';
    overlay.innerHTML = `<div class="rename-dialog"><h4>重命名会话</h4><input type="text" id="renameInput" value="${escapeHtml(currentTitle)}" placeholder="输入会话名称" maxlength="30"><div class="rename-actions"><button class="btn-cancel" onclick="this.closest('.rename-overlay').remove()">取消</button><button class="btn-ok" onclick="doRename('${sessionId}')">确定</button></div></div>`;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);
    setTimeout(() => { const input = document.getElementById('renameInput'); if (input) { input.focus(); input.select(); } }, 50);
}

function doRename(sessionId) {
    const input = document.getElementById('renameInput'), title = input?input.value.trim():'';
    document.querySelector('.rename-overlay').remove();
    if (!title) return;
    fetch('/api/sessions/'+sessionId+'/rename',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({title})}).then(()=>refreshAfterChange(currentSessionId)).catch(err=>console.error('重命名失败:',err));
}

// 点击空白关闭菜单
document.addEventListener('click', (e) => {
    if (!e.target.closest('.session-more') && !e.target.closest('.session-menu') && !e.target.closest('.msg-more') && !e.target.closest('.msg-menu'))
        { closeAllMenus(); closeAllMsgMenus(); }
});

// ===== 消息菜单 =====
function toggleMsgMenu(e, messageId) { e.stopPropagation(); const menu=document.getElementById('msgMenu-'+messageId); if(!menu)return; const isOpen=menu.classList.contains('show'); closeAllMsgMenus(); if(!isOpen)menu.classList.add('show'); }
function closeAllMsgMenus() { document.querySelectorAll('.msg-menu.show').forEach(m=>m.classList.remove('show')); }

function msgCopy(e, messageId) {
    e.stopPropagation(); closeAllMsgMenus(); if (!messageId) return;
    const row = document.querySelector(`.msg-row[data-message-id="${messageId}"]`); if (!row) return;
    const bubble = row.querySelector('.msg-bubble'); if (!bubble) return;
    navigator.clipboard.writeText(bubble.textContent).then(() => { const orig=bubble.style.background; bubble.style.background='#E6F7FF'; setTimeout(()=>{bubble.style.background=orig;},500); }).catch(()=>{});
}

function msgEditUser(e, messageId) {
    e.stopPropagation(); closeAllMsgMenus(); if (!messageId) return;
    const row = document.querySelector(`.msg-row[data-message-id="${messageId}"]`); if (!row) return;
    const bubble = row.querySelector('.msg-bubble'); if (!bubble) return;
    const currentText = bubble.textContent, newText = prompt('编辑消息（AI 将重新回复）：', currentText);
    if (newText === null || newText === currentText) return;
    bubble.textContent = newText; bubble.style.opacity = '1';
    var oldAiRow = null, next = row.nextElementSibling;
    while (next) { if(next.classList.contains('msg-row')&&next.classList.contains('agent')){oldAiRow=next;break;} if(next.classList.contains('process-group')){next=next.nextElementSibling;continue;} break; }
    if (oldAiRow) { oldAiRow.querySelector('.msg-bubble').textContent = '正在重新生成...'; oldAiRow.style.opacity = '0.6'; }
    fetch('/api/messages/'+messageId,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:newText,rerun:true})})
    .then(r=>r.json()).then(data=>{ if(data.reply){ if(oldAiRow&&oldAiRow.parentNode){oldAiRow.querySelector('.msg-bubble').textContent=data.reply;oldAiRow.style.opacity='1';oldAiRow.setAttribute('data-old-branch',messageId);} updateBranchNav(messageId); } else refreshAfterChange(currentSessionId); })
    .catch(()=>{ bubble.textContent=currentText; if(oldAiRow)oldAiRow.style.opacity='1'; });
}

function updateBranchNav(userMessageId) {
    fetch('/api/messages/'+userMessageId+'/branches').then(r=>r.json()).then(branches=>{
        var row=document.querySelector(`.msg-row[data-message-id="${userMessageId}"]`);if(!row)return;
        if(branches.length>0){row.dataset.branches=JSON.stringify(branches);row.dataset.branchIdx='0';var nav=row.querySelector('.branch-nav'),label=row.querySelector('.branch-label');if(!nav){row.querySelector('.msg-footer')?.insertAdjacentHTML('afterbegin',`<div class="branch-nav"><button class="branch-arrow" onclick="switchBranch(event,${userMessageId},-1)">◀</button><span class="branch-label">分支 1/${branches.length+1}</span><button class="branch-arrow" onclick="switchBranch(event,${userMessageId},1)">▶</button></div>`);}else if(label)label.textContent=`分支 1/${branches.length+1}`;}
    }).catch(()=>{});
}

function msgDelete(e, messageId) { e.stopPropagation(); closeAllMsgMenus(); if(!messageId)return; if(!confirm('确定要删除这条消息吗？'))return; fetch('/api/messages/'+messageId,{method:'DELETE'}).then(()=>{const row=document.querySelector(`.msg-row[data-message-id="${messageId}"]`);if(row){const prev=row.previousElementSibling;if(prev&&prev.classList.contains('process-group'))prev.remove();row.remove();}}); }

// ===== 分支切换 =====
function switchBranch(e, userMessageId, direction) {
    e.stopPropagation();
    const userRow = document.querySelector(`.msg-row[data-message-id="${userMessageId}"]`); if (!userRow) return;
    let aiRow = userRow.nextElementSibling;
    while (aiRow) { if(aiRow.classList.contains('process-group')){aiRow=aiRow.nextElementSibling;continue;} if(aiRow.classList.contains('msg-row')&&aiRow.classList.contains('agent'))break; aiRow=aiRow.nextElementSibling; }
    if (!aiRow) return;
    const aiBubble = aiRow.querySelector('.msg-bubble'), branchLabel = userRow.querySelector('.branch-label'); if(!aiBubble)return;
    function doSwitch(branches){if(!branches||branches.length===0)return;var ci=parseInt(userRow.dataset.branchIdx)||0,ni=ci+direction;if(ni<0)ni=branches.length;if(ni>branches.length)ni=0;if(ci===0&&ni>0)userRow.dataset.latestReply=aiBubble.innerHTML;if(ni===0)aiBubble.innerHTML=userRow.dataset.latestReply||aiBubble.innerHTML;else{var b=branches[ni-1];if(b.user_content)userRow.querySelector('.msg-bubble').textContent=b.user_content;aiBubble.innerHTML=b.content||'';}userRow.dataset.branchIdx=ni;if(branchLabel)branchLabel.textContent='分支 '+(ni+1)+'/'+(branches.length+1);}
    try{var raw=userRow.dataset.branches,br=raw?JSON.parse(raw):[];if(br.length>0){doSwitch(br);return;}}catch(_){}
    fetch('/api/messages/'+userMessageId+'/branches').then(r=>r.json()).then(br=>{userRow.dataset.branches=JSON.stringify(br);doSwitch(br);}).catch(()=>{});
}

// ===== 批量选择 =====
function toggleSelectMode() { selectMode=!selectMode; if(!selectMode)selectedSessions.clear(); refreshAfterChange(currentSessionId); }
function exitSelectMode() { selectMode=false; selectedSessions.clear(); updateBatchBar(); }
function toggleSessionCheck(e, sessionId) { e.stopPropagation(); if(selectedSessions.has(sessionId))selectedSessions.delete(sessionId);else selectedSessions.add(sessionId); const item=document.querySelector(`.session-item[data-session-id="${sessionId}"]`);if(item)item.classList.toggle('checked',selectedSessions.has(sessionId)); updateBatchBar(); }

function toggleSelectAll() {
    const items = document.querySelectorAll('#sessionList .session-item');
    if (selectedSessions.size === items.length) { selectedSessions.clear(); items.forEach(el=>el.classList.remove('checked')); }
    else { items.forEach(el=>{const sid=el.dataset.sessionId;if(sid)selectedSessions.add(sid);el.classList.add('checked');}); }
    updateBatchBar();
}

function updateBatchBar() {
    const bar=document.getElementById('batchBar'),count=selectedSessions.size,btn=document.getElementById('batchDeleteBtn'),countEl=document.getElementById('batchCount');
    if(selectMode){bar.classList.add('show');countEl.textContent=`已选 ${count} 项`;btn.disabled=count===0;}else{bar.classList.remove('show');}
}

function batchDelete() {
    if (selectedSessions.size === 0) return;
    if (!confirm(`确定要删除选中的 ${selectedSessions.size} 个会话吗？所有聊天记录将被永久删除。`)) return;
    const ids = Array.from(selectedSessions);
    console.log('[batchDelete] 开始批量删除:', ids);
    fetch('/api/sessions/batch',{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_ids:ids})})
    .then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json();})
    .then(data=>{selectedSessions.clear();exitSelectMode();if(data.sessions)renderSessionList(data.sessions,data.new_current||currentSessionId);wsSend({type:'switch_session',session_id:data.new_current||currentSessionId});})
    .catch(err=>{console.error('批量删除失败:',err);alert('批量删除失败，请稍后重试');});
}

// ===== 清空聊天 =====
function clearChat() {
    if (!confirm('确定要清空当前会话的所有聊天记录吗？')) return;
    fetch('/api/sessions/current/messages',{method:'DELETE'}).then(r=>r.json()).then(()=>{document.getElementById('chatMessages').innerHTML=`<div class="welcome-message"><div class="welcome-icon"><i class="fas fa-robot"></i></div><h3>聊天记录已清空</h3><p>输入消息开始新对话</p></div>`;currentProcessGroup=null;}).catch(err=>console.error('清空失败:',err));
}
