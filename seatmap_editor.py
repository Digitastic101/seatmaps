import streamlit as st
import json
import re
from io import StringIO

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

run_process = st.button("▶️ Go")

def generate_seat_range(start, end):
    row_match = re.match(r"(\D+)", start)
    if row_match:
        row = row_match.group(1)
    else:
        raise ValueError("Invalid row format in seat number")
    start_num = int(re.search(r"\d+", start).group())
    end_num = int(re.search(r"\d+", end).group())
    return [f"{row}{i}" for i in range(start_num, end_num + 1)]

if uploaded_file and run_process:
    if not seat_range_input:
        st.error("Please enter seat ranges before pressing Go.")
    else:
        try:
            # Load the uploaded JSON
            raw_data = uploaded_file.read().decode("utf-8")
            seat_data = json.loads(raw_data)

            # Normalize all spacing formats
            cleaned_input = re.sub(r"(\D)\s+(\d+)", r"\1\2", seat_range_input.strip())  # 'O 23' -> 'O23'
            cleaned_input = re.sub(r"(\d+)\s*-\s*(\d+)", r"\1-\2", cleaned_input)  # '23 - 51' -> '23-51'
            cleaned_input = re.sub(r"(\D+)(\d+)-(\d+)", lambda m: f"{m.group(1)}{m.group(2)}-{m.group(1)}{m.group(3)}", cleaned_input)  # 'O23-51' -> 'O23-O51'

            # Parse multiple seat ranges
            all_available_seats = set()
            pattern = re.compile(r"(?P<section>[\w\s]+?)\s+(?P<start>\w+)(?:\s*to\s*|\s*-\s*|-)(?P<end>\w+)", re.IGNORECASE)
            matches = pattern.findall(cleaned_input)

            if not matches:
                st.error("Please enter valid seat ranges like 'Stalls O23 to O51', 'Stalls O23-O51', or 'Stalls O 23-51'.")
            else:
                for section_name, start_seat, end_seat in matches:
                    seat_range = generate_seat_range(start_seat.upper(), end_seat.upper())
                    all_available_seats.update((section_name.strip().lower(), s.upper()) for s in seat_range)

                # Update all seat statuses and prices
                for section in seat_data.values():
                    if 'rows' in section:
                        parent_section_name = section.get('section_name', '').strip().lower()
                        for row in section['rows'].values():
                            for seat in row['seats'].values():
                                seat_number = seat['number'].upper()
                                if (parent_section_name, seat_number) in all_available_seats:
                                    seat['status'] = 'av'
                                else:
                                    seat['status'] = 'uav'
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
