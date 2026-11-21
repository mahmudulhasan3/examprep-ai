import os

import requests
import streamlit as st

API_URL = os.getenv("EXAMPREP_API_URL", "http://127.0.0.1:8000")
TIMEOUT = 60  # Gemini can take a while to reply

st.set_page_config(page_title="ExamPrep AI", page_icon="📚", layout="wide")


# ---------- session state ----------
def init_state():
    defaults = {
        "token": None,  # JWT; None means not logged in
        "email": None,
        "messages": [],  # [{"role": "user"/"assistant", "content": "..."}]
        "session_id": None,  # str (uuid) for guests, int for logged-in users
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
    if detail:  # 422 validation errors come back as a list
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


def new_chat():
    st.session_state.messages = []
    st.session_state.session_id = None


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


def render_sidebar():
    st.sidebar.title("📚 ExamPrep AI")
    if st.session_state.token:
        st.sidebar.caption(f"Logged in as {st.session_state.email}")
        if st.sidebar.button("Logout", use_container_width=True):
            logout()
            st.rerun()
        st.sidebar.divider()
        render_history()
    else:
        st.sidebar.info("You are chatting as a guest. History is not saved.")
        if st.sidebar.button("➕ New chat", use_container_width=True):
            new_chat()
            st.rerun()
        st.sidebar.divider()
        if st.sidebar.button("🔑 Login", use_container_width=True):
            auth_dialog()


# ---------- main chat area ----------
def render_chat():
    st.title("Examprep AI")
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


render_sidebar()
render_chat()
