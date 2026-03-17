window.createGhostTraceWorkspace = function createGhostTraceWorkspace(config) {
    const {
        $,
        stateModule,
        chatModule,
        analysisModule,
    } = config;

    function focusChatInput() {
        $('#chat-input').focus();
    }

    function restoreJobSession(jobId) {
        chatModule.restoreChatHistory(jobId);

        const cachedOperatorState = stateModule.getJobOperatorState(jobId);
        if (cachedOperatorState.payload) {
            analysisModule.renderOperatorPanel(cachedOperatorState.payload);
        }

        analysisModule.loadOperatorPanel(jobId);

        if (stateModule.getActiveView() === 'triage') {
            analysisModule.loadTriageReport(jobId);
        } else if (stateModule.getActiveView() === 'x64dbg') {
            analysisModule.loadX64dbgOverview(jobId);
        } else if (stateModule.getActiveView() === 'reconstruct') {
            analysisModule.loadReconstructionBundle(jobId);
        } else {
            focusChatInput();
        }
    }

    function refreshCurrentJobWorkspace(jobId) {
        if (stateModule.getActiveView() === 'triage' && stateModule.getCurrentJobId() === jobId) {
            analysisModule.loadTriageReport(jobId);
        } else if (stateModule.getActiveView() === 'x64dbg' && stateModule.getCurrentJobId() === jobId) {
            analysisModule.loadX64dbgOverview(jobId);
        } else if (stateModule.getActiveView() === 'reconstruct' && stateModule.getCurrentJobId() === jobId) {
            analysisModule.loadReconstructionBundle(jobId);
        }

        if (stateModule.getCurrentJobId() === jobId) {
            analysisModule.loadOperatorPanel(jobId);
        }
    }

    function clearJobChatHistory(jobId) {
        chatModule.clearJobChatHistory(jobId);
    }

    function renderOperatorEmpty() {
        analysisModule.renderOperatorEmpty();
    }

    return {
        clearJobChatHistory,
        focusChatInput,
        refreshCurrentJobWorkspace,
        renderOperatorEmpty,
        restoreJobSession,
    };
};
