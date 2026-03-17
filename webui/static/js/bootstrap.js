$(document).ready(function() {
    const stateModule = createGhostTraceBootstrapState({ $ });
    const moduleRefs = {
        analysis: null,
        jobs: null,
        pageControls: null,
    };

    function getAnalysisModule() {
        return moduleRefs.analysis;
    }

    function getJobsModule() {
        return moduleRefs.jobs;
    }

    function getPageControls() {
        return moduleRefs.pageControls;
    }

    const chatModule = createGhostTraceChat({
        $,
        marked,
        ANALYSIS_TRACKS: stateModule.ANALYSIS_TRACKS,
        NOVICE_PLAYBOOKS: window.GHOST_TRACE_CONFIG.NOVICE_PLAYBOOKS,
        storageKey: stateModule.STORAGE_KEYS.chatHistory,
        getCurrentJob: stateModule.getCurrentJob,
        getCurrentJobId: stateModule.getCurrentJobId,
        getActiveView: stateModule.getActiveView,
        loadTriageReport: (...args) => getAnalysisModule().loadTriageReport(...args),
        loadX64dbgOverview: (...args) => getAnalysisModule().loadX64dbgOverview(...args),
        escapeHtml: stateModule.escapeHtml,
        getShortJobId: stateModule.getShortJobId,
    });

    const analysisModule = createGhostTraceAnalysis({
        $,
        getCurrentJob: stateModule.getCurrentJob,
        getCurrentJobId: stateModule.getCurrentJobId,
        getActiveView: stateModule.getActiveView,
        setActiveView: (...args) => getPageControls().setActiveView(...args),
        escapeHtml: stateModule.escapeHtml,
        getShortJobId: stateModule.getShortJobId,
        getJobOperatorState: stateModule.getJobOperatorState,
        updateJobOperatorState: stateModule.updateJobOperatorState,
        showOperatorToast: stateModule.showOperatorToast,
        getAutopilotEnabled: stateModule.getAutopilotEnabled,
    });
    moduleRefs.analysis = analysisModule;

    const statusModule = createGhostTraceStatus({
        $,
        analysisModule,
        jobsModuleRef: {
            get current() {
                return getJobsModule();
            }
        },
    });

    const pageControls = createGhostTracePageControls({
        $,
        stateModule,
        analysisModule,
        jobsModuleRef: {
            get current() {
                return getJobsModule();
            }
        },
        statusModule,
    });
    moduleRefs.pageControls = pageControls;
    const workspaceModule = createGhostTraceWorkspace({
        $,
        stateModule,
        chatModule,
        analysisModule,
    });

    const uploadModule = createGhostTraceUpload({
        $,
        upsertStoredJob: (job) => getJobsModule().upsertStoredJob(job),
        loadStoredJobs: () => getJobsModule().loadStoredJobs(),
        pollStatus: statusModule.pollStatus,
        workspaceModule,
    });

    const jobsModule = createGhostTraceJobs({
        $,
        jobsStorageKey: stateModule.STORAGE_KEYS.jobs,
        activeJobStorageKey: stateModule.STORAGE_KEYS.activeJob,
        getShowArchivedJobs: stateModule.getShowArchivedJobs,
        setCurrentJobState: stateModule.setCurrentJobState,
        getCurrentJobId: stateModule.getCurrentJobId,
        setActiveView: pageControls.setActiveView,
        getJobDisplayName: stateModule.getJobDisplayName,
        getShortJobId: stateModule.getShortJobId,
        showUploadStatus: uploadModule.showUploadStatus,
        clearJobRuntimeState: statusModule.clearJobRuntimeState,
        pollStatus: statusModule.pollStatus,
        workspaceModule,
    });
    moduleRefs.jobs = jobsModule;

    getPageControls().setActiveView(stateModule.getActiveView());
    stateModule.setAutopilotEnabled(stateModule.getAutopilotEnabled());
    stateModule.setHelpModeEnabled(stateModule.getHelpModeEnabled());
    stateModule.setShowArchivedJobs(stateModule.getShowArchivedJobs());
    stateModule.restoreCollapseState();

    jobsModule.loadJobsFromServer();
    uploadModule.showUploadStatus('');
    uploadModule.resetUploadProgress();
    chatModule.bindEvents();
    getAnalysisModule().bindEvents();
    uploadModule.bindEvents();
    getPageControls().bindEvents();
});
