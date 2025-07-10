// static/script.js
let sessionId = null;
let currentQuestion = '';
let correctAnswer = '';
let currentSkill = ''; // NEW: To store the current skill/concept
let username = '';
let score = 0;
let totalQuestions = 10; // Total questions in a quiz session
let answered = 0;       // Questions attempted
let correct = 0;        // Correct answers
let currentLevel = 1;
let heartbeatInterval; // For session timeout
let scoreChart = null; // Chart.js instance

// --- DOMContentLoaded: Ensures script runs after HTML is loaded ---
document.addEventListener("DOMContentLoaded", () => {
    // --- Get DOM Elements ---
    const startBtn = document.getElementById("start-btn");
    const submitBtn = document.getElementById("submit-btn");
    const nextBtn = document.getElementById("next-btn");
    const restartBtn = document.getElementById("restart-btn");

    // Feedback elements
    const feedbackEl = document.getElementById("feedback");
    const feedbackJudgment = document.getElementById("feedback-judgment");
    const feedbackExplanation = document.getElementById("feedback-explanation");
    const toggleExplanationBtn = document.getElementById("toggle-explanation-btn");

    // NEW: Skill/Concept display element
    const skillBadge = document.getElementById("skill-badge");

    // NEW: AI Insights elements
    const aiSummaryEl = document.getElementById("ai-summary");
    const aiRecommendationsEl = document.getElementById("ai-recommendations");

    // Settings Panel Elements
    const settingsBtn = document.getElementById("settings");
    const settingsPanel = document.getElementById("settings-panel");
    const closeSettingsBtn = document.getElementById("close-settings-btn");
    const themeOptions = document.querySelectorAll(".theme-option"); // All theme color swatches

    // --- Event Listeners ---

    // Start Quiz Button
    startBtn.addEventListener("click", async () => {
        username = document.getElementById("username").value.trim();
        const topic = document.getElementById("topic").value;

        if (!username || !topic) {
            alert("Please enter your name and select a topic to begin.");
            return;
        }

        try {
            // Disable button and show loading state
            startBtn.disabled = true;
            startBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Starting...'; // Spinner icon

            // Make API call to start the session
            const res = await fetch("/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username, topic }),
            });
            const data = await res.json();

            if (data.error) {
                throw new Error(data.error); // Propagate error for catch block
            }

            // Initialize session variables from server response
            sessionId = data.session_id;
            currentQuestion = data.question;
            correctAnswer = data.correct_answer;
            currentSkill = data.skill; // NEW: Get initial skill
            currentLevel = data.difficulty || 1; // Use difficulty from server or default to 1
            answered = 0;
            correct = 0;
            score = 0;

            // Update UI with first question
            document.getElementById("question-text").innerText = currentQuestion;
            updateDifficultyBadge(currentLevel); // Update difficulty badge color/text
            if (skillBadge) skillBadge.textContent = `Skill: ${currentSkill}`; // NEW: Display initial skill

            switchScreen("quiz-section"); // Transition to quiz screen
            updateProgress(); // Update progress bar and score display
            startHeartbeat(); // Start sending heartbeats to keep session alive

        } catch (err) {
            alert("Error starting quiz: " + err.message);
            console.error("Error starting quiz:", err); // Log error to console for debugging
        } finally {
            // Re-enable button and reset text regardless of success or failure
            startBtn.disabled = false;
            startBtn.innerHTML = '<i class="fas fa-play"></i> Start Quiz';
        }
    });

    // Submit Answer Button
    submitBtn.addEventListener("click", async () => {
        const userAnswer = document.getElementById("answer").value.trim();
        if (!userAnswer) {
            alert("Please enter your answer.");
            return;
        }
        if (!sessionId) { // Ensure session exists before submitting
            alert("Quiz session not active. Please start a new quiz.");
            return;
        }

        // Disable button and show loading state
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Checking...';

        // Hide previous feedback elements immediately
        if (feedbackEl) feedbackEl.classList.add("hidden");
        if (feedbackExplanation) feedbackExplanation.classList.add("hidden");
        if (toggleExplanationBtn) toggleExplanationBtn.classList.add("hidden");

        try {
            // Make API call to submit answer
            const res = await fetch("/answer", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    session_id: sessionId,
                    question: currentQuestion,
                    correct_answer: correctAnswer,
                    user_answer: userAnswer,
                    skill: currentSkill, // NEW: Include currentSkill in the payload
                }),
            });

            const data = await res.json();

            if (data.error) {
                throw new Error(data.error); // Propagate error
            }

            // Update client-side stats from server response
            const isCorrect = data.is_correct === true;
            correct += (isCorrect ? 1 : 0);
            answered++;
            score = data.score;
            currentLevel = data.level;

            updateProgress();
            updateDifficultyBadge(currentLevel);

            // Display feedback
            if (feedbackEl) {
                feedbackEl.classList.remove("hidden");
                feedbackEl.classList.remove("correct-feedback", "incorrect-feedback");
                feedbackEl.classList.add(isCorrect ? "correct-feedback" : "incorrect-feedback");
            }

            if (feedbackJudgment) feedbackJudgment.innerHTML = `<h3>${isCorrect ? '✅ Correct!' : '❌ Incorrect!'}</h3><p>${data.judgment_text || 'No specific judgment provided.'}</p>`;

            if (feedbackExplanation) feedbackExplanation.innerHTML = `<strong>Explanation:</strong> ${data.explanation_text || 'No detailed explanation available.'}`;

            // Show explanation toggle if there is an explanation
            if (toggleExplanationBtn) {
                if (data.explanation_text && data.explanation_text !== "No detailed explanation available.") {
                    toggleExplanationBtn.classList.remove("hidden");
                    toggleExplanationBtn.textContent = "Show Explanation";
                } else {
                    toggleExplanationBtn.classList.add("hidden");
                }
            }

            // Check if quiz is complete AFTER processing feedback
            if (data.quiz_complete) {
                generateReport(); // Go to report screen
                return; // Exit function early
            }

            // Prepare for next question
            currentQuestion = data.question;
            correctAnswer = data.correct_answer;
            currentSkill = data.skill; // NEW: Update current skill for the next question

            // Set data attributes on the next button so it knows what to load
            if (nextBtn) {
                nextBtn.dataset.nextQuestion = data.question;
                nextBtn.dataset.nextCorrectAnswer = data.correct_answer;
                nextBtn.dataset.nextSkill = data.skill; // NEW: Store next skill

                // Hide submit button, show next button
                submitBtn.classList.add("hidden");
                nextBtn.classList.remove("hidden");
            }
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fas fa-paper-plane"></i> Submit Answer';
            }

        } catch (err) {
            alert("Failed to submit answer: " + err.message);
            console.error("Submit error:", err);
            // Re-enable submit button and hide feedback on error
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fas fa-paper-plane"></i> Submit Answer';
            }
            if (feedbackEl) feedbackEl.classList.add("hidden");
            if (nextBtn) nextBtn.classList.add("hidden");
        }
    });

    // Toggle Explanation Button
    if (toggleExplanationBtn) {
        toggleExplanationBtn.addEventListener("click", () => {
            if (feedbackExplanation && feedbackExplanation.classList.contains("hidden")) {
                feedbackExplanation.classList.remove("hidden");
                toggleExplanationBtn.textContent = "Hide Explanation";
            } else if (feedbackExplanation) {
                feedbackExplanation.classList.add("hidden");
                toggleExplanationBtn.textContent = "Show Explanation";
            }
        });
    }

    // Next Question Button (manual click)
    if (nextBtn) {
        nextBtn.addEventListener("click", () => {
            // Load the next question data stored in the button's dataset
            currentQuestion = nextBtn.dataset.nextQuestion;
            correctAnswer = nextBtn.dataset.nextCorrectAnswer;
            currentSkill = nextBtn.dataset.nextSkill; // NEW: Load next skill

            const answerInput = document.getElementById("answer");
            if (answerInput) answerInput.value = '';

            const questionTextEl = document.getElementById("question-text");
            if (questionTextEl) questionTextEl.innerText = currentQuestion;

            if (skillBadge) skillBadge.textContent = `Skill: ${currentSkill}`; // NEW: Update skill badge

            // Hide feedback elements for the new question
            if (feedbackEl) feedbackEl.classList.add("hidden");
            if (feedbackJudgment) feedbackJudgment.innerHTML = '';
            if (feedbackExplanation) feedbackExplanation.innerHTML = '';
            if (feedbackExplanation) feedbackExplanation.classList.add("hidden");
            if (toggleExplanationBtn) toggleExplanationBtn.classList.add("hidden");

            if (submitBtn) submitBtn.classList.remove("hidden");
            if (nextBtn) nextBtn.classList.add("hidden");
        });
    }

    // Restart Quiz Button (on report screen)
    if (restartBtn) {
        restartBtn.addEventListener("click", () => {
            resetQuiz(); // Reset all quiz variables
            switchScreen("start-section"); // Go back to start screen
        });
    }

    // --- Settings Panel Functionality ---
    if (settingsBtn && settingsPanel && closeSettingsBtn) {
        settingsBtn.addEventListener("click", () => {
            settingsPanel.classList.add("active");
        });

        closeSettingsBtn.addEventListener("click", () => {
            settingsPanel.classList.remove("active");
        });
    }

    // Theme Selector Logic
    themeOptions.forEach(option => {
        option.addEventListener("click", () => {
            const selectedTheme = option.dataset.theme;
            applyTheme(selectedTheme);
        });
    });

    // Initialize theme on page load (from localStorage or default to 'dark')
    applyTheme(localStorage.getItem('theme') || 'dark');
}); // End DOMContentLoaded

// --- Helper Functions ---

/**
 * Switches the active screen in the UI.
 * @param {string} id The ID of the section to activate (e.g., 'start-section', 'quiz-section', 'report-section').
 */
function switchScreen(id) {
    document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
    const targetScreen = document.getElementById(id);
    if (targetScreen) {
        targetScreen.classList.add("active");
    } else {
        console.error(`Screen with ID '${id}' not found.`);
    }
}

/**
 * Updates the progress bar, question count, and score display.
 */
function updateProgress() {
    const progressBar = document.getElementById("progress-bar");
    if (progressBar) progressBar.value = answered;

    const progressText = document.getElementById("progress-text");
    if (progressText) progressText.innerText = `Question ${answered} of ${totalQuestions}`;

    const scoreText = document.getElementById("score-text");
    if (scoreText) scoreText.innerText = `Score: ${score}`;
}

/**
 * Updates the difficulty badge's text and styling.
 * @param {number} level The current difficulty level.
 */
function updateDifficultyBadge(level) {
    const badge = document.getElementById("difficulty-badge");
    if (badge) {
        badge.className = `difficulty difficulty-${level}`;
        badge.textContent = `Level ${level}`;
    }
}

/**
 * Starts a heartbeat interval to keep the server session alive.
 */
function startHeartbeat() {
    clearInterval(heartbeatInterval); // Clear any existing interval
    heartbeatInterval = setInterval(() => {
        if (sessionId) {
            fetch("/session/heartbeat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: sessionId }),
            }).catch((error) => {
                console.error("Heartbeat failed, stopping heartbeat:", error);
                clearInterval(heartbeatInterval); // Stop heartbeat on network error
            });
        }
    }, 30000); // Send heartbeat every 30 seconds
}

/**
 * Fetches and displays the quiz completion report, including AI insights.
 */
async function generateReport() {
    try {
        if (!sessionId) {
            alert("No active session to generate report.");
            return;
        }

        // Show loading state for AI insights
        const aiSummaryEl = document.getElementById("ai-summary");
        const aiRecommendationsEl = document.getElementById("ai-recommendations");
        if (aiSummaryEl) aiSummaryEl.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating AI summary...';
        if (aiRecommendationsEl) aiRecommendationsEl.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating AI recommendations...';

        const res = await fetch("/report", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessionId }),
        });
        const data = await res.json();

        if (data.error) {
            throw new Error(data.error);
        }

        // Update summary text and download link
        const summaryTextEl = document.getElementById("summary-text");
        if (summaryTextEl) summaryTextEl.innerText = `${username}, you got ${correct} out of ${totalQuestions} questions correct!`;

        const downloadReportEl = document.getElementById("download-report");
        if (downloadReportEl) downloadReportEl.href = data.report_path;

        // NEW: Populate AI Insights
        if (aiSummaryEl) aiSummaryEl.innerText = data.ai_summary || "No summary provided by AI.";
        if (aiRecommendationsEl) aiRecommendationsEl.innerText = data.ai_recommendations || "No recommendations provided by AI.";

        renderChart(); // Draw the Chart.js pie chart
        switchScreen("report-section"); // Go to report screen
        clearInterval(heartbeatInterval); // Stop heartbeat as quiz is complete

    } catch (err) {
        alert("Error generating report: " + err.message);
        console.error("Report generation error:", err);
        // Clear loading state for AI insights and show error
        const aiSummaryEl = document.getElementById("ai-summary");
        const aiRecommendationsEl = document.getElementById("ai-recommendations");
        if (aiSummaryEl) aiSummaryEl.innerText = 'Error loading AI summary.';
        if (aiRecommendationsEl) aiRecommendationsEl.innerText = 'Error loading AI recommendations.';
    }
}

/**
 * Renders or re-renders the Chart.js score distribution chart.
 */
function renderChart() {
    const ctx = document.getElementById("score-chart");
    if (!ctx) {
        console.warn("Chart canvas with ID 'score-chart' not found. Skipping chart rendering.");
        return;
    }
    const chartCtx = ctx.getContext("2d");

    if (scoreChart) {
        scoreChart.destroy();
    }

    // Get current theme colors from computed style for chart consistency
    const successColor = getComputedStyle(document.body).getPropertyValue('--success').trim();
    const dangerColor = getComputedStyle(document.body).getPropertyValue('--danger').trim();
    const textColor = getComputedStyle(document.body).getPropertyValue('--text-color').trim();

    scoreChart = new Chart(chartCtx, {
        type: 'doughnut',
        data: {
            labels: ['Correct', 'Incorrect'],
            datasets: [{
                data: [correct, totalQuestions - correct],
                backgroundColor: [successColor, dangerColor],
                hoverOffset: 10,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: textColor
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(tooltipItem) {
                            return tooltipItem.label + ': ' + tooltipItem.raw;
                        }
                    }
                }
            }
        }
    });
}

/**
 * Resets all quiz-related variables and UI elements to initial state.
 */
function resetQuiz() {
    sessionId = null;
    currentQuestion = '';
    correctAnswer = '';
    currentSkill = ''; // NEW: Reset skill
    username = '';
    score = 0;
    answered = 0;
    correct = 0;
    currentLevel = 1;
    clearInterval(heartbeatInterval);

    // Clear input fields and reset display elements
    const usernameInput = document.getElementById("username");
    if (usernameInput) usernameInput.value = '';

    const topicSelect = document.getElementById("topic");
    if (topicSelect) topicSelect.value = '';

    const answerInput = document.getElementById("answer");
    if (answerInput) answerInput.value = '';

    // Hide all feedback elements
    const feedbackEl = document.getElementById("feedback");
    const feedbackJudgment = document.getElementById("feedback-judgment");
    const feedbackExplanation = document.getElementById("feedback-explanation");
    const toggleExplanationBtn = document.getElementById("toggle-explanation-btn");

    if (feedbackEl) feedbackEl.classList.add("hidden");
    if (feedbackJudgment) feedbackJudgment.innerHTML = '';
    if (feedbackExplanation) feedbackExplanation.innerHTML = '';
    if (feedbackExplanation) feedbackExplanation.classList.add("hidden");
    if (toggleExplanationBtn) toggleExplanationBtn.classList.add("hidden");

    // Show/hide correct buttons
    const submitBtn = document.getElementById("submit-btn");
    const nextBtn = document.getElementById("next-btn");
    if (submitBtn) submitBtn.classList.remove("hidden");
    if (nextBtn) nextBtn.classList.add("hidden");

    // Reset button states
    if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="fas fa-paper-plane"></i> Submit Answer';
    }

    // NEW: Reset skill badge
    const skillBadge = document.getElementById("skill-badge");
    if (skillBadge) skillBadge.textContent = 'Skill: Loading...';

    // NEW: Reset AI insights text
    const aiSummaryEl = document.getElementById("ai-summary");
    const aiRecommendationsEl = document.getElementById("ai-recommendations");
    if (aiSummaryEl) aiSummaryEl.textContent = '';
    if (aiRecommendationsEl) aiRecommendationsEl.textContent = '';

    updateProgress();
    updateDifficultyBadge(1);

    if (scoreChart) {
        scoreChart.destroy();
        scoreChart = null;
    }
}

/**
 * Applies the selected theme to the <body> element and updates UI.
 * @param {string} themeName The name of the theme ('dark', 'light', 'purple').
 */
function applyTheme(themeName) {
    // Remove all potential theme classes from the body
    document.body.classList.remove('dark-theme', 'light-theme', 'purple-theme');

    // Add the selected theme class to the body
    document.body.classList.add(themeName + '-theme');

    // Update active state for theme options in the settings panel
    document.querySelectorAll('.theme-option').forEach(option => {
        option.classList.remove('active');
    });
    // Add 'active' class to the currently selected theme swatch
    const selectedOption = document.querySelector(`.theme-option[data-theme="${themeName}"]`);
    if (selectedOption) {
        selectedOption.classList.add('active');
    }

    // Save selected theme to localStorage for persistence
    localStorage.setItem('theme', themeName);

    // If on the report section, re-render the chart to update its colors
    const reportSection = document.getElementById('report-section');
    if (reportSection && reportSection.classList.contains('active')) {
        renderChart();
    }
}
function speakText(text) {
  if ('speechSynthesis' in window) {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1;         // Normal speed
    utterance.pitch = 1;        // Normal pitch
    utterance.lang = 'en-US';   // You can change this if needed
    speechSynthesis.cancel();   // Stop any ongoing speech
    speechSynthesis.speak(utterance);
  } else {
    alert("Sorry, your browser doesn't support text-to-speech.");
  }
}
