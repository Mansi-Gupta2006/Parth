from flask import Flask, render_template, request, jsonify
import google.generativeai as genai
import uuid, os, logging, time
from datetime import datetime, timedelta
# Import all necessary functions from utils
from utils import get_question, evaluate_answer, record_response, generate_report, get_math_concepts 
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configure Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    logger.error("GEMINI_API_KEY is not set in environment variables or .env file. Please set it to run the application.")
    # In production, you might raise an error here. For development, a fallback.
    # We will initialize with a dummy key or let genai.configure handle the error.
    # For now, let's ensure it attempts to configure to catch issues early.
    genai.configure(api_key="dummy_key_if_not_set") # A dummy key to allow the line to execute. Real API calls will fail.
else:
    genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel("gemini-1.5-flash") # Using 1.5-flash for speed/cost

# Create Flask app
app = Flask(__name__)

# Rate limiting for API endpoints to prevent abuse and manage quota
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["5 per second", "30 per minute"]
)

# In-memory session store (for simplicity, consider a database for production)
SESSIONS = {}
SESSION_BACKUPS = {} # Simple in-memory backup for recovery

# --- Session Management Functions ---
def cleanup_sessions():
    """Removes expired sessions (inactive for more than 30 minutes)."""
    now = datetime.now()
    expired_sids = [sid for sid, sess in SESSIONS.items()
                    if now - sess["last_activity"] > timedelta(minutes=30)]
    for sid in expired_sids:
        logger.info(f"Cleaning up expired session: {sid}")
        del SESSIONS[sid]
        if sid in SESSION_BACKUPS:
            del SESSION_BACKUPS[sid]

def backup_session(session_id):
    """Creates a deep copy backup of a session to prevent data corruption."""
    if session_id in SESSIONS:
        import copy
        SESSION_BACKUPS[session_id] = copy.deepcopy(SESSIONS[session_id])
        logger.debug(f"Backed up session: {session_id}")

def get_session_backup(session_id):
    """Retrieves a session backup."""
    return SESSION_BACKUPS.get(session_id)

def recover_session(session_id):
    """Recovers a session from backup if the primary is lost/expired."""
    if session_id in SESSIONS:
        return SESSIONS[session_id]
    backup = get_session_backup(session_id)
    if backup:
        import copy
        SESSIONS[session_id] = copy.deepcopy(backup) # Restore with deep copy
        logger.info(f"Recovered session: {session_id}")
        return SESSIONS[session_id]
    logger.warning(f"Could not recover session: {session_id}")
    return None

# --- Flask Routes ---
@app.route("/")
def index():
    """Renders the main quiz application page."""
    return render_template("index.html")

@app.route("/start", methods=["POST"])
@limiter.limit("3 per minute") # Limit quiz starts
def start():
    """Handles the start of a new quiz session."""
    try:
        data = request.json
        topic = data.get("topic")
        username = data.get("username")

        if not topic or not username:
            logger.warning("Missing topic or username in /start request.")
            return jsonify({"error": "Topic and username are required"}), 400

        session_id = str(uuid.uuid4())
        
        concepts = get_math_concepts(model, topic) # Pass model
        if not concepts:
            logger.error(f"Failed to generate concepts for session {session_id}: No concepts returned. Check AI model response.")
            return jsonify({"error": "Failed to initialize quiz concepts. Please try again."}), 500

        SESSIONS[session_id] = {
            "username": username,
            "topic": topic,
            "history": [], 
            "asked_set": set(),
            "level": 1,
            "score": 0, # This will store the cumulative score (correct count)
            "last_activity": datetime.now(),
            "concepts": concepts, 
            "current_concept_idx": 0 
        }
        logger.info(f"New session started: {session_id} for {username} on {topic}. Concepts: {[c['concept_name'] for c in concepts]}")

        first_concept = SESSIONS[session_id]["concepts"][SESSIONS[session_id]["current_concept_idx"]]
        q_data = get_question(model, topic, level=SESSIONS[session_id]["level"], concept_name=first_concept['concept_name'], asked_set=SESSIONS[session_id]["asked_set"]) # Pass model
        
        if "error" in q_data:
            logger.error(f"Failed to generate initial question for session {session_id}: {q_data['error']}")
            del SESSIONS[session_id] 
            return jsonify({"error": q_data["error"]}), 500
        
        SESSIONS[session_id]["asked_set"].add(q_data["question"]) 

        return jsonify({
            "session_id": session_id,
            **q_data
        })

    except Exception as e:
        logger.exception(f"Unexpected error in /start route: {str(e)}")
        return jsonify({"error": "Failed to start quiz due to an internal server error."}), 500

@app.route("/answer", methods=["POST"])
@limiter.limit("10 per minute") # Limit answer submissions
def answer():
    """Processes user's answer, provides feedback, and generates the next question."""
    session_id = None
    try:
        data = request.json
        if not data:
            logger.warning("No JSON data provided in /answer request.")
            return jsonify({"error": "No data provided"}), 400

        session_id = data.get("session_id")
        if not session_id:
            logger.warning("Session ID missing in /answer request.")
            return jsonify({"error": "Session ID required"}), 400

        session = SESSIONS.get(session_id) or recover_session(session_id)
        if not session:
            logger.warning(f"Session {session_id} expired or invalid during /answer submission.")
            return jsonify({"error": "Session expired or invalid. Please restart the quiz."}), 400

        required_fields = ["question", "user_answer", "correct_answer", "skill"] 
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            logger.warning(f"Missing required fields for session {session_id}: {', '.join(missing_fields)}")
            return jsonify({
                "error": f"Missing required fields: {', '.join(missing_fields)}"
            }), 400

        session["last_activity"] = datetime.now()
        backup_session(session_id)

        feedback_raw = None
        is_correct = False
        judgment_text = "Evaluating your answer..."
        explanation_text = "No detailed explanation available."

        for attempt in range(3):
            try:
                feedback_raw = evaluate_answer(model, data["question"], data["correct_answer"], data["user_answer"]) # Pass model
                if feedback_raw:
                    feedback_lines = feedback_raw.split('\n')
                    
                    judgment_line = next((line for line in feedback_lines if line.startswith("Judgment:")), None)
                    if judgment_line:
                        judgment_text = judgment_line.replace("Judgment:", "").strip()
                        is_correct = "correct" in judgment_text.lower() and "not correct" not in judgment_text.lower() and "incorrect" not in judgment_text.lower()
                    
                    explanation_line = next((line for line in feedback_lines if line.startswith("Explanation:")), None)
                    if explanation_line:
                        explanation_text = explanation_line.replace("Explanation:", "").strip()
                break 

            except Exception as e:
                logger.warning(f"Evaluation attempt {attempt + 1} failed for session {session_id}: {str(e)}")
                time.sleep(1) 

        if feedback_raw is None:
            judgment_text = "Could not evaluate answer."
            explanation_text = "The AI model was unable to provide feedback."
            is_correct = False 

        if is_correct:
            session["score"] += 1 # Increment raw correct count
            session["level"] = min(session["level"] + 1, 5) 
        else:
            session["level"] = max(session["level"] - 1, 1) 

        # Record the response in session history (full raw feedback for PDF report)
        record_response(
            session,
            data["question"],
            data["user_answer"],
            data["correct_answer"],
            feedback_raw, 
            data["skill"] 
        )
        logger.info(f"Session {session_id}: Answer submitted for Q{len(session['history'])}, Correct: {is_correct}, Level: {session['level']}, Score: {session['score']}, Skill: {data['skill']}")

        total_quiz_questions = 10 # Define this here or get from config
        quiz_complete = len(session["history"]) >= total_quiz_questions

        if quiz_complete:
            # --- NEW: Calculate final percentage score before report ---
            total_correct = session["score"] # This is the count
            final_percentage_score = (total_correct / total_quiz_questions) * 100 if total_quiz_questions > 0 else 0
            session['final_percentage_score'] = final_percentage_score # Store this for the report endpoint

            cleanup_sessions() # Cleanup session when quiz is truly complete
            logger.info(f"Session {session_id}: Quiz completed. Final score: {final_percentage_score:.1f}%")
            return jsonify({"quiz_complete": True}) # Just return quiz_complete here

        # --- Select next concept for the question ---
        session["current_concept_idx"] = (session["current_concept_idx"] + 1) % len(session["concepts"])
        next_concept = session["concepts"][session["current_concept_idx"]]
        logger.info(f"Session {session_id}: Next question concept will be '{next_concept['concept_name']}'.")

        # Generate next question with retries
        next_q_data = None
        for attempt in range(3):
            try:
                next_q_data = get_question(
                    model, # Pass model
                    session["topic"], 
                    session["level"], 
                    concept_name=next_concept['concept_name'], 
                    asked_set=session["asked_set"]
                )
                if next_q_data and next_q_data.get("question") and next_q_data["question"] not in session["asked_set"]:
                    session["asked_set"].add(next_q_data["question"])
                    break
                elif next_q_data and next_q_data.get("question"):
                    logger.info(f"Session {session_id}: Duplicate question '{next_q_data['question']}' generated for concept '{next_concept['concept_name']}', retrying.")
                else:
                    logger.warning(f"Session {session_id}: get_question returned empty/invalid data for concept '{next_concept['concept_name']}', attempt {attempt + 1}.")
            except Exception as e:
                logger.warning(f"Question generation attempt {attempt + 1} failed for session {session_id}, concept '{next_concept['concept_name']}': {str(e)}")
                time.sleep(1)

        if not next_q_data or "question" not in next_q_data:
            next_q_data = {
                "question": "We couldn't generate a new question right now. Please try again later.",
                "correct_answer": "N/A",
                "explanation": "No explanation available for this fallback question.",
                "skill": "Fallback Question", 
                "difficulty": session["level"]
            }
            logger.error(f"Session {session_id}: All attempts to generate a new question failed for concept '{next_concept['concept_name']}'.")

        return jsonify({
            "is_correct": is_correct, 
            "judgment_text": judgment_text, 
            "explanation_text": explanation_text, 
            "question": next_q_data["question"],
            "correct_answer": next_q_data["correct_answer"],
            "level": session["level"],
            "progress": len(session["history"]),
            "score": session["score"], # Still send raw score (correct count) to frontend for progress
            "skill": next_q_data["skill"] 
        })

    except Exception as e:
        logger.exception(f"Severe unexpected error in /answer for session {session_id}: {str(e)}")
        return jsonify({
            "error": "An unexpected server error occurred. Please try again.",
            "details": str(e)
        }), 500

@app.route("/report", methods=["POST"])
def report():
    """Generates and provides a link to the quiz performance report, including AI insights."""
    session_id = None
    try:
        session_id = request.json.get("session_id")
        if not session_id:
            logger.warning("Session ID missing in /report request.")
            return jsonify({"error": "Session ID required"}), 400

        session = SESSIONS.get(session_id) or recover_session(session_id)
        if not session:
            logger.warning(f"Invalid session ID {session_id} for report generation.")
            return jsonify({"error": "Invalid session ID or session expired. Please restart the quiz."}), 400

        # Calculate final percentage score if not already set (e.g., direct call to /report)
        final_percentage_score = session.get('final_percentage_score')
        if final_percentage_score is None:
            total_questions_answered = len(session.get('history', []))
            correct_answers_count = 0
            for entry in session.get('history', []):
                # Robustly check if answer was correct from feedback string
                feedback_lines = entry.get('feedback', '').split('\n')
                judgment_line = next((line for line in feedback_lines if line.strip().lower().startswith("judgment:")), None)
                if judgment_line and "correct" in judgment_line.lower() and "incorrect" not in judgment_line.lower():
                    correct_answers_count += 1
            final_percentage_score = (correct_answers_count / total_questions_answered) * 100 if total_questions_answered > 0 else 0
            session['final_percentage_score'] = final_percentage_score # Store it for next time

        # --- Call generate_report and get all the data back ---
        report_data = generate_report(model, session, final_percentage_score) # Pass model and final_percentage_score
        
        if "error" in report_data:
            logger.error(f"Error within generate_report for session {session_id}: {report_data['error']}")
            return jsonify({"error": report_data['error']}), 500

        logger.info(f"Report generated for session {session_id}: {report_data['filename']}")
        # Return all necessary data to the frontend
        return jsonify({
            "report_path": f"/static/reports/{report_data['filename']}",
            "ai_summary": report_data.get('ai_summary', 'No AI summary available.'),
            "ai_recommendations": report_data.get('ai_recommendations', 'No AI recommendations available.')
        })

    except Exception as e:
        logger.exception(f"Error generating report for session {session_id}: {str(e)}")
        return jsonify({"error": "Failed to generate report due to an internal server error.", "details": str(e)}), 500

@app.route("/session/recover", methods=["POST"])
def recover_session_route():
    """Attempts to recover a session given a session ID."""
    session_id = None
    try:
        session_id = request.json.get("session_id")
        if not session_id:
            logger.warning("Session ID missing in /session/recover request.")
            return jsonify({"error": "Session ID required"}), 400

        session = recover_session(session_id)
        if not session:
            logger.info(f"Session {session_id} not found or not recoverable.")
            return jsonify({"error": "Session not recoverable"}), 404

        logger.info(f"Session {session_id} successfully recovered.")
        return jsonify({
            "status": "recovered",
            "progress": len(session["history"]),
            "score": session["score"], # This is correct count
            "final_percentage_score": session.get('final_percentage_score', 0), # Include final percentage if available
            "level": session["level"],
            "username": session["username"],
            "topic": session["topic"]
        })
    except Exception as e:
        logger.exception(f"Error in /session/recover for session {session_id}: {str(e)}")
        return jsonify({"error": "An internal error occurred during session recovery."}), 500

@app.route("/session/heartbeat", methods=["POST"])
def heartbeat():
    """Updates the last activity timestamp for a session to prevent expiry."""
    session_id = request.json.get("session_id")
    if session_id in SESSIONS:
        SESSIONS[session_id]["last_activity"] = datetime.now()
        logger.debug(f"Heartbeat for session {session_id}")
        return jsonify({"status": "active"})
    logger.debug(f"Heartbeat received for inactive or invalid session {session_id}")
    return jsonify({"status": "inactive"}), 404

# Run the Flask app
if __name__ == "__main__":
    reports_dir = os.path.join(app.root_path, 'static', 'reports')
    os.makedirs(reports_dir, exist_ok=True)
    
    app.run(debug=True, host='0.0.0.0', port=5000)