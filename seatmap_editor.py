import streamlit as st
import json
import re
from io import StringIO

st.title("🎭 Seat Map Availability Editor")

# Session state setup
if 'seat_range_input' not in st.session_state:
    st.session_state.seat_range_input = ''
if 'price_input' not in st.session_state:
    st.session_state.price_input = ''
if 'uploaded_file' not in st.session_state:
    st.session_state.uploaded_file = None

uploaded_file = st.file_uploader("Upload your seat map JSON file", type=["json"], key="uploaded_file")

seat_range_input = st.text_input(
    "Enter seat ranges (e.g. Stalls O23 to O51, Stalls O 23-51, Dress Circle D 3 - D 6)",
    placeholder="Stalls O23 to O51, Dress Circle D3-D6",
    key="seat_range_input"
)

price_input = st.text_input(
    "Enter new price for all seats (optional)",
    placeholder="e.g. 65",
    key="price_input"
)

col1, col2 = st.columns(2)
run_process = col1.button("▶️ Go")
reset = col2.button("🔄 Reset")

def generate_seat_range(start, end):
    row_match = re.match(r"(\D+)", start)
    if row_match:
        row = row_match.group(1)
    else:
        raise ValueError("Invalid row format in seat number")
    start_num = int(re.search(r"\d+", start).group())
    end_num = int(re.search(r"\d+", end).group())
    return [f"{row}{i}" for i in range(start_num, end_num + 1)]

if reset:
    st.session_state.seat_range
