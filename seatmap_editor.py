import streamlit as st
import json
import re
from io import StringIO

st.title("🎭 Seat Map Availability Editor")

uploaded_file = st.file_uploader("Upload your seat map JSON file", type=["json"])

seat_range_input = st.text_input(
    "Enter seat ranges (e.g. Stalls O23 to O51, Dress Circle D3 to D6)",
    placeholder="Stalls O23 to O51, Dress Circle D3 to D6"
)

price_input = st.text_input(
    "Enter new price for all seats (optional)",
    placeholder="e.g. 65"
)

col1, col2 = st.columns(2)
run_process = col1.button("▶️ Go")
reset = col2.button("🔄 Reset")

def generate_seat_range(start, end):
    row = re.match(r"(\D+)", start).group(1)
    start_num = int(re.search(r"\d+", start).group())
    end_num = int(re.search(r"\d+", end).group())
    return [f"{row}{i}" for i in range(start_num, end_num + 1)]

if reset:
    st.experimental_rerun()

if uploaded_file and run_process:
    if not seat_range_input:
        st.error("Please enter seat ranges before pressing Go.")
    else:
        try:
            # Load the uploaded JSON
            raw_data = uploaded_file.read().decode("utf-8")
            seat_data = json.loads(raw_data)

            # Parse multiple seat ranges
            all_available_seats = set()
            pattern = re.compile(r"(?P<section>[\w\s]+)\s+(?P<start>\w+?)\s+to\s+(?P<end>\w+)", re.IGNORECASE)
            matches = pattern.findall(seat_range_input.strip())

            if not matches:
                st.error("Please enter valid seat ranges like 'Stalls O23 to O51, Dress Circle D3 to D6'.")
            else:
                for section_name, start_seat, end_seat in matches:
                    seat_range = generate_seat_range(start_seat.upper(), end_seat.upper())
                    all_available_seats.update((section_name.strip().lower(), s) for s in seat_range)

                # Update all seat statuses and prices
                for section in seat_data.values():
                    if 'rows' in section:
                        parent_section_name = section.get('section_name', '').strip().lower()
                        for row in section['rows'].values():
                            for seat in row['seats'].values():
                                seat_number = seat['number'].upper()
                                seat['status'] = 'av' if (parent_section_name, seat_number) in all_available_seats else 'uav'
                                if price_input.strip():
                                    seat['price'] = price_input.strip()

                # Save updated JSON
                updated_json = json.dumps(seat_data, indent=2)
                st.success("✅ Seat map updated successfully!")
                st.download_button(
                    label="Download Updated JSON",
                    data=updated_json,
                    file_name="updated_seatmap.json",
                    mime="application/json"
                )

        except Exception as e:
            st.error(f"❌ Error: {e}")
