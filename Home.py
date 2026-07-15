import streamlit as st
from page_modules.tickets import render as render_tickets
from page_modules.assets import render as render_assets

st.set_page_config(
    page_title="KACE SMA Intelligence Portal",
    page_icon=":shield:",
    layout="wide",
)


def render_home():
    st.title("KACE SMA Intelligence Portal")
    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        st.page_link(tickets_page, label="Ticket Info", use_container_width=True)
        st.info(
            "Query the KACE **ticket** database using natural language.\n\n"
            "Ask about open tickets, queue counts, statuses, and more."
        )

    with col2:
        st.page_link(assets_page, label="Asset Info", use_container_width=True)
        st.info(
            "Query the KACE **asset** database using natural language.\n\n"
            "Ask about computers, cost accounts, assigned users, and more."
        )

    st.markdown("---")
    st.caption("Select a page above or use the sidebar to navigate between apps.")


home_page = st.Page(render_home, title="Home", url_path="home", default=True)
tickets_page = st.Page(render_tickets, title="Ticket Info", url_path="tickets")
assets_page = st.Page(render_assets, title="Asset Info", url_path="assets")

pg = st.navigation([home_page, tickets_page, assets_page])
pg.run()