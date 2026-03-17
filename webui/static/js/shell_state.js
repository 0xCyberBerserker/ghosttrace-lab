document.addEventListener('alpine:init', () => {
    const storageKeys = (window.GHOST_TRACE_CONFIG || {}).STORAGE_KEYS || {};
    const modeStorageKey = storageKeys.workflowMode || 'ghidraaas-workflow-mode';
    const activeViewStorageKey = storageKeys.activeView || 'ghidraaas-active-view';
    const themeStorageKey = storageKeys.theme || 'ghidraaas-theme';

    const modeDefinitions = {
        upload: {
            title: 'Start with one clear sample',
            eyebrow: 'Upload Mode',
            summary: 'Create or refresh an analysis job before exposing the rest of the workspace.',
            nextStep: 'Upload one binary, wait for the analysis job to finish, then move into triage.',
            preferredView: 'chat',
            allowedViews: ['chat'],
        },
        analyze: {
            title: 'Understand and narrow the binary',
            eyebrow: 'Analyze Mode',
            summary: 'Use triage, chat, and reconstruction to understand the sample before debugger work.',
            nextStep: 'Read the triage, pick one subsystem, and build an evidence-grounded reconstruction package.',
            preferredView: 'triage',
            allowedViews: ['chat', 'triage', 'reconstruct'],
        },
        validate: {
            title: 'Confirm behavior with runtime evidence',
            eyebrow: 'Validate Mode',
            summary: 'Use x64dbg and validation plans to confirm what the subsystem really does.',
            nextStep: 'Queue the minimum debugger or sandbox action needed to confirm or falsify the current hypothesis.',
            preferredView: 'x64dbg',
            allowedViews: ['chat', 'reconstruct', 'x64dbg'],
        },
    };

    const viewDefinitions = {
        chat: {
            label: 'Chat',
            title: 'Ask the assistant',
            description: 'Use guided questions, summaries, and follow-up prompts to narrow the sample.',
            now: 'Best when you still need orientation and want help choosing one subsystem or behavior path.',
        },
        triage: {
            label: 'Triage',
            title: 'Read the first pass',
            description: 'Review structured capabilities, imports, strings, and likely intent before going deeper.',
            now: 'Best when you need a disciplined first read before committing to a target.',
        },
        reconstruct: {
            label: 'Reconstruct',
            title: 'Build the subsystem package',
            description: 'Turn evidence into targets, hypotheses, draft packages, and validation plans.',
            now: 'Best when you already know the subsystem and want one bounded engineering package.',
        },
        x64dbg: {
            label: 'x64dbg',
            title: 'Confirm runtime behavior',
            description: 'Use the debugger bridge only when you need runtime proof for a specific claim.',
            now: 'Best when one claim or hypothesis needs runtime confirmation and nothing broader.',
        },
    };

    const investigationStages = [
        {
            id: 'understand',
            label: 'Understand',
            title: 'Get oriented',
            description: 'Start with the assistant and a high-level summary before drilling into subsystems.',
            view: 'chat',
        },
        {
            id: 'narrow',
            label: 'Narrow',
            title: 'Read the first pass',
            description: 'Use triage to choose one suspicious capability, subsystem, or path worth pursuing.',
            view: 'triage',
        },
        {
            id: 'reconstruct',
            label: 'Reconstruct',
            title: 'Build the package',
            description: 'Turn evidence into targets, hypotheses, draft packages, and validation plans.',
            view: 'reconstruct',
        },
        {
            id: 'validate',
            label: 'Validate',
            title: 'Confirm at runtime',
            description: 'Use x64dbg only when you need proof for one specific claim or hypothesis.',
            view: 'x64dbg',
        },
    ];

    const themeDefinitions = {
        'default-lab': {
            label: 'Default Lab',
            copy: 'Balanced neon lab theme for general analysis.',
        },
        'operator-tactical': {
            label: 'Operator Tactical',
            copy: 'Cool tactical shell with stronger operator contrast.',
        },
        'fallout-3-terminal': {
            label: 'Fallout 3 Terminal',
            copy: 'Diegetic green-field operator theme with CRT character.',
        },
        'amber-command': {
            label: 'Amber Command',
            copy: 'Warm command-console palette for long sessions.',
        },
    };

    Alpine.data('ghostTraceShell', () => ({
        currentTheme: localStorage.getItem(themeStorageKey) || 'default-lab',
        workflowMode: localStorage.getItem(modeStorageKey) || 'upload',
        activeView: localStorage.getItem(activeViewStorageKey) || 'chat',
        hasActiveJob: false,
        currentJobId: null,
        currentJobName: '',
        currentJobStatus: 'idle',
        telemetryOverview: {
            overallState: 'unknown',
            overallTone: 'state-idle',
            servicesSummary: '-',
            queuesSummary: '-',
            activeJobsSummary: '-',
            statusMessage: 'Loading stack telemetry...',
        },
        init() {
            this.syncFromStorage();
            this.applyTheme(this.currentTheme, false);
            this.syncThemePicker();
            window.addEventListener('ghosttrace:view-changed', (event) => {
                this.activeView = event.detail?.view || 'chat';
                this.syncModeForView();
            });
            window.addEventListener('ghosttrace:job-changed', (event) => {
                this.currentJobId = event.detail?.jobId || null;
                this.hasActiveJob = Boolean(event.detail?.hasActiveJob);
                this.currentJobName = event.detail?.job?.label || event.detail?.job?.filename || '';
                this.currentJobStatus = String(event.detail?.job?.status || 'idle').toLowerCase();
                if (!this.hasActiveJob) {
                    this.currentJobStatus = 'idle';
                    this.setWorkflowMode('upload', { persist: true, steerView: true });
                    return;
                }
                if (this.activeView === 'x64dbg') {
                    this.setWorkflowMode('validate', { persist: true, steerView: false });
                    return;
                }
                if (this.workflowMode === 'upload') {
                    this.setWorkflowMode('analyze', { persist: true, steerView: false });
                }
            });
            window.addEventListener('ghosttrace:upload-started', () => {
                this.setWorkflowMode('upload', { persist: true, steerView: true });
            });
            window.addEventListener('ghosttrace:upload-complete', () => {
                this.setWorkflowMode('analyze', { persist: true, steerView: true });
            });
            window.addEventListener('ghosttrace:metrics-updated', (event) => {
                this.telemetryOverview = {
                    ...this.telemetryOverview,
                    ...(event.detail || {}),
                };
            });
        },
        syncFromStorage() {
            this.currentTheme = localStorage.getItem(themeStorageKey) || this.currentTheme || 'default-lab';
            this.currentTheme = this.normalizeTheme(this.currentTheme);
            this.workflowMode = this.normalizeMode(this.workflowMode);
            this.activeView = this.activeView || 'chat';
            this.syncModeForView();
        },
        normalizeTheme(themeName) {
            return Object.prototype.hasOwnProperty.call(themeDefinitions, themeName) ? themeName : 'default-lab';
        },
        normalizeMode(mode) {
            return Object.prototype.hasOwnProperty.call(modeDefinitions, mode) ? mode : 'upload';
        },
        themeOptions() {
            return Object.entries(themeDefinitions).map(([id, payload]) => ({
                id,
                ...payload,
            }));
        },
        themeMeta() {
            return themeDefinitions[this.currentTheme] || themeDefinitions['default-lab'];
        },
        themeLabel() {
            return this.themeMeta().label;
        },
        themeCopy() {
            return this.themeMeta().copy;
        },
        applyTheme(themeName, persist = true) {
            const normalizedTheme = this.normalizeTheme(themeName);
            this.currentTheme = normalizedTheme;
            document.body.dataset.theme = normalizedTheme;
            document.documentElement.dataset.theme = normalizedTheme;
            this.syncThemePicker();
            if (persist) {
                localStorage.setItem(themeStorageKey, normalizedTheme);
            }
        },
        syncThemePicker() {
            window.requestAnimationFrame(() => {
                document.querySelectorAll('.theme-picker-select').forEach((element) => {
                    element.value = this.currentTheme;
                });
            });
        },
        modeMeta() {
            return modeDefinitions[this.normalizeMode(this.workflowMode)];
        },
        setWorkflowMode(mode, options = {}) {
            const normalizedMode = this.normalizeMode(mode);
            const persist = options.persist !== false;
            const steerView = options.steerView !== false;
            this.workflowMode = normalizedMode;
            if (persist) {
                localStorage.setItem(modeStorageKey, normalizedMode);
            }
            if (steerView) {
                this.ensureAllowedView();
            }
        },
        syncModeForView() {
            if (!this.hasActiveJob) {
                this.workflowMode = 'upload';
                localStorage.setItem(modeStorageKey, this.workflowMode);
                return;
            }
            if (this.activeView === 'x64dbg') {
                this.workflowMode = 'validate';
            }
            localStorage.setItem(modeStorageKey, this.workflowMode);
        },
        allowView(viewName) {
            return this.modeMeta().allowedViews.includes(viewName);
        },
        ensureAllowedView() {
            const preferredView = this.modeMeta().preferredView;
            if (!this.allowView(this.activeView)) {
                window.dispatchEvent(new CustomEvent('ghosttrace:request-view', {
                    detail: { view: preferredView },
                }));
            }
        },
        setModeAndSteer(mode) {
            this.setWorkflowMode(mode, { persist: true, steerView: true });
        },
        workflowBadge() {
            return this.modeMeta().eyebrow;
        },
        primaryTitle() {
            return this.modeMeta().title;
        },
        primarySummary() {
            return this.modeMeta().summary;
        },
        primaryNextStep() {
            if (!this.hasActiveJob && this.workflowMode !== 'upload') {
                return 'Open an existing job or upload a binary first so the rest of the workflow has something concrete to guide.';
            }
            return this.modeMeta().nextStep;
        },
        currentTargetLabel() {
            if (!this.hasActiveJob) {
                return 'No active analysis job';
            }
            return this.currentJobName || this.currentJobId || 'Active analysis job';
        },
        currentJobSummary() {
            if (!this.hasActiveJob) {
                return 'No active analysis job';
            }
            if (this.currentJobStatus === 'done') {
                return 'Resume the current workspace and continue the guided analysis flow.';
            }
            if (this.currentJobStatus === 'failed' || this.currentJobStatus === 'error') {
                return 'This sample hit a problem earlier. Reopen it to inspect the current state and decide the next safe step.';
            }
            return 'This sample is still progressing. You can reopen it now and GhostTrace will keep refreshing the state.';
        },
        telemetryPillClass() {
            return `tool-state-pill ${this.telemetryOverview.overallTone || 'state-idle'}`;
        },
        shouldShowOperations() {
            return this.hasActiveJob || this.workflowMode !== 'upload';
        },
        shouldShowDebuggerAccess() {
            return this.workflowMode === 'validate';
        },
        shouldShowReconstructionTab() {
            return this.allowView('reconstruct') && this.hasActiveJob;
        },
        shouldShowTriageTab() {
            return this.allowView('triage') && this.hasActiveJob;
        },
        shouldShowX64dbgTab() {
            return this.allowView('x64dbg') && this.hasActiveJob;
        },
        visibleViews() {
            return this.modeMeta().allowedViews.filter((viewName) => {
                if (viewName === 'triage') {
                    return this.shouldShowTriageTab();
                }
                if (viewName === 'reconstruct') {
                    return this.shouldShowReconstructionTab();
                }
                if (viewName === 'x64dbg') {
                    return this.shouldShowX64dbgTab();
                }
                return this.hasActiveJob || viewName === 'chat';
            });
        },
        viewMeta(viewName) {
            return viewDefinitions[viewName] || viewDefinitions.chat;
        },
        viewLabel(viewName) {
            return this.viewMeta(viewName).label;
        },
        viewTitle(viewName) {
            return this.viewMeta(viewName).title;
        },
        viewDescription(viewName) {
            return this.viewMeta(viewName).description;
        },
        isViewActive(viewName) {
            return this.activeView === viewName;
        },
        openView(viewName) {
            if (!this.visibleViews().includes(viewName)) {
                return;
            }
            window.dispatchEvent(new CustomEvent('ghosttrace:request-view', {
                detail: { view: viewName },
            }));
        },
        activeViewTitle() {
            return this.viewTitle(this.activeView);
        },
        activeViewDescription() {
            return this.viewDescription(this.activeView);
        },
        activeViewNow() {
            return this.viewMeta(this.activeView).now || this.activeViewDescription();
        },
        stageDefinitions() {
            return investigationStages.filter((stage) => this.visibleViews().includes(stage.view));
        },
        currentStageIndex() {
            const activeIndex = investigationStages.findIndex((stage) => stage.view === this.activeView);
            if (activeIndex >= 0) {
                return activeIndex;
            }
            if (this.workflowMode === 'validate') {
                return 3;
            }
            if (this.workflowMode === 'analyze') {
                return 1;
            }
            return 0;
        },
        stageStatus(stage) {
            if (!this.hasActiveJob) {
                return 'locked';
            }
            const stageIndex = investigationStages.findIndex((entry) => entry.id === stage.id);
            const currentIndex = this.currentStageIndex();
            if (stageIndex < currentIndex) {
                return 'done';
            }
            if (stageIndex === currentIndex) {
                return 'current';
            }
            return 'next';
        },
        stageClass(stage) {
            return `is-${this.stageStatus(stage)}`;
        },
        currentStage() {
            const current = this.stageDefinitions().find((stage) => stage.view === this.activeView);
            return current || this.stageDefinitions()[0] || investigationStages[0];
        },
        nextStage() {
            const stages = this.stageDefinitions();
            const current = this.currentStage();
            const currentIndex = stages.findIndex((stage) => stage.id === current?.id);
            if (currentIndex < 0 || currentIndex >= stages.length - 1) {
                return null;
            }
            return stages[currentIndex + 1];
        },
        currentStageTitle() {
            return this.currentStage()?.title || 'Get oriented';
        },
        currentStageDescription() {
            return this.currentStage()?.description || 'Use the current workspace to keep the investigation bounded.';
        },
        nextStageTitle() {
            return this.nextStage()?.title || 'Stay on the current step';
        },
        nextStageDescription() {
            if (!this.nextStage()) {
                return 'You are already on the furthest visible step for this mode. Finish the current task before widening scope.';
            }
            return this.nextStage().description;
        },
        hasNextStage() {
            return Boolean(this.nextStage());
        },
        openNextStage() {
            const stage = this.nextStage();
            if (!stage) {
                return;
            }
            this.openStage(stage);
        },
        stageBadge(stage) {
            const status = this.stageStatus(stage);
            if (status === 'done') return 'Done';
            if (status === 'current') return 'Current';
            if (status === 'next') return 'Next';
            return 'Locked';
        },
        stageActionLabel(stage) {
            return this.stageStatus(stage) === 'current' ? 'Continue' : 'Open';
        },
        openStage(stage) {
            if (!stage || !this.visibleViews().includes(stage.view)) {
                return;
            }
            this.openView(stage.view);
        },
    }));
});
