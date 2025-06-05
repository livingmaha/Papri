// frontend/static/js/index.js

document.addEventListener('alpine:init', () => {
    Alpine.data('papriDemo', () => ({
        trialSearchesLeft: 3,
        trialBlocked: false,
        queryText: '',
        queryImage: null,
        queryImageName: '',
        demoResults: [],
        demoLoading: false,
        demoError: false, // Changed to boolean
        demoStatusMessage: '', // For user feedback
        maxDemoSearches: 3,

        // Curated demo scenarios
        curatedDemos: {
            1: { 
                queryText: "Recipe for delicious Spanish Paella", 
                queryImage: null,
                queryImageName: '', 
                mockResults: [
                    { id: 'cd1_res1', title: 'Authentic Spanish Paella Recipe (Demo)', platform_name: 'YouTube', uploader_name: 'CookingMaster', duration_str: '15:22', publication_date_str: '2024-03-10', description: 'Learn to make delicious seafood paella. PAPRI finds specific recipes easily!', thumbnail_url: 'https://source.unsplash.com/random/400x225/?paella,food&sig=1', original_url: '#' },
                    { id: 'cd1_res2', title: 'Quick Paella for Beginners (Demo)', platform_name: 'Vimeo', uploader_name: 'EasyMeals', duration_str: '08:05', publication_date_str: '2024-02-15', description: 'A simplified paella recipe perfect for weeknights. PAPRI finds videos for all skill levels.', thumbnail_url: 'https://source.unsplash.com/random/400x225/?rice,dish&sig=2', original_url: '#' }
                ]
            },
            2: { 
                queryText: "How to fix a common leaky kitchen faucet", 
                queryImage: null,
                queryImageName: '',
                mockResults: [
                    { id: 'cd2_res1', title: 'DIY: Fix Leaky Faucet in 5 Min (Demo)', platform_name: 'PeerTube', uploader_name: 'HomeFixIt', duration_str: '05:10', publication_date_str: '2023-11-20', description: 'Step-by-step guide to fixing a common leaky faucet. PAPRI finds practical tutorials quickly.', thumbnail_url: 'https://source.unsplash.com/random/400x225/?faucet,repair&sig=3', original_url: '#' }
                ]
            },
            3: { // Image-focused demo
                queryText: "Beautiful sunset over mountains", // Optional accompanying text
                queryImageName: "simulated_sunset.jpg", // Display name for simulated image
                queryImage: true, // Flag to indicate image component for mock generation
                mockResults: [
                    { id: 'cd3_res1', title: 'Mountain Sunset Timelapse (Visual Match Demo)', platform_name: 'Dailymotion', uploader_name: 'ScenicViews', duration_str: '03:45', publication_date_str: '2024-01-05', description: 'Stunning timelapse found by PAPRI based on visual similarity to a sunset image.', thumbnail_url: 'https://source.unsplash.com/random/400x225/?sunset,mountains&sig=4', original_url: '#' },
                    { id: 'cd3_res2', title: 'Painting a Mountain Sunset - Art Tutorial (Demo)', platform_name: 'YouTube', uploader_name: 'ArtCreator', duration_str: '22:10', publication_date_str: '2023-12-12', description: 'PAPRI also brings text-relevant results like this art tutorial for "sunset".', thumbnail_url: 'https://source.unsplash.com/random/400x225/?painting,landscape&sig=5', original_url: '#' }
                ]
            }
        },

        init() {
            const storedTrials = localStorage.getItem('papriDemoTrialsLeft');
            if (storedTrials !== null) {
                this.trialSearchesLeft = parseInt(storedTrials, 10);
            }
            this.checkTrialStatus();
            // No initial demo results on load, user must click a demo or search
        },

        checkTrialStatus() {
            if (this.trialSearchesLeft <= 0) {
                this.trialBlocked = true;
                this.trialSearchesLeft = 0; 
            } else {
                this.trialBlocked = false;
            }
        },
        
        useTrial(){
            if(this.trialSearchesLeft > 0 && !this.trialBlocked) {
                this.trialSearchesLeft--;
                localStorage.setItem('papriDemoTrialsLeft', this.trialSearchesLeft.toString());
                this.checkTrialStatus();
                return true; // Trial used
            }
            this.checkTrialStatus(); // Re-check in case it was already 0
            if(this.trialBlocked){
                 this.demoStatusMessage = "Demo search limit reached. Please sign up for full access.";
                 this.demoError = true;
            }
            return false; // Trial not used or limit reached
        },

        handleFileSelect(event) {
            if (event.target.files.length > 0) {
                this.queryImage = event.target.files[0]; // Store File object for potential real upload
                this.queryImageName = this.queryImage.name;
            } else {
                this.queryImage = null;
                this.queryImageName = '';
            }
        },
        
        runCuratedDemo(demoId) {
            if (!this.useTrial()) return; // Checks trial limit and decrements if available

            const demoData = this.curatedDemos[demoId];
            if (!demoData) {
                this.demoStatusMessage = "Selected demo scenario not found.";
                this.demoError = true;
                return;
            }

            this.queryText = demoData.queryText || ''; // Set query text for display/potential real search
            // For curated demos, we don't actually use queryImage File object, just simulate
            this.queryImageName = demoData.queryImageName || ''; 
            this.queryImage = null; // Clear any actual selected file for curated demo

            this.demoLoading = true;
            this.demoResults = [];
            this.demoError = false;
            this.demoStatusMessage = `Running curated demo: "${this.queryText || this.queryImageName}"...`;
            
            setTimeout(() => { // Simulate API call delay
                this.demoLoading = false;
                this.demoResults = demoData.mockResults;
                if (this.demoResults.length > 0) {
                    this.demoStatusMessage = `Showing results for curated demo: "${this.queryText || this.queryImageName}".`;
                } else {
                     this.demoStatusMessage = "Simulated: No results found for this curated demo.";
                     this.demoError = true;
                }
            }, 1200); 
        },
        
        performDemoSearch() {
            if (!this.useTrial()) return; // Checks trial limit

            if (!this.queryText.trim() && !this.queryImage) {
                this.demoStatusMessage = "Please enter a text query or select an image for custom search.";
                this.demoError = true;
                return;
            }

            this.demoLoading = true;
            this.demoResults = [];
            this.demoError = false;
            this.demoStatusMessage = 'Performing your custom demo search...';

            setTimeout(() => { // Simulate API call delay
                this.demoLoading = false;
                if (this.queryText.toLowerCase().includes("error_test_case")) {
                    this.demoStatusMessage = "Simulated error: Could not process your custom demo request.";
                    this.demoError = true;
                } else if (this.queryText.toLowerCase().includes("no_match_custom_test")) {
                    this.demoResults = [];
                    this.demoStatusMessage = "Simulated: No results found for your custom query.";
                } else {
                    this.demoResults = this.generateMockResultsForCustomSearch(this.queryText, this.queryImageName);
                     if (this.demoResults.length === 0) {
                        this.demoStatusMessage = "Simulated: No results found for your custom query.";
                    } else {
                        this.demoStatusMessage = "Displaying mock results for your custom search.";
                    }
                }
            }, 1500);
        },

        generateMockResultsForCustomSearch(query, imageName) {
            const results = [];
            const baseDesc = `This is a PAPRI demo result for your query "${query}". Image used: ${imageName || 'None'}.`;
            results.push({ 
                id: `custom_mock_${Date.now()}_1`, 
                title: `Custom Search: Finding for "${query || 'Image Search'}" (Demo)`, 
                platform_name: 'YouTube', uploader_name: 'Demo Creator', 
                duration_str: '07:42', publication_date_str: '2024-05-01', 
                description: baseDesc, 
                thumbnail_url: `https://source.unsplash.com/random/400x225/?${query.split(" ")[0] || 'abstract'}&sig=${Date.now()}`, 
                original_url: '#' 
            });
            if (Math.random() > 0.5) { // Randomly add a second result
                 results.push({ 
                    id: `custom_mock_${Date.now()}_2`, 
                    title: `Another Result for "${query}" (Demo)`, 
                    platform_name: 'Vimeo', uploader_name: 'Demo Engine', 
                    duration_str: '03:15', publication_date_str: '2024-04-15', 
                    description: `More insights from PAPRI's powerful demo search. ${baseDesc}`, 
                    thumbnail_url: `https://source.unsplash.com/random/400x225/?${query.split(" ").pop() || 'technology'}&sig=${Date.now()+1}`, 
                    original_url: '#' 
                });
            }
            return results;
        }
    }));

    // Smooth scrolling for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            const hrefAttribute = this.getAttribute('href');
            if (hrefAttribute.length > 1 && document.querySelector(hrefAttribute)) { 
                e.preventDefault();
                document.querySelector(hrefAttribute).scrollIntoView({ behavior: 'smooth' });
            }
        });
    });
});

console.log("Papri Index JS (refined) loaded.");
