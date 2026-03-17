window.createGhostTraceStatus = function createGhostTraceStatus(config) {
    const {
        $,
        analysisModule,
        jobsModuleRef,
    } = config;

    const jobStatusPollers = {};

    function syncJobStatusPill(jobId, status) {
        const normalizedStatus = (status || 'unknown').toLowerCase();
        const $pill = $(`#job-${jobId} .job-status-pill`);
        if (!$pill.length) {
            return;
        }

        $pill
            .removeClass('is-ready is-danger is-processing')
            .addClass(
                normalizedStatus === 'done'
                    ? 'is-ready'
                    : normalizedStatus === 'failed' || normalizedStatus === 'error'
                        ? 'is-danger'
                        : 'is-processing'
            )
            .text(normalizedStatus.toUpperCase());
    }

    function clearJobRuntimeState(jobId) {
        if (!jobId) return;
        if (jobStatusPollers[jobId]) {
            clearInterval(jobStatusPollers[jobId]);
            delete jobStatusPollers[jobId];
        }
        analysisModule.clearRuntimeState(jobId);
    }

    function pollStatus(jobId) {
        if (jobStatusPollers[jobId]) return;

        jobStatusPollers[jobId] = setInterval(async () => {
            try {
                const response = await fetch(`/status/${jobId}`);
                if (!response.ok) throw new Error('Network response was not ok');

                const data = await response.json();
                const status = data.status || 'unknown';
                syncJobStatusPill(jobId, status);
                jobsModuleRef.current.updateStoredJobStatus(jobId, status);
                window.dispatchEvent(new CustomEvent('ghosttrace:job-status', {
                    detail: {
                        jobId,
                        status,
                        phase: data.phase || null,
                    },
                }));

                if (status === 'done') {
                    clearInterval(jobStatusPollers[jobId]);
                    delete jobStatusPollers[jobId];
                } else if (status === 'failed') {
                    clearInterval(jobStatusPollers[jobId]);
                    delete jobStatusPollers[jobId];
                }
            } catch (error) {
                console.error('Polling error:', error);
                syncJobStatusPill(jobId, 'error');
                jobsModuleRef.current.updateStoredJobStatus(jobId, 'error');
                clearInterval(jobStatusPollers[jobId]);
                delete jobStatusPollers[jobId];
            }
        }, 3000);
    }

    return {
        clearJobRuntimeState,
        pollStatus,
    };
};
