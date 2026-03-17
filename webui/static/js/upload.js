window.createGhostTraceUpload = function createGhostTraceUpload(config) {
    const {
        $,
        upsertStoredJob,
        loadStoredJobs,
        pollStatus,
        workspaceModule,
    } = config;

    let uploadStartedAt = null;

    function showUploadStatus(message, isError = false) {
        const $status = $('#upload-status');
        if (!message) {
            $status.addClass('hidden').removeClass('flex text-red-400 text-green-400 text-cyan-200');
            $status.text('');
            return;
        }
        $status.removeClass('hidden').addClass('flex');
        $status.removeClass('text-red-400 text-green-400 text-cyan-200');
        $status.addClass(isError ? 'text-red-400' : 'text-cyan-200');
        $status.text(message);
    }

    function updateSelectedFileName() {
        const fileInput = $('#file-input')[0];
        const filename = fileInput.files.length > 0 ? fileInput.files[0].name : 'No file selected';
        $('#file-name-display').text(filename);
    }

    function formatBytes(bytes) {
        const megabytes = bytes / (1024 * 1024);
        if (megabytes >= 1024) {
            return `${(megabytes / 1024).toFixed(2)} GB`;
        }
        return `${megabytes.toFixed(1)} MB`;
    }

    function formatRate(bytesPerSecond) {
        if (!Number.isFinite(bytesPerSecond) || bytesPerSecond <= 0) {
            return '0 MB/s';
        }
        const megabytesPerSecond = bytesPerSecond / (1024 * 1024);
        if (megabytesPerSecond >= 1024) {
            return `${(megabytesPerSecond / 1024).toFixed(2)} GB/s`;
        }
        return `${megabytesPerSecond.toFixed(2)} MB/s`;
    }

    function formatEta(secondsRemaining) {
        if (!Number.isFinite(secondsRemaining) || secondsRemaining < 0) {
            return '--';
        }
        if (secondsRemaining < 60) {
            return `${Math.ceil(secondsRemaining)}s`;
        }
        const minutes = Math.floor(secondsRemaining / 60);
        const seconds = Math.ceil(secondsRemaining % 60);
        return `${minutes}m ${seconds}s`;
    }

    function setUploadTelemetry(loadedBytes, totalBytes, bytesPerSecond = 0, etaSeconds = NaN) {
        $('#upload-telemetry-bytes').text(`${formatBytes(loadedBytes)} / ${formatBytes(totalBytes)}`);
        $('#upload-telemetry-speed').text(formatRate(bytesPerSecond));
        $('#upload-telemetry-eta').text(formatEta(etaSeconds));
    }

    function setUploadProgress(percent, label) {
        const normalizedPercent = Math.max(0, Math.min(100, Math.round(percent)));
        $('#upload-progress').removeClass('hidden');
        $('#upload-progress-bar').css('width', `${normalizedPercent}%`);
        $('#upload-progress-label').text(label || `${normalizedPercent}%`);
        $('#upload-stage-upload-status').text(label || `${normalizedPercent}%`);
    }

    function resetUploadProgress() {
        $('#upload-progress').addClass('hidden');
        $('#upload-progress-bar').css('width', '0%');
        $('#analysis-progress-bar').css('width', '0%');
        $('#analysis-progress-track').removeClass('is-active');
        $('#upload-progress-label').text('Idle');
        $('#upload-stage-upload-status').text('Pending');
        $('#upload-stage-analysis-status').text('Pending');
        setUploadTelemetry(0, 0, 0, NaN);
        uploadStartedAt = null;
    }

    function startAnalysisProgress() {
        $('#upload-progress').removeClass('hidden');
        $('#analysis-progress-track').addClass('is-active');
        $('#analysis-progress-bar').css('width', '42%');
        $('#upload-progress-label').text('Analyzing');
        $('#upload-stage-analysis-status').text('Running');
        $('#upload-telemetry-eta').text('Processing');
    }

    function finishAnalysisProgress() {
        $('#analysis-progress-track').removeClass('is-active');
        $('#analysis-progress-bar').css('width', '100%');
        $('#upload-progress-label').text('Complete');
        $('#upload-stage-analysis-status').text('Complete');
        $('#upload-telemetry-eta').text('Done');
    }

    function failAnalysisProgress() {
        $('#analysis-progress-track').removeClass('is-active');
        $('#analysis-progress-bar').css('width', '100%');
        $('#upload-progress-label').text('Failed');
        $('#upload-stage-analysis-status').text('Failed');
        $('#upload-telemetry-eta').text('Failed');
    }

    function bindEvents() {
        $('#file-input').on('change', updateSelectedFileName);
        window.addEventListener('ghosttrace:job-status', function(event) {
            const detail = event.detail || {};
            const status = (detail.status || '').toLowerCase();
            if (status === 'done') {
                finishAnalysisProgress();
                showUploadStatus('Analysis complete. Review triage and reconstruction next.', false);
                setTimeout(() => {
                    showUploadStatus('');
                    resetUploadProgress();
                }, 2400);
            } else if (status === 'failed' || status === 'error') {
                failAnalysisProgress();
                showUploadStatus('Analysis failed. Check backend logs or retry the sample.', true);
            }
        });

        $('#upload-form').on('submit', function(e) {
            e.preventDefault();
            const fileInput = $('#file-input')[0];
            if (fileInput.files.length === 0) {
                showUploadStatus('ERROR: No file selected.', true);
                return;
            }

            const formData = new FormData();
            formData.append('file', fileInput.files[0]);
            window.dispatchEvent(new CustomEvent('ghosttrace:upload-started', {
                detail: {
                    filename: fileInput.files[0].name,
                },
            }));
            showUploadStatus('Uploading sample...', false);
            setUploadProgress(0, '0%');
            $('#upload-stage-analysis-status').text('Pending');
            uploadStartedAt = Date.now();
            setUploadTelemetry(0, fileInput.files[0].size || 0, 0, NaN);

            $.ajax({
                url: '/upload',
                type: 'POST',
                data: formData,
                processData: false,
                contentType: false,
                xhr: function() {
                    const xhr = $.ajaxSettings.xhr();
                    if (xhr.upload) {
                        xhr.upload.addEventListener('progress', function(event) {
                            if (!event.lengthComputable) {
                                setUploadProgress(100, 'Streaming');
                                setUploadTelemetry(0, 0, 0, NaN);
                                return;
                            }
                            const elapsedSeconds = Math.max((Date.now() - uploadStartedAt) / 1000, 0.001);
                            const bytesPerSecond = event.loaded / elapsedSeconds;
                            const remainingBytes = Math.max(event.total - event.loaded, 0);
                            const etaSeconds = bytesPerSecond > 0 ? remainingBytes / bytesPerSecond : NaN;
                            const percent = (event.loaded / event.total) * 100;
                            setUploadProgress(percent, `${Math.round(percent)}%`);
                            setUploadTelemetry(event.loaded, event.total, bytesPerSecond, etaSeconds);
                            if (event.loaded === event.total) {
                                showUploadStatus('Upload complete. Waiting for Ghidra analysis...', false);
                                setUploadProgress(100, 'Uploaded');
                                setUploadTelemetry(event.total, event.total, bytesPerSecond, 0);
                                startAnalysisProgress();
                            }
                        });
                    }
                    return xhr;
                },
                success: function(data) {
                    if (data.error) {
                        failAnalysisProgress();
                        resetUploadProgress();
                        showUploadStatus(`ERROR: ${data.error}`, true);
                        return;
                    }

                    setUploadProgress(100, 'Uploaded');
                    startAnalysisProgress();
                    showUploadStatus('Upload complete. Analysis queued and polling for status...', false);

                    const { job_id, status } = data;
                    const filename = data.filename || fileInput.files[0].name;
                    workspaceModule.clearJobChatHistory(job_id);
                    upsertStoredJob({ job_id, filename, status: (status || 'analyzing').toLowerCase() });
                    window.dispatchEvent(new CustomEvent('ghosttrace:upload-complete', {
                        detail: {
                            jobId: job_id,
                            filename,
                        },
                    }));
                    loadStoredJobs();
                    workspaceModule.refreshCurrentJobWorkspace(job_id);

                    fileInput.value = '';
                    updateSelectedFileName();
                    pollStatus(job_id);

                    setTimeout(() => {
                        showUploadStatus('');
                    }, 2400);
                },
                error: function(xhr) {
                    failAnalysisProgress();
                    const error = xhr.responseJSON ? xhr.responseJSON.error : 'Unknown error.';
                    showUploadStatus(`UPLOAD FAILED: ${error}`, true);
                    setTimeout(() => resetUploadProgress(), 3200);
                }
            });
        });
    }

    return {
        bindEvents,
        resetUploadProgress,
        showUploadStatus,
    };
};
