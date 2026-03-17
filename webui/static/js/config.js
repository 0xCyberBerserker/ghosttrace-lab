window.GHOST_TRACE_CONFIG = {
    STORAGE_KEYS: {
        jobs: 'ghidraaas-analysis-jobs',
        activeJob: 'ghidraaas-active-job',
        activeView: 'ghidraaas-active-view',
        theme: 'ghidraaas-theme',
        workflowMode: 'ghidraaas-workflow-mode',
        operatorState: 'ghidraaas-operator-state',
        chatHistory: 'ghidraaas-chat-history',
        autopilot: 'ghidraaas-autopilot-enabled',
        helpMode: 'ghidraaas-help-mode-enabled',
        showArchived: 'ghidraaas-show-archived-jobs',
        collapseState: 'ghidraaas-collapse-state',
        uiStateVersion: 'ghidraaas-ui-state-version',
    },
    UI_STATE_VERSION: 'phase3-operator-shell-v4',
    ANALYSIS_TRACKS: [
        {
            title: 'Static Triage',
            copy: 'Fast capability mapping inspired by classic reverse engineering triage.',
            prompts: [
                "Summarize the binary's main capabilities and likely purpose.",
                "List the most interesting functions to inspect first.",
                "Explain what this program appears to do at a high level."
            ]
        },
        {
            title: 'PE / API Behavior',
            copy: 'Use imported APIs to infer filesystem, process, registry, crypto, and service behavior.',
            prompts: [
                "List the most important imported APIs and explain what behaviors they suggest.",
                "Identify imports related to process injection, services, registry, or persistence.",
                "Find imports related to file handling and installation behavior."
            ]
        },
        {
            title: 'Strings & Config',
            copy: 'Mine extracted strings for URLs, paths, mutexes, branding, config markers, and feature toggles.',
            prompts: [
                "List the most interesting strings and group them by URLs, file paths, config, and product markers.",
                "Find strings that look related to licensing, updates, telemetry, or remote endpoints.",
                "Use strings plus imports to infer what external services or local resources this binary may touch."
            ]
        },
        {
            title: 'Network Clues',
            copy: 'Infer probable network or telemetry behavior from static evidence only.',
            prompts: [
                "Check for imported APIs related to HTTP, WinINet, WinHTTP, Winsock, or telemetry.",
                "Based on imports and function names, infer whether this binary likely performs network activity.",
                "Find the best functions to inspect for update checks, licensing, or remote communication."
            ]
        },
        {
            title: 'Dynamic Evidence',
            copy: 'Correlate uploaded sandbox or telemetry artifacts with the static findings already cached.',
            prompts: [
                "Summarize any uploaded dynamic evidence and compare it with the static imports and strings.",
                "Highlight where sandbox evidence confirms or contradicts the static analysis.",
                "Use dynamic evidence plus decompilation to explain the most suspicious behavior chain."
            ]
        }
    ],
    NOVICE_PLAYBOOKS: {
        upload: {
            title: 'Start with the first useful question',
            copy: 'These prompts are meant to orient a new analyst before they start drilling into details.',
            prompts: [
                "Summarize this binary at a high level and explain what kind of program it appears to be.",
                "List the 3 most important things I should inspect first as a novice analyst.",
                "Explain the safest next step after the current triage state."
            ]
        },
        analyze: {
            title: 'Narrow the sample before going deeper',
            copy: 'These prompts help turn the current evidence into one concrete subsystem to investigate next.',
            prompts: [
                "Summarize the triage report and tell me which subsystem to focus on first.",
                "Based on imports and strings, what is the most suspicious behavior path here?",
                "Help me choose one reconstruction target and explain why it matters."
            ]
        },
        validate: {
            title: 'Ask for one confirmation step',
            copy: 'These prompts are tuned for validation so the debugger work stays bounded and evidence-driven.',
            prompts: [
                "What exact runtime behavior should I validate next, and why?",
                "Turn the current reconstruction target into one concrete x64dbg or sandbox check.",
                "What would confirm or falsify the main hypothesis for this subsystem?"
            ]
        }
    }
};
