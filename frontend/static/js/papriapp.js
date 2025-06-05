// frontend/static/js/papriapp.js

// --- Alpine.js Data for the Main Application ---
document.addEventListener('alpine:init', () => {
    Alpine.data('papriApp', () => ({
        // --- Application State ---
        currentView: 'search',
        isLoading: false, // Global loading for initial app load or major transitions
        isSidebarOpen: false,
        authenticatedUser: null, // Stores { email, username, profile: { subscription_plan, ... } }
        
        djangoContext: {}, // Populated from <script id="django-context">

        // --- Search View State ---
        searchForm: {
            query_text: '',
            query_image: null, // File object
            query_image_name: '',
            query_video_url: '',
            filters: {
                platform: [],
                min_duration_sec: null,
                max_duration_sec: null,
                upload_date_after: '',
                upload_date_before: '',
                // sort_by: 'relevance' // Example for future
            }
        },
        searchLoading: false, // Specific to search operation (initiate, poll, fetch results)
        searchStatusMessage: '',
        searchErrorMessage: false, // True if searchStatusMessage is an error
        searchResults: [],
        searchCurrentTaskId: null,
        searchPollingInterval: null,
        searchTotalResults: 0,
        searchTotalPages: 0,
        searchCurrentPage: 1,
        searchAttempted: false, // To show "no results" only after a search

        // --- Video Player Modal State ---
        showVideoModal: false,
        videoToPlay: null,
        modalPlayer: null, // Plyr instance for the modal

        // --- AI Video Editor State ---
        editorVideoSource: null, // { title, original_url, video_source_id, uploaded_name, file_object }
        editorPrompt: '',
        editorLoading: false, // Specific to editor operation
        editorStatusMessage: '',
        editorErrorMessage: false,
        editedVideoUrl: null,
        editedPlayer: null, // Plyr instance for the edited video
        editorProjectId: null, // Stores current project ID for the editor

        // --- Global Notification ---
        globalNotification: {
            visible: false,
            message: '',
            type: 'info', // 'info', 'success', 'error'
            timeoutInstance: null
        },

        // --- Initialization ---
        initializeApplication() {
            this.isLoading = true;
            this.loadDjangoContext();
            this.fetchAuthStatus().finally(() => { this.isLoading = false; });
            this.handleHashChange();
            window.addEventListener('popstate', () => this.handleHashChange());
        },

        loadDjangoContext() {
            try {
                const contextEl = document.getElementById('django-context');
                if (contextEl) {
                    this.djangoContext = JSON.parse(contextEl.textContent || '{}');
                    console.log("Django context loaded:", this.djangoContext);
                } else {
                    console.warn("Django context script block not found.");
                }
            } catch (e) {
                console.error("Error parsing Django context:", e);
                this.showGlobalNotification("Failed to load app configuration.", "error");
            }
        },

        // --- Authentication ---
        async fetchAuthStatus() {
            try {
                const response = await fetch(this.djangoContext.API_BASE_URL + '/auth/status/');
                if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
                const data = await response.json();
                if (data.isAuthenticated) {
                    this.authenticatedUser = data.user;
                    this.authenticatedUser.profile = data.profile;
                    console.log("User authenticated:", this.authenticatedUser);
                } else {
                    this.authenticatedUser = null;
                    console.log("User not authenticated.");
                }
            } catch (error) {
                console.error("Error fetching auth status:", error);
                this.showGlobalNotification("Could not verify authentication status. Some features might be unavailable.", "error");
            }
        },

        logoutUser() {
            window.location.href = this.djangoContext.LOGOUT_URL || '/accounts/logout/';
        },
        
        // --- Routing ---
        handleHashChange() {
            const hash = window.location.hash.substring(1) || 'search';
            if (['search', 'editor', 'history', 'collections', 'settings'].includes(hash)) {
                this.currentView = hash;
            } else {
                this.currentView = 'search';
                window.location.hash = 'search'; // Correct invalid hash
            }
            document.querySelector('main')?.scrollTo(0, 0);
        },

        // --- Search Functionality ---
        handleSearchImageFile(event) {
            if (event.target.files.length > 0) {
                this.searchForm.query_image = event.target.files[0];
                this.searchForm.query_image_name = this.searchForm.query_image.name;
            } else {
                this.searchForm.query_image = null;
                this.searchForm.query_image_name = '';
            }
        },

        async initiateNewSearchTask() {
            if (!this.searchForm.query_text.trim() && !this.searchForm.query_image && !this.searchForm.query_video_url.trim()) {
                this.showGlobalNotification("Please provide a text query, an image, or a video URL.", "error");
                return;
            }
            this.searchLoading = true;
            this.searchAttempted = true;
            this.searchStatusMessage = "🚀 Initiating search... please wait.";
            this.searchErrorMessage = false;
            this.searchResults = [];
            this.searchCurrentTaskId = null;
            if (this.searchPollingInterval) clearInterval(this.searchPollingInterval);

            const formData = new FormData();
            if (this.searchForm.query_text.trim()) formData.append('query_text', this.searchForm.query_text.trim());
            if (this.searchForm.query_image) formData.append('query_image', this.searchForm.query_image);
            if (this.searchForm.query_video_url.trim()) formData.append('query_video_url', this.searchForm.query_video_url.trim());
            
            const activeFilters = {};
            for (const key in this.searchForm.filters) {
                const value = this.searchForm.filters[key];
                if (value !== null && value !== '' && (!Array.isArray(value) || value.length > 0)) {
                    activeFilters[key] = value;
                }
            }
            if (Object.keys(activeFilters).length > 0) {
                formData.append('filters', JSON.stringify(activeFilters));
            }
            
            try {
                const response = await fetch(this.djangoContext.API_BASE_URL + '/search/initiate/', {
                    method: 'POST',
                    body: formData,
                    headers: { 'X-CSRFToken': this.getCSRFToken() }
                });
                const data = await response.json();

                if (response.status === 202 && data.id) { // Check for 202 Accepted
                    this.searchCurrentTaskId = data.id;
                    this.searchStatusMessage = `🔍 Search task started (ID: ${data.id}). Polling for updates...`;
                    this.showGlobalNotification("Search initiated! We'll notify you of progress.", "info", 2500);
                    this.startPollingSearchStatus(data.id);
                } else {
                    throw new Error(data.error || data.detail || `Failed to initiate search (status ${response.status})`);
                }
            } catch (error) {
                console.error("Error initiating search task:", error);
                this.searchStatusMessage = `Error: ${error.message}`;
                this.searchErrorMessage = true;
                this.searchLoading = false;
                this.showGlobalNotification(`Search initiation failed: ${error.message}`, "error");
            }
        },

        startPollingSearchStatus(taskId) {
            this.searchPollingInterval = setInterval(async () => {
                if (!this.searchCurrentTaskId) {
                    clearInterval(this.searchPollingInterval);
                    return;
                }
                try {
                    const response = await fetch(`${this.djangoContext.API_BASE_URL}/search/status/${taskId}/`);
                    const data = await response.json();

                    if (!response.ok) throw new Error(data.error || `Status check failed (HTTP ${response.status})`);

                    this.searchStatusMessage = `📊 Status: ${data.status || 'Unknown'}. ${data.error_message || ''}`;
                    if (data.status === 'completed' || data.status === 'partial_results') {
                        clearInterval(this.searchPollingInterval);
                        this.searchLoading = false;
                        this.searchStatusMessage = `✅ Search ${data.status}. Fetching results...`;
                        this.showGlobalNotification("Search processing complete. Fetching results!", "success", 2000);
                        this.fetchResultsPage(1, taskId);
                    } else if (data.status === 'failed') {
                        clearInterval(this.searchPollingInterval);
                        this.searchLoading = false;
                        this.searchStatusMessage = `❌ Search failed: ${data.error_message || 'Unknown error'}`;
                        this.searchErrorMessage = true;
                        this.showGlobalNotification(`Search task failed: ${data.error_message || 'Unknown error'}`, "error");
                    } else {
                         this.searchStatusMessage = `⏳ Status: ${data.status || 'Processing'}... ${data.error_message || ''}`;
                    }
                } catch (error) {
                    console.error("Error polling search status:", error);
                    this.searchStatusMessage = `Error polling status: ${error.message}`;
                    this.searchErrorMessage = true;
                    // Optionally stop polling on repeated errors or specific conditions
                    // clearInterval(this.searchPollingInterval);
                    // this.searchLoading = false;
                    this.showGlobalNotification("Error fetching search status. Will keep trying.", "warning", 2000);
                }
            }, 3500); // Poll every 3.5 seconds
        },

        async fetchResultsPage(pageNumber, taskId = null) {
            const currentTask = taskId || this.searchCurrentTaskId;
            if (!currentTask) {
                this.showGlobalNotification("No active search task to fetch results for.", "warning");
                return;
            }

            this.searchLoading = true;
            this.searchStatusMessage = `📄 Fetching results page ${pageNumber}...`;
            this.searchErrorMessage = false;

            try {
                const params = new URLSearchParams({ page: pageNumber });
                const response = await fetch(`${this.djangoContext.API_BASE_URL}/search/results/${currentTask}/?${params.toString()}`);
                const data = await response.json();

                if (!response.ok) throw new Error(data.error || `Failed to fetch results (HTTP ${response.status})`);

                this.searchResults = data.results_data || [];
                this.searchTotalResults = data.count || 0;
                this.searchTotalPages = data.num_pages || 0;
                this.searchCurrentPage = data.current_page || 1;
                
                if (this.searchResults.length > 0) {
                    this.searchStatusMessage = `Displaying ${this.searchResults.length} of ${this.searchTotalResults} results. (Page ${this.searchCurrentPage}/${this.searchTotalPages})`;
                    this.showGlobalNotification(`Page ${this.searchCurrentPage} loaded.`, "success", 1500);
                } else if (this.searchAttempted) {
                     this.searchStatusMessage = "No results found for your query matching the criteria.";
                     this.showGlobalNotification("No results found for this query.", "info");
                }

            } catch (error) {
                console.error("Error fetching search results:", error);
                this.searchStatusMessage = `Error fetching results: ${error.message}`;
                this.searchErrorMessage = true;
                this.showGlobalNotification(`Failed to fetch results: ${error.message}`, "error");
            } finally {
                this.searchLoading = false;
            }
        },
        
        applyFiltersAndReSearch() {
            this.showGlobalNotification("Filters changed. Re-initiating search with new criteria.", "info", 2000);
            this.initiateNewSearchTask(); // Re-initiates with current searchForm.filters
        },
        
        resetFilters() {
            this.searchForm.filters = {
                platform: [], min_duration_sec: null, max_duration_sec: null,
                upload_date_after: '', upload_date_before: '',
            };
            this.showGlobalNotification("Filters have been reset.", "info");
            if (this.searchCurrentTaskId && this.searchResults.length > 0) { // If results were visible
                this.applyFiltersAndReSearch(); // Re-search with no filters
            }
        },

        // --- Video Player Modal ---
        playVideoModal(videoResult) {
            this.videoToPlay = videoResult;
            this.showVideoModal = true;
            this.$nextTick(() => {
                if (this.modalPlayer) this.modalPlayer.destroy();
                const playerElement = document.getElementById('modal-video-player');
                if (playerElement) {
                    let sourceUrl = videoResult.primary_source_display?.embed_url || 
                                    videoResult.sources?.[0]?.embed_url ||
                                    videoResult.primary_source_display?.original_url ||
                                    videoResult.sources?.[0]?.original_url;
                    
                    let sourceType = 'video'; // Default
                    if (sourceUrl) {
                        if (sourceUrl.includes('youtube.com') || sourceUrl.includes('youtu.be')) sourceType = 'youtube';
                        else if (sourceUrl.includes('vimeo.com')) sourceType = 'vimeo';
                    }
                    
                    if (sourceUrl) {
                        this.modalPlayer = new Plyr(playerElement);
                        this.modalPlayer.source = {
                             type: 'video',
                             sources: [{
                                 src: sourceUrl,
                                 provider: (sourceType === 'youtube' || sourceType === 'vimeo') ? sourceType : undefined
                             }],
                             title: videoResult.title
                        };
                        this.modalPlayer.play();
                    } else {
                        this.showGlobalNotification("Could not load video: No valid source URL.", "error");
                    }
                }
            });
        },
        closeVideoModal() {
            if (this.modalPlayer) {
                this.modalPlayer.stop();
                this.modalPlayer.destroy();
                this.modalPlayer = null;
            }
            this.showVideoModal = false;
            this.videoToPlay = null;
        },
        seekPlayerTo(timeInSeconds) {
            if (this.modalPlayer && this.modalPlayer.ready) {
                this.modalPlayer.currentTime = timeInSeconds;
                this.modalPlayer.play();
            }
        },

        // --- AI Video Editor ---
        openAiEditor(videoResult) {
            this.currentView = 'editor'; // Switch view
            this.editorVideoSource = {
                title: videoResult.title,
                original_url: videoResult.primary_source_display?.original_url || videoResult.sources?.[0]?.original_url,
                video_source_id: videoResult.primary_source_display?.id || videoResult.sources?.[0]?.id,
                uploaded_name: null, 
                file_object: null 
            };
            this.editorPrompt = '';
            this.editedVideoUrl = null;
            this.editorStatusMessage = `Editing: ${videoResult.title.substring(0, 70)}...`;
            this.editorErrorMessage = false;
            if(this.editedPlayer) { this.editedPlayer.destroy(); this.editedPlayer = null; }
            this.showGlobalNotification(`Opened '${videoResult.title.substring(0,30)}...' in AI Editor.`, "info", 2000);
            window.location.hash = 'editor';
        },
        clearEditorVideoSource() {
            this.editorVideoSource = null;
            this.editorPrompt = '';
            this.editedVideoUrl = null;
            this.editorStatusMessage = "Video source cleared from editor.";
            this.editorProjectId = null;
            if(this.editedPlayer) { this.editedPlayer.destroy(); this.editedPlayer = null; }
        },
        handleEditorVideoUpload(event) {
            if (event.target.files.length > 0) {
                const file = event.target.files[0];
                this.editorVideoSource = {
                    title: `Uploaded: ${file.name}`,
                    uploaded_name: file.name,
                    file_object: file,
                    original_url: null,
                    video_source_id: null
                };
                this.editedVideoUrl = null; // Clear previous edited video
                this.editorStatusMessage = `Ready to edit uploaded: ${file.name}`;
                this.showGlobalNotification(`Video '${file.name}' selected for editing.`, "info");
            }
        },
        
        async initiateVideoEdit() {
            if (!this.editorVideoSource || (!this.editorVideoSource.file_object && !this.editorVideoSource.video_source_id)) {
                this.showGlobalNotification("Please select or upload a video for editing.", "error");
                return;
            }
            if (!this.editorPrompt.trim()) {
                 this.showGlobalNotification("Please provide editing instructions (prompt).", "error");
                return;
            }

            this.editorLoading = true;
            this.editorStatusMessage = "🚀 Initiating video edit project...";
            this.editorErrorMessage = false;
            this.editedVideoUrl = null;
            if(this.editedPlayer) { this.editedPlayer.destroy(); this.editedPlayer = null; }

            try {
                const projectData = new FormData();
                let projectName = "Untitled Papri Edit";
                if (this.editorVideoSource.video_source_id && this.editorVideoSource.title) { 
                    projectData.append('original_video_source_id', this.editorVideoSource.video_source_id);
                    projectName = `Edit of ${this.editorVideoSource.title.substring(0,50)}`;
                } else if (this.editorVideoSource.file_object) { 
                    projectData.append('uploaded_video_file', this.editorVideoSource.file_object, this.editorVideoSource.uploaded_name);
                    projectName = `Edit of uploaded ${this.editorVideoSource.uploaded_name.substring(0,50)}`;
                } else {
                    throw new Error("No valid video source details for creating edit project.");
                }
                projectData.append('project_name', projectName);

                const projectResponse = await fetch(this.djangoContext.API_BASE_URL + '/video_editor/projects/', {
                    method: 'POST',
                    body: projectData,
                    headers: { 'X-CSRFToken': this.getCSRFToken() }
                });
                const projectResult = await projectResponse.json();

                if (!projectResponse.ok || !projectResult.id) {
                     let errorMsg = "Failed to create video edit project.";
                     if(projectResult.detail) errorMsg = projectResult.detail;
                     else if(projectResult.uploaded_video_file && Array.isArray(projectResult.uploaded_video_file)) errorMsg = projectResult.uploaded_video_file.join(' ');
                     else if (typeof projectResult === 'object' && Object.keys(projectResult).length > 0 && Object.values(projectResult)[0]) errorMsg = JSON.stringify(projectResult);
                    throw new Error(errorMsg);
                }
                this.editorProjectId = projectResult.id;
                this.editorStatusMessage = `📝 Edit project '${projectName}' created (ID: ${this.editorProjectId}). Submitting edit task...`;
                this.showGlobalNotification("Edit project created. Submitting task...", "info", 1500);

                // Now submit the task under this project
                const taskPayload = { prompt_text: this.editorPrompt.trim() };
                const taskResponse = await fetch(`${this.djangoContext.API_BASE_URL}/video_editor/projects/${this.editorProjectId}/tasks/`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.getCSRFToken() },
                    body: JSON.stringify(taskPayload)
                });
                const taskResult = await taskResponse.json();

                if (taskResponse.ok && taskResult.id) {
                    this.editorStatusMessage = `🎞️ Edit task submitted (ID: ${taskResult.id}). Processing video... this may take a while.`;
                    this.showGlobalNotification("Edit task submitted! Processing video...", "info");
                    this.pollEditStatus(taskResult.id);
                } else {
                    throw new Error(taskResult.detail || taskResult.error || JSON.stringify(taskResult) || "Failed to submit edit task.");
                }

            } catch (error) {
                console.error("Error in video edit initiation process:", error);
                this.editorStatusMessage = `Error: ${error.message}`;
                this.editorErrorMessage = true;
                this.editorLoading = false;
                this.showGlobalNotification(`Edit initiation failed: ${error.message}`, "error");
            }
        },

        pollEditStatus(editTaskId) {
            const interval = setInterval(async () => {
                try {
                    const response = await fetch(`${this.djangoContext.API_BASE_URL}/video_editor/tasks/${editTaskId}/status/`);
                    const data = await response.json();

                    if (!response.ok) throw new Error(data.detail || data.error || "Edit status check failed.");

                    this.editorStatusMessage = `⏳ Processing status: ${data.status}. ${data.error_message || ''}`;
                    if (data.status === 'completed') {
                        clearInterval(interval);
                        this.editorLoading = false;
                        this.editedVideoUrl = data.result_url; // Full URL from backend (MEDIA_URL + path)
                        this.editorStatusMessage = "✅ Video editing completed!";
                        this.showGlobalNotification("Video editing complete! Preview available.", "success");
                        this.$nextTick(() => {
                            const playerEl = document.getElementById('edited-video-player');
                            if(playerEl && this.editedVideoUrl) {
                                if(this.editedPlayer) this.editedPlayer.destroy();
                                this.editedPlayer = new Plyr(playerEl);
                                this.editedPlayer.source = { type: 'video', sources: [{ src: this.editedVideoUrl, type: 'video/mp4' }] };
                            }
                        });
                    } else if (data.status === 'failed') {
                        clearInterval(interval);
                        this.editorLoading = false;
                        this.editorStatusMessage = `❌ Editing failed: ${data.error_message || 'Unknown error'}`;
                        this.editorErrorMessage = true;
                        this.showGlobalNotification(`Editing failed: ${data.error_message || 'Unknown error'}`, "error");
                    }
                } catch (error) {
                    console.error("Error polling edit status:", error);
                    this.editorStatusMessage = `Error polling edit status: ${error.message}`;
                    // Don't set editorErrorMessage to true for polling errors, as task might still be running.
                    this.showGlobalNotification("Error checking edit status. Will keep trying.", "warning", 2000);
                    // Consider stopping polling on specific errors or too many attempts
                }
            }, 5000); // Poll every 5 seconds
        },

        // --- Utility / Helper functions ---
        formatDuration(totalSeconds) {
            if (totalSeconds === null || totalSeconds === undefined || isNaN(totalSeconds)) return 'N/A';
            const hours = Math.floor(totalSeconds / 3600);
            const minutes = Math.floor((totalSeconds % 3600) / 60);
            const seconds = Math.floor(totalSeconds % 60);
            let formatted = '';
            if (hours > 0) formatted += `${hours}:`;
            formatted += `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
            return formatted;
        },
        formatTimestamp(ms) {
            if (ms === null || ms === undefined || isNaN(ms)) return '';
            return this.formatDuration(Math.floor(ms / 1000));
        },
        formatSimpleDate(dateString) {
            if (!dateString) return 'N/A';
            try {
                return new Date(dateString).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
            } catch (e) { return dateString; }
        },
        showGlobalNotification(message, type = 'info', duration = 4000) {
            this.globalNotification.message = message;
            this.globalNotification.type = type;
            this.globalNotification.visible = true;
            if (this.globalNotification.timeoutInstance) {
                clearTimeout(this.globalNotification.timeoutInstance);
            }
            this.globalNotification.timeoutInstance = setTimeout(() => {
                this.globalNotification.visible = false;
            }, duration);
        },
        getCSRFToken() {
            let csrfToken = null;
            const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
            if (csrfInput) {
                csrfToken = csrfInput.value;
            } else if (document.cookie && document.cookie !== '') {
                const cookies = document.cookie.split(';');
                for (let i = 0; i < cookies.length; i++) {
                    const cookie = cookies[i].trim();
                    if (cookie.substring(0, 'csrftoken'.length + 1) === ('csrftoken' + '=')) {
                        csrfToken = decodeURIComponent(cookie.substring('csrftoken'.length + 1));
                        break;
                    }
                }
            }
            return csrfToken;
        },
        // Add Collections method (placeholder)
        addToCollection(videoResult) {
            this.showGlobalNotification(`Video "${videoResult.title.substring(0,30)}..." added to collections (feature coming soon).`, "info");
            // Placeholder for actual API call
            // POST to /api/collections/add/ with video_id: videoResult.id
        }

    }));
});

console.log("PapriApp JS (refined) loaded.");
