document.addEventListener('DOMContentLoaded', () => {
    // DOM elements
    const form = document.getElementById('playlistForm');
    const skeletonState = document.getElementById('skeletonState');
    const results = document.getElementById('results');
    const playlistName = document.getElementById('playlistName');
    const tracksList = document.getElementById('tracksList');
    const trackCount = document.getElementById('trackCount');
    const plexLink = document.getElementById('plexLink');
    const errorMessage = document.getElementById('errorMessage');
    const errorText = document.getElementById('errorText');
    const dismissError = document.getElementById('dismissError');
    const llmProviderSelect = document.getElementById('llmProvider');
    const submitBtn = document.getElementById('submitBtn');
    const submitSpinner = document.getElementById('submitSpinner');
    const submitBtnText = document.getElementById('submitBtnText');

    // Library stats elements
    const libraryStats = document.getElementById('libraryStats');
    const statArtists = document.getElementById('statArtists');
    const statAlbums = document.getElementById('statAlbums');
    const statTracks = document.getElementById('statTracks');
    const refreshBtn = document.getElementById('refreshBtn');
    const refreshIcon = document.getElementById('refreshIcon');

    // LLM providers
    let providers = [];

    // Fetch available LLM providers
    async function fetchProviders() {
        try {
            const response = await fetch('/providers');
            if (!response.ok) {
                throw new Error('Failed to fetch providers');
            }
            providers = await response.json();

            // Populate the dropdown
            llmProviderSelect.innerHTML = '';

            if (providers.length === 0) {
                llmProviderSelect.innerHTML = '<option value="" disabled selected>No providers configured</option>';
                return;
            }

            providers.forEach((provider, index) => {
                const option = document.createElement('option');
                option.value = provider.model;
                option.textContent = `${provider.name} - ${provider.description}`;
                if (index === 0) {
                    option.selected = true;
                }
                llmProviderSelect.appendChild(option);
            });
        } catch (error) {
            console.error('Error fetching providers:', error);
            llmProviderSelect.innerHTML = '<option value="" disabled selected>Error loading providers</option>';
        }
    }

    // Fetch library stats
    async function fetchLibraryStats() {
        try {
            const response = await fetch('/stats');
            if (!response.ok) {
                throw new Error('Failed to fetch library stats');
            }
            const stats = await response.json();

            // Remove skeleton classes and set content
            const skeletonClasses = ['w-8', 'w-10', 'h-4', 'bg-gray-200', 'dark:bg-plex-gray', 'rounded', 'animate-pulse'];
            [statArtists, statAlbums, statTracks].forEach(el => {
                skeletonClasses.forEach(cls => el.classList.remove(cls));
            });

            statArtists.textContent = stats.artists.toLocaleString();
            statAlbums.textContent = stats.albums.toLocaleString();
            statTracks.textContent = stats.tracks.toLocaleString();
        } catch (error) {
            console.error('Error fetching library stats:', error);
            // Hide stats on error
            libraryStats.classList.add('hidden');
        }
    }

    // Refresh library cache
    async function refreshLibraryCache() {
        refreshBtn.disabled = true;
        refreshIcon.classList.add('animate-spin');

        try {
            const response = await fetch('/refresh', { method: 'POST' });
            if (!response.ok) {
                throw new Error('Failed to refresh cache');
            }
            const data = await response.json();

            // Update stats with new values
            statArtists.textContent = data.stats.artists.toLocaleString();
            statAlbums.textContent = data.stats.albums.toLocaleString();
            statTracks.textContent = data.stats.tracks.toLocaleString();
        } catch (error) {
            console.error('Error refreshing cache:', error);
        } finally {
            refreshBtn.disabled = false;
            refreshIcon.classList.remove('animate-spin');
        }
    }

    // Refresh button click handler
    refreshBtn.addEventListener('click', refreshLibraryCache);

    // Fetch providers and stats on page load
    fetchProviders();
    fetchLibraryStats();

    // Playlist length handling
    const lengthButtons = document.querySelectorAll('.playlist-length-btn');
    let selectedLength = 'medium'; // Default length

    const lengthConfigs = {
        short: { min: 20, max: 40 },
        medium: { min: 50, max: 70 },
        long: { min: 100, max: 140 }
    };

    function setActiveLength(length) {
        selectedLength = length;
        lengthButtons.forEach(btn => {
            const isActive = btn.dataset.length === length;
            // Reset all buttons first
            btn.classList.remove('border-plex-accent', 'border-gray-300', 'bg-plex-accent/10', 'dark:bg-plex-accent/20', 'dark:border-plex-gray');
            // Add appropriate styles
            if (isActive) {
                btn.classList.add('border-plex-accent', 'bg-plex-accent/10', 'dark:bg-plex-accent/20');
            } else {
                btn.classList.add('border-gray-300', 'dark:border-plex-gray');
            }
        });
    }

    // Set initial selection
    setActiveLength(selectedLength);

    // Handle button clicks
    lengthButtons.forEach(button => {
        button.addEventListener('click', () => {
            setActiveLength(button.dataset.length);
        });
    });

    // Error handling
    function showError(message) {
        // Make sure error elements exist
        if (!errorMessage || !errorText) {
            console.error('Error elements not found in DOM');
            alert(message); // Fallback to alert if error elements don't exist
            return;
        }

        errorText.textContent = message;
        errorMessage.classList.remove('hidden');
        // Scroll error into view smoothly
        errorMessage.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function hideError() {
        if (errorMessage) {
            errorMessage.classList.add('hidden');
        }
    }

    // Add error dismiss handler if element exists
    if (dismissError) {
        dismissError.addEventListener('click', hideError);
    }

    // Loading state helpers
    function setLoading(isLoading) {
        if (isLoading) {
            submitBtn.disabled = true;
            submitSpinner.classList.remove('hidden');
            submitBtnText.textContent = 'Generating...';
            skeletonState.classList.remove('hidden');
            results.classList.add('hidden');
        } else {
            submitBtn.disabled = false;
            submitSpinner.classList.add('hidden');
            submitBtnText.textContent = 'Generate Playlist';
            skeletonState.classList.add('hidden');
        }
    }

    // Handle form submission
    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        // Show loading state
        setLoading(true);
        hideError(); // Hide any previous errors

        // Get form data
        const prompt = document.getElementById('prompt').value;
        const { min, max } = lengthConfigs[selectedLength];
        const selectedModel = llmProviderSelect.value;

        if (!selectedModel) {
            showError('Please select an AI provider');
            setLoading(false);
            return;
        }

        try {
            const response = await fetch('/recommendations', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    prompt,
                    model: selectedModel,
                    min_tracks: min,
                    max_tracks: max
                }),
            });

            let errorMessage;
            if (!response.ok) {
                const contentType = response.headers.get("content-type");
                if (contentType && contentType.includes("application/json")) {
                    const errorData = await response.json();
                    errorMessage = errorData.detail || `HTTP error! status: ${response.status}`;
                } else {
                    const textError = await response.text();
                    errorMessage = textError || `HTTP error! status: ${response.status}`;
                }
                throw new Error(errorMessage);
            }

            const data = await response.json();

            if (!data.tracks || !Array.isArray(data.tracks)) {
                throw new Error('Invalid response format: missing tracks data');
            }

            // Update UI with results
            playlistName.textContent = data.name;
            trackCount.textContent = `${data.track_count} tracks`;

            // Render tracks list
            tracksList.innerHTML = data.tracks
                .map((track, index) => `
                    <li class="py-3 flex items-center space-x-4 hover:bg-gray-50 dark:hover:bg-plex-gray/50 px-4 -mx-4">
                        <span class="text-gray-400 dark:text-gray-500 w-8">${index + 1}</span>
                        <div class="min-w-0 flex-1">
                            <p class="text-sm font-medium text-plex-gray dark:text-white truncate">${track.title}</p>
                            <p class="text-sm text-gray-500 dark:text-gray-400 truncate">${track.artist}</p>
                        </div>
                    </li>
                `)
                .join('');

            // Update Plex link if ID is available
            if (data.id && data.machine_identifier) {
                plexLink.href = `https://app.plex.tv/desktop/#!/server/${data.machine_identifier}/playlist?key=/playlists/${data.id}&context=source:content.playlists`;
            }

            // Show results
            setLoading(false);
            results.classList.remove('hidden');
            // Scroll results into view
            results.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

        } catch (error) {
            console.error('Error:', error);
            showError(error.message || 'Failed to generate playlist. Please try again.');
            setLoading(false);
        }
    });
});
