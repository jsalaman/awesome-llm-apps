"""
Research Planner using Gemini Interactions API - demonstrates stateful conversations, model mixing, and background execution.
"""

import time
import re
import streamlit as st
from google import genai

# Constants
MODEL_PLANNER = "gemini-3-flash-preview"
MODEL_RESEARCH_AGENT = "deep-research-pro-preview-12-2025"
MODEL_SYNTHESIS = "gemini-3-pro-preview"
MODEL_IMAGE = "gemini-3-pro-image-preview"
POLLING_INTERVAL = 3  # seconds
TIMEOUT = 300  # seconds

def get_text(outputs: list) -> str:
    """Helper to extract text from interaction outputs."""
    if not outputs:
        return ""
    return "\n".join(o.text for o in outputs if hasattr(o, 'text') and o.text) or ""

def parse_tasks(text: str) -> list[dict]:
    """Parses the research plan text into a list of tasks."""
    tasks = []
    # Regex to find numbered items (e.g., "1. Task Name - Details")
    pattern = r'^(\d+)[\.\)\-]\s*(.+?)(?=\n\d+[\.\)\-]|\n\n|\Z)'
    matches = re.finditer(pattern, text, re.MULTILINE | re.DOTALL)
    
    for match in matches:
        num = match.group(1)
        # Clean up the task text by removing newlines and extra spaces
        task_text = match.group(2).strip().replace('\n', ' ')
        tasks.append({"num": num, "text": task_text})

    return tasks

def wait_for_completion(client: genai.Client, interaction_id: str, timeout: int = TIMEOUT):
    """Waits for an interaction to complete with a progress bar."""
    progress_bar = st.progress(0)
    status_text = st.empty()
    elapsed = 0

    while elapsed < timeout:
        try:
            interaction = client.interactions.get(interaction_id)
            if interaction.status != "in_progress":
                progress_bar.progress(100)
                status_text.empty()
                return interaction

            # Update progress bar (cap at 90% while waiting)
            progress_val = min(90, int((elapsed / timeout) * 100))
            progress_bar.progress(progress_val)
            status_text.text(f"⏳ Researching... ({elapsed}s elapsed)")

            time.sleep(POLLING_INTERVAL)
            elapsed += POLLING_INTERVAL
        except Exception as e:
            st.error(f"Error checking status: {e}")
            break

    return client.interactions.get(interaction_id)

def init_session_state():
    """Initializes session state variables."""
    defaults = {
        "plan_id": None,
        "plan_text": None,
        "tasks": [],
        "research_id": None,
        "research_text": None,
        "synthesis_text": None,
        "infographic": None
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def reset_session_state():
    """Resets session state variables."""
    st.session_state.plan_id = None
    st.session_state.plan_text = None
    st.session_state.tasks = []
    st.session_state.research_id = None
    st.session_state.research_text = None
    st.session_state.synthesis_text = None
    st.session_state.infographic = None
    st.rerun()

def main():
    st.set_page_config(page_title="Research Planner", page_icon="🔬", layout="wide")
    st.title("🔬 AI Research Planner & Executor Agent (Gemini Interactions API) ✨")

    init_session_state()

    with st.sidebar:
        api_key = st.text_input("🔑 Google API Key", type="password")
        if st.button("Reset"):
            reset_session_state()

        st.markdown("""
        ### How It Works
        1. **Plan** → Gemini 3 Flash creates research tasks
        2. **Select** → Choose which tasks to research
        3. **Research** → Deep Research Agent investigates
        4. **Synthesize** → Gemini 3 Pro writes report + TL;DR infographic
        
        Each phase chains via `previous_interaction_id` for context.
        """)

    if not api_key:
        st.info("👆 Enter API key to start")
        st.stop()

    client = genai.Client(api_key=api_key)

    # Phase 1: Plan
    research_goal = st.text_area("📝 Research Goal", placeholder="e.g., Research B2B HR SaaS market in Germany")

    if st.button("📋 Generate Plan", disabled=not research_goal, type="primary"):
        with st.spinner("Planning..."):
            try:
                interaction = client.interactions.create(
                    model=MODEL_PLANNER,
                    input=f"Create a numbered research plan for: {research_goal}\n\nFormat: 1. [Task] - [Details]\n\nInclude 5-8 specific tasks.",
                    tools=[{"type": "google_search"}],
                    store=True
                )

                st.session_state.plan_id = interaction.id
                st.session_state.plan_text = get_text(interaction.outputs)
                st.session_state.tasks = parse_tasks(st.session_state.plan_text)

            except Exception as e:
                st.error(f"Error during planning: {e}")

    # Phase 2: Select & Research
    if st.session_state.plan_text:
        st.divider()
        st.subheader("🔍 Select Tasks & Research")

        # Task Selection
        selected_tasks = []
        for task in st.session_state.tasks:
            is_selected = st.checkbox(f"**{task['num']}.** {task['text']}", value=True, key=f"t{task['num']}")
            if is_selected:
                selected_tasks.append(f"{task['num']}. {task['text']}")

        st.caption(f"✅ {len(selected_tasks)}/{len(st.session_state.tasks)} selected")

        if st.button("🚀 Start Deep Research", type="primary", disabled=not selected_tasks):
            with st.spinner("Researching (2-5 min)..."):
                try:
                    tasks_str = "\n\n".join(selected_tasks)
                    interaction = client.interactions.create(
                        agent=MODEL_RESEARCH_AGENT,
                        input=f"Research these tasks thoroughly with sources:\n\n{tasks_str}",
                        previous_interaction_id=st.session_state.plan_id,
                        background=True,
                        store=True
                    )

                    interaction = wait_for_completion(client, interaction.id)
                    st.session_state.research_id = interaction.id
                    st.session_state.research_text = get_text(interaction.outputs) or f"Status: {interaction.status}"
                    st.rerun()

                except Exception as e:
                    st.error(f"Error during research: {e}")

    if st.session_state.research_text:
        st.divider()
        st.subheader("📄 Research Results")
        st.markdown(st.session_state.research_text)

    # Phase 3: Synthesis + Infographic
    if st.session_state.research_id:
        if st.button("📊 Generate Executive Report", type="primary"):
            with st.spinner("Synthesizing report..."):
                try:
                    interaction = client.interactions.create(
                        model=MODEL_SYNTHESIS,
                        input=f"Create executive report with Summary, Findings, Recommendations, Risks:\n\n{st.session_state.research_text}",
                        previous_interaction_id=st.session_state.research_id,
                        store=True
                    )
                    st.session_state.synthesis_text = get_text(interaction.outputs)
                except Exception as e:
                    st.error(f"Error during synthesis: {e}")
                    st.stop()

            with st.spinner("Creating TL;DR infographic..."):
                try:
                    response = client.models.generate_content(
                        model=MODEL_IMAGE,
                        contents=f"Create a whiteboard summary infographic for the following: {st.session_state.synthesis_text}"
                    )

                    # Look for inline data in the response parts
                    if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                        for part in response.candidates[0].content.parts:
                            if hasattr(part, 'inline_data') and part.inline_data:
                                st.session_state.infographic = part.inline_data.data
                                break
                except Exception as e:
                    st.warning(f"Infographic generation failed (optional step): {e}")
            st.rerun()

    if st.session_state.synthesis_text:
        st.divider()
        st.markdown("## 📊 Executive Report")

        # TL;DR Infographic at the top
        if st.session_state.infographic:
            st.markdown("### 🎨 TL;DR")
            st.image(st.session_state.infographic, use_container_width=True)
            st.divider()

        st.markdown(st.session_state.synthesis_text)
        st.download_button("📥 Download Report", st.session_state.synthesis_text, "research_report.md", "text/markdown")

    st.divider()
    st.caption("[Gemini Interactions API](https://ai.google.dev/gemini-api/docs/interactions)")

if __name__ == "__main__":
    main()
