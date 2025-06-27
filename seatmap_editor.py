import streamlit as st
import json
import re

st.title("🎭 Seat Map Availability Editor")

uploaded_file = st.file_uploader("Upload your seat map JSON file", type=["json"])

seat_range_input = st.text_input(
    "Enter seat ranges (e.g. Stalls O23 to O51, Stalls O 23-51, Dress Circle D 3 - D 6)",
    placeholder="Stalls O23 to O51, Dress Circle D3-D6"
)

price_input = st.text_input(
    "Enter new price for all seats (optional)",
    placeholder="e.g. 65"
)

# ✅ Checkbox for price-only mode
price_only_mode = st.checkbox("💸 Only update seat prices (leave availability unchanged)")

# ✅ Button to run the update
if st.button("▶️ Go"):
    matched_seats_output = []

    def generate_seat_range(start, end):
        row_match = re.match(r"(\D+)", start)
        if row_match:
            row = row_match.group(1)
        else:
            raise ValueError("Invalid row format in seat number")
        start_num = int(re.search(r"\d+", start).group())
        end_num = int(re.search(r"\d+", end).group())
        return [f"{row}{i}" for i in range(start_num, end_num + 1)]

    if not uploaded_file:
        st.error("Please upload a seat map JSON file.")
    elif not seat_range_input:
        st.error("Please enter seat ranges before pressing Go.")
    else:
        try:
            raw_data = uploaded_file.read().decode("utf-8")
            seat_data = json.loads(raw_data)

            # Clean and normalize input
            cleaned_input = re.sub(r"\b([A-Za-z])\s+(\d+)\b", r"\1\2", seat_range_input.strip())
            cleaned_input = re.sub(r"(\d+)\s*-\s*(\d+)", r"\1-\2", cleaned_input)
            cleaned_input = re.sub(r"([A-Za-z]+)(\d+)-(\d+)", lambda m: f"{m.group(1)}{m.group(2)}-{m.group(1)}{m.group(3)}", cleaned_input)

            pattern = re.compile(r"(?P<section>[A-Za-z0-9 ]+?)\s+(?P<start>[A-Za-z]\d+)(?:\s*to\s*|\s*-\s*|-
