window.createGhostTraceAnalysis = function createGhostTraceAnalysis(config) {
    const {
        $,
        getCurrentJob,
        getCurrentJobId,
        getActiveView,
        setActiveView,
        escapeHtml,
        getShortJobId,
        getJobOperatorState,
        updateJobOperatorState,
        showOperatorToast,
        getAutopilotEnabled,
    } = config;

    const triagePollers = {};
    const x64dbgPollers = {};
    const operatorPollers = {};
    const triageStateDigests = {};
    const x64dbgStateDigests = {};
    const reconstructionState = {};
    let windowsLabCredentials = null;
    let windowsLabPasswordVisible = false;
    let metricsPoller = null;

    function clearTriagePolling(jobId) {
        if (triagePollers[jobId]) {
            clearTimeout(triagePollers[jobId]);
            delete triagePollers[jobId];
        }
    }

    function clearX64dbgPolling(jobId) {
        if (x64dbgPollers[jobId]) {
            clearTimeout(x64dbgPollers[jobId]);
            delete x64dbgPollers[jobId];
        }
    }

    function clearOperatorPolling(jobId) {
        if (operatorPollers[jobId]) {
            clearTimeout(operatorPollers[jobId]);
            delete operatorPollers[jobId];
        }
    }

    function clearRuntimeState(jobId) {
        clearTriagePolling(jobId);
        clearX64dbgPolling(jobId);
        clearOperatorPolling(jobId);
        delete triageStateDigests[jobId];
        delete x64dbgStateDigests[jobId];
    }

    function renderMetrics(summary) {
        const jobs = summary.jobs || {};
        const triage = summary.triage || {};
        const runtime = summary.runtime || {};
        const services = summary.services || {};
        const queues = summary.queues || {};
        const serviceEntries = Object.entries(services);
        const queueEntries = Object.entries(queues);
        const healthyServices = serviceEntries.filter(([, payload]) => payload.status === 'ok').length;
        const backlogQueues = queueEntries.filter(([, payload]) => Number(payload.messages || 0) > 0).length;
        const activeJobs = Math.max(Number(jobs.total || 0) - Number(jobs.archived || 0), 0);
        const overallHealthy = serviceEntries.every(([, payload]) => payload.status === 'ok' || payload.status === 'unconfigured')
            && queueEntries.every(([, payload]) => Number(payload.messages || 0) === 0 || Number(payload.consumers || 0) > 0);
        const statusMessage = overallHealthy
            ? 'Stack telemetry looks healthy.'
            : 'Something needs attention. Open advanced telemetry for detail.';
        window.dispatchEvent(new CustomEvent('ghosttrace:metrics-updated', {
            detail: {
                overallState: overallHealthy ? 'healthy' : 'attention',
                overallTone: overallHealthy ? 'state-ready' : 'state-processing',
                servicesSummary: `${healthyServices}/${serviceEntries.length || 0}`,
                queuesSummary: backlogQueues ? `${backlogQueues} busy` : 'clear',
                activeJobsSummary: String(activeJobs),
                statusMessage,
            },
        }));

        $('#metrics-jobs-total').text(String(jobs.total ?? '-'));
        $('#metrics-jobs-archived').text(String(jobs.archived ?? '-'));
        $('#metrics-triage-completed').text(String(triage.completed ?? '-'));
        $('#metrics-evidence-jobs').text(String(jobs.with_dynamic_evidence ?? '-'));

        const serviceCards = serviceEntries.map(([serviceName, payload]) => {
            const normalizedStatus = payload.status || 'unknown';
            const stateClass = normalizedStatus === 'ok' ? 'state-ready' : normalizedStatus === 'unconfigured' ? 'state-idle' : 'state-processing';
            const detailText = payload.error
                ? payload.error
                : payload.http_status
                    ? `HTTP ${payload.http_status}`
                    : normalizedStatus;
            return `
                <div class="tool-state-rail">
                    <div class="tool-state-copy">
                        <div class="tool-state-label">${escapeHtml(serviceName)}</div>
                        <div class="tool-state-message">${escapeHtml(detailText)}</div>
                    </div>
                    <div class="tool-state-pill ${stateClass}">${escapeHtml(normalizedStatus)}</div>
                </div>
            `;
        });
        $('#metrics-services').html(serviceCards.join(''));
        const queueCards = queueEntries.map(([queueName, payload]) => {
            const hasBacklog = Number(payload.messages || 0) > 0;
            const hasConsumers = Number(payload.consumers || 0) > 0;
            let stateClass = 'state-idle';
            if (payload.status === 'ok' && hasConsumers && !hasBacklog) {
                stateClass = 'state-ready';
            } else if (payload.status === 'ok') {
                stateClass = 'state-processing';
            }
            const detailBits = [
                `${payload.messages || 0} queued`,
                `${payload.consumers || 0} consumers`,
            ];
            if (payload.error) {
                detailBits.push(payload.error);
            }
            return `
                <div class="tool-state-rail">
                    <div class="tool-state-copy">
                        <div class="tool-state-label">${escapeHtml(queueName)}</div>
                        <div class="tool-state-message">${escapeHtml(detailBits.join(' / '))}</div>
                    </div>
                    <div class="tool-state-pill ${stateClass}">${escapeHtml(payload.status || 'unknown')}</div>
                </div>
            `;
        });
        $('#metrics-queues').html(queueCards.join(''));
        $('#metrics-runtime').html(`
            <div>RabbitMQ: <span class="mono">${runtime.rabbitmq_enabled ? 'enabled' : 'disabled'}</span></div>
            <div>Sandbox: <span class="mono">${runtime.sandbox_configured ? 'configured' : 'disabled'}</span></div>
            <div>Operator Auth: <span class="mono">${runtime.operator_auth_enabled ? 'enabled' : 'disabled'}</span></div>
        `);
    }

    async function loadMetricsSummary() {
        if (metricsPoller) {
            clearTimeout(metricsPoller);
            metricsPoller = null;
        }
        try {
            const response = await fetch('/metrics/summary');
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.error || `HTTP ${response.status}`);
            }
            renderMetrics(payload);
        } catch (error) {
            console.error('metrics summary error:', error);
            window.dispatchEvent(new CustomEvent('ghosttrace:metrics-updated', {
                detail: {
                    overallState: 'error',
                    overallTone: 'state-processing',
                    statusMessage: `Could not load stack telemetry: ${error.message}`,
                },
            }));
        } finally {
            metricsPoller = setTimeout(loadMetricsSummary, 10000);
        }
    }

    function renderTriageLoading(jobId, data = {}) {
        $('#triage-content').addClass('hidden');
        const processingList = Array.isArray(data.processing) && data.processing.length
            ? ` Waiting on: ${data.processing.join(', ')}.`
            : '';
        $('#triage-status').html(`
            <div class="eyebrow mb-2">Auto Triage</div>
            <div class="flex flex-wrap items-center gap-3">
                <div class="triage-pill processing">Processing</div>
                <div class="text-white text-lg font-semibold">Building triage report for ${escapeHtml(getShortJobId(jobId))}</div>
            </div>
            <p class="mt-3 text-sm text-cyan-100/60">The report is waiting for structured artifacts from Ghidra and will refresh automatically.${escapeHtml(processingList)}</p>
        `);
    }

    function renderTriageError(jobId, message) {
        $('#triage-content').addClass('hidden');
        $('#triage-status').html(`
            <div class="eyebrow mb-2">Auto Triage</div>
            <div class="flex flex-wrap items-center gap-3">
                <div class="triage-pill processing">Unavailable</div>
                <div class="text-white text-lg font-semibold">Triage report could not be loaded</div>
            </div>
            <p class="mt-3 text-sm text-red-300/80 mono">${escapeHtml(message || `Failed to load triage for ${jobId}`)}</p>
        `);
    }

    function renderTriageReport(report) {
        const currentJob = getCurrentJob();
        const summary = report.summary || {};
        const importsSummary = summary.imports_summary || {};
        const stringsSummary = summary.strings_summary || {};
        const dynamicSummary = summary.dynamic_summary || {};
        const functionsSummary = summary.functions_summary || {};
        const capabilities = summary.capabilities || [];
        $('#triage-content').removeClass('hidden');
        $('#triage-status').html(`
            <div class="eyebrow mb-2">Auto Triage</div>
            <div class="text-white text-lg font-semibold">Cached report ready for ${escapeHtml(report.filename || currentJob?.filename || 'Recovered analysis')}</div>
            <p class="mt-2 text-sm text-cyan-100/60">This report is grounded in structured Ghidra artifacts plus any uploaded dynamic evidence.</p>
        `);
        $('#triage-capabilities').text(capabilities.length);
        $('#triage-import-count').text((importsSummary.interesting_imports || []).length);
        $('#triage-string-count').text(stringsSummary.string_count || 0);
        $('#triage-dynamic-count').text(dynamicSummary.artifact_count || 0);
        $('#triage-pill').attr('class', 'triage-pill ready').text('Ready');
        $('#triage-report-title').text(report.filename || currentJob?.filename || 'Recovered analysis');
        $('#triage-meta').html(`
            <div>Target ID: <span class="mono">${escapeHtml(getShortJobId(report.job_id))}</span></div>
            <div>Functions indexed: <span class="mono">${escapeHtml(String(functionsSummary.function_count || 0))}</span></div>
            <div>Libraries observed: <span class="mono">${escapeHtml(String(importsSummary.library_count || 0))}</span></div>
            <div>Dynamic highlights: <span class="mono">${escapeHtml(String((dynamicSummary.highlights || []).length))}</span></div>
        `);
        $('#triage-markdown').html(marked.parse(report.markdown || '_No markdown report available._'));
    }

    function computeTriageDigest(payload) {
        try {
            return JSON.stringify(payload || {});
        } catch (error) {
            return `${Date.now()}`;
        }
    }

    async function loadTriageReport(jobId, options = {}) {
        clearTriagePolling(jobId);
        const silent = Boolean(options.silent);
        if (!silent || !triageStateDigests[jobId]) {
            renderTriageLoading(jobId);
        }
        try {
            const response = await fetch(`/triage/${jobId}`);
            const data = await response.json();
            if (!response.ok && response.status !== 202) {
                throw new Error(data.error || `HTTP ${response.status}`);
            }
            if (response.status === 202 || data.status === 'queued' || data.status === 'processing') {
                if (!silent || !triageStateDigests[jobId]) {
                    renderTriageLoading(jobId, data);
                }
                triagePollers[jobId] = setTimeout(() => loadTriageReport(jobId, { silent: true }), 4000);
                return;
            }
            const digest = computeTriageDigest(data);
            if (triageStateDigests[jobId] !== digest || !silent) {
                renderTriageReport(data);
                triageStateDigests[jobId] = digest;
            }
        } catch (error) {
            console.error('Triage loading error:', error);
            renderTriageError(jobId, error.message);
        }
    }

    function renderDebugCards($container, entries, emptyMessage, formatter) {
        if (!entries.length) {
            $container.html(`<div class="debug-empty-note">${escapeHtml(emptyMessage)}</div>`);
            return;
        }
        $container.html(entries.map((entry, index) => formatter(entry, index)).join(''));
    }

    function computeX64dbgDigest(state, findingsPayload, requestsPayload) {
        try {
            return JSON.stringify({
                state: state || {},
                findings: Array.isArray(findingsPayload?.findings) ? findingsPayload.findings : [],
                requests: Array.isArray(requestsPayload?.requests) ? requestsPayload.requests : [],
            });
        } catch (error) {
            return `${Date.now()}`;
        }
    }

    function renderX64dbgLoading(jobId) {
        $('#x64dbg-content').addClass('hidden');
        $('#x64dbg-status').html(`
            <div class="eyebrow mb-2">x64dbg MCP</div>
            <div class="flex flex-wrap items-center gap-3">
                <div class="triage-pill processing">Syncing</div>
                <div class="text-white text-lg font-semibold">Loading debugger bridge for ${escapeHtml(getShortJobId(jobId))}</div>
            </div>
            <p class="mt-3 text-sm text-cyan-100/60">Fetching session state, queued requests, and captured findings from the sandbox bridge.</p>
        `);
    }

    function renderWindowsLabCredentials() {
        if (!windowsLabCredentials) {
            $('#windows-lab-username').text('unavailable');
            $('#windows-lab-password').text('unavailable');
            return;
        }
        $('#windows-lab-username').text(windowsLabCredentials.username || 'Docker');
        $('#windows-lab-password').text(
            windowsLabPasswordVisible
                ? (windowsLabCredentials.password || 'unavailable')
                : '••••••••••••••••••••••••'
        );
        $('#windows-lab-vnc').text(windowsLabCredentials.vnc_url || 'http://127.0.0.1:8006');
        $('#windows-lab-rdp').text(windowsLabCredentials.rdp_host || '127.0.0.1:3389');
        $('#windows-lab-ssh').text(windowsLabCredentials.ssh_host || '127.0.0.1:2222');
        $('#toggle-windows-lab-password').text(windowsLabPasswordVisible ? 'Hide Password' : 'Reveal Password');
    }

    async function loadWindowsLabCredentials() {
        try {
            const response = await fetch('/sandbox/windows_lab_credentials');
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.error || `HTTP ${response.status}`);
            }
            windowsLabCredentials = payload;
            windowsLabCredentials.password = null;
            renderWindowsLabCredentials();
            $('#windows-lab-credentials-status').text('Generated local lab credentials loaded from the server.');
        } catch (error) {
            console.error('windows lab credentials error:', error);
            $('#windows-lab-credentials-status').text(`Could not load lab credentials: ${error.message}`);
            $('#windows-lab-username').text('unavailable');
            $('#windows-lab-password').text('unavailable');
        }
    }

    async function revealWindowsLabPassword() {
        if (windowsLabCredentials?.password) {
            return windowsLabCredentials.password;
        }
        const response = await fetch('/sandbox/windows_lab_credentials/reveal', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: '{}'
        });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.error || `HTTP ${response.status}`);
        }
        windowsLabCredentials = {
            ...(windowsLabCredentials || {}),
            ...payload,
        };
        return windowsLabCredentials.password;
    }

    function renderX64dbgError(jobId, message) {
        $('#x64dbg-content').addClass('hidden');
        $('#x64dbg-status').html(`
            <div class="eyebrow mb-2">x64dbg MCP</div>
            <div class="flex flex-wrap items-center gap-3">
                <div class="triage-pill processing">Unavailable</div>
                <div class="text-white text-lg font-semibold">Debugger bridge could not be loaded</div>
            </div>
            <p class="mt-3 text-sm text-red-300/80 mono">${escapeHtml(message || `Failed to load x64dbg data for ${jobId}`)}</p>
        `);
    }

    function getReconstructionState(jobId) {
        if (!reconstructionState[jobId]) {
            reconstructionState[jobId] = {
                selectedTargetId: null,
                selectedDraftId: null,
            };
        }
        return reconstructionState[jobId];
    }

    function setReconstructionSelections(jobId, bundle) {
        const state = getReconstructionState(jobId);
        const targets = Array.isArray(bundle.targets) ? bundle.targets : [];
        const drafts = Array.isArray(bundle.draft_artifacts) ? bundle.draft_artifacts : [];
        if (!state.selectedTargetId || !targets.some(target => target.target_id === state.selectedTargetId)) {
            state.selectedTargetId = targets[0]?.target_id || null;
        }
        if (!state.selectedDraftId || !drafts.some(artifact => artifact.artifact_id === state.selectedDraftId)) {
            const matchingDraft = drafts.find(artifact => artifact.target_id === state.selectedTargetId);
            state.selectedDraftId = matchingDraft?.artifact_id || drafts[0]?.artifact_id || null;
        }
        return state;
    }

    function renderStageBadge(label, status) {
        return `
            <div class="reconstruction-stage ${escapeHtml(status)}">
                <div class="reconstruction-stage-label">${escapeHtml(label)}</div>
                <div class="reconstruction-stage-status">${escapeHtml(status.replaceAll('_', ' '))}</div>
            </div>
        `;
    }

    function renderReconstructionLoading(jobId) {
        $('#reconstruction-content').addClass('hidden');
        $('#reconstruction-status').html(`
            <div class="eyebrow mb-2">Reconstruction Workflow</div>
            <div class="flex flex-wrap items-center gap-3">
                <div class="triage-pill processing">Loading</div>
                <div class="text-white text-lg font-semibold">Preparing reconstruction view for ${escapeHtml(getShortJobId(jobId))}</div>
            </div>
            <p class="mt-3 text-sm text-cyan-100/60">Loading targets, hypotheses, draft artifacts, and validation plans for this analysis job.</p>
        `);
    }

    function renderReconstructionError(jobId, message) {
        $('#reconstruction-content').addClass('hidden');
        $('#reconstruction-status').html(`
            <div class="eyebrow mb-2">Reconstruction Workflow</div>
            <div class="flex flex-wrap items-center gap-3">
                <div class="triage-pill processing">Unavailable</div>
                <div class="text-white text-lg font-semibold">Reconstruction bundle could not be loaded</div>
            </div>
            <p class="mt-3 text-sm text-red-300/80 mono">${escapeHtml(message || `Failed to load reconstruction data for ${jobId}`)}</p>
        `);
    }

    function stageStatus(bundle) {
        const targets = bundle.targets || [];
        const hypotheses = bundle.hypotheses || [];
        const drafts = bundle.draft_artifacts || [];
        const plans = bundle.validation_plans || [];
        return {
            understand: targets.length ? 'complete' : 'next',
            narrow: hypotheses.length ? 'complete' : (targets.length ? 'next' : 'locked'),
            reconstruct: drafts.length ? 'complete' : (hypotheses.length ? 'next' : 'locked'),
            validate: plans.length ? 'complete' : (drafts.length ? 'next' : 'locked'),
        };
    }

    function renderReconstructionBundle(jobId, bundle) {
        const state = setReconstructionSelections(jobId, bundle);
        const statuses = stageStatus(bundle);
        const targets = Array.isArray(bundle.targets) ? bundle.targets : [];
        const hypotheses = Array.isArray(bundle.hypotheses) ? bundle.hypotheses : [];
        const drafts = Array.isArray(bundle.draft_artifacts) ? bundle.draft_artifacts : [];
        const plans = Array.isArray(bundle.validation_plans) ? bundle.validation_plans : [];
        const selectedTargetId = state.selectedTargetId;
        const selectedDraftId = state.selectedDraftId;
        const selectedTarget = targets.find(target => target.target_id === selectedTargetId) || null;
        const filteredHypotheses = selectedTargetId
            ? hypotheses.filter(record => record.target_id === selectedTargetId)
            : hypotheses;
        const selectedDraft = drafts.find(artifact => artifact.artifact_id === selectedDraftId)
            || drafts.find(artifact => artifact.target_id === selectedTargetId)
            || drafts[0]
            || null;
        if (selectedDraft) {
            state.selectedDraftId = selectedDraft.artifact_id;
        }
        const filteredPlans = selectedTargetId
            ? plans.filter(plan => plan.target_id === selectedTargetId)
            : plans;

        $('#reconstruction-content').removeClass('hidden');
        $('#reconstruction-status').html(`
            <div class="eyebrow mb-2">Reconstruction Workflow</div>
            <div class="text-white text-lg font-semibold">Evidence-grounded subsystem reconstruction</div>
            <p class="mt-2 text-sm text-cyan-100/60">Follow the staged flow: identify a target, review explicit hypotheses, generate a readable draft package, then validate behavior before making stronger claims.</p>
        `);
        $('#reconstruction-stage-grid').html([
            renderStageBadge('Understand', statuses.understand),
            renderStageBadge('Narrow', statuses.narrow),
            renderStageBadge('Reconstruct', statuses.reconstruct),
            renderStageBadge('Validate', statuses.validate),
        ].join(''));
        $('#reconstruction-focus').html(`
            <div class="reconstruction-focus-card">
                <div class="eyebrow mb-2">Focused Target</div>
                <div class="reconstruction-focus-title">${escapeHtml(selectedTarget?.title || 'Choose one target')}</div>
                <div class="reconstruction-focus-copy">${escapeHtml(
                    selectedTarget?.rationale
                    || 'Generate targets from triage, then pick one subsystem so the rest of the reconstruction flow stays bounded.'
                )}</div>
            </div>
            <div class="reconstruction-focus-card">
                <div class="eyebrow mb-2">Current Output</div>
                <div class="reconstruction-focus-title">${escapeHtml(selectedDraft?.title || 'No draft package yet')}</div>
                <div class="reconstruction-focus-copy">${escapeHtml(
                    selectedDraft?.summary
                    || 'Once the target and hypotheses look sensible, generate one draft package and review it here before opening deeper detail.'
                )}</div>
            </div>
        `);

        $('#reconstruction-targets-list').html(targets.length ? targets.map(target => `
            <button type="button" class="reconstruction-card ${target.target_id === selectedTargetId ? 'is-selected' : ''}" data-target-id="${escapeHtml(target.target_id)}">
                <div class="reconstruction-card-title">${escapeHtml(target.title)}</div>
                <div class="reconstruction-card-copy">${escapeHtml(target.rationale || 'No rationale recorded.')}</div>
                <div class="triage-meta-list mt-3">
                    <div>Scope: <span class="mono">${escapeHtml(target.scope)}</span></div>
                    <div>Priority: <span class="mono">${escapeHtml(String(target.priority ?? 'n/a'))}</span></div>
                    <div>Evidence: <span class="mono">${escapeHtml(String((target.evidence_links || []).length))}</span></div>
                </div>
            </button>
        `).join('') : '<div class="debug-empty-note">No reconstruction targets yet. Start by generating them from triage.</div>');

        $('#reconstruction-hypotheses-list').html(filteredHypotheses.length ? filteredHypotheses.map(record => `
            <div class="reconstruction-card">
                <div class="reconstruction-card-title">${escapeHtml(record.title)}</div>
                <div class="reconstruction-card-copy">${escapeHtml(record.claim)}</div>
                <div class="triage-meta-list mt-3">
                    <div>Confidence: <span class="mono">${escapeHtml(record.confidence || 'unknown')}</span></div>
                    <div>Supporting evidence: <span class="mono">${escapeHtml(String((record.supporting_evidence || []).length))}</span></div>
                    <div>Next step: <span class="mono">${escapeHtml(record.next_step || 'n/a')}</span></div>
                </div>
            </div>
        `).join('') : '<div class="debug-empty-note">No hypotheses yet for this target. Generate them once the target list looks sensible.</div>');

        $('#reconstruction-draft-list').html(drafts.length ? drafts.map(artifact => `
            <button type="button" class="reconstruction-card ${artifact.artifact_id === state.selectedDraftId ? 'is-selected' : ''}" data-draft-id="${escapeHtml(artifact.artifact_id)}">
                <div class="reconstruction-card-title">${escapeHtml(artifact.title)}</div>
                <div class="reconstruction-card-copy">${escapeHtml(artifact.summary || 'No summary recorded.')}</div>
                <div class="triage-meta-list mt-3">
                    <div>Type: <span class="mono">${escapeHtml(artifact.artifact_type || 'unknown')}</span></div>
                    <div>Status: <span class="mono">${escapeHtml(artifact.validation_status || 'draft')}</span></div>
                </div>
            </button>
        `).join('') : '<div class="debug-empty-note">No draft reconstruction package yet. Generate one after reviewing hypotheses.</div>');

        $('#reconstruction-draft-preview').html(selectedDraft ? `
            <div class="reconstruction-preview-title">${escapeHtml(selectedDraft.title)}</div>
            <div class="reconstruction-preview-copy">${escapeHtml(selectedDraft.summary || 'No summary recorded.')}</div>
            <div class="triage-meta-list mt-4">
                <div>Evidence links: <span class="mono">${escapeHtml(String((selectedDraft.evidence_links || []).length))}</span></div>
                <div>Assumptions: <span class="mono">${escapeHtml(String((selectedDraft.assumptions || []).length))}</span></div>
            </div>
            <div class="markdown-content panel p-4 mt-4">${marked.parse(selectedDraft.body || '_No draft body available._')}</div>
        ` : '<div class="debug-empty-note">Select or generate a draft package to preview it here.</div>');

        $('#reconstruction-validation-list').html(filteredPlans.length ? filteredPlans.map(plan => `
            <div class="reconstruction-card">
                <div class="reconstruction-card-title">${escapeHtml(plan.title)}</div>
                <div class="triage-meta-list mt-3">
                    <div>Checks: <span class="mono">${escapeHtml(String((plan.checks || []).length))}</span></div>
                    <div>Open risks: <span class="mono">${escapeHtml(String((plan.open_risks || []).length))}</span></div>
                    <div>Status: <span class="mono">${escapeHtml(plan.status || 'draft')}</span></div>
                </div>
                <div class="reconstruction-check-list mt-4">
                    ${(plan.checks || []).map(check => `
                        <div class="reconstruction-check-item">
                            <div class="reconstruction-check-title">${escapeHtml(check.label || 'Check')}</div>
                            <div class="reconstruction-check-copy">${escapeHtml(check.expected || 'No expected behavior recorded.')}</div>
                            <div class="mono text-xs text-cyan-200/65 mt-2">${escapeHtml(check.method || 'n/a')}</div>
                        </div>
                    `).join('')}
                    ${(plan.open_risks || []).map(risk => `
                        <div class="reconstruction-risk-item">Open risk: ${escapeHtml(risk)}</div>
                    `).join('')}
                </div>
            </div>
        `).join('') : '<div class="debug-empty-note">No validation plan yet. Generate one before treating any draft as trustworthy.</div>');

        $('#reconstruction-generate-hypotheses').prop('disabled', !targets.length);
        $('#reconstruction-generate-drafts').prop('disabled', !hypotheses.length);
        $('#reconstruction-generate-validation').prop('disabled', !drafts.length && !hypotheses.length);
        $('#reconstruction-export-draft').prop('disabled', !selectedDraft);
        $('#reconstruction-status-line').text(selectedTarget
            ? `Focused target: ${selectedTarget.title}. Review the preview first, then open hypotheses or validation only if you need more detail.`
            : 'Generate or select a reconstruction target to focus the workflow.');
    }

    async function loadReconstructionBundle(jobId) {
        renderReconstructionLoading(jobId);
        try {
            const response = await fetch(`/reconstruction/${jobId}`);
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.error || `HTTP ${response.status}`);
            }
            renderReconstructionBundle(jobId, payload);
        } catch (error) {
            console.error('reconstruction bundle error:', error);
            renderReconstructionError(jobId, error.message);
        }
    }

    async function generateReconstruction(jobId, action, body = null) {
        const response = await fetch(`/reconstruction/${jobId}/${action}`, {
            method: 'POST',
            headers: body ? { 'Content-Type': 'application/json' } : {},
            body: body ? JSON.stringify(body) : null,
        });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.error || `HTTP ${response.status}`);
        }
        return payload;
    }

    async function runReconstructionAction(action) {
        const currentJobId = getCurrentJobId();
        if (!currentJobId) {
            $('#reconstruction-status-line').text('Select a job before using reconstruction tools.');
            return;
        }
        const state = getReconstructionState(currentJobId);
        const targetScopedAction = action === 'drafts/generate' || action === 'validation_plans/generate';
        const body = targetScopedAction && state.selectedTargetId ? { target_id: state.selectedTargetId } : null;
        $('#reconstruction-status-line').text('Running reconstruction step...');
        try {
            await generateReconstruction(currentJobId, action, body);
            $('#reconstruction-status-line').text('Reconstruction step completed. Refreshing bundle...');
            await loadReconstructionBundle(currentJobId);
        } catch (error) {
            console.error('reconstruction action error:', error);
            $('#reconstruction-status-line').text(`Reconstruction step failed: ${error.message}`);
        }
    }

    function exportSelectedReconstructionDraft() {
        const currentJobId = getCurrentJobId();
        const state = currentJobId ? getReconstructionState(currentJobId) : null;
        if (!currentJobId || !state?.selectedDraftId) {
            $('#reconstruction-status-line').text('Select a draft package before exporting.');
            return;
        }
        window.open(
            `/reconstruction/${currentJobId}/drafts/${encodeURIComponent(state.selectedDraftId)}/export?format=md`,
            '_blank',
            'noopener,noreferrer'
        );
    }

    function renderX64dbgOverview(jobId, state, findingsPayload, requestsPayload) {
        const currentJob = getCurrentJob();
        const findings = Array.isArray(findingsPayload.findings) ? findingsPayload.findings : [];
        const requests = Array.isArray(requestsPayload.requests) ? requestsPayload.requests : [];
        const normalizedStatus = String(state.status || 'idle').toLowerCase();
        const pillClass = ['ready', 'attached', 'active'].includes(normalizedStatus) ? 'ready' : 'processing';
        const nextAction = findings.length
            ? 'Review the latest finding and queue only one debugger request that confirms or refutes it.'
            : normalizedStatus === 'idle'
                ? 'Start with one low-risk quick action, usually an entry breakpoint or API trace.'
                : 'Check bridge state, then queue the smallest next request that gives you runtime proof.';
        $('#x64dbg-content').removeClass('hidden');
        $('#x64dbg-status').html(`
            <div class="eyebrow mb-2">x64dbg MCP</div>
            <div class="text-white text-lg font-semibold">Debugger bridge loaded for ${escapeHtml(currentJob?.filename || getShortJobId(jobId))}</div>
            <p class="mt-2 text-sm text-cyan-100/60">This panel tracks the sandbox-side x64dbg MCP session, captured findings, and queued debugging actions.</p>
        `);
        $('#x64dbg-focus').html(`
            <div class="reconstruction-focus-card">
                <div class="eyebrow mb-2">What this lane is for</div>
                <div class="reconstruction-focus-title">Runtime confirmation, not broad exploration</div>
                <div class="reconstruction-focus-copy">Use x64dbg only when one claim needs proof. Start from the bridge snapshot, then take one bounded action.</div>
            </div>
            <div class="reconstruction-focus-card">
                <div class="eyebrow mb-2">Recommended next step</div>
                <div class="reconstruction-focus-title">${escapeHtml(findings.length ? 'Pivot from captured evidence' : 'Queue one focused request')}</div>
                <div class="reconstruction-focus-copy">${escapeHtml(nextAction)}</div>
            </div>
        `);
        $('#x64dbg-session-status').text(normalizedStatus);
        $('#x64dbg-pid').text(state.pid ? String(state.pid) : '-');
        $('#x64dbg-findings-count').text(String(findings.length));
        $('#x64dbg-requests-count').text(String(requests.length));
        $('#x64dbg-pill').attr('class', `triage-pill ${pillClass}`).text(normalizedStatus === 'idle' ? 'Idle' : normalizedStatus.replaceAll('_', ' '));
        $('#x64dbg-title').text(state.target_module || currentJob?.filename || 'x64dbg MCP bridge');
        $('#x64dbg-meta').html(`
            <div>Target ID: <span class="mono">${escapeHtml(getShortJobId(jobId))}</span></div>
            <div>Transport: <span class="mono">${escapeHtml(state.transport || 'mcp')}</span></div>
            <div>Sample present: <span class="mono">${state.sample_present ? 'yes' : 'no'}</span></div>
            <div>Last update: <span class="mono">${escapeHtml(state.updated_at || 'n/a')}</span></div>
        `);
        renderDebugCards(
            $('#x64dbg-findings-list'),
            findings,
            'No debugger findings have been captured for this job yet.',
            (finding) => `
                <div class="debug-log-card">
                    <div class="debug-log-title">${escapeHtml(finding.summary || finding.type || 'Debugger finding')}</div>
                    <div class="debug-log-copy">${escapeHtml(finding.evidence || 'No debugger evidence text recorded.')}</div>
                    <div class="triage-meta-list mt-3">
                        <div>Type: <span class="mono">${escapeHtml(finding.type || 'unknown')}</span></div>
                        <div>Address: <span class="mono">${escapeHtml(finding.address || 'n/a')}</span></div>
                    </div>
                </div>
            `
        );
        renderDebugCards(
            $('#x64dbg-requests-list'),
            requests.slice().reverse(),
            'No debugger requests are queued for this job yet.',
            (request) => `
                <div class="debug-log-card">
                    <div class="debug-log-title">${escapeHtml(request.action || 'debug action')}</div>
                    <div class="debug-log-copy">${escapeHtml(request.notes || 'No operator note was attached to this request.')}</div>
                    <div class="triage-meta-list mt-3">
                        <div>Status: <span class="mono">${escapeHtml(request.status || 'queued')}</span></div>
                        <div>Address: <span class="mono">${escapeHtml(request.address || 'n/a')}</span></div>
                        <div>Requested: <span class="mono">${escapeHtml(request.requested_at || 'n/a')}</span></div>
                    </div>
                </div>
            `
        );
    }

    async function loadX64dbgOverview(jobId, options = {}) {
        clearX64dbgPolling(jobId);
        const silent = Boolean(options.silent);
        const forceRender = Boolean(options.forceRender);
        if (!silent || !x64dbgStateDigests[jobId]) {
            renderX64dbgLoading(jobId);
        }
        try {
            const [stateResponse, findingsResponse, requestsResponse] = await Promise.all([
                fetch(`/debug/x64dbg/${jobId}`),
                fetch(`/debug/x64dbg/${jobId}/findings`),
                fetch(`/debug/x64dbg/${jobId}/requests`)
            ]);
            const [state, findingsPayload, requestsPayload] = await Promise.all([
                stateResponse.json(),
                findingsResponse.json(),
                requestsResponse.json()
            ]);
            if (!stateResponse.ok) throw new Error(state.error || `HTTP ${stateResponse.status}`);
            if (!findingsResponse.ok) throw new Error(findingsPayload.error || `HTTP ${findingsResponse.status}`);
            if (!requestsResponse.ok) throw new Error(requestsPayload.error || `HTTP ${requestsResponse.status}`);
            const digest = computeX64dbgDigest(state, findingsPayload, requestsPayload);
            if (x64dbgStateDigests[jobId] !== digest || !silent || forceRender) {
                renderX64dbgOverview(jobId, state, findingsPayload, requestsPayload);
                x64dbgStateDigests[jobId] = digest;
            }
            x64dbgPollers[jobId] = setTimeout(() => {
                if (getActiveView() === 'x64dbg' && getCurrentJobId() === jobId) {
                    loadX64dbgOverview(jobId, { silent: true });
                }
            }, 5000);
        } catch (error) {
            console.error('x64dbg overview error:', error);
            renderX64dbgError(jobId, error.message);
        }
    }

    async function queueX64dbgRequest(payload) {
        const currentJobId = getCurrentJobId();
        const currentJob = getCurrentJob();
        if (!currentJobId) {
            $('#x64dbg-request-status').text('Select a job before queuing debugger requests.');
            return;
        }
        $('#x64dbg-request-status').text('Queueing debugger request...');
        try {
            const response = await fetch(`/debug/x64dbg/${currentJobId}/requests`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.error || `HTTP ${response.status}`);
            }
            $('#x64dbg-request-status').text(`Queued ${payload.action} for ${currentJob?.filename || getShortJobId(currentJobId)}.`);
            loadX64dbgOverview(currentJobId, { silent: true, forceRender: true });
        } catch (error) {
            console.error('x64dbg queue request error:', error);
            $('#x64dbg-request-status').text(`Failed to queue request: ${error.message}`);
        }
    }

    function renderOperatorAlerts(alerts = []) {
        if (!alerts.length) {
            $('#operator-alerts').html('');
            return;
        }
        const visibleAlert = alerts[0];
        const remainingAlerts = Math.max(alerts.length - 1, 0);
        $('#operator-alerts').html(`
            <div class="operator-alert ${escapeHtml(visibleAlert.level || 'info')}">
                <div class="operator-alert-header">
                    <div class="operator-alert-title">${escapeHtml(visibleAlert.title || 'Operator Alert')}</div>
                    <div class="operator-alert-chip">${remainingAlerts > 0 ? `+${remainingAlerts} more` : 'Current signal'}</div>
                </div>
                <div class="operator-alert-copy">${escapeHtml(visibleAlert.description || '')}</div>
            </div>
        `);
    }

    function renderOperatorChecklist(checklist = []) {
        if (!checklist.length) {
            $('#operator-checklist').html('');
            return;
        }
        $('#operator-checklist').html(checklist.map(item => `
            <div class="operator-checklist-item ${item.status === 'completed' ? 'is-completed' : item.status === 'active' ? 'is-active' : ''}">
                <div class="operator-checkpoint-dot"></div>
                <div>
                    <div class="operator-checkpoint-title">${escapeHtml(item.label || 'Step')}</div>
                    <div class="operator-checkpoint-copy">${escapeHtml(item.description || '')}</div>
                </div>
            </div>
        `).join(''));
    }

    function renderOperatorPrimary(action) {
        if (!action) {
            $('#operator-primary').removeData('suggestion').addClass('hidden').html('');
            return;
        }
        $('#operator-primary').removeClass('hidden').html(`
            <div class="operator-primary-header">
                <div>
                    <div class="eyebrow mb-2">Recommended Step</div>
                    <div class="text-white text-lg font-semibold">${escapeHtml(action.label || 'Recommended action')}</div>
                </div>
                <div class="operator-primary-kind">${escapeHtml(action.kind || 'action')}</div>
            </div>
            <div class="operator-primary-copy">${escapeHtml(action.description || '')}</div>
            <button type="button" class="operator-action operator-primary-button">
                <div class="text-white font-semibold">Do this next</div>
                <div class="text-sm text-cyan-100/65 mt-2">Run the primary action for the current phase.</div>
            </button>
        `);
        $('#operator-primary').data('suggestion', action);
    }

    function renderOperatorEmpty() {
        $('#operator-shell').addClass('hidden');
    }

    function renderOperatorPanel(payload) {
        const currentJob = getCurrentJob();
        const summary = payload.summary || {};
        const suggestions = Array.isArray(payload.suggestions) ? payload.suggestions : [];
        const alerts = Array.isArray(payload.alerts) ? payload.alerts : [];
        const checklist = Array.isArray(payload.checklist) ? payload.checklist : [];
        const primaryAction = payload.primary_action || suggestions[0] || null;
        const secondarySuggestions = primaryAction
            ? suggestions.filter((suggestion, index) => {
                if (payload.primary_action) {
                    return suggestion !== primaryAction;
                }
                return index !== 0;
            })
            : suggestions;
        $('#operator-shell').removeClass('hidden');
        $('#operator-title').text(`AI Operator for ${currentJob?.filename || payload.filename || 'current target'}`);
        $('#operator-copy').text([payload.stage_headline, payload.stage_copy].filter(Boolean).join(' '));
        $('#operator-stage').attr('class', `triage-pill ${String(payload.stage || '').includes('debug') ? 'ready' : 'processing'}`).text(String(payload.stage || 'analysis').replaceAll('_', ' '));
        $('#operator-summary').html(`
            <div class="operator-card">
                <div class="eyebrow mb-2">Triage</div>
                <div class="text-white text-xl font-semibold">${escapeHtml(summary.triage_status || 'missing')}</div>
                <div class="operator-card-copy">Structured first-pass state for this job.</div>
            </div>
            <div class="operator-card">
                <div class="eyebrow mb-2">Runtime Evidence</div>
                <div class="text-white text-xl font-semibold">${escapeHtml(String(summary.dynamic_artifacts || 0))}</div>
                <div class="operator-card-copy">Captured files, logs, commands, or debugger evidence.</div>
            </div>
            <div class="operator-card">
                <div class="eyebrow mb-2">Debugger</div>
                <div class="text-white text-xl font-semibold">${escapeHtml(summary.x64dbg_status || 'idle')}</div>
                <div class="operator-card-copy">${escapeHtml(String(summary.x64dbg_findings || 0))} findings captured so far.</div>
            </div>
        `);
        renderOperatorAlerts(alerts);
        renderOperatorPrimary(primaryAction);
        renderOperatorChecklist(checklist);
        $('#operator-actions').html(secondarySuggestions.length ? secondarySuggestions.map((suggestion, index) => `
            <button type="button" class="operator-action" data-index="${index}">
                <div class="eyebrow mb-2">${escapeHtml(suggestion.kind || 'action')}</div>
                <div class="text-white font-semibold">${escapeHtml(suggestion.label || 'Recommended action')}</div>
                <div class="text-sm text-cyan-100/65 mt-2">${escapeHtml(suggestion.description || '')}</div>
            </button>
        `).join('') : `
            <div class="operator-empty-note">No alternate actions right now. Follow the recommended step above and refresh once the state changes.</div>
        `);
        $('#operator-actions').data('suggestions', secondarySuggestions);
    }

    function maybeNotifyOperatorChanges(jobId, payload) {
        const previous = getJobOperatorState(jobId);
        if (previous.state_digest && previous.state_digest !== payload.state_digest) {
            const incomingAlerts = Array.isArray(payload.alerts) ? payload.alerts : [];
            incomingAlerts.forEach((alert, index) => {
                const fingerprint = `${payload.state_digest}:${index}:${alert.title || 'alert'}`;
                if (previous.last_alert_fingerprint !== fingerprint) {
                    showOperatorToast(alert);
                    updateJobOperatorState(jobId, { last_alert_fingerprint: fingerprint });
                }
            });
        }
        updateJobOperatorState(jobId, {
            payload,
            state_digest: payload.state_digest,
            stage: payload.stage,
        });
    }

    function applyOperatorSuggestion(suggestion, mode = 'manual') {
        if (!suggestion) return;
        const payload = suggestion.payload || {};
        if (suggestion.kind === 'chat_prompt' && payload.prompt) {
            setActiveView('chat');
            $('#chat-input').val(payload.prompt).trigger('input').focus();
            if (mode === 'autopilot') {
                showOperatorToast({
                    level: 'info',
                    title: 'Autopilot staged a chat step',
                    description: 'The next recommended prompt has been inserted into the chat box for review.',
                });
            }
        } else if (suggestion.kind === 'open_view' && payload.view) {
            setActiveView(payload.view);
            if (mode === 'autopilot') {
                showOperatorToast({
                    level: 'info',
                    title: 'Autopilot changed the workspace view',
                    description: `The operator moved you to ${payload.view} because it is the best next place to look.`,
                });
            }
        } else if (suggestion.kind === 'debug_request' && payload.action) {
            setActiveView('x64dbg');
            if (mode === 'manual') {
                queueX64dbgRequest(payload);
            } else {
                $('#x64dbg-request-action').val(payload.action || '');
                $('#x64dbg-request-address').val(payload.address || '');
                $('#x64dbg-request-notes').val(payload.notes || '');
                $('#x64dbg-request-status').text(`Autopilot prepared ${payload.action} but left execution to you.`);
                showOperatorToast({
                    level: 'warning',
                    title: 'Autopilot prepared a debugger action',
                    description: 'The request is prefilled in x64dbg, but it was not sent automatically.',
                });
            }
        }
    }

    function maybeRunAutopilot(jobId, payload) {
        if (!getAutopilotEnabled() || !jobId || !payload) return;
        const state = getJobOperatorState(jobId);
        if (state.autopilot_digest_applied === payload.state_digest) return;
        const primaryAction = payload.primary_action || (Array.isArray(payload.suggestions) ? payload.suggestions[0] : null);
        if (!primaryAction) return;
        applyOperatorSuggestion(primaryAction, 'autopilot');
        updateJobOperatorState(jobId, { autopilot_digest_applied: payload.state_digest });
    }

    async function loadOperatorPanel(jobId) {
        clearOperatorPolling(jobId);
        try {
            const response = await fetch(`/assistant/next_steps/${jobId}`);
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.error || `HTTP ${response.status}`);
            }
            const cachedState = getJobOperatorState(jobId);
            if (cachedState.state_digest !== payload.state_digest || !$('#operator-shell').is(':visible')) {
                renderOperatorPanel(payload);
            }
            maybeNotifyOperatorChanges(jobId, payload);
            maybeRunAutopilot(jobId, payload);
            operatorPollers[jobId] = setTimeout(() => {
                if (getCurrentJobId() === jobId) {
                    loadOperatorPanel(jobId);
                }
            }, 6000);
        } catch (error) {
            console.error('operator panel error:', error);
            renderOperatorEmpty();
        }
    }

    async function copyX64dbgBridgeCommand() {
        const command = $('#x64dbg-bridge-command').text().trim();
        try {
            await navigator.clipboard.writeText(command);
            $('#x64dbg-bridge-copy-status').text('Recovery command copied to clipboard.');
        } catch (error) {
            console.error('clipboard copy failed:', error);
            $('#x64dbg-bridge-copy-status').text('Could not copy automatically. Select the recovery command manually inside the panel.');
        }
    }

    function bindEvents() {
        loadWindowsLabCredentials();
        loadMetricsSummary();

        $('#refresh-metrics').on('click', function() {
            window.dispatchEvent(new CustomEvent('ghosttrace:metrics-updated', {
                detail: {
                    statusMessage: 'Refreshing stack telemetry...',
                },
            }));
            loadMetricsSummary();
        });

        $('#x64dbg-view').on('click', '.debug-request-chip', function() {
            const action = $(this).data('action');
            const address = $(this).data('address');
            const notes = $(this).data('notes');
            $('#x64dbg-request-action').val(action || '');
            $('#x64dbg-request-address').val(address || '');
            $('#x64dbg-request-notes').val(notes || '');
            queueX64dbgRequest({
                action,
                address: address || undefined,
                notes: notes || ''
            });
        });

        $('#x64dbg-request-form').on('submit', function(e) {
            e.preventDefault();
            const action = $('#x64dbg-request-action').val().trim();
            const address = $('#x64dbg-request-address').val().trim();
            const notes = $('#x64dbg-request-notes').val().trim();
            if (!action) {
                $('#x64dbg-request-status').text('Action is required.');
                return;
            }
            queueX64dbgRequest({
                action,
                address: address || undefined,
                notes
            });
        });

        $('#copy-x64dbg-bridge-command').on('click', function() {
            copyX64dbgBridgeCommand();
        });

        $('#toggle-windows-lab-password').on('click', function() {
            (async () => {
                try {
                    if (!windowsLabPasswordVisible) {
                        await revealWindowsLabPassword();
                    }
                    windowsLabPasswordVisible = !windowsLabPasswordVisible;
                    renderWindowsLabCredentials();
                    $('#windows-lab-credentials-status').text(
                        windowsLabPasswordVisible
                            ? 'Generated Windows lab password revealed for this session.'
                            : 'Generated Windows lab password hidden again.'
                    );
                } catch (error) {
                    console.error('windows lab password reveal failed:', error);
                    $('#windows-lab-credentials-status').text(`Could not reveal lab password: ${error.message}`);
                }
            })();
        });

        $('#copy-windows-lab-password').on('click', async function() {
            try {
                const password = await revealWindowsLabPassword();
                await navigator.clipboard.writeText(password);
                $('#windows-lab-credentials-status').text('Generated Windows lab password copied to clipboard.');
            } catch (error) {
                console.error('windows lab password copy failed:', error);
                $('#windows-lab-credentials-status').text('Could not copy the generated password automatically.');
            }
        });

        $('#operator-actions').on('click', '.operator-action', function() {
            const suggestions = $('#operator-actions').data('suggestions') || [];
            const suggestion = suggestions[$(this).data('index')];
            if (!suggestion) return;
            applyOperatorSuggestion(suggestion, 'manual');
        });

        $('#operator-primary').on('click', '.operator-action', function() {
            const suggestion = $('#operator-primary').data('suggestion');
            if (!suggestion) return;
            applyOperatorSuggestion(suggestion, 'manual');
        });

        $('#reconstruction-view').on('click', '[data-target-id]', function() {
            const currentJobId = getCurrentJobId();
            if (!currentJobId) return;
            getReconstructionState(currentJobId).selectedTargetId = $(this).data('target-id');
            loadReconstructionBundle(currentJobId);
        });

        $('#reconstruction-view').on('click', '[data-draft-id]', function() {
            const currentJobId = getCurrentJobId();
            if (!currentJobId) return;
            getReconstructionState(currentJobId).selectedDraftId = $(this).data('draft-id');
            loadReconstructionBundle(currentJobId);
        });

        $('#reconstruction-generate-targets').on('click', function() {
            runReconstructionAction('targets/generate');
        });

        $('#reconstruction-generate-hypotheses').on('click', function() {
            runReconstructionAction('hypotheses/generate');
        });

        $('#reconstruction-generate-drafts').on('click', function() {
            runReconstructionAction('drafts/generate');
        });

        $('#reconstruction-generate-validation').on('click', function() {
            runReconstructionAction('validation_plans/generate');
        });

        $('#reconstruction-export-draft').on('click', function() {
            exportSelectedReconstructionDraft();
        });
    }

    return {
        bindEvents,
        clearRuntimeState,
        exportSelectedReconstructionDraft,
        loadOperatorPanel,
        loadMetricsSummary,
        loadReconstructionBundle,
        loadTriageReport,
        loadX64dbgOverview,
        renderOperatorEmpty,
        renderOperatorPanel,
        queueX64dbgRequest,
    };
};
