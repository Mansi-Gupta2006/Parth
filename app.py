from flask import Flask, render_template, request, jsonify
import google.generativeai as genai
import uuid, os, logging, time
from datetime import datetime, timedelta
from utils import get_question, evaluate_answer, record_response, generate_report, get_math_concepts, log_interaction_to_csv  # ✅ Added log_interaction_to_csv
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
    genai.configure(api_key="dummy_key_if_not_set")
else:
    genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel("gemini-1.5-flash")

# Create Flask app
app = Flask(__name__)

# Rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["5 per second", "30 per minute"]
)

# In-memory session store
SESSIONS = {}
SESSION_BACKUPS = {}

# Session Management Functions
def cleanup_sessions():
    now = datetime.now()
    expired_sids = [sid for sid, sess in SESSIONS.items()
                    if now - sess["last_activity"] > timedelta(minutes=30)]
    for sid in expired_sids:
        logger.info(f"Cleaning up expired session: {sid}")
        del SESSIONS[sid]
        if sid in SESSION_BACKUPS:
            del SESSION_BACKUPS[sid]

def backup_session(session_id):
    if session_id in SESSIONS:
        import copy
        SESSION_BACKUPS[session_id] = copy.deepcopy(SESSIONS[session_id])

def get_session_backup(session_id):
    return SESSION_BACKUPS.get(session_id)

def recover_session(session_id):
    if session_id in SESSIONS:
        return SESSIONS[session_id]
    backup = get_session_backup(session_id)
    if backup:
        import copy
        SESSIONS[session_id] = copy.deepcopy(backup)
        logger.info(f"Recovered session: {session_id}")
        return SESSIONS[session_id]
    logger.warning(f"Could not recover session: {session_id}")
    return None

# Routes
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/start", methods=["POST"])
@limiter.limit("3 per minute")
def start():
    try:
        data = request.json
        topic = data.get("topic")
        username = data.get("username")

        if not topic or not username:
            return jsonify({"error": "Topic and username are required"}), 400

        session_id = str(uuid.uuid4())
        concepts = get_math_concepts(model, topic)
        if not concepts:
            return jsonify({"error": "Failed to initialize quiz concepts."}), 500

        SESSIONS[session_id] = {
            "username": username,
            "topic": topic,
            "history": [],
            "asked_set": set(),
            "level": 1,
            "score": 0,
            "last_activity": datetime.now(),
            "concepts": concepts,
            "current_concept_idx": 0
        }

        first_concept = SESSIONS[session_id]["concepts"][0]
        q_data = get_question(model, topic, level=1, concept_name=first_concept["concept_name"], asked_set=set())

        if "error" in q_data:
            del SESSIONS[session_id]
            return jsonify({"error": q_data["error"]}), 500

        SESSIONS[session_id]["asked_set"].add(q_data["question"])

        return jsonify({
            "session_id": session_id,
            **q_data
        })

    except Exception as e:
        logger.exception("Error in /start")
        return jsonify({"error": "Internal server error"}), 500

@app.route("/answer", methods=["POST"])
@limiter.limit("10 per minute")
def answer():
    session_id = None
    try:
        data = request.json
        session_id = data.get("session_id")
        if not session_id:
            return jsonify({"error": "Session ID required"}), 400

        session = SESSIONS.get(session_id) or recover_session(session_id)
        if not session:
            return jsonify({"error": "Session expired or invalid."}), 400

        required_fields = ["question", "user_answer", "correct_answer", "skill"]
        if any(k not in data for k in required_fields):
            return jsonify({"error": "Missing required fields"}), 400

        session["last_activity"] = datetime.now()
        backup_session(session_id)

        evaluation_result = evaluate_answer(model, data["question"], data["correct_answer"], data["user_answer"])
        feedback_raw = evaluation_result["feedback"]
        is_correct = evaluation_result["is_correct"]


        if is_correct:
            session["score"] += 1
            session["level"] = min(session["level"] + 1, 5)
        else:
            session["level"] = max(session["level"] - 1, 1)

        record_response(session, data["question"], data["user_answer"], data["correct_answer"], feedback_raw, data["skill"])
        log_interaction_to_csv(
        session,
        data["question"],
        data["user_answer"],
        data["correct_answer"],
        feedback_raw,
        session.get("level", 1),
        is_correct
        )



        if len(session["history"]) >= 10:
            score_percent = (session["score"] / 10) * 100
            session["final_percentage_score"] = score_percent
            cleanup_sessions()
            return jsonify({"quiz_complete": True})

        session["current_concept_idx"] = (session["current_concept_idx"] + 1) % len(session["concepts"])
        next_concept = session["concepts"][session["current_concept_idx"]]

        next_q_data = get_question(model, session["topic"], level=session["level"], concept_name=next_concept["concept_name"], asked_set=session["asked_set"])
        if next_q_data and "question" in next_q_data:
            session["asked_set"].add(next_q_data["question"])
        else:
            next_q_data = {
                "question": "No new question available.",
                "correct_answer": "N/A",
                "explanation": "Unable to generate question.",
                "skill": next_concept["concept_name"],
                "difficulty": session["level"]
            }

        return jsonify({
            "is_correct": is_correct,
            "judgment_text": feedback_raw.split("\n")[0],
            "explanation_text": "\n".join(feedback_raw.split("\n")[1:]),
            "question": next_q_data["question"],
            "correct_answer": next_q_data["correct_answer"],
            "level": session["level"],
            "progress": len(session["history"]),
            "score": session["score"],
            "skill": next_q_data["skill"]
        })

    except Exception as e:
        logger.exception(f"Unexpected error in /answer for session {session_id}")
        return jsonify({"error": "Server error", "details": str(e)}), 500

@app.route("/report", methods=["POST"])
def report():
    try:
        session_id = request.json.get("session_id")
        session = SESSIONS.get(session_id) or recover_session(session_id)
        if not session:
            return jsonify({"error": "Session not found"}), 400

        final_score = session.get("final_percentage_score", 0)
        report_data = generate_report(model, session, final_score)
        if "error" in report_data:
            return jsonify({"error": report_data["error"]}), 500

        return jsonify({
            "report_path": f"/static/reports/{report_data['filename']}",
            "ai_summary": report_data["ai_summary"],
            "ai_recommendations": report_data["ai_recommendations"]
        })

    except Exception as e:
        logger.exception("Error generating report")
        return jsonify({"error": "Error generating report"}), 500

@app.route("/generate-subtopics", methods=["POST"])
def generate_subtopics():
    try:
        topic = request.json.get("topic")
        if not topic:
            return jsonify({"error": "Topic required"}), 400

        concepts = get_math_concepts(model, topic)
        return jsonify({"concepts": concepts})

    except Exception as e:
        logger.exception("Error generating subtopics")
        return jsonify({"error": "Failed to generate subtopics"}), 500

@app.route("/session/recover", methods=["POST"])
def recover_session_route():
    try:
        session_id = request.json.get("session_id")
        session = recover_session(session_id)
        if not session:
            return jsonify({"error": "Session not recoverable"}), 404

        return jsonify({
            "status": "recovered",
            "progress": len(session["history"]),
            "score": session["score"],
            "final_percentage_score": session.get("final_percentage_score", 0),
            "level": session["level"],
            "username": session["username"],
            "topic": session["topic"]
        })
    except Exception as e:
        logger.exception("Error in session recovery")
        return jsonify({"error": "Error recovering session"}), 500

@app.route("/session/heartbeat", methods=["POST"])
def heartbeat():
    session_id = request.json.get("session_id")
    if session_id in SESSIONS:
        SESSIONS[session_id]["last_activity"] = datetime.now()
        return jsonify({"status": "active"})
    return jsonify({"status": "inactive"}), 404

if __name__ == "__main__":
    os.makedirs(os.path.join(app.root_path, 'static', 'reports'), exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=5000)
