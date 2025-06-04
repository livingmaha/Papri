
// frontend/static/js/papriapp.js

// --- Alpine.js Data for the Main Application ---
document.addEventListener('alpine:init', () => {
    Alpine.data('papriApp', () => ({
        // --- Application State ---
        currentView: 'search', // Default view: 'search', 'history', 'collections', 'settings', 'editor'
        isLoading: false, // Global loading state for the app if needed
        isSidebarOpen: false, // For mobile sidebar
        authenticatedUser: null, // Stores user details { email, username, profile: { subscription_plan, ... } }
        
        // --- Django Context (from backend) ---
        djangoContext: {}, // Will be populated from <script id="django-context">

        // --- Search View State ---
        searchForm: {
            query_text: '',
            query_image: null, // File object
            query_image_name: '',
            query_video_url: '',
            filters: {
                platform: [], // Array of selected platform names
                min_duration_sec: null,
                max_duration_sec: null,
                upload_date_after: '',
                upload_date_before: '',
                // sort_by: 'relevance' // Example
            }
        },
        searchLoading: false,
        searchStatusMessage: '',
        searchErrorMessage: false, // True if status message is an error
        searchResults: [],
        searchCurrentTaskId: null,
        searchPollingInterval: null,
        searchTotalResults: 0,
        searchTotalPages: 0,
        searchCurrentPage: 1,
        searchAttempted: false, // To show "no results" message only after a search

        // --- Video Player Modal State ---
        showVideoModal: false,
        videoToPlay: null, // Object of the video to play in modal
        modalPlayer: null, // Plyr instance for the modal

        // --- AI Video Editor State ---
        editorVideoSource: null, // { title, original_url, video_source_id (from Papri), uploaded_name, file_object }
        editorPrompt: '',
        editorLoading: false,
        editorStatusMessage: '',
        editorErrorMessage: false,
        editedVideoUrl: null, // URL of the processed video
        editedPlayer: null, // Plyr instance for the edited video

        // --- Global Notification ---
        globalNotification: {
            visible: false,
            message: '',
            type: 'info', // 'info', 'success', 'error'
            timeoutInstance: null
        },

        // --- Initialization ---
        initializeApplication() {
            this.loadDjangoContext();
            this.fetchAuthStatus(); // Check if user is logged in
            this.handleHashChange(); // Set initial view based on URL hash
            window.addEventListener('popstate', () => this.handleHashChange()); // Handle browser back/forward
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
                    this.authenticatedUser.profile = data.profile; // Attach profile data
                    console.log("User authenticated:", this.authenticatedUser);
                } else {
                    this.authenticatedUser = null;
                    console.log("User not authenticated.");
                    // Redirect to login if not authenticated and trying to access app?
                    // window.location.href = '/accounts/login/';
                }
            } catch (error) {
                console.error("Error fetching auth status:", error);
                this.showGlobalNotification("Could not verify authentication status.", "error");
                // this.authenticatedUser = null; // Assume not authenticated on error
            }
        },

        logoutUser() {
            // Assuming Django allauth handles logout via a GET request to /accounts/logout/
            // For DRF, if using token auth, you'd call a /api/auth/logout/ endpoint.
            window.location.href = '/accounts/logout/';
        },
        
        // --- Routing ---
        handleHashChange() {
            const hash = window.location.hash.substring(1) || 'search';
            if (['search', 'history', 'collections', 'settings', 'editor'].includes(hash)) {
                this.currentView = hash;
            } else {
                this.currentView = 'search'; // Default to search if hash is invalid
            }
            // Scroll to top of main content on view change
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
                this.searchStatusMessage = "Please provide a text query, an image, or a video URL to search.";
                this.searchErrorMessage = true;
                return;
            }
            this.searchLoading = true;
            this.searchAttempted = true;
            this.searchStatusMessage = "Initiating search...";
            this.searchErrorMessage = false;
            this.searchResults = [];
            this.searchCurrentTaskId = null;
            if (this.searchPollingInterval) clearInterval(this.searchPollingInterval);

            const formData = new FormData();
            if (this.searchForm.query_text.trim()) formData.append('query_text', this.searchForm.query_text.trim());
            if (this.searchForm.query_image) formData.append('query_image', this.searchForm.query_image);
            if (this.searchForm.query_video_url.trim()) formData.append('query_video_url', this.searchForm.query_video_url.trim());
            
            // Clean up filters: remove null/empty values before sending
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
                    headers: { 'X-CSRFToken': this.getCSRFToken() } // If CSRF needed for POSTs
                });
                const data = await response.json();

                if (response.ok && data.id) {
                    this.searchCurrentTaskId = data.id;
                    this.searchStatusMessage = `Search task started (ID: ${data.id}). Polling for status...`;
                    this.startPollingSearchStatus(data.id);
                } else {
                    throw new Error(data.error || `Failed to initiate search (status ${response.status})`);
                }
            } catch (error) {
                console.error("Error initiating search task:", error);
                this.searchStatusMessage = `Error: ${error.message}`;
                this.searchErrorMessage = true;
                this.searchLoading = false;
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

                    this.searchStatusMessage = `Status: ${data.status || 'Unknown'}. ${data.error_message || ''}`;
                    if (data.status === 'completed' || data.status === 'partial_results') {
                        clearInterval(this.searchPollingInterval);
                        this.searchLoading = false;
                        this.searchStatusMessage = `Search ${data.status}. Fetching results...`;
                        this.fetchResultsPage(1, taskId); // Fetch first page of results
                    } else if (data.status === 'failed') {
                        clearInterval(this.searchPollingInterval);
                        this.searchLoading = false;
                        this.searchStatusMessage = `Search failed: ${data.error_message || 'Unknown error'}`;
                        this.searchErrorMessage = true;
                    }
                    // Continue polling if 'pending' or 'processing'
                } catch (error) {
                    console.error("Error polling search status:", error);
                    this.searchStatusMessage = `Error polling status: ${error.message}`;
                    this.searchErrorMessage = true;
                    // Optional: Stop polling on repeated errors
                    // clearInterval(this.searchPollingInterval);
                    // this.searchLoading = false;
                }
            }, 3000); // Poll every 3 seconds
        },

        async fetchResultsPage(pageNumber, taskId = null) {
            const currentTask = taskId || this.searchCurrentTaskId;
            if (!currentTask) return;

            this.searchLoading = true; // Indicate loading for results fetch
            this.searchStatusMessage = `Fetching results page ${pageNumber}...`;
            this.searchErrorMessage = false;

            try {
                // Add pagination and filter params to results URL if API supports it
                const params = new URLSearchParams({ page: pageNumber });
                // Example: if API supports passing filters to results endpoint too
                // for (const key in this.searchForm.filters) { ... params.append(`filter_${key}`, value) ... }

                const response = await fetch(`${this.djangoContext.API_BASE_URL}/search/results/${currentTask}/?${params.toString()}`);
                const data = await response.json();

                if (!response.ok) throw new Error(data.error || `Failed to fetch results (HTTP ${response.status})`);

                this.searchResults = data.results_data || [];
                this.searchTotalResults = data.count || 0;
                this.searchTotalPages = data.num_pages || 0;
                this.searchCurrentPage = data.current_page || 1;
                this.searchStatusMessage = `Displaying ${this.searchResults.length} of ${this.searchTotalResults} results. (Page ${this.searchCurrentPage}/${this.searchTotalPages})`;
                if (this.searchResults.length === 0 && this.searchAttempted) {
                     this.searchStatusMessage = "No results found for your query.";
                }

            } catch (error) {
                console.error("Error fetching search results:", error);
                this.searchStatusMessage = `Error fetching results: ${error.message}`;
                this.searchErrorMessage = true;
            } finally {
                this.searchLoading = false;
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
                    // Determine source URL: prefer embed_url from VideoSource if available
                    let sourceUrl = videoResult.primary_source_display?.embed_url || 
                                    videoResult.sources?.[0]?.embed_url ||
                                    videoResult.primary_source_display?.original_url ||
                                    videoResult.sources?.[0]?.original_url;
                    
                    // Basic type detection for Plyr
                    let sourceType = 'video'; // Default
                    if (sourceUrl) {
                        if (sourceUrl.includes('youtube.com') || sourceUrl.includes('youtu.be')) sourceType = 'youtube';
                        else if (sourceUrl.includes('vimeo.com')) sourceType = 'vimeo';
                    }
                    
                    if (sourceUrl) {
                        playerElement.src = sourceUrl; // For HTML5 video element if not using Plyr's provider
                        this.modalPlayer = new Plyr(playerElement, {
                            // Plyr options
                            // If using YouTube/Vimeo, Plyr handles it if given the video page URL
                            // For direct mp4, it just works.
                        });
                        // If source is not a direct video file but a page URL (youtube/vimeo)
                        // Plyr's 'source' setter handles this well:
                         this.modalPlayer.source = {
                             type: 'video', // HTML5 video
                             sources: [{
                                 src: sourceUrl,
                                 provider: (sourceType === 'youtube' || sourceType === 'vimeo') ? sourceType : undefined
                             }],
                             title: videoResult.title
                         };
                        this.modalPlayer.play();
                    } else {
                        console.error("No valid video URL found for modal player:", videoResult);
                        this.showGlobalNotification("Could not load video: No valid source URL.", "error");
                    }
                }
            });
        },
        closeVideoModal() {
            if (this.modalPlayer) {
                this.modalPlayer.stop();
                this.modalPlayer.destroy(); // Important to clean up Plyr instance
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
            this.currentView = 'editor';
            this.editorVideoSource = {
                title: videoResult.title,
                original_url: videoResult.primary_source_display?.original_url || videoResult.sources?.[0]?.original_url,
                video_source_id: videoResult.primary_source_display?.id || videoResult.sources?.[0]?.id, // Papri VideoSource ID
                // If direct upload, this would be different.
                uploaded_name: null, 
                file_object: null 
            };
            this.editorPrompt = '';
            this.editedVideoUrl = null;
            this.editorStatusMessage = `Selected video: ${videoResult.title}`;
            this.editorErrorMessage = false;
            if(this.editedPlayer) { this.editedPlayer.destroy(); this.editedPlayer = null; }
            window.location.hash = 'editor'; // Update hash
        },
        clearEditorVideoSource() {
            this.editorVideoSource = null;
            this.editorPrompt = '';
            this.editedVideoUrl = null;
             if(this.editedPlayer) { this.editedPlayer.destroy(); this.editedPlayer = null; }
        },
        handleEditorVideoUpload(event) {
            if (event.target.files.length > 0) {
                const file = event.target.files[0];
                this.editorVideoSource = {
                    title: `Uploaded: ${file.name}`,
                    uploaded_name: file.name,
                    file_object: file, // Store the File object for upload
                    original_url: null,
                    video_source_id: null
                };
                this.editedVideoUrl = null;
                this.editorStatusMessage = `Selected uploaded video: ${file.name}`;
                this.editorErrorMessage = false;
            }
        },
        async initiateVideoEdit() {
            if (!this.editorVideoSource || !this.editorPrompt.trim()) {
                this.editorStatusMessage = "Please select a video and provide editing instructions.";
                this.editorErrorMessage = true;
                return;
            }
            this.editorLoading = true;
            this.editorStatusMessage = "Initiating video edit...";
            this.editorErrorMessage = false;
            this.editedVideoUrl = null;
            if(this.editedPlayer) { this.editedPlayer.destroy(); this.editedPlayer = null; }


            const formData = new FormData();
            formData.append('prompt_text', this.editorPrompt.trim());

            let projectId = null;

            // Step 1: Create/Ensure VideoEditProject
            try {
                const projectData = new FormData();
                if (this.editorVideoSource.video_source_id) { // From search results
                    projectData.append('original_video_source_id', this.editorVideoSource.video_source_id);
                    projectData.append('project_name', `Edit of ${this.editorVideoSource.title.substring(0,50)}`);
                } else if (this.editorVideoSource.file_object) { // User uploaded file
                    projectData.append('uploaded_video_file', this.editorVideoSource.file_object, this.editorVideoSource.uploaded_name);
                    projectData.append('project_name', `Edit of uploaded ${this.editorVideoSource.uploaded_name.substring(0,50)}`);
                } else {
                    throw new Error("No valid video source for project.");
                }

                const projectResponse = await fetch(this.djangoContext.API_BASE_URL + '/video_editor/projects/', {
                    method: 'POST',
                    body: projectData,
                    headers: { 'X-CSRFToken': this.getCSRFToken() }
                });
                const projectResult = await projectResponse.json();
                if (!projectResponse.ok || !projectResult.id) {
                    throw new Error(projectResult.detail || projectResult.error || "Failed to create video edit project.");
                }
                projectId = projectResult.id;
                this.editorStatusMessage = `Edit project created (ID: ${projectId}). Submitting edit task...`;

            } catch (error) {
                 console.error("Error creating video edit project:", error);
                this.editorStatusMessage = `Error creating project: ${error.message}`;
                this.editorErrorMessage = true;
                this.editorLoading = false;
                return;
            }
            
            // Step 2: Create EditTask under the project
            if (projectId) {
                try {
                     const taskPayload = { prompt_text: this.editorPrompt.trim() };
                     const taskResponse = await fetch(`${this.djangoContext.API_BASE_URL}/video_editor/projects/${projectId}/tasks/`, {
                        method: 'POST',
                        headers: { 
                            'Content-Type': 'application/json',
                            'X-CSRFToken': this.getCSRFToken() 
                        },
                        body: JSON.stringify(taskPayload)
                    });
                    const taskResult = await taskResponse.json();

                    if (taskResponse.ok && taskResult.id) {
                        this.editorStatusMessage = `Edit task submitted (ID: ${taskResult.id}). Processing...`;
                        this.pollEditStatus(taskResult.id);
                    } else {
                        throw new Error(taskResult.detail || taskResult.error || "Failed to submit edit task.");
                    }
                } catch (error) {
                    console.error("Error submitting edit task:", error);
                    this.editorStatusMessage = `Error submitting task: ${error.message}`;
                    this.editorErrorMessage = true;
                    this.editorLoading = false;
                }
            }
        },

        pollEditStatus(editTaskId) {
            const interval = setInterval(async () => {
                try {
                    const response = await fetch(`${this.djangoContext.API_BASE_URL}/video_editor/tasks/${editTaskId}/status/`);
                    const data = await response.json();

                    if (!response.ok) throw new Error(data.detail || data.error || "Status check failed.");

                    this.editorStatusMessage = `Processing status: ${data.status}. ${data.error_message || ''}`;
                    if (data.status === 'completed') {
                        clearInterval(interval);
                        this.editorLoading = false;
                        this.editedVideoUrl = data.result_url; // This should be full URL from backend (MEDIA_URL + path)
                        this.editorStatusMessage = "Video editing completed!";
                        this.$nextTick(() => {
                            const playerEl = document.getElementById('edited-video-player');
                            if(playerEl && this.editedVideoUrl) {
                                if(this.editedPlayer) this.editedPlayer.destroy();
                                playerEl.src = this.editedVideoUrl; // For HTML5 video
                                this.editedPlayer = new Plyr(playerEl);
                                // this.editedPlayer.source = { type: 'video', sources: [{ src: this.editedVideoUrl }] };
                            }
                        });
                    } else if (data.status === 'failed') {
                        clearInterval(interval);
                        this.editorLoading = false;
                        this.editorStatusMessage = `Editing failed: ${data.error_message || 'Unknown error'}`;
                        this.editorErrorMessage = true;
                    }
                } catch (error) {
                    console.error("Error polling edit status:", error);
                    this.editorStatusMessage = `Error polling status: ${error.message}`;
                    this.editorErrorMessage = true;
                    // Consider stopping polling on repeated errors
                    // clearInterval(interval);
                    // this.editorLoading = false;
                }
            }, 5000); // Poll every 5 seconds
        },

        // --- Utility / Helper functions ---
        formatDuration(totalSeconds) {
            if (totalSeconds === null || totalSeconds === undefined) return 'N/A';
            const hours = Math.floor(totalSeconds / 3600);
            const minutes = Math.floor((totalSeconds % 3600) / 60);
            const seconds = Math.floor(totalSeconds % 60);
            let formatted = '';
            if (hours > 0) formatted += `${hours}:`;
            formatted += `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
            return formatted;
        },
        formatTimestamp(ms) {
            if (ms === null || ms === undefined) return '';
            const totalSeconds = Math.floor(ms / 1000);
            return this.formatDuration(totalSeconds); // Reuse duration formatter
        },
         formatSimpleDate(dateString) {
            if (!dateString) return 'N/A';
            try {
                return new Date(dateString).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
            } catch (e) {
                return dateString; // Return original if parsing fails
            }
        },
        showGlobalNotification(message, type = 'info', duration = 3000) {
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
        getCSRFToken() { // Standard Django CSRF token getter
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
            // console.debug("CSRF Token found:", csrfToken);
            return csrfToken;
        }

    }));
});

// Initialize Plyr for any existing players on page load (not strictly necessary if only creating dynamically)
// document.addEventListener('DOMContentLoaded', () => {
//   const players = Plyr.setup('.plyr-instance'); // If you have static Plyr instances
// });

console.log("PapriApp JS loaded.");
