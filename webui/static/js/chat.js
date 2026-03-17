window.createGhostTraceChat = function createGhostTraceChat(config) {
    const {
        $,
        marked,
        ANALYSIS_TRACKS,
        NOVICE_PLAYBOOKS,
        storageKey,
        getCurrentJob,
        getCurrentJobId,
        getActiveView,
        loadTriageReport,
        loadX64dbgOverview,
        escapeHtml,
        getShortJobId,
    } = config;

    function getChatHistoryStore() {
        try {
            return JSON.parse(localStorage.getItem(storageKey) || '{}');
        } catch (error) {
            return {};
        }
    }

    function isLegacyUnsupportedToolsEntry(entry) {
        if (!entry || entry.type !== 'assistant') {
            return false;
        }
        const content = String(entry.content || '');
        const toolStateMessage = String(entry.toolState?.message || '');
        return (
            content.includes('ERROR: LLM tool-planning request failed') ||
            toolStateMessage.includes('does not support tools')
        );
    }

    function saveChatHistoryStore(store) {
        localStorage.setItem(storageKey, JSON.stringify(store));
    }

    function getJobChatHistory(jobId) {
        if (!jobId) return [];
        const store = getChatHistoryStore();
        const entries = store[jobId];
        if (!Array.isArray(entries)) {
            return [];
        }
        const filteredEntries = entries.filter((entry) => !isLegacyUnsupportedToolsEntry(entry));
        if (filteredEntries.length !== entries.length) {
            setJobChatHistory(jobId, filteredEntries);
        }
        return filteredEntries;
    }

    function getWorkflowMode() {
        try {
            const modeKey = window.GHOST_TRACE_CONFIG?.STORAGE_KEYS?.workflowMode;
            return localStorage.getItem(modeKey) || 'analyze';
        } catch (error) {
            return 'analyze';
        }
    }

    function getNovicePlaybook() {
        const workflowMode = getWorkflowMode();
        return NOVICE_PLAYBOOKS[workflowMode] || NOVICE_PLAYBOOKS.analyze;
    }

    function setJobChatHistory(jobId, entries) {
        if (!jobId) return;
        const store = getChatHistoryStore();
        if (Array.isArray(entries) && entries.length) {
            store[jobId] = entries;
        } else {
            delete store[jobId];
        }
        saveChatHistoryStore(store);
    }

    function appendJobChatHistory(jobId, entry) {
        if (!jobId || !entry) return;
        const history = getJobChatHistory(jobId);
        history.push(entry);
        setJobChatHistory(jobId, history.slice(-50));
    }

    function updateJobChatHistoryEntry(jobId, entryId, updates = {}) {
        if (!jobId || !entryId) return;
        const history = getJobChatHistory(jobId).map(entry => {
            if (entry.id !== entryId) {
                return entry;
            }
            return { ...entry, ...updates };
        });
        setJobChatHistory(jobId, history);
    }

    function clearJobChatHistory(jobId) {
        if (!jobId) return;
        const store = getChatHistoryStore();
        delete store[jobId];
        saveChatHistoryStore(store);
    }

    function renderChatEmptyState() {
        const currentJob = getCurrentJob();
        if ($('#chat-empty-state').length || !currentJob) return;
        const novicePlaybook = getNovicePlaybook();
        const starterChips = (novicePlaybook?.prompts || []).map(prompt =>
            `<button type="button" class="prompt-chip suggestion-chip primary-suggestion-chip" data-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>`
        ).join('');
        const trackHtml = ANALYSIS_TRACKS.map(track => {
            const promptChips = track.prompts.map(prompt =>
                `<button type="button" class="prompt-chip suggestion-chip" data-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>`
            ).join('');
            return `
                <div class="prompt-track">
                    <div class="prompt-track-title">${escapeHtml(track.title)}</div>
                    <div class="prompt-track-copy">${escapeHtml(track.copy)}</div>
                    <div class="mt-3 flex flex-wrap gap-2">${promptChips}</div>
                </div>
            `;
        }).join('');
        $('#chat-log').append(`
            <div id="chat-empty-state" class="chat-empty-state p-5 mb-4">
                <div class="eyebrow mb-2">Start Here</div>
                <div class="text-white text-xl font-semibold">${escapeHtml(novicePlaybook?.title || 'Pick the first useful prompt')}</div>
                <p class="mt-2 text-sm text-cyan-100/60">${escapeHtml(novicePlaybook?.copy || 'Use one of these prompts to get oriented before going deeper.')}</p>
                <div class="primary-prompt-grid mt-4">${starterChips}</div>
                <details class="advanced-playbooks mt-5">
                    <summary class="advanced-playbooks-summary">Advanced prompt library</summary>
                    <p class="mt-3 text-sm text-cyan-100/60">These broader prompt tracks are still available when you want a more article-style reversing workflow.</p>
                    <div class="mt-4">${trackHtml}</div>
                </details>
            </div>
        `);
    }

    function renderChatComposerGuide() {
        const currentJob = getCurrentJob();
        const $shell = $('#chat-composer-guide');
        if (!$shell.length) {
            return;
        }
        if (!currentJob) {
            $shell.addClass('hidden');
            return;
        }

        const novicePlaybook = getNovicePlaybook();
        const prompts = Array.isArray(novicePlaybook?.prompts) ? novicePlaybook.prompts.slice(0, 2) : [];
        const titleMap = {
            upload: 'Recommended first question',
            analyze: 'Recommended next question',
            validate: 'Recommended validation question',
        };
        const workflowMode = getWorkflowMode();
        const placeholderMap = {
            upload: 'Ask for a high-level summary or the safest first step...',
            analyze: 'Ask for one subsystem, one function cluster, or one suspicious behavior path...',
            validate: 'Ask for one concrete runtime check to confirm the current hypothesis...',
        };
        const hasHistory = Array.isArray(getJobChatHistory(currentJob.job_id)) && getJobChatHistory(currentJob.job_id).length > 0;

        $('#chat-input').attr('placeholder', placeholderMap[workflowMode] || 'Ask one focused question about the current sample...');
        if (!hasHistory) {
            $shell.addClass('hidden');
            return;
        }
        $('#chat-composer-guide-title').text(titleMap[workflowMode] || 'Recommended next question');
        $('#chat-composer-guide-text').text(novicePlaybook?.copy || 'Use one of the guided prompts to keep the investigation narrow and evidence-driven.');
        $('#chat-composer-guide-actions').html(
            prompts.map(prompt => (
                `<button type="button" class="prompt-chip suggestion-chip composer-suggestion-chip" data-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>`
            )).join('')
        );
        $shell.removeClass('hidden');
    }

    function dismissChatEmptyState() {
        $('#chat-empty-state').remove();
    }

    function addChatCard(html, isUser = false) {
        dismissChatEmptyState();
        const senderClass = isUser ? 'chat-bubble-user' : '';
        $('#chat-log').append(`
            <div class="mb-4">
                <div class="${senderClass}">${html}</div>
            </div>
        `);
        $('#chat-log').scrollTop($('#chat-log')[0].scrollHeight);
    }

    function addChatMessage(role, message) {
        const senderClass = role === 'user' ? 'chat-bubble-user' : 'chat-bubble-assistant';
        const sanitizedMessage = escapeHtml(message);
        dismissChatEmptyState();
        $('#chat-log').append(`
            <div class="mb-4">
                <div class="p-3 rounded-md ${senderClass}">${sanitizedMessage}</div>
            </div>
        `);
        $('#chat-log').scrollTop($('#chat-log')[0].scrollHeight);
    }

    function addShimmerPlaceholder() {
        const placeholderId = `shimmer-${Date.now()}`;
        dismissChatEmptyState();
        $('#chat-log').append(`
            <div id="${placeholderId}" class="mb-4">
                <div class="thinking-card p-4">
                    <div class="eyebrow mb-3">Signal Incoming</div>
                    <div class="space-y-3">
                        <div class="thinking-line w-2/5"></div>
                        <div class="thinking-line w-full"></div>
                        <div class="thinking-line w-4/6"></div>
                    </div>
                </div>
            </div>
        `);
        $('#chat-log').scrollTop($('#chat-log')[0].scrollHeight);
        return placeholderId;
    }

    function setProcessingBadge($container, message, isActive = true) {
        const badgeHtml = isActive
            ? `<div class="processing-badge"><span class="processing-dot"></span><span>${escapeHtml(message)}</span></div>`
            : '';
        const $existing = $container.find('.processing-badge');
        if ($existing.length) {
            $existing.remove();
        }
        if (badgeHtml) {
            $container.prepend(badgeHtml);
        }
    }

    function setToolStateRail($container, state, message) {
        const normalizedState = state || 'idle';
        const stateLabelMap = {
            active: 'Tool Active',
            processing: 'Warming Cache',
            ready: 'Ready',
            idle: 'Idle'
        };
        const railHtml = message
            ? `
                <div class="tool-state-rail">
                    <div class="tool-state-copy">
                        <div class="tool-state-label">Execution State</div>
                        <div class="tool-state-message">${escapeHtml(message)}</div>
                    </div>
                    <div class="tool-state-pill state-${escapeHtml(normalizedState)}">${escapeHtml(stateLabelMap[normalizedState] || 'Idle')}</div>
                </div>
            `
            : '';
        const $existing = $container.find('.tool-state-rail');
        if ($existing.length) {
            $existing.remove();
        }
        if (railHtml) {
            $container.prepend(railHtml);
        }
    }

    function renderAssistantResponse(content = '', toolCalls = [], toolState = null) {
        const markdown = content ? marked.parse(content) : '';
        const toolLogs = Array.isArray(toolCalls) && toolCalls.length
            ? `<div class="tool-calls mt-3"><div class="tool-log-card"><div class="eyebrow">System Log</div><ul>${toolCalls.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul></div></div>`
            : '<div class="tool-calls mt-3"></div>';
        const toolRail = toolState && toolState.message
            ? `
                <div class="tool-state-rail">
                    <div class="tool-state-copy">
                        <div class="tool-state-label">Execution State</div>
                        <div class="tool-state-message">${escapeHtml(toolState.message)}</div>
                    </div>
                    <div class="tool-state-pill state-${escapeHtml(toolState.state || 'idle')}">${escapeHtml({
                        active: 'Tool Active',
                        processing: 'Warming Cache',
                        ready: 'Ready',
                        idle: 'Idle'
                    }[toolState.state || 'idle'] || 'Idle')}</div>
                </div>
            `
            : '';
        return `
            <div class="chat-bubble-assistant assistant-shell p-4 rounded-md">
                ${toolRail}
                <div class="markdown-content">${markdown}</div>
                ${toolLogs}
            </div>
        `;
    }

    function renderStoredChatEntry(entry) {
        if (!entry) return;
        if (entry.type === 'user') {
            addChatMessage('user', entry.content || '');
            return;
        }
        if (entry.type === 'assistant') {
            addChatCard(renderAssistantResponse(entry.content || '', entry.toolCalls || [], entry.toolState || null), false);
        }
    }

    function addSessionMessage() {
        const currentJob = getCurrentJob();
        if (!currentJob) return;
        renderChatComposerGuide();
        addChatCard(`
            <div class="chat-status-card p-3">
                <div class="eyebrow mb-2">Session Linked</div>
                <div class="text-white font-semibold text-base">Connected to ${escapeHtml(currentJob.filename || 'Recovered analysis')}</div>
                <div class="job-meta mono text-xs mt-1">Target ID: ${escapeHtml(getShortJobId(currentJob.job_id))}</div>
                <div class="text-cyan-100/58 text-sm mt-2">Awaiting command. Start with static triage, inspect imported APIs, then pivot into specific functions and decompilation paths.</div>
            </div>
        `, false);
        renderChatEmptyState();
        if (getActiveView() === 'triage') {
            loadTriageReport(currentJob.job_id);
        } else if (getActiveView() === 'x64dbg') {
            loadX64dbgOverview(currentJob.job_id);
        }
    }

    function restoreChatHistory(jobId) {
        renderChatComposerGuide();
        const history = getJobChatHistory(jobId);
        addSessionMessage();
        if (!history.length) {
            return;
        }
        history.forEach(renderStoredChatEntry);
    }

    function bindEvents() {
        window.addEventListener('ghosttrace:view-changed', renderChatComposerGuide);
        window.addEventListener('ghosttrace:job-changed', renderChatComposerGuide);

        $('#chat-log').on('click', '.suggestion-chip', function() {
            const prompt = $(this).data('prompt');
            $('#chat-input').val(prompt).trigger('input').focus();
        });

        $('#chat-composer-guide').on('click', '.suggestion-chip', function() {
            const prompt = $(this).data('prompt');
            $('#chat-input').val(prompt).trigger('input').focus();
        });

        $('#chat-input').on('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                $('#chat-form').submit();
            }
        }).on('input', function() {
            this.style.height = 'auto';
            this.style.height = `${this.scrollHeight}px`;
        });

        $('#chat-form').on('submit', function(e) {
            e.preventDefault();
            const currentJobId = getCurrentJobId();
            const $chatInput = $('#chat-input');
            const message = $chatInput.val().trim();
            if (!message || !currentJobId) return;

            addChatMessage('user', message);
            appendJobChatHistory(currentJobId, {
                id: `user-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
                type: 'user',
                content: message
            });

            $chatInput.val('').trigger('input');
            $('#chat-input, #chat-form button').prop('disabled', true);

            const placeholderId = addShimmerPlaceholder();
            const $placeholder = $(`#${placeholderId}`);
            const $responseContainer = $placeholder.find('.thinking-card');
            const assistantEntryId = `assistant-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;

            let fullResponse = '';
            let toolCallsHtml = '';
            let toolCalls = [];
            let lastToolState = null;

            appendJobChatHistory(currentJobId, {
                id: assistantEntryId,
                type: 'assistant',
                content: '',
                toolCalls: [],
                toolState: null
            });

            fetch('/chat', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ message, job_id: currentJobId })
            })
            .then(response => {
                if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                $responseContainer.removeClass('thinking-card').addClass('chat-bubble-assistant assistant-shell p-4 rounded-md');
                $responseContainer.html('<div class="markdown-content"></div><div class="tool-calls mt-3"></div>');
                setToolStateRail($responseContainer, 'active', 'Assistant linked to Ghidra and waiting for the first tool result.');

                function read() {
                    reader.read().then(({ done, value }) => {
                        if (done) {
                            $('#chat-input, #chat-form button').prop('disabled', false);
                            $('#chat-input').focus();
                            return;
                        }
                        const chunk = decoder.decode(value, {stream: true});
                        const lines = chunk.split('\n\n').filter(line => line.trim());
                        lines.forEach(line => {
                            if (!line.startsWith('data: ')) {
                                return;
                            }
                            try {
                                const data = JSON.parse(line.substring(6));
                                if (data.type === 'token') {
                                    fullResponse += data.content;
                                    $responseContainer.find('.markdown-content').html(marked.parse(fullResponse));
                                    updateJobChatHistoryEntry(currentJobId, assistantEntryId, {
                                        content: fullResponse
                                    });
                                } else if (data.type === 'tool_call') {
                                    toolCalls.push(data.description);
                                    toolCallsHtml += `<li>${data.description}</li>`;
                                    $responseContainer.find('.tool-calls').html(`<div class="tool-log-card"><div class="eyebrow">System Log</div><ul>${toolCallsHtml}</ul></div>`);
                                    updateJobChatHistoryEntry(currentJobId, assistantEntryId, {
                                        toolCalls
                                    });
                                } else if (data.type === 'tool_state') {
                                    lastToolState = {
                                        state: data.state,
                                        message: data.content
                                    };
                                    setToolStateRail($responseContainer, data.state, data.content);
                                    updateJobChatHistoryEntry(currentJobId, assistantEntryId, {
                                        toolState: lastToolState
                                    });
                                } else if (data.type === 'processing_status') {
                                    if (data.state === 'start') {
                                        lastToolState = {
                                            state: 'processing',
                                            message: data.content
                                        };
                                        setToolStateRail($responseContainer, 'processing', data.content);
                                        setProcessingBadge($responseContainer, data.content, true);
                                    } else {
                                        setProcessingBadge($responseContainer, '', false);
                                        lastToolState = {
                                            state: 'ready',
                                            message: data.content
                                        };
                                        setToolStateRail($responseContainer, 'ready', data.content);
                                        toolCalls.push(data.content);
                                        toolCallsHtml += `<li>${data.content}</li>`;
                                        $responseContainer.find('.tool-calls').html(`<div class="tool-log-card"><div class="eyebrow">System Log</div><ul>${toolCallsHtml}</ul></div>`);
                                    }
                                    updateJobChatHistoryEntry(currentJobId, assistantEntryId, {
                                        toolCalls,
                                        toolState: lastToolState
                                    });
                                } else if (data.type === 'error') {
                                    setProcessingBadge($responseContainer, '', false);
                                    lastToolState = {
                                        state: 'idle',
                                        message: data.content
                                    };
                                    setToolStateRail($responseContainer, 'idle', data.content);
                                    $responseContainer.html(`<div class="text-red-400">ERROR: ${data.content}</div>`);
                                    updateJobChatHistoryEntry(currentJobId, assistantEntryId, {
                                        content: `ERROR: ${data.content}`,
                                        toolCalls,
                                        toolState: lastToolState
                                    });
                                }
                            } catch (error) {
                                console.error('Error parsing stream data:', error, 'Data:', line);
                            }
                        });
                        $('#chat-log').scrollTop($('#chat-log')[0].scrollHeight);
                        read();
                    });
                }

                read();
            }).catch(err => {
                console.error('Fetch stream error:', err);
                $responseContainer.html('<div class="text-red-400">FATAL ERROR: Connection to assistant failed.</div>');
                updateJobChatHistoryEntry(currentJobId, assistantEntryId, {
                    content: 'FATAL ERROR: Connection to assistant failed.',
                    toolCalls,
                    toolState: {
                        state: 'idle',
                        message: err.message || 'Connection to assistant failed.'
                    }
                });
                $('#chat-input, #chat-form button').prop('disabled', false);
            });
        });
    }

    return {
        bindEvents,
        clearJobChatHistory,
        restoreChatHistory,
    };
};
