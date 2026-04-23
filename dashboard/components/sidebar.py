"""Provide shared Streamlit dashboard UI and API helpers for the network monitoring project."""

import streamlit as st


def collapse_sidebar_on_page_load() -> None:
    """Handle collapse sidebar on page load for shared Streamlit dashboard UI and API helpers.

    Returns:
        None. The routine is executed for its side effects.
    """
    st.iframe(
        """
        <script>
        const findCollapseButton = () => (
          window.parent.document.querySelector('button[aria-label="Close sidebar"]') ||
          window.parent.document.querySelector('button[aria-label="Collapse sidebar"]') ||
          window.parent.document.querySelector('[data-testid="stSidebarCollapseButton"] button')
        );

        let attempts = 0;
        const timer = setInterval(() => {
          const button = findCollapseButton();
          if (button) {
            button.click();
            clearInterval(timer);
          }
          attempts += 1;
          if (attempts > 20) {
            clearInterval(timer);
          }
        }, 80);
        </script>
        """,
        width="content",
        height="content",
    )
