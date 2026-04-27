"""Define module logic for `dashboard/components/sidebar.py`.

This module contains project-specific implementation details.
"""

import streamlit.components.v1 as components


def collapse_sidebar_on_page_load() -> None:
    """Collapse sidebar on initial page load.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    components.html(
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
        height=0,
        width=0,
    )
