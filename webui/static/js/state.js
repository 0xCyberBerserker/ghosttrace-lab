window.createGhostTraceBootstrapState = function createGhostTraceBootstrapState(config) {
    const { $ } = config;
    const { STORAGE_KEYS, ANALYSIS_TRACKS, UI_STATE_VERSION } = window.GHOST_TRACE_CONFIG;

    let currentJobId = null;
    let currentJob = null;
    let activeView = localStorage.getItem(STORAGE_KEYS.activeView) || 'chat';
    let autopilotEnabled = localStorage.getItem(STORAGE_KEYS.autopilot) === 'true';
    let helpModeEnabled = localStorage.getItem(STORAGE_KEYS.helpMode) === 'true';
    let showArchivedJobs = localStorage.getItem(STORAGE_KEYS.showArchived) === 'true';

    function getCurrentJobId() {
        return currentJobId;
    }

    function getCurrentJob() {
        return currentJob;
    }

    function setCurrentJobState(jobId, job) {
        currentJobId = jobId;
        currentJob = job;
        window.dispatchEvent(new CustomEvent('ghosttrace:job-changed', {
            detail: {
                jobId,
                job,
                hasActiveJob: Boolean(jobId),
            },
        }));
    }

    function getActiveView() {
        return activeView;
    }

    function setStoredActiveView(viewName) {
        activeView = viewName;
        localStorage.setItem(STORAGE_KEYS.activeView, activeView);
        window.dispatchEvent(new CustomEvent('ghosttrace:view-changed', {
            detail: { view: activeView },
        }));
    }

    function getAutopilotEnabled() {
        return autopilotEnabled;
    }

    function setAutopilotEnabled(enabled) {
        autopilotEnabled = Boolean(enabled);
        localStorage.setItem(STORAGE_KEYS.autopilot, autopilotEnabled ? 'true' : 'false');
        $('#autopilot-toggle').toggleClass('is-active', autopilotEnabled);
        $('#autopilot-toggle-label').text(autopilotEnabled ? 'Autopilot On' : 'Autopilot Off');
    }

    function getHelpModeEnabled() {
        return helpModeEnabled;
    }

    function setHelpModeEnabled(enabled) {
        helpModeEnabled = Boolean(enabled);
        localStorage.setItem(STORAGE_KEYS.helpMode, helpModeEnabled ? 'true' : 'false');
        $('body').toggleClass('help-mode-enabled', helpModeEnabled);
        $('#help-mode-toggle').toggleClass('is-on', helpModeEnabled);
        $('#help-mode-label').text(helpModeEnabled ? 'Help Mode On' : 'Help Mode Off');
    }

    function getShowArchivedJobs() {
        return showArchivedJobs;
    }

    function setShowArchivedJobs(enabled) {
        showArchivedJobs = Boolean(enabled);
        localStorage.setItem(STORAGE_KEYS.showArchived, String(showArchivedJobs));
        $('#toggle-archived-jobs')
            .toggleClass('is-active', showArchivedJobs)
            .text(showArchivedJobs ? 'Hide Archived' : 'Show Archived');
    }

    function getOperatorStateStore() {
        try {
            return JSON.parse(localStorage.getItem(STORAGE_KEYS.operatorState) || '{}');
        } catch (error) {
            return {};
        }
    }

    function saveOperatorStateStore(store) {
        localStorage.setItem(STORAGE_KEYS.operatorState, JSON.stringify(store));
    }

    function getJobOperatorState(jobId) {
        const store = getOperatorStateStore();
        return store[jobId] || {};
    }

    function updateJobOperatorState(jobId, updates = {}) {
        if (!jobId) return {};
        const store = getOperatorStateStore();
        const current = store[jobId] || {};
        store[jobId] = { ...current, ...updates };
        saveOperatorStateStore(store);
        return store[jobId];
    }

    function getCollapseStateStore() {
        try {
            return JSON.parse(localStorage.getItem(STORAGE_KEYS.collapseState) || '{}');
        } catch (error) {
            return {};
        }
    }

    function migrateUiStateIfNeeded() {
        const storedVersion = localStorage.getItem(STORAGE_KEYS.uiStateVersion);
        if (storedVersion === UI_STATE_VERSION) {
            return;
        }
        const store = getCollapseStateStore();
        [
            'metrics-shell',
            'operator-body',
            'reconstruction-draft-list-shell',
            'reconstruction-hypotheses-shell',
            'reconstruction-validation-shell',
            'workspace-tools',
            'x64dbg-findings-shell',
            'x64dbg-operations-shell',
            'x64dbg-requests-shell',
            'x64dbg-request-compose-shell',
            'x64dbg-bridge-shell',
            'windows-lab-shell',
        ].forEach((targetId) => {
            store[targetId] = true;
        });
        saveCollapseStateStore(store);
        localStorage.setItem(STORAGE_KEYS.uiStateVersion, UI_STATE_VERSION);
    }

    function getDefaultCollapsedState(targetId) {
        const isSmallScreen = window.matchMedia('(max-width: 1024px)').matches;
        const alwaysCollapsedTargets = new Set([
            'metrics-shell',
            'metrics-advanced',
            'jobs-batch-shell',
            'operator-body',
            'operator-advanced',
            'reconstruction-draft-list-shell',
            'reconstruction-hypotheses-shell',
            'reconstruction-validation-shell',
            'workspace-tools',
            'x64dbg-findings-shell',
            'x64dbg-operations-shell',
            'x64dbg-bridge-shell',
            'x64dbg-requests-shell',
            'windows-lab-shell',
            'x64dbg-request-compose-shell',
        ]);
        if (alwaysCollapsedTargets.has(targetId)) {
            return true;
        }
        if (!isSmallScreen) {
            return false;
        }
        const mobileCollapsedTargets = new Set(['jobs-list-shell']);
        return mobileCollapsedTargets.has(targetId);
    }

    function saveCollapseStateStore(store) {
        localStorage.setItem(STORAGE_KEYS.collapseState, JSON.stringify(store));
    }

    function setCollapseState(targetId, isCollapsed) {
        const store = getCollapseStateStore();
        store[targetId] = Boolean(isCollapsed);
        saveCollapseStateStore(store);
    }

    function applyCollapseState(buttonEl, targetId, isCollapsed) {
        const $target = $(`#${targetId}`);
        const $button = $(buttonEl);
        $target.toggleClass('hidden', isCollapsed);
        $button
            .toggleClass('is-collapsed', isCollapsed)
            .attr('aria-expanded', isCollapsed ? 'false' : 'true');
    }

    function restoreCollapseState() {
        migrateUiStateIfNeeded();
        const store = getCollapseStateStore();
        $('[data-collapse-target]').each(function() {
            const targetId = $(this).data('collapse-target');
            const isCollapsed = Object.prototype.hasOwnProperty.call(store, targetId)
                ? Boolean(store[targetId])
                : getDefaultCollapsedState(targetId);
            applyCollapseState(this, targetId, isCollapsed);
        });
    }

    function escapeHtml(value) {
        return $('<div/>').text(value).html();
    }

    function getShortJobId(jobId) {
        return `${jobId.substring(0, 8)}...${jobId.substring(jobId.length - 4)}`;
    }

    function getJobDisplayName(job) {
        if (!job) return 'Recovered analysis';
        return job.label || job.filename || `${getShortJobId(job.job_id)}.bin`;
    }

    function showOperatorToast(alert) {
        if (!alert || !alert.title) return;
        const toastId = `toast-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
        const level = escapeHtml(alert.level || 'info');
        $('#operator-toast-stack').append(`
            <div id="${toastId}" class="operator-toast ${level}">
                <div class="eyebrow mb-2">AI Operator Alert</div>
                <div class="operator-toast-title">${escapeHtml(alert.title)}</div>
                <div class="operator-toast-copy">${escapeHtml(alert.description || '')}</div>
            </div>
        `);
        setTimeout(() => {
            $(`#${toastId}`).fadeOut(220, function() {
                $(this).remove();
            });
        }, 4800);
    }

    return {
        ANALYSIS_TRACKS,
        STORAGE_KEYS,
        applyCollapseState,
        escapeHtml,
        getActiveView,
        getAutopilotEnabled,
        getCurrentJob,
        getCurrentJobId,
        getHelpModeEnabled,
        getJobDisplayName,
        getJobOperatorState,
        getShortJobId,
        getShowArchivedJobs,
        restoreCollapseState,
        setAutopilotEnabled,
        setCollapseState,
        setCurrentJobState,
        setHelpModeEnabled,
        setShowArchivedJobs,
        setStoredActiveView,
        showOperatorToast,
        updateJobOperatorState,
    };
};
