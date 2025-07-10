import os
import logging
import json
import re
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import black, HexColor
from reportlab.platypus import Paragraph
from reportlab.lib.styles import getSampleStyleSheet
import matplotlib.pyplot as plt
import io

logger = logging.getLogger(__name__)

# --- Helper for AI JSON/Text Extraction ---
def extract_json_from_markdown(text):
    """
    Extracts a JSON string from a markdown code block (```json ... ```).
    Returns the extracted JSON string or the original text if no block is found.
    Handles cases where the JSON might just be present without markdown.
    """
    # Regex to find JSON within ```json ... ``` or just { ... }
    match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if match:
        return match.group(1).strip()
    
    # Fallback if no markdown block, try to find the first '{' and last '}'
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and start < end:
        try:
            # Attempt to parse to ensure it's valid JSON before returning
            json.loads(text[start:end+1].strip())
            return text[start:end+1].strip()
        except json.JSONDecodeError:
            pass # Not valid JSON, continue to return original text
            
    return text.strip() # Return original text (or stripped) if no JSON structure found

def strip_unwanted_characters(text):
    """Removes common AI conversational filler or markdown that can interfere with display."""
    text = text.strip()
    # Remove common conversational intros/outros
    text = re.sub(r'^(Sure, here\'s your summary|Here is the summary|Alright, here\'s your personalized feedback|I can provide that summary for you|Here is the requested summary and recommendations|Okay, here\'s a summary and recommendations based on the data|Based on the data, here is a summary and recommendations|Here is your summary and recommendations):?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^(Here are the recommendations|Below are some recommendations|And for recommendations|Recommendations for you):?\s*', '', text, 1, flags=re.IGNORECASE)
    # Remove markdown formatting if still present (e.g., if AI wrapped something in ** but we didn't want it)
    text = text.replace('**', '').replace('*', '') # Basic markdown removal
    return text.strip()


# --- AI Interaction Functions ---

def get_math_concepts(model, topic):
    """
    Generates a list of math concepts/skills for a given topic, ordered by increasing difficulty.
    """
    prompt = f"""
    You are a math education assistant.
    For the math topic '{topic}', generate a JSON array of 5 distinct math concepts or skills, ordered by increasing difficulty.
    Each object in the array should have:
    - "concept_name": A concise name for the concept (e.g., "Solving Linear Equations").
    - "description": A brief explanation of what the concept entails.
    - "base_difficulty": An integer from 1 to 5 indicating its inherent difficulty within the topic.

    The output MUST be a JSON array.
    Example for 'Algebra':
    [
        {{"concept_name": "Simplifying Expressions", "description": "Combining like terms and applying order of operations.", "base_difficulty": 1}},
        {{"concept_name": "Solving Linear Equations", "description": "Finding the value of a single variable in equations like ax + b = c.", "base_difficulty": 2}},
        {{"concept_name": "Factoring Quadratics", "description": "Decomposing quadratic trinomials into binomial factors.", "base_difficulty": 3}},
        {{"concept_name": "Solving Systems of Equations", "description": "Finding common solutions for multiple linear equations.", "base_difficulty": 4}},
        {{"concept_name": "Quadratic Formula", "description": "Using the quadratic formula to find roots of quadratic equations.", "base_difficulty": 5}}
    ]
    """
    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        logger.debug(f"Raw AI response for concepts:\n{response_text}")

        json_string_to_parse = extract_json_from_markdown(response_text)

        logger.debug(f"Attempting to parse concepts JSON:\n{json_string_to_parse}")

        concepts = json.loads(json_string_to_parse)
        if not isinstance(concepts, list) or not all(isinstance(c, dict) and 'concept_name' in c and 'description' in c and 'base_difficulty' in c for c in concepts):
            raise ValueError("Parsed JSON is not a valid list of concept objects or missing required keys.")
        
        logger.info(f"Generated concepts for {topic}: {[c['concept_name'] for c in concepts]}")
        return concepts

    except json.JSONDecodeError as jde:
        logger.error(f"Failed to decode JSON from AI response for concepts: {jde}. Raw response: {response_text}")
        return fallback_concepts(topic)
    except Exception as e:
        logger.error(f"Error generating concepts for topic '{topic}': {str(e)}", exc_info=True)
        return fallback_concepts(topic)

def fallback_concepts(topic):
    """Provides a hardcoded fallback list of concepts if AI generation fails."""
    logger.warning(f"Using fallback concepts for topic: {topic}")
    topic_lower = topic.lower()
    if topic_lower == "algebra":
        return [
            {"concept_name": "Basic Operations", "description": "Addition, subtraction, multiplication, division.", "base_difficulty": 1},
            {"concept_name": "Solving Linear Equations", "description": "Equations with one variable.", "base_difficulty": 2},
            {"concept_name": "Factoring Simple Polynomials", "description": "Factoring expressions like x^2 + bx + c.", "base_difficulty": 3},
            {"concept_name": "Systems of Two Equations", "description": "Solving two linear equations simultaneously.", "base_difficulty": 4},
            {"concept_name": "Quadratic Equations", "description": "Solving equations of the form ax^2 + bx + c = 0.", "base_difficulty": 5}
        ]
    elif topic_lower == "calculus":
        return [
            {"concept_name": "Limits", "description": "Understanding limits of functions.", "base_difficulty": 1},
            {"concept_name": "Basic Derivatives", "description": "Derivatives of simple power functions.", "base_difficulty": 2},
            {"concept_name": "Chain Rule", "description": "Applying the chain rule for derivatives.", "base_difficulty": 3},
            {"concept_name": "Basic Integrals", "description": "Indefinite integrals of simple functions.", "base_difficulty": 4},
            {"concept_name": "Definite Integrals", "description": "Calculating definite integrals.", "base_difficulty": 5}
        ]
    elif topic_lower == "geometry":
        return [
            {"concept_name": "Basic Shapes & Area", "description": "Area of squares, rectangles, triangles.", "base_difficulty": 1},
            {"concept_name": "Perimeter & Circumference", "description": "Calculating perimeter of polygons and circumference of circles.", "base_difficulty": 2},
            {"concept_name": "Angles & Lines", "description": "Properties of parallel lines, transversals, and angles.", "base_difficulty": 3},
            {"concept_name": "Pythagorean Theorem", "description": "Applying the theorem to right triangles.", "base_difficulty": 4},
            {"concept_name": "Volume of 3D Shapes", "description": "Calculating volume of prisms, cylinders, spheres.", "base_difficulty": 5}
        ]
    elif topic_lower == "statistics":
        return [
            {"concept_name": "Mean, Median, Mode", "description": "Calculating measures of central tendency.", "base_difficulty": 1},
            {"concept_name": "Range & Variance", "description": "Understanding measures of spread.", "base_difficulty": 2},
            {"concept_name": "Probability of Events", "description": "Calculating simple probabilities.", "base_difficulty": 3},
            {"concept_name": "Normal Distribution Basics", "description": "Understanding the normal curve and standard deviation.", "base_difficulty": 4},
            {"concept_name": "Correlation & Regression", "description": "Basic concepts of relationships between variables.", "base_difficulty": 5}
        ]
    elif topic_lower == "basic arithmetic":
        return [
            {"concept_name": "Addition & Subtraction", "description": "Operations with whole numbers.", "base_difficulty": 1},
            {"concept_name": "Multiplication & Division", "description": "Operations with whole numbers.", "base_difficulty": 2},
            {"concept_name": "Fractions & Decimals", "description": "Basic operations and conversions.", "base_difficulty": 3},
            {"concept_name": "Percentages", "description": "Calculating percentages and finding parts of a whole.", "base_difficulty": 4},
            {"concept_name": "Order of Operations (PEMDAS)", "description": "Solving multi-step expressions correctly.", "base_difficulty": 5}
        ]
    else:
        return [
            {"concept_name": f"{topic} Basics", "description": f"Fundamental concepts in {topic}.", "base_difficulty": 1},
            {"concept_name": f"{topic} Intermediate", "description": f"Intermediate problems in {topic}.", "base_difficulty": 3},
            {"concept_name": f"{topic} Advanced", "description": f"Complex problems in {topic}.", "base_difficulty": 5}
        ]


def get_question(model, topic, level, concept_name, asked_set=None):
    """
    Generates a math question using the Gemini model for a specific concept.
    Includes previously asked questions in the prompt to prevent repetition.
    """
    asked_set = asked_set or set()
    asked_questions_str = ", ".join(list(asked_set)[-5:]) 

    prompt = f"""
You are a strict math quiz generator.

**ONLY** output a **pure JSON object** that includes:
- A new and varied math question (not from: {asked_questions_str if asked_questions_str else "No questions asked yet."})
- Must be based on: Topic = {topic}, Concept = {concept_name}, Difficulty = {level}

Respond ONLY in this exact JSON format (NO explanation, no text around it):

{{
  "question": "<question text>",
  "answer": "<correct answer>",
  "explanation": "<brief step-by-step explanation>",
  "skill": "{concept_name}",
  "difficulty": {level}
}}

Example:
{{
  "question": "Factor the quadratic expression: x^2 - 7x + 12",
  "answer": "(x - 3)(x - 4)",
  "explanation": "To factor x^2 - 7x + 12, find two numbers that multiply to 12 and add to -7. These numbers are -3 and -4. So, (x - 3)(x - 4).",
  "skill": "Factoring Quadratics",
  "difficulty": 3
}}
"""
    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()

        logger.debug(f"Raw Gemini question output:\n{response_text}")

        json_str_to_parse = extract_json_from_markdown(response_text)
        
        logger.debug(f"Attempting to parse question JSON:\n{json_str_to_parse}")

        q_data = json.loads(json_str_to_parse)

        required_fields = ["question", "answer", "explanation", "skill", "difficulty"]
        if not all(k in q_data for k in required_fields):
            raise ValueError(f"Missing required fields in JSON response. Expected: {required_fields}, Got: {list(q_data.keys())}")

        if q_data.get("skill") != concept_name:
            logger.warning(f"Skill mismatch: Gemini returned '{q_data.get('skill')}', expected '{concept_name}'. Forcing override.")
            q_data["skill"] = concept_name

        if q_data["question"] in asked_set:
            logger.warning(f"Duplicate question generated: {q_data['question']}")
            raise ValueError("Duplicate question received, requesting new one.") 

        logger.info(f"Generated question for concept '{concept_name}', level {level}: {q_data['question'][:70]}...")
        return {
            "question": q_data["question"],
            "correct_answer": str(q_data["answer"]), 
            "explanation": q_data["explanation"],
            "skill": q_data["skill"],
            "difficulty": q_data["difficulty"]
        }

    except json.JSONDecodeError as jde:
        logger.error(f"Failed to decode JSON from AI response for question: {jde}. Raw response: {response_text}")
        return {
            "question": f"Error: Could not generate a valid question. (Topic: {topic}, Concept: {concept_name}, Level: {level})",
            "correct_answer": "N/A",
            "explanation": "The AI response was not valid JSON. Please try again.",
            "skill": concept_name,
            "difficulty": level,
            "error": "Failed to parse question JSON"
        }
    except ValueError as ve:
        logger.error(f"Question generation validation error: {ve}. Raw response: {response_text if 'response_text' in locals() else 'N/A'}")
        return {
            "question": f"Error: {ve}. (Topic: {topic}, Concept: {concept_name}, Level: {level})",
            "correct_answer": "N/A",
            "explanation": "The AI response failed validation checks. Please try again.",
            "skill": concept_name,
            "difficulty": level,
            "error": "Question validation failed"
        }
    except Exception as e:
        logger.error(f"Failed to generate a custom question for '{concept_name}', level {level}. Error: {str(e)}", exc_info=True)
        # Specific handling for API quota error during question generation
        if "quota" in str(e).lower() or "resourceexhausted" in str(e).lower():
            logger.warning("API quota likely exceeded during question generation. Returning generic question.")
            return {
                "question": f"Error: API limit reached. Cannot generate custom question. (Topic: {topic}, Concept: {concept_name}, Level: {level})",
                "correct_answer": "Please check your API quota.",
                "explanation": "The system could not generate a question because the daily API request limit was reached.",
                "skill": concept_name,
                "difficulty": level,
                "error": "API quota exceeded during question generation"
            }
        return {
            "question": f"An unexpected error occurred generating question. (Topic: {topic}, Concept: {concept_name}, Level: {level})",
            "correct_answer": "N/A",
            "explanation": "Sorry! An internal error occurred while generating the question.",
            "skill": concept_name,
            "difficulty": level,
            "error": "Internal server error during question generation"
        }
    
def evaluate_answer(model, question, correct, user_answer):
    """
    Evaluates a user's answer with more lenient validation for equivalent forms.
    """
    prompt = f"""
    You are a math answer evaluator. Your goal is to determine if the user's answer is mathematically equivalent to the **PROVIDED Correct Answer**, considering common variations and precision.

    **Question**: {question}
    **PROVIDED Correct Answer**: {correct}
    **User's Answer**: {user_answer}

    **Strict Rules for Evaluation and Explanation:**
    1.  **Mathematical Equivalence:** Determine if '{user_answer}' is mathematically equivalent to the **PROVIDED Correct Answer** '{correct}'.
    2.  **Equations:** For equations, accept 'x=VALUE' or just 'VALUE'.
    3.  **Fractions/Decimals:** Accept decimal equivalents for fractions and vice-versa.
    4.  **Formatting Leniency:** Ignore differences in spacing, non-meaningful parentheses, and leading/trailing zeros.
    5.  **Case Insensitivity:** Ignore case for text-based answers.
    6.  **Crucially, base your judgment and explanation SOLELY on the PROVIDED 'Correct Answer' ('{correct}'), not on any re-calculation you might perform. You MUST trust '{correct}' as the ultimate correct value.**
    7.  **Rounding:** If the PROVIDED 'Correct Answer' implies a certain precision (e.g., two decimal places), compare the user's answer with that precision. If the question involves division leading to many decimals, assume the PROVIDED 'Correct Answer' is already rounded appropriately.

    **Output ONLY as a JSON object** with the following structure:
    {{
      "is_correct": <true/false>,
      "judgment_reason": "<Concise reason for Correct/Incorrect, e.g., 'Correct: Equivalent solution', 'Incorrect: Off by a decimal place'>",
      "explanation": "<ALWAYS provide a full, step-by-step detailed explanation of how to solve the problem and arrive at the PROVIDED Correct Answer ('{correct}'). IF THE USER'S ANSWER IS INCORRECT, YOU MUST explicitly state why their answer was wrong by comparing it to the PROVIDED Correct Answer, pointing out the error in their approach or calculation. Your explanation must be comprehensive and helpful. Do NOT invent new correct answers or complex rounding explanations if the problem is straightforward arithmetic. Your explanation must guide the user to the PROVIDED Correct Answer.>"
    }}

    Example 1 (Exact match):
    Question: Solve 2x + 3 = 7
    PROVIDED Correct Answer: x = 2
    User's Answer: 2
    {{
      "is_correct": true,
      "judgment_reason": "Correct: Solution is equivalent to x=2",
      "explanation": "To solve 2x + 3 = 7: Subtract 3 from both sides (2x = 4). Divide by 2 (x = 2). Your answer '2' is correct and equivalent to the solution."
    }}

    Example 2 (Rounding difference based on PROVIDED Correct Answer):
    Question: Calculate 10 / 3, rounded to two decimal places.
    PROVIDED Correct Answer: 3.33
    User's Answer: 3.333
    {{
      "is_correct": false,
      "judgment_reason": "Incorrect: Precision error, answer not rounded to two decimal places as per correct answer.",
      "explanation": "To calculate 10 / 3, the exact value is 3.333... When rounded to two decimal places, as specified by the PROVIDED Correct Answer '3.33', it becomes 3.33. Your answer of 3.333 is incorrect because it was not rounded to the specified two decimal places as required."
    }}

    Example 3 (Calculation error):
    Question: Simplify 3(x + 5) - 2(x - 1)
    PROVIDED Correct Answer: x + 17
    User's Answer: x + 13
    {{
      "is_correct": false,
      "judgment_reason": "Incorrect: Error in constant term",
      "explanation": "To simplify 3(x + 5) - 2(x - 1): First, distribute the numbers into the parentheses: 3x + 15 - 2x + 2. Next, combine the like terms: (3x - 2x) + (15 + 2). This simplifies to x + 17. Your answer 'x + 13' is incorrect because you likely made an error in combining the constant terms (15 + 2 should be 17, not 13). The PROVIDED Correct Answer is x + 17."
    }}
    """
    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        logger.debug(f"Raw AI evaluation output:\n{response_text}")

        # Extract JSON from markdown or raw text
        json_str_to_parse = extract_json_from_markdown(response_text)
        logger.debug(f"Attempting to parse evaluation JSON:\n{json_str_to_parse}")

        evaluation_data = json.loads(json_str_to_parse)

        if not all(k in evaluation_data for k in ["is_correct", "judgment_reason", "explanation"]):
            raise ValueError(f"Missing required fields in AI evaluation JSON. Got: {list(evaluation_data.keys())}")

        is_correct = evaluation_data["is_correct"]
        judgment_reason = evaluation_data["judgment_reason"]
        explanation = evaluation_data["explanation"]

        # --- Robust Explanation Check and Fallback ---
        # If explanation is missing or too short, provide a fallback
        if not explanation or len(explanation.strip()) < 30: # Minimum length for a helpful explanation
            logger.warning(f"AI provided insufficient explanation. User Answer: {user_answer}, Correct: {correct}. Providing fallback.")
            if is_correct:
                explanation = f"Your answer '{user_answer}' is correct! The step-by-step solution confirms your result. Well done!"
            else:
                # Provide a generic but helpful message for incorrect answers
                explanation = (
                    f"Your answer '{user_answer}' is incorrect. The correct answer is '{correct}'. "
                    "Please carefully review the correct solution steps. "
                    "There might be a calculation error or a misunderstanding of the concept involved. "
                    f"Here's how to get to the correct answer '{correct}': [AI failed to provide detailed steps here, but this is the correct result. Re-check the problem and solution based on '{correct}']."
                )


        # Construct the feedback string in the old format for compatibility with existing code
        feedback_status = "Correct" if is_correct else "Incorrect"
        feedback_full_text = f"Judgment: {feedback_status} ({judgment_reason})\nExplanation: {explanation}"

        return feedback_full_text

    except json.JSONDecodeError as jde:
        logger.error(f"Failed to decode JSON from AI evaluation response: {jde}. Raw response: {response_text}")
        return f"Judgment: Error - Failed to parse AI feedback\nExplanation: Evaluation system encountered a JSON parsing error. Please check the logs for the raw AI response. The correct answer was: {correct}"
    except ValueError as ve:
        logger.error(f"AI evaluation validation error: {ve}. Raw response: {response_text if 'response_text' in locals() else 'N/A'}")
        return f"Judgment: Error - Invalid AI feedback format\nExplanation: Evaluation system received malformed data from AI. Please check the logs. The correct answer was: {correct}"
    except Exception as e:
        logger.error(f"Evaluation error for Q: '{question[:50]}...', A: '{user_answer[:50]}...': {str(e)}", exc_info=True)
        # Fallback for API quota exhaustion specifically
        if "quota" in str(e).lower() or "resourceexhausted" in str(e).lower():
            logger.warning("API quota likely exceeded during evaluation. Returning generic incorrect feedback.")
            return f"Judgment: Incorrect! (Evaluation failed due to API limit)\nExplanation: Could not fully evaluate your answer due to an API service issue. Your daily API quota might be exhausted. Please try again later. The correct answer was: {correct}"
        return f"Judgment: Incorrect! (Evaluation failed due to technical error)\nExplanation: Evaluation system encountered an unexpected error. Please try again. The correct answer was: {correct}"

# ... (rest of your utils.py code) ...
def normalize_math_expression(expr):
    """Normalize math expressions for comparison"""
    expr = re.sub(r'\s+', '', expr)  # Remove all whitespace
    expr = expr.replace('^', '**')    # Standardize exponent notation
    return expr.lower()

def generate_summary_and_recommendations(model, skill_performance, topic, username):
    """
    Generates a synthetic summary of strengths/weaknesses and study recommendations
    based on the user's performance per skill.
    """
    performance_str_list = []
    for skill, data in skill_performance.items():
        score_percent = f"{data['score']:.1f}%" if 'score' in data else 'N/A'
        performance_str_list.append(f"- {skill}: {data['correct']} out of {data['total']} correct ({score_percent})")
    performance_str = "\n".join(performance_str_list)

    weak_areas = [skill for skill, data in skill_performance.items() if data['score'] < 60 and data['total'] > 0]
    # weak_areas_str = ", ".join(weak_areas) if weak_areas else "none specifically identified from these skills" # Not directly used in prompt now

    prompt = f"""
    You are an AI tutor providing personalized feedback to a student named {username}.
    Analyze their performance in a math quiz on the topic of {topic}.

    Here is their performance breakdown by skill:
    {performance_str}

    Based on this, please provide:
    1. A concise, encouraging **Summary of Strengths and Weaknesses**. Highlight overall performance and pinpoint specific areas where they struggled (if any).
    2. **Specific Study Recommendations**: For any identified weak areas, suggest 2-3 actionable learning strategies or types of resources (e.g., "review quadratic formula tutorials", "practice more solving linear equations", "focus on geometry theorems for triangles"). If no specific weak areas are identified, provide general advice for continued learning in math.

    Output Format:
    Summary: <Your concise summary here.>
    Recommendations: <Your specific recommendations here, bulleted if possible.>
    """
    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        logger.debug(f"Raw AI response for insights:\n{response_text}")
        
        summary_line = "No summary available."
        recommendations_line = "No specific recommendations available."

        # Use findall to get all matches for Summary and Recommendations
        summary_matches = re.findall(r"Summary:\s*(.*?)(?=\nRecommendations:|\Z)", response_text, re.DOTALL)
        recommendations_matches = re.findall(r"Recommendations:\s*(.*)", response_text, re.DOTALL)

        if summary_matches:
            summary_line = strip_unwanted_characters(summary_matches[0])
        if recommendations_matches:
            recommendations_line = strip_unwanted_characters(recommendations_matches[0]) # Corrected variable name
        
        if not summary_matches or not recommendations_matches:
            logger.warning(f"AI did not return expected summary/recommendation format. Using fallback. Raw: {response_text}")
            summary_line = "Overall, you did well! Keep practicing."
            recommendations_line = "Continue to review concepts regularly. Practice makes perfect!"

        return {
            "summary": summary_line,
            "recommendations": recommendations_line
        }

    except Exception as e:
        logger.error(f"Error generating summary and recommendations for {username} on {topic}: {str(e)}", exc_info=True)
        # Fallback for API quota exhaustion specifically for report generation
        if "quota" in str(e).lower() or "resourceexhausted" in str(e).lower():
            logger.warning("API quota likely exceeded during summary/recommendation generation. Returning generic fallback.")
            return {
                "summary": "We couldn't generate a detailed summary due to an API service issue. Your progress is still recorded!",
                "recommendations": "Please check your API quota. Meanwhile, keep practicing all areas of math to improve."
            }
        return {
            "summary": "We couldn't generate a detailed summary at this time. Keep up the good work!",
            "recommendations": "Continue practicing all areas of math to improve."
        }

# --- Session & Report Management Functions ---

def record_response(session, question, user_answer, correct_answer, feedback, skill):
    """Records the details of each question and answer into the session history."""
    session["history"].append({
        "question": question,
        "user_answer": user_answer,
        "correct_answer": correct_answer,
        "feedback": feedback, # Store raw feedback for report
        "timestamp": datetime.now().isoformat(),
        "level": session.get("level", 1), # Capture current quiz level at time of question
        "skill": skill # Store the skill associated with the question
    })
    session.setdefault("asked_set", set()).add(question)


def create_score_chart(correct_count, incorrect_count, chart_path):
    """Generates a pie chart of correct vs. incorrect answers."""
    try:
        buf = io.BytesIO()
        
        total = correct_count + incorrect_count
        if total == 0: 
            logger.warning("No questions answered, cannot create score chart.")
            # Create an empty/placeholder chart if no data, to avoid errors later
            fig, ax = plt.subplots(figsize=(4, 4))
            ax.text(0.5, 0.5, 'No Data', horizontalalignment='center', verticalalignment='center', transform=ax.transAxes, fontsize=16, color='gray')
            ax.set_title("Score Summary (No Data)", color='black')
            fig.patch.set_alpha(0) 
            ax.patch.set_alpha(0)
            plt.savefig(buf, format='png', bbox_inches='tight', transparent=True)
            plt.close(fig)
            with open(chart_path, 'wb') as f:
                f.write(buf.getvalue())
            return


        fig, ax = plt.subplots(figsize=(4, 4))
        labels = ["Correct", "Incorrect"]
        sizes = [correct_count, incorrect_count]
        colors = ["#00b894", "#d63031"] 

        ax.pie(sizes, labels=labels, colors=colors,
                autopct="%1.1f%%", startangle=90, explode=(0.05, 0), shadow=True,
                textprops={'color': 'white'})
        ax.set_title("Score Summary", color='black') 
        
        fig.patch.set_alpha(0) 
        ax.patch.set_alpha(0)

        plt.savefig(buf, format='png', bbox_inches='tight', transparent=True)
        plt.close(fig)

        with open(chart_path, 'wb') as f:
            f.write(buf.getvalue())
        logger.info(f"Chart saved to {chart_path}")

    except Exception as e:
        logger.error(f"Chart creation error: {str(e)}", exc_info=True)


def generate_report(model, session, final_score): # Added final_score parameter
    """Generates a PDF report of the quiz session, including skill-based performance and AI insights."""
    try:
        username_safe = re.sub(r'[^\w\s-]', '', session.get('username', 'Student')).replace(" ", "_") 
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{username_safe}_quiz_report_{timestamp_str}.pdf"
        
        report_dir = os.path.join("static", "reports")
        os.makedirs(report_dir, exist_ok=True)
        filepath = os.path.join(report_dir, filename)

        chart_filename = f"{username_safe}_chart_{timestamp_str}.png"
        chart_path = os.path.join(report_dir, chart_filename)

        correct_answers = 0
        incorrect_answers = 0 
        total_questions = len(session["history"])
        
        skill_performance = {}
        for h in session["history"]:
            skill = h.get("skill", "Unknown Skill") 
            if skill not in skill_performance:
                skill_performance[skill] = {'correct': 0, 'incorrect': 0, 'total': 0, 'score': 0.0}
            
            skill_performance[skill]['total'] += 1

            judgment_line = None
            if h.get("feedback"):
                lines = h["feedback"].split('\n')
                judgment_line = next((line for line in lines if line.strip().lower().startswith("judgment:")), None)

            if judgment_line:
                # IMPORTANT: Use the new structure for 'Judgment: Correct (Reason)'
                # If the feedback string contains "Incorrect!" (from the quota fallback)
                # it will be correctly handled here.
                judgment_text = judgment_line.replace("Judgment:", "").strip().lower()
                if "correct" in judgment_text and "not correct" not in judgment_text and "incorrect" not in judgment_text: 
                    correct_answers += 1
                    skill_performance[skill]['correct'] += 1
                else:
                    incorrect_answers += 1
                    skill_performance[skill]['incorrect'] += 1
            else:
                logger.warning(f"Missing or malformed Judgment line in feedback for question: {h.get('question', 'Unknown')}. Marking as incorrect.")
                incorrect_answers += 1 
                skill_performance[skill]['incorrect'] += 1 


        # Calculate scores for each skill
        for skill, data in skill_performance.items():
            if data['total'] > 0:
                skill_performance[skill]['score'] = (data['correct'] / data['total']) * 100
            else:
                skill_performance[skill]['score'] = 0.0

        # --- Generate AI Summary and Recommendations ---
        ai_insights = generate_summary_and_recommendations(model, skill_performance, session.get('topic', 'N/A'), session.get('username', 'Student'))
        summary_text = ai_insights['summary']
        recommendations_text = ai_insights['recommendations']

        # --- Create Score Chart ---
        create_score_chart(correct_answers, incorrect_answers, chart_path)

        # --- PDF Generation ---
        c = canvas.Canvas(filepath, pagesize=letter)
        width, height = letter
        
        TEXT_COLOR = black

        c.setFont("Helvetica-Bold", 24)
        c.setFillColor(HexColor('#6C5CE7'))
        c.drawCentredString(width / 2.0, height - 50, "Math Quiz Performance Report")

        c.setFillColor(TEXT_COLOR)
        c.setFont("Helvetica", 12)
        y = height - 100
        
        info_lines = [
            f"Student: {session.get('username', 'N/A')}",
            f"Topic: {session.get('topic', 'N/A')}",
            f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Total Questions: {total_questions}",
            f"Correct Answers: {correct_answers}",
            f"Incorrect Answers: {incorrect_answers}",
            f"Final Score: {final_score:.1f}%" 
        ]
        
        for line in info_lines:
            c.drawString(50, y, line)
            y -= 15
        
        y -= 20

        # Draw main score chart
        try:
            if os.path.exists(chart_path):
                img_width = 3.5 * inch
                img_height = 3.5 * inch
                x_offset = (width - img_width) / 2
                chart_y_pos = y - img_height - 20 
                if chart_y_pos < 50:
                    c.showPage()
                    y = height - 50
                    chart_y_pos = y - img_height - 20
                
                c.drawImage(chart_path, x_offset, chart_y_pos, width=img_width, height=img_height, preserveAspectRatio=True, mask='auto')
                y = chart_y_pos - 20 
            else:
                c.drawString(50, y - 30, "(Overall Score chart not available)")
                y -= 50
        except Exception as img_e:
            logger.error(f"Error drawing chart to PDF: {img_e}", exc_info=True)
            c.drawString(50, y - 30, f"(Error loading chart: {img_e})")
            y -= 50

        y -= 30

        # --- NEW: AI Summary and Recommendations Section (after chart) ---
        c.setFont("Helvetica-Bold", 16)
        # Check if new page needed for this section
        # Calculate approximate height needed for AI insights (summary + recs + padding)
        # Assuming avg 2-3 lines for summary, 2-3 for recs
        ai_insights_approx_height = (3 * 12) + (3 * 12) + 50 # lines * font_size + padding
        if y < ai_insights_approx_height + 50: # Check if current y is too low
            c.showPage()
            y = height - 50

        c.drawString(50, y, "AI Insights & Recommendations:")
        y -= 20
        
        styles = getSampleStyleSheet()
        styleN = styles['Normal']
        styleN.fontSize = 10 
        styleN.leading = 12 

        p_summary = Paragraph(f"<b>Summary:</b> {summary_text}", styleN)
        text_width_summary, text_height_summary = p_summary.wrapOn(c, width - 100, height)
        if y - text_height_summary < 50: c.showPage(); y = height - 50 
        p_summary.drawOn(c, 50, y - text_height_summary)
        y -= (text_height_summary + 10)

        p_recs = Paragraph(f"<b>Recommendations:</b> {recommendations_text}", styleN)
        text_width_recs, text_height_recs = p_recs.wrapOn(c, width - 100, height)
        if y - text_height_recs < 50: c.showPage(); y = height - 50 
        p_recs.drawOn(c, 50, y - text_height_recs)
        y -= (text_height_recs + 20)


        # --- Skill Performance Section (moved below AI Insights) ---
        c.setFont("Helvetica-Bold", 16)
        if y < 150: 
            c.showPage()
            y = height - 50
        c.drawString(50, y, "Performance by Skill/Concept:")
        y -= 20
        
        styleN.fontSize = 11 
        styleN.leading = 14 

        sorted_skills = sorted(skill_performance.items(), key=lambda item: item[1]['score'])
        
        for skill, data in sorted_skills:
            score_line = f"{skill}: {data['correct']} / {data['total']} correct ({data['score']:.1f}%)"
            p_skill = Paragraph(score_line, styleN)
            text_width, text_height = p_skill.wrapOn(c, width - 100, height)

            if y - text_height < 70: 
                c.showPage()
                y = height - 50
            
            p_skill.drawOn(c, 70, y - text_height)
            y -= (text_height + 5)
        y -= 20

        # --- Detailed Quiz Questions & Answers Section ---
        c.setFont("Helvetica-Bold", 16)
        if y < 50: 
            c.showPage()
            y = height - 50
        c.drawString(50, y, "Detailed Quiz Questions & Answers:")
        y -= 20
        
        styleN.fontSize = 10 

        for idx, entry in enumerate(session["history"], 1):
            feedback_status = "N/A"
            explanation_content = "No explanation provided."

            if entry["feedback"]:
                feedback_lines = entry["feedback"].split('\n')
                judgment_line = next((line for line in feedback_lines if line.strip().startswith("Judgment:")), None)
                explanation_line = next((line for line in feedback_lines if line.strip().startswith("Explanation:")), None)
                
                if judgment_line:
                    feedback_status = judgment_line.replace("Judgment:", "").strip()
                if explanation_line:
                    explanation_content = explanation_line.replace("Explanation:", "").strip()

            lines_to_draw = [
                f"<b>Q{idx}</b> (Level {entry.get('level', 1)}, Skill: {entry.get('skill', 'N/A')}): {entry['question']}", 
                f"<b>Your Answer:</b> {entry['user_answer']}",
                f"<b>Correct Answer:</b> {entry['correct_answer']}",
                f"<b>Result:</b> {feedback_status}",
                f"<b>Explanation:</b> {explanation_content}"
            ]
            
            for line in lines_to_draw:
                p = Paragraph(line, styleN)
                text_width, text_height = p.wrapOn(c, width - 100, height)
                
                if y - text_height < 50: 
                    c.showPage()
                    y = height - 50
                
                p.drawOn(c, 50, y - text_height)
                y -= (text_height + 5)
            y -= 10 

        c.save()
        logger.debug(f"Skill performance breakdown: {json.dumps(skill_performance, indent=2)}")
        
        if os.path.exists(chart_path):
            os.remove(chart_path)
            logger.info(f"Cleaned up temporary chart file: {chart_path}")
            
        # Return AI insights along with filename
        return {
            "filename": filename,
            "ai_summary": summary_text,
            "ai_recommendations": recommendations_text
        }

    except Exception as e:
        logger.exception(f"Fatal error generating report for session {session.get('username', 'Unknown')}: {str(e)}")
        raise