import base64
import html
import json
import os
import re

import requests
import streamlit as st

API_URL = os.getenv("EXAMPREP_API_URL", "http://127.0.0.1:8000")
TIMEOUT = 90  # Gemini can take a while to reply

st.set_page_config(page_title="ExamPrep AI", page_icon="📚", layout="wide")

# Layout tweaks: user messages on the right and AI messages on the left (no avatar
# icons), plain history items without background or border, and a profile card.
st.markdown(
    """
    <style>
    [data-testid="stChatMessageAvatarUser"],
    [data-testid="stChatMessageAvatarAssistant"] {
        display: none;
    }
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
    [class*="st-key-session_"] button,
    [class*="st-key-exam_"] button {
        background: transparent;
        border: none;
        box-shadow: none;
        justify-content: flex-start;
        padding-left: 0;
    }
    [class*="st-key-session_"] button:hover,
    [class*="st-key-exam_"] button:hover {
        background: transparent;
        opacity: 0.7;
    }
    [class*="st-key-session_"] button > div,
    [class*="st-key-exam_"] button > div {
        justify-content: flex-start;
    }
    [class*="st-key-session_"] button p,
    [class*="st-key-exam_"] button p {
        text-align: left;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    [class*="st-key-session_cur_"] button p,
    [class*="st-key-exam_cur_"] button p {
        font-weight: 700;
    }
    [data-testid="stSidebarUserContent"] > div > [data-testid="stVerticalBlock"] {
        min-height: calc(100vh - 8rem);
    }
    [data-testid="stSidebarContent"],
    [data-testid="stSidebarUserContent"],
    [data-testid="stSidebarUserContent"] > div,
    [data-testid="stSidebarUserContent"] > div > [data-testid="stVerticalBlock"] {
        background-color: inherit;
    }
    [data-testid="stSidebarUserContent"] > div > [data-testid="stVerticalBlock"]
        > [data-testid="stLayoutWrapper"]:has(> .st-key-profile) {
        position: sticky;
        bottom: 0;
        margin-top: auto;
        padding: 0.5rem 0;
        background-color: inherit;
        z-index: 1;
    }
    .st-key-profile button {
        justify-content: flex-start;
    }
    .st-key-profile button::before {
        content: "";
        flex: none;
        width: 28px;
        height: 28px;
        border-radius: 50%;
        background: var(--avatar-image) center / cover no-repeat;
        margin-right: 0.6rem;
    }
    .st-key-profile button p {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


AVATAR_COLORS = ["#E4572E", "#17BEBB", "#7B6CF6", "#F2A541", "#3D9970", "#D6457E"]


def avatar_uri(email: str) -> str:
    """A round avatar image (SVG) showing the first letter of the email name."""
    name = email.split("@")[0].strip()
    letter = next((char for char in name if char.isalnum()), "?").upper()
    color = AVATAR_COLORS[ord(letter) % len(AVATAR_COLORS)]
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" '
        'viewBox="0 0 64 64">'
        f'<circle cx="32" cy="32" r="32" fill="{color}"/>'
        '<text x="32" y="32" text-anchor="middle" dominant-baseline="central" '
        'font-family="Arial, sans-serif" font-size="30" font-weight="600" '
        f'fill="#ffffff">{html.escape(letter)}</text></svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def escape_markdown(text: str) -> str:
    """Backslash-escape characters that Streamlit's markdown would interpret."""
    return re.sub(r"([\\`*_\[\]()#~:$<>])", r"\\\1", text)


def render_profile_card(email: str):
    """Bottom-of-sidebar card: round letter avatar and name; click for email + Logout."""
    name = email.split("@")[0]
    st.sidebar.markdown(
        f'<style>.st-key-profile {{ --avatar-image: url("{avatar_uri(email)}"); }}</style>',
        unsafe_allow_html=True,
    )
    with st.sidebar.container(key="profile"):
        with st.popover(escape_markdown(name), use_container_width=True):
            st.caption("Signed in as")
            st.text(email)
            if st.button("Logout", key="logout", use_container_width=True):
                logout()
                st.rerun()


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


def stream_message(text: str) -> str | None:
    """Send the message and stream the reply into the page as it arrives.

    Returns an error message, or None on success. On success both the user message
    and the full reply are added to the chat history.
    """
    if st.session_state.token:
        path = "/chat/authenticated/stream"
    else:
        path = "/chat/guest/stream"
    payload = {"message": text, "session_id": st.session_state.session_id}

    response, error = api_request("POST", path, json=payload, stream=True)
    if response is None:
        return error
    response.encoding = "utf-8"

    problem: dict[str, str | None] = {"message": None}

    def pieces():
        """Yield the text pieces of the NDJSON stream; remember an error if one comes."""
        try:
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                event = json.loads(line)
                if event["type"] == "delta":
                    yield event["text"]
                elif event["type"] == "error":
                    problem["message"] = event["detail"]
                    return
        except requests.exceptions.RequestException:
            problem["message"] = "The connection was lost while the reply was coming."
        finally:
            response.close()

    reply = str(st.write_stream(pieces()))
    if problem["message"]:
        return problem["message"]

    session_id = response.headers["X-Session-Id"]
    st.session_state.session_id = (
        int(session_id) if st.session_state.token else session_id
    )
    st.session_state.messages.append({"role": "user", "content": text})
    st.session_state.messages.append({"role": "assistant", "content": reply})
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
            confirm = st.text_input(
                "Confirm password", type="password", key="register_confirm"
            )
            st.caption("Password must be at least 8 characters.")
            submitted = st.form_submit_button("Create account")
        if submitted and password != confirm:
            st.error("Passwords do not match.")
        elif submitted:
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
            key=f"session_cur_{item['id']}" if is_current else f"session_{item['id']}",
            use_container_width=True,
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
        is_current = item["id"] == current_id
        if st.sidebar.button(
            f"{item['title']} · {status}",
            key=f"exam_cur_{item['id']}" if is_current else f"exam_{item['id']}",
            use_container_width=True,
        ):
            open_exam(item)
            st.rerun()


def render_sidebar():
    st.sidebar.title("📚 ExamPrep AI")
    if st.session_state.token:
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
        render_profile_card(st.session_state.email)
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
            error = stream_message(prompt)
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
