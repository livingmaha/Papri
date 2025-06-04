// frontend/static/js/index.js

// Alpine.js component for the Demo Section
document.addEventListener('alpine:init', () => {
    Alpine.data('papriDemo', () => ({
        trialSearchesLeft: 3, // Initial trial searches
        trialBlocked: false,
        queryText: '',
        queryImage: null,
        queryImageName: '',
        demoResults: [],
        demoLoading: false,
        demoError: '',
        maxDemoSearches: 3, // Should match the display

        init() {
            // Load trial count from localStorage
            const storedTrials = localStorage.getItem('papriDemoTrialsLeft');
            if (storedTrials !== null) {
                this.trialSearchesLeft = parseInt(storedTrials, 10);
            }
            this.checkTrialStatus();
            
            // Populate with some initial placeholder "trending" or example results
            this.populateInitialDemoResults();
        },

        checkTrialStatus() {
            if (this.trialSearchesLeft <= 0) {
                this.trialBlocked = true;
                this.trialSearchesLeft = 0; // Ensure it doesn't go negative on display
            } else {
                this.trialBlocked = false;
            }
        },

        handleFileSelect(event) {
            if (event.target.files.length > 0) {
                this.queryImage = event.target.files[0];
                this.queryImageName = this.queryImage.name;
            } else {
                this.queryImage = null;
                this.queryImageName = '';
            }
        },

        performDemoSearch() {
            if (this.trialBlocked) {
                this.demoError = "Demo search limit reached. Please sign up for full access.";
                return;
            }
            if (!this.queryText.trim() && !this.queryImage) {
                this.demoError = "Please enter a text query or select an image.";
                return;
            }

            this.demoLoading = true;
            this.demoResults = [];
            this.demoError = '';

            // Decrement trial count
            this.trialSearchesLeft--;
            localStorage.setItem('papriDemoTrialsLeft', this.trialSearchesLeft.toString());
            this.checkTrialStatus();

            // Simulate API call
            setTimeout(() => {
                this.demoLoading = false;
                if (this.queryText.toLowerCase().includes("error")) {
                    this.demoError = "Simulated error: Could not process your demo request.";
                } else if (this.queryText.toLowerCase().includes("no result")) {
                    this.demoResults = []; // Show no results
                } else {
                    // Generate mock results based on query or image
                    this.demoResults = this.generateMockResults(this.queryText, this.queryImageName);
                }
            }, 1500);
        },
        
        populateInitialDemoResults() {
            // These could be fetched from a static JSON or hardcoded examples
             this.demoResults = [
                {
                    id: 'demo1',
                    title: 'Exploring Ancient Ruins in Greece (Demo)',
                    platform_name: 'YouTube',
                    uploader_name: 'TravelExplorer',
                    duration_str: '12:35',
                    publication_date_str: '2024-05-10',
                    description: 'A breathtaking journey through historical sites and ancient wonders of Greece. This is a sample result for the Papri demo.',
                    thumbnail_url: 'https://source.unsplash.com/random/400x225?ruins,greece', // Placeholder
                    original_url: '#'
                },
                {
                    id: 'demo2',
                    title: 'The Art of Wildlife Photography (Demo)',
                    platform_name: 'Vimeo',
                    uploader_name: 'NatureLens',
                    duration_str: '08:17',
                    publication_date_str: '2024-04-22',
                    description: 'Learn tips and tricks for capturing stunning wildlife photos. This demonstrates Papri\'s diverse content discovery.',
                    thumbnail_url: 'https://source.unsplash.com/random/400x225?wildlife,camera', // Placeholder
                    original_url: '#'
                }
            ];
        },

        generateMockResults(query, imageName) {
            const baseResults = [
                {
                    id: 'mock1',
                    title: `Search result for "${query || 'your query'}" (Demo)`,
                    platform_name: 'YouTube',
                    uploader_name: 'Demo Channel',
                    duration_str: '05:30',
                    publication_date_str: '2024-01-15',
                    description: `This is a simulated search result. Papri's AI would find much more relevant content across many platforms. Image searched: ${imageName || 'None'}.`,
                    thumbnail_url: 'https://source.unsplash.com/random/400x225?technology',
                    original_url: '#'
                },
                {
                    id: 'mock2',
                    title: `Another finding for "${query || 'your topic'}" (Demo)`,
                    platform_name: 'PeerTube',
                    uploader_name: 'OpenContentOrg',
                    duration_str: '15:00',
                    publication_date_str: '2023-11-02',
                    description: 'Deep dive into the subject matter you searched for, demonstrating Papri finding niche content.',
                    thumbnail_url: 'https://source.unsplash.com/random/400x225?nature',
                    original_url: '#'
                }
            ];
            if (imageName) {
                 baseResults.push({
                    id: 'mock_img',
                    title: `Visual match for ${imageName} (Demo)`,
                    platform_name: 'Dailymotion',
                    uploader_name: 'VisualSearcher',
                    duration_str: '02:10',
                    publication_date_str: '2024-03-01',
                    description: 'This video was found based on visual similarity to your uploaded image. PAPRI can search by screenshot!',
                    thumbnail_url: 'https://source.unsplash.com/random/400x225?abstract',
                    original_url: '#'
                 });
            }
            // Simple filter: if query includes 'cat', add a cat video
            if (query && query.toLowerCase().includes('cat')) {
                baseResults.unshift({
                    id: 'mock_cat',
                    title: 'Funny Cat Antics (Demo Special for "cat" query!)',
                    platform_name: 'YouTube',
                    uploader_name: 'CatLover101',
                    duration_str: '03:45',
                    publication_date_str: '2024-06-01',
                    description: 'A collection of hilarious cat moments found by PAPRI because you searched for cats!',
                    thumbnail_url: 'https://source.unsplash.com/random/400x225?cat,funny',
                    original_url: '#'
                });
            }
            return baseResults.slice(0, Math.floor(Math.random() * 2) + 1); // Return 1 or 2 results randomly
        }
    }));

    // FAQ Accordion (already handled by Alpine.js x-data="{ openFAQ: null }" in HTML)
    // Mobile menu toggle (already handled by Alpine.js x-data="{ isMobileMenuOpen: false }" in HTML)
});

// Smooth scrolling for anchor links (optional, CSS scroll-behavior is often enough)
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        const hrefAttribute = this.getAttribute('href');
        // Ensure it's not just a hash for Alpine.js navigation within the page itself
        if (hrefAttribute.length > 1 && document.querySelector(hrefAttribute)) { 
            e.preventDefault();
            document.querySelector(hrefAttribute).scrollIntoView({
                behavior: 'smooth'
            });
        }
    });
});

// Initialize Plyr.js for any video players on the landing page if needed (e.g., in a "How it Works" video)
// const player = new Plyr('#player_id_on_landing_page'); // Example
