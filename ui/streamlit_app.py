import os

import requests
import streamlit as st

API_URL = os.getenv("EXAMPREP_API_URL", "http://127.0.0.1:8000")
TIMEOUT = 90  # Gemini can take a while to reply

st.set_page_config(page_title="ExamPrep AI", page_icon="📚", layout="wide")

# The user's own messages sit on the right, the AI's on the left.
st.markdown(
    """
    <style>
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
        flex-direction: row-reverse;
        text-align: right;
    }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"])
        [data-testid="stChatMessageContent"] {
        flex: 0 1 auto;
        max-width: 75%;
        margin-left: auto;
        margin-right: 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------- session state ----------
def init_state():
    defaults = {
        "token": None,  # JWT; None means not logged in
        "email": None,
        "mode": "Chat",  # "Chat" or "Exam" (Exam needs a login)
        "messages": [],  # [{"role": "user"/"assistant", "content": "..."}]
        "session_id": None,  # str (uuid) for guests, int for logged-in users
        "exam": None,  # the exam being taken (questions only)
        "exam_result": None,  # the graded result being viewed
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_state()


# ---------- API helpers ----------
def error_text(response: requests.Response) -> str:
    """Extract a readable message from a FastAPI error response."""
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list) and detail:  # 422 validation errors come as a list
        first = detail[0]
        if isinstance(first, dict) and first.get("msg"):
            field = str(first["loc"][-1]) if first.get("loc") else "input"
            return f"{field}: {first['msg']}"
        return "Invalid input. Please check your data."
    return f"Request failed ({response.status_code})"


def api_request(
    method: str, path: str, **kwargs
) -> tuple[requests.Response | None, str | None]:
    """Every API call goes through here. Returns (response, error_message)."""
    headers = kwargs.pop("headers", {})
    if st.session_state.token:
        headers["Authorization"] = f"Bearer {st.session_state.token}"
    try:
        response = requests.request(
            method, f"{API_URL}{path}", headers=headers, timeout=TIMEOUT, **kwargs
        )
    except requests.exceptions.ConnectionError:
        return None, f"Cannot reach the API at {API_URL}. Is the server running?"
    except requests.exceptions.Timeout:
        return None, "The request timed out. Please try again."

    if response.status_code == 401 and st.session_state.token:
        logout()  # the token has expired
        return None, "Your session expired. Please log in again."
    if not response.ok:
        return None, error_text(response)
    return response, None


def logout():
    st.session_state.token = None
    st.session_state.email = None
    new_chat()
    new_exam()


def new_chat():
    st.session_state.messages = []
    st.session_state.session_id = None


def new_exam():
    st.session_state.exam = None
    st.session_state.exam_result = None


def load_session(session_id: int):
    response, error = api_request("GET", f"/chat/sessions/{session_id}")
    if response is None:
        st.sidebar.error(error)
        return
    data = response.json()
    st.session_state.session_id = data["id"]
    st.session_state.messages = [
        {"role": m["role"], "content": m["content"]} for m in data["messages"]
    ]


def open_exam(item: dict):
    """Open a past exam: its result if it was submitted, otherwise its questions."""
    if item["percentage"] is not None:
        response, error = api_request("GET", f"/exams/{item['id']}/result")
        if response is None:
            st.sidebar.error(error)
            return
        st.session_state.exam = None
        st.session_state.exam_result = response.json()
    else:
        response, error = api_request("GET", f"/exams/{item['id']}")
        if response is None:
            st.sidebar.error(error)
            return
        st.session_state.exam = response.json()
        st.session_state.exam_result = None


def send_message(text: str):
    """Send the message; on success add both user and assistant messages to history."""
    if st.session_state.token:
        path = "/chat/authenticated"
    else:
        path = "/chat/guest"
    payload = {"message": text, "session_id": st.session_state.session_id}

    response, error = api_request("POST", path, json=payload)
    if response is None:
        return error

    data = response.json()
    st.session_state.session_id = data["session_id"]
    st.session_state.messages.append({"role": "user", "content": text})
    st.session_state.messages.append({"role": "assistant", "content": data["reply"]})
    return None


# ---------- sidebar ----------
@st.dialog("Welcome to ExamPrep AI")
def auth_dialog():
    """Popup with Login and Register tabs, opened from the sidebar Login button."""
    login_tab, register_tab = st.tabs(["Login", "Register"])

    with login_tab:
        with st.form("login_form"):
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_password")
            submitted = st.form_submit_button("Login")
        if submitted:
            response, error = api_request(
                "POST", "/auth/login", json={"email": email, "password": password}
            )
            if response is None:
                st.error(error)
            else:
                st.session_state.token = response.json()["access_token"]
                st.session_state.email = email
                new_chat()  # guest chat is separate, start fresh after login
                st.rerun()  # rerun the whole app, which also closes the dialog

    with register_tab:
        with st.form("register_form"):
            email = st.text_input("Email", key="register_email")
            password = st.text_input(
                "Password", type="password", key="register_password"
            )
            st.caption("Password must be at least 8 characters.")
            submitted = st.form_submit_button("Create account")
        if submitted:
            _, error = api_request(
                "POST", "/auth/register", json={"email": email, "password": password}
            )
            if error:
                st.error(error)
            else:
                st.success("Account created. Now switch to the Login tab.")


def render_history():
    if st.sidebar.button("➕ New chat", use_container_width=True):
        new_chat()
        st.rerun()

    st.sidebar.subheader("History")
    response, error = api_request("GET", "/chat/sessions")
    if response is None:
        st.sidebar.error(error)
        return
    sessions = response.json()
    if not sessions:
        st.sidebar.caption("No chats yet.")
    for item in sessions:
        label = item["title"] or f"Chat #{item['id']}"
        is_current = item["id"] == st.session_state.session_id
        if st.sidebar.button(
            label,
            key=f"session_{item['id']}",
            use_container_width=True,
            type="primary" if is_current else "secondary",
        ):
            load_session(item["id"])
            st.rerun()


def render_exam_list():
    if st.sidebar.button("➕ New exam", use_container_width=True):
        new_exam()
        st.rerun()

    st.sidebar.subheader("My exams")
    response, error = api_request("GET", "/exams")
    if response is None:
        st.sidebar.error(error)
        return
    exams = response.json()
    if not exams:
        st.sidebar.caption("No exams yet.")

    current = st.session_state.exam or st.session_state.exam_result
    current_id = None
    if current:
        current_id = current.get("id", current.get("exam_id"))

    for item in exams:
        if item["percentage"] is None:
            status = "not submitted"
        else:
            status = f"{item['percentage']:g}%"
        if st.sidebar.button(
            f"{item['title']} · {status}",
            key=f"exam_{item['id']}",
            use_container_width=True,
            type="primary" if item["id"] == current_id else "secondary",
        ):
            open_exam(item)
            st.rerun()


def render_sidebar():
    st.sidebar.title("📚 ExamPrep AI")
    if st.session_state.token:
        st.sidebar.caption(f"Logged in as {st.session_state.email}")
        if st.sidebar.button("Logout", use_container_width=True):
            logout()
            st.rerun()
        st.sidebar.radio(
            "Mode",
            ["Chat", "Exam"],
            key="mode",
            horizontal=True,
            label_visibility="collapsed",
            format_func=lambda mode: {"Chat": "💬 Chat", "Exam": "📝 Exam"}[mode],
        )
        st.sidebar.divider()
        if st.session_state.mode == "Exam":
            render_exam_list()
        else:
            render_history()
    else:
        st.sidebar.info("You are chatting as a guest. History is not saved.")
        if st.sidebar.button("➕ New chat", use_container_width=True):
            new_chat()
            st.rerun()
        st.sidebar.caption("Log in to save your chats and take exams.")
        st.sidebar.divider()
        if st.sidebar.button("🔑 Login", use_container_width=True):
            auth_dialog()


# ---------- chat mode ----------
def render_chat():
    st.title("Study Assistant")
    if not st.session_state.messages:
        st.caption("Ask anything about your subject to get started.")

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("Type your question...")
    if prompt:
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                error = send_message(prompt)
            if error:
                st.error(error)
        if not error:
            st.rerun()  # refresh the sidebar history and redraw the messages


# ---------- exam mode ----------
def render_exam_creator():
    st.title("Practice Exam")
    st.caption(
        "Generate written exam questions on any topic, answer them, "
        "and get AI feedback."
    )
    with st.form("create_exam_form"):
        topic = st.text_input(
            "Topic", placeholder="e.g. Genetic Algorithm", max_chars=100
        )
        left, right = st.columns(2)
        num_questions = left.slider("Number of questions", 1, 10, 5)
        difficulty = right.selectbox("Difficulty", ["easy", "medium", "hard"], index=1)
        submitted = st.form_submit_button("Generate exam")

    if submitted:
        if len(topic.strip()) < 3:
            st.warning("Please enter a topic of at least 3 characters.")
            return
        with st.spinner("Writing your exam..."):
            response, error = api_request(
                "POST",
                "/exams",
                json={
                    "topic": topic,
                    "num_questions": num_questions,
                    "difficulty": difficulty,
                },
            )
        if response is None:
            st.error(error)
            return
        st.session_state.exam = response.json()
        st.session_state.exam_result = None
        st.rerun()


def render_exam_questions(exam: dict):
    st.title(exam["title"])
    st.caption(f"{exam['difficulty'].title()} · {exam['num_questions']} questions")

    answers_text: dict[int, str] = {}
    with st.form(f"answer_form_{exam['id']}"):
        for number, question in enumerate(exam["questions"], start=1):
            with st.chat_message("assistant"):
                st.markdown(f"**Q{number}.** {question['question_text']}")
            answers_text[question["id"]] = st.text_area(
                f"Answer to question {number}",
                key=f"answer_{question['id']}",
                height=120,
                placeholder="Write your answer here...",
                label_visibility="collapsed",
            )
        submitted = st.form_submit_button("Submit answers")

    if submitted:
        answers = [
            {"question_id": question_id, "answer_text": text.strip()}
            for question_id, text in answers_text.items()
        ]
        if any(not item["answer_text"] for item in answers):
            st.warning("Please answer every question before submitting.")
            return
        with st.spinner("Grading your answers..."):
            response, error = api_request(
                "POST", f"/exams/{exam['id']}/submit", json={"answers": answers}
            )
        if response is None:
            st.error(error)
            return
        st.session_state.exam_result = response.json()
        st.session_state.exam = None
        st.rerun()


def render_exam_result(result: dict):
    st.title(result["title"])
    left, right = st.columns(2)
    left.metric("Score", f"{result['total_score']} / {result['max_score']}")
    right.metric("Percentage", f"{result['percentage']:g}%")
    st.info(result["overall_feedback"])

    per_question_max = result["max_score"] // max(len(result["answers"]), 1)
    for number, item in enumerate(result["answers"], start=1):
        with st.chat_message("assistant"):
            st.markdown(f"**Q{number}.** {item['question_text']}")
        with st.chat_message("user"):
            st.markdown(item["user_answer"])
        with st.chat_message("assistant"):
            st.markdown(f"**Score: {item['score']} / {per_question_max}**")
            st.markdown(item["feedback"])
            with st.expander("Model answer"):
                st.markdown(item["model_answer"])


def render_exam_mode():
    if st.session_state.exam_result:
        render_exam_result(st.session_state.exam_result)
    elif st.session_state.exam:
        render_exam_questions(st.session_state.exam)
    else:
        render_exam_creator()


render_sidebar()
if st.session_state.token and st.session_state.mode == "Exam":
    render_exam_mode()
else:
    render_chat()
