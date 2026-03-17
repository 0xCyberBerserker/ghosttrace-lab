window.createGhostTracePageControls = function createGhostTracePageControls(config) {
    const {
        $,
        stateModule,
        analysisModule,
        jobsModuleRef,
    } = config;

    function setActiveView(viewName) {
        const allowedViews = new Set(['chat', 'triage', 'x64dbg', 'reconstruct']);
        const activeView = allowedViews.has(viewName) ? viewName : 'chat';
        stateModule.setStoredActiveView(activeView);

        const isTriage = activeView === 'triage';
        const isX64dbg = activeView === 'x64dbg';
        const isReconstruct = activeView === 'reconstruct';

        $('#chat-view').toggleClass('hidden', isTriage || isX64dbg || isReconstruct);
        $('#triage-view').toggleClass('hidden', !isTriage);
        $('#x64dbg-view').toggleClass('hidden', !isX64dbg);
        $('#reconstruction-view').toggleClass('hidden', !isReconstruct);
        $('#chat-form').toggleClass('hidden', isTriage || isX64dbg || isReconstruct);

        if (isTriage && stateModule.getCurrentJobId()) {
            analysisModule.loadTriageReport(stateModule.getCurrentJobId());
        } else if (isX64dbg && stateModule.getCurrentJobId()) {
            analysisModule.loadX64dbgOverview(stateModule.getCurrentJobId());
        } else if (isReconstruct && stateModule.getCurrentJobId()) {
            analysisModule.loadReconstructionBundle(stateModule.getCurrentJobId());
        } else if (!isTriage && stateModule.getCurrentJobId()) {
            $('#chat-input').focus();
        }
    }

    function bindEvents() {
        window.addEventListener('ghosttrace:request-view', function(event) {
            const requestedView = event?.detail?.view || 'chat';
            setActiveView(requestedView);
        });

        $('#jobs-list').on('click', '.job-item', function() {
            jobsModuleRef.current.activateJob($(this).data('job-id'));
        });

        $('#jobs-list').on('click', '.job-open-button', function(e) {
            e.stopPropagation();
            jobsModuleRef.current.activateJob($(this).data('job-id'));
        });

        $('#jobs-list').on('click', '.job-more-toggle', function(e) {
            e.stopPropagation();
            jobsModuleRef.current.toggleJobMenu($(this).data('job-id'));
        });

        $('#jobs-list').on('click', '.job-delete-button', function(e) {
            e.stopPropagation();
            jobsModuleRef.current.closeAllJobMenus();
            jobsModuleRef.current.deleteJob($(this).data('job-id'));
        });

        $('#jobs-list').on('click', '.job-rename-button', function(e) {
            e.stopPropagation();
            jobsModuleRef.current.closeAllJobMenus();
            jobsModuleRef.current.renameJob($(this).data('job-id'));
        });

        $('#jobs-list').on('click', '.job-export-button', function(e) {
            e.stopPropagation();
            jobsModuleRef.current.closeAllJobMenus();
            jobsModuleRef.current.exportTriage($(this).data('job-id'), 'md');
        });

        $('#jobs-list').on('click', '.job-archive-button', function(e) {
            e.stopPropagation();
            jobsModuleRef.current.closeAllJobMenus();
            jobsModuleRef.current.toggleJobArchive($(this).data('job-id'));
        });

        $(document).on('click', function(e) {
            const $target = $(e.target);
            if ($target.closest('#jobs-list').length && !$target.closest('.job-more-toggle, .job-item-menu').length) {
                jobsModuleRef.current.closeAllJobMenus();
            } else if (!$target.closest('#jobs-list').length) {
                jobsModuleRef.current.closeAllJobMenus();
            }
        });

        $('#toggle-archived-jobs').on('click', function() {
            stateModule.setShowArchivedJobs(!stateModule.getShowArchivedJobs());
            jobsModuleRef.current.loadStoredJobs();
        });

        $('#archive-completed-jobs').on('click', function() {
            jobsModuleRef.current.archiveCompletedJobs();
        });

        $('#resume-active-job').on('click', function() {
            jobsModuleRef.current.resumeActiveJob();
        });

        $('#restore-archived-jobs').on('click', function() {
            jobsModuleRef.current.restoreArchivedJobs();
        });

        $('#delete-completed-jobs').on('click', function() {
            jobsModuleRef.current.deleteCompletedJobs();
        });

        $('#autopilot-toggle').on('click', function() {
            stateModule.setAutopilotEnabled(!stateModule.getAutopilotEnabled());
            if (stateModule.getAutopilotEnabled() && stateModule.getCurrentJobId()) {
                const cachedState = stateModule.getJobOperatorState(stateModule.getCurrentJobId());
                if (cachedState.payload) {
                    analysisModule.loadOperatorPanel(stateModule.getCurrentJobId());
                }
            }
        });

        $('#help-mode-toggle').on('click', function() {
            stateModule.setHelpModeEnabled(!stateModule.getHelpModeEnabled());
        });

        $(document).on('click', '[data-collapse-target]', function() {
            const targetId = $(this).data('collapse-target');
            if (!targetId) return;
            const isCollapsed = !$(this).hasClass('is-collapsed');
            stateModule.applyCollapseState(this, targetId, isCollapsed);
            stateModule.setCollapseState(targetId, isCollapsed);
        });

        $(document).on('click', '.info-button', function() {
            const targetId = $(this).data('info-target');
            if (!targetId) return;
            const $panel = $(`#${targetId}`);
            const willOpen = $panel.hasClass('hidden');
            $panel.toggleClass('hidden', !willOpen);
            $(this).toggleClass('is-open', willOpen).attr('aria-expanded', willOpen ? 'true' : 'false');
        });
    }

    return {
        bindEvents,
        setActiveView,
    };
};
