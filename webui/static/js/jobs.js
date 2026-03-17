window.createGhostTraceJobs = function createGhostTraceJobs(config) {
    const {
        $,
        jobsStorageKey,
        activeJobStorageKey,
        getShowArchivedJobs,
        setCurrentJobState,
        getCurrentJobId,
        setActiveView,
        getJobDisplayName,
        getShortJobId,
        showUploadStatus,
        clearJobRuntimeState,
        pollStatus,
        workspaceModule,
    } = config;

    function flashUploadStatus(message, isError = false, durationMs = 1800) {
        showUploadStatus(message, isError);
        if (!message) {
            return;
        }
        setTimeout(() => showUploadStatus(''), durationMs);
    }

    function readStoredJobs() {
        try {
            const raw = localStorage.getItem(jobsStorageKey);
            if (!raw) return [];
            const jobs = JSON.parse(raw);
            return Array.isArray(jobs) ? jobs : [];
        } catch (error) {
            console.warn('Failed to read stored jobs:', error);
            return [];
        }
    }

    function writeStoredJobs(jobs) {
        localStorage.setItem(jobsStorageKey, JSON.stringify(jobs));
    }

    function setStoredActiveJob(jobId) {
        if (jobId) {
            localStorage.setItem(activeJobStorageKey, jobId);
        } else {
            localStorage.removeItem(activeJobStorageKey);
        }
    }

    function getStoredActiveJob() {
        return localStorage.getItem(activeJobStorageKey);
    }

    function upsertStoredJob(job) {
        const jobs = readStoredJobs().filter(existing => existing.job_id !== job.job_id);
        jobs.unshift(job);
        writeStoredJobs(jobs);
    }

    function removeStoredJob(jobId) {
        const jobs = readStoredJobs().filter(job => job.job_id !== jobId);
        writeStoredJobs(jobs);
    }

    function updateStoredJobStatus(jobId, status) {
        const jobs = readStoredJobs().map(job => job.job_id === jobId ? { ...job, status } : job);
        writeStoredJobs(jobs);
    }

    function updateStoredJob(jobId, updates = {}) {
        const jobs = readStoredJobs().map(job => job.job_id === jobId ? { ...job, ...updates } : job);
        writeStoredJobs(jobs);
    }

    function findStoredJob(jobId) {
        return readStoredJobs().find(job => job.job_id === jobId) || null;
    }

    function resolveMergedJobStatus(remoteStatus, existingStatus) {
        const normalizedRemote = (remoteStatus || '').toLowerCase();
        const normalizedExisting = (existingStatus || '').toLowerCase();

        if (
            normalizedRemote === 'done' &&
            normalizedExisting &&
            !['done', 'failed', 'error'].includes(normalizedExisting)
        ) {
            return normalizedExisting;
        }

        return normalizedRemote || normalizedExisting || 'pending';
    }

    function renderJobItem(job, prepend = false) {
        const safeFilename = $('<div/>').text(getJobDisplayName(job)).html();
        const normalizedStatus = (job.status || 'pending').toLowerCase();
        const isArchived = Boolean(job.archived);
        const isActive = getCurrentJobId() === job.job_id;
        const primaryActionLabel = isActive ? 'Resume' : 'Open';
        const statusTone = normalizedStatus === 'done'
            ? 'is-ready'
            : normalizedStatus === 'failed' || normalizedStatus === 'error'
                ? 'is-danger'
                : 'is-processing';
        const jobHtml = `
            <div id="job-${job.job_id}" class="job-item p-3 bg-gray-800 hover:bg-gray-700 rounded-md cursor-pointer transition ${isArchived ? 'opacity-70' : ''} ${isActive ? 'is-current bg-gray-700' : ''}" data-job-id="${job.job_id}">
                <div class="job-item-header">
                    <div class="job-title-shell">
                        <div class="job-title font-medium truncate">${safeFilename}</div>
                        <div class="job-subline">
                            <span class="mono job-id-chip">${job.job_id.substring(0, 8)}...</span>
                            <span class="job-status-pill ${statusTone}">${normalizedStatus.toUpperCase()}${isArchived ? ' · ARCHIVED' : ''}</span>
                            ${isActive ? '<span class="job-current-pill">CURRENT</span>' : ''}
                        </div>
                    </div>
                    <div class="job-item-actions">
                        <button type="button" class="job-open-button" data-job-id="${job.job_id}">${primaryActionLabel}</button>
                        <button
                            type="button"
                            class="job-action-button job-more-toggle"
                            data-job-id="${job.job_id}"
                            data-job-menu-id="job-menu-${job.job_id}"
                            aria-expanded="false"
                            aria-controls="job-menu-${job.job_id}"
                            title="Show more actions"
                            aria-label="Show more actions"
                        >⋯</button>
                    </div>
                </div>
                <div id="job-menu-${job.job_id}" class="job-item-menu hidden">
                    <button type="button" class="job-menu-action job-rename-button" data-job-id="${job.job_id}">Rename</button>
                    <button type="button" class="job-menu-action job-export-button" data-job-id="${job.job_id}">Export Triage</button>
                    <button type="button" class="job-menu-action job-archive-button" data-job-id="${job.job_id}">${isArchived ? 'Restore Job' : 'Archive Job'}</button>
                    <button type="button" class="job-menu-action is-danger job-delete-button" data-job-id="${job.job_id}">Delete Job</button>
                </div>
            </div>`;

        const $existing = $(`#job-${job.job_id}`);
        if ($existing.length) {
            $existing.replaceWith(jobHtml);
        } else if (prepend) {
            $('#jobs-list').prepend(jobHtml);
        } else {
            $('#jobs-list').append(jobHtml);
        }
    }

    function activateJob(jobId) {
        const $job = $(`#job-${jobId}`);
        if (!$job.length) return;
        const nextJob = findStoredJob(jobId) || { job_id: jobId, filename: `${jobId.slice(0, 8)}.bin` };
        closeAllJobMenus();
        setCurrentJobState(jobId, nextJob);
        setStoredActiveJob(jobId);
        $('.job-item').removeClass('bg-gray-700');
        $job.addClass('bg-gray-700');
        $('#welcome-message').hide();
        $('#chat-container').removeClass('hidden').addClass('flex');
        $('#chat-input, #chat-form button').prop('disabled', false);
        $('#chat-log').html('');
        workspaceModule.restoreJobSession(jobId);
    }

    function closeAllJobMenus() {
        $('.job-item-menu').addClass('hidden');
        $('.job-more-toggle').removeClass('is-open').attr('aria-expanded', 'false');
    }

    function toggleJobMenu(jobId) {
        const $menu = $(`#job-menu-${jobId}`);
        const $toggle = $(`.job-more-toggle[data-job-id="${jobId}"]`);
        if (!$menu.length || !$toggle.length) {
            return;
        }
        const shouldOpen = $menu.hasClass('hidden');
        closeAllJobMenus();
        if (shouldOpen) {
            $menu.removeClass('hidden');
            $toggle.addClass('is-open').attr('aria-expanded', 'true');
        }
    }

    function resetWorkspaceAfterJobRemoval(jobId) {
        clearJobRuntimeState(jobId);
        if (getCurrentJobId() !== jobId) {
            return;
        }

        setCurrentJobState(null, null);
        setStoredActiveJob(null);
        $('#chat-log').html('');
        $('#chat-input').val('').prop('disabled', true);
        $('#chat-form button').prop('disabled', true);
        $('#chat-container').removeClass('flex').addClass('hidden');
        $('#welcome-message').show();
        workspaceModule.renderOperatorEmpty();
        setActiveView('chat');
    }

    async function patchJob(jobId, updates = {}) {
        const response = await fetch(`/jobs/${jobId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updates),
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        return data;
    }

    async function deleteJob(jobId) {
        const job = findStoredJob(jobId);
        const label = getJobDisplayName(job) || getShortJobId(jobId);
        const confirmed = window.confirm(`Delete analysis job "${label}"? This will remove cached artifacts, dynamic evidence, and the Ghidra project if it exists.`);
        if (!confirmed) return;

        const $button = $(`#job-${jobId} .job-delete-button`);
        $button.prop('disabled', true).text('…');

        try {
            const response = await fetch(`/jobs/${jobId}`, { method: 'DELETE' });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.error || `HTTP ${response.status}`);
            }

            removeStoredJob(jobId);
            workspaceModule.clearJobChatHistory(jobId);
            resetWorkspaceAfterJobRemoval(jobId);
            $(`#job-${jobId}`).remove();
            flashUploadStatus(`Deleted analysis job: ${label}`, false, 2200);
        } catch (error) {
            console.error('delete job error:', error);
            $button.prop('disabled', false).text('x');
            showUploadStatus(`DELETE FAILED: ${error.message}`, true);
        }
    }

    async function toggleJobArchive(jobId) {
        const job = findStoredJob(jobId);
        if (!job) return;
        const nextArchived = !Boolean(job.archived);
        try {
            await patchJob(jobId, { archived: nextArchived });
        } catch (error) {
            showUploadStatus(`ARCHIVE FAILED: ${error.message}`, true);
            return;
        }
        updateStoredJob(jobId, { archived: nextArchived });
        if (!getShowArchivedJobs() && nextArchived) {
            resetWorkspaceAfterJobRemoval(jobId);
        }
        loadStoredJobs();
        if (!nextArchived && getCurrentJobId() === jobId) {
            activateJob(jobId);
        }
        flashUploadStatus(`${nextArchived ? 'Archived' : 'Restored'} analysis job: ${getJobDisplayName(job)}`);
    }

    async function renameJob(jobId) {
        const job = findStoredJob(jobId);
        if (!job) return;

        const currentName = getJobDisplayName(job);
        const nextName = window.prompt('Choose a label for this analysis job.', currentName);
        if (nextName === null) return;

        const trimmed = nextName.trim();
        if (trimmed === currentName) return;

        try {
            await patchJob(jobId, { label: trimmed || null });
            updateStoredJob(jobId, { label: trimmed || null });
            loadStoredJobs();
            if (getCurrentJobId() === jobId) {
                activateJob(jobId);
            }
            flashUploadStatus(`Updated analysis label: ${trimmed || (job.filename || getShortJobId(jobId))}`);
        } catch (error) {
            showUploadStatus(`RENAME FAILED: ${error.message}`, true);
        }
    }

    function exportTriage(jobId, format = 'md') {
        window.open(`/triage/${jobId}/export?format=${encodeURIComponent(format)}`, '_blank', 'noopener,noreferrer');
    }

    async function archiveCompletedJobs() {
        const jobs = readStoredJobs().filter(job => (job.status || '').toLowerCase() === 'done' && !job.archived);
        if (!jobs.length) {
            flashUploadStatus('No completed jobs available to archive.');
            return;
        }

        $('#archive-completed-jobs').prop('disabled', true).text('Archiving...');
        const failures = [];

        for (const job of jobs) {
            try {
                await patchJob(job.job_id, { archived: true });
                updateStoredJob(job.job_id, { archived: true });
                if (!getShowArchivedJobs() && getCurrentJobId() === job.job_id) {
                    resetWorkspaceAfterJobRemoval(job.job_id);
                }
            } catch (error) {
                failures.push(`${getJobDisplayName(job)}: ${error.message}`);
            }
        }

        loadStoredJobs();
        $('#archive-completed-jobs').prop('disabled', false).text('Archive Completed');

        if (failures.length) {
            showUploadStatus(`ARCHIVE FAILED FOR ${failures.length} JOB(S): ${failures[0]}`, true);
            return;
        }

        flashUploadStatus(`Archived ${jobs.length} completed analysis job(s).`, false, 2200);
    }

    async function restoreArchivedJobs() {
        const jobs = readStoredJobs().filter(job => Boolean(job.archived));
        if (!jobs.length) {
            flashUploadStatus('No archived jobs to restore.');
            return;
        }

        $('#restore-archived-jobs').prop('disabled', true).text('Restoring...');
        const failures = [];

        for (const job of jobs) {
            try {
                await patchJob(job.job_id, { archived: false });
                updateStoredJob(job.job_id, { archived: false });
            } catch (error) {
                failures.push(`${getJobDisplayName(job)}: ${error.message}`);
            }
        }

        loadStoredJobs();
        $('#restore-archived-jobs').prop('disabled', false).text('Restore Archived');

        if (failures.length) {
            showUploadStatus(`RESTORE FAILED FOR ${failures.length} JOB(S): ${failures[0]}`, true);
            return;
        }

        flashUploadStatus(`Restored ${jobs.length} archived analysis job(s).`, false, 2200);
    }

    async function deleteCompletedJobs() {
        const jobs = readStoredJobs().filter(job => (job.status || '').toLowerCase() === 'done');
        if (!jobs.length) {
            flashUploadStatus('No completed jobs to delete.');
            return;
        }

        const confirmed = window.confirm(`Delete ${jobs.length} completed analysis job(s)? This will remove cached artifacts and associated backend state.`);
        if (!confirmed) return;

        $('#delete-completed-jobs').prop('disabled', true).text('Deleting...');
        const failures = [];

        for (const job of jobs) {
            try {
                const response = await fetch(`/jobs/${job.job_id}`, { method: 'DELETE' });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.error || `HTTP ${response.status}`);
                }
                removeStoredJob(job.job_id);
                workspaceModule.clearJobChatHistory(job.job_id);
                resetWorkspaceAfterJobRemoval(job.job_id);
                $(`#job-${job.job_id}`).remove();
            } catch (error) {
                failures.push(`${job.filename || getShortJobId(job.job_id)}: ${error.message}`);
            }
        }

        loadStoredJobs();
        $('#delete-completed-jobs').prop('disabled', false).text('Delete Completed');

        if (failures.length) {
            showUploadStatus(`DELETE FAILED FOR ${failures.length} JOB(S): ${failures[0]}`, true);
            return;
        }

        flashUploadStatus(`Deleted ${jobs.length} completed analysis job(s).`, false, 2200);
    }

    function resumeActiveJob() {
        const activeJobId = getCurrentJobId() || getStoredActiveJob();
        if (!activeJobId) {
            flashUploadStatus('No active job to resume.');
            return;
        }
        activateJob(activeJobId);
    }

    function loadStoredJobs() {
        const jobs = readStoredJobs().filter(job => getShowArchivedJobs() || !job.archived);
        $('#jobs-list').empty();
        jobs.forEach(job => {
            renderJobItem(job);
            pollStatus(job.job_id);
        });
    }

    async function loadJobsFromServer() {
        try {
            const response = await fetch('/jobs');
            if (!response.ok) throw new Error('Failed to load jobs');
            const data = await response.json();
            const serverJobs = Array.isArray(data.jobs) ? data.jobs : [];
            const storedJobs = readStoredJobs();
            const jobMap = new Map(storedJobs.map(job => [job.job_id, job]));

            serverJobs.forEach(job => {
                const existing = jobMap.get(job.job_id) || {};
                jobMap.set(job.job_id, {
                    job_id: job.job_id,
                    filename: job.filename || existing.filename || `${job.job_id.slice(0, 8)}.bin`,
                    label: job.label ?? existing.label ?? null,
                    archived: typeof job.archived === 'boolean' ? job.archived : Boolean(existing.archived),
                    status: resolveMergedJobStatus(job.status, existing.status),
                });
            });

            const mergedJobs = Array.from(jobMap.values());
            writeStoredJobs(mergedJobs);
            loadStoredJobs();

            const activeJobId = getStoredActiveJob();
            if (activeJobId) {
                activateJob(activeJobId);
            }
        } catch (error) {
            console.error('Failed to load jobs from server:', error);
            loadStoredJobs();
            const activeJobId = getStoredActiveJob();
            if (activeJobId) {
                activateJob(activeJobId);
            }
        }
    }

    return {
        activateJob,
        archiveCompletedJobs,
        deleteCompletedJobs,
        deleteJob,
        exportTriage,
        findStoredJob,
        loadJobsFromServer,
        loadStoredJobs,
        removeStoredJob,
        renameJob,
        resetWorkspaceAfterJobRemoval,
        resumeActiveJob,
        restoreArchivedJobs,
        closeAllJobMenus,
        toggleJobMenu,
        toggleJobArchive,
        updateStoredJob,
        updateStoredJobStatus,
        upsertStoredJob,
    };
};
