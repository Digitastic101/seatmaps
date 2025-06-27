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

price_only_mode = st.checkbox("💸 Only update seat prices (leave availability unchanged)")

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
    elif not seat_range_input and not price_only_mode:
        st.error("Please enter seat ranges OR tick 'Only update seat prices'.")
    else:
        try:
            raw_data = uploaded_file.read().decode("utf-8")
            seat_data = json.loads(raw_data)

            all_available_seats = set()
            debug_table = []

            if seat_range_input:
                cleaned_input = re.sub(r"\b([A-Za-z])\s+(\d+)\b", r"\1\2", seat_range_input.strip())
                cleaned_input = re.sub(r"(\d+)\s*-\s*(\d+)", r"\1-\2", cleaned_input)
                cleaned_input = re.sub(r"([A-Za-z]+)(\d+)-(\d+)", lambda m: f"{m.group(1)}{m.group(2)}-{m.group(1)}{m.group(3)}", cleaned_input)

                pattern = re.compile(
                    r"(?P<section>[A-Za-z0-9 ]+?)\s+(?P<start>[A-Za-z]\d+)(?:\s*to\s*|\s*-\s*|-)(?P<end>[A-Za-z]?[0-9]+)",
                    re.IGNORECASE
                )
                matches = pattern.findall(cleaned_input)

                for section_name, start_seat, end_seat in matches:
                    normalized_section = section_name.strip().lower()
                    seat_range = generate_seat_range(start_seat.upper(), end_seat.upper())
                    for s in seat_range:
                        all_available_seats.add((normalized_section, s.upper()))
                        debug_table.append((normalized_section, s.upper()))

            # 🔁 Process seat updates
            for section in seat_data.values():
                if 'rows' in section:
                    parent_section_name = section.get('section_name', '').strip().lower()
                    for row in section['rows'].values():
                        for seat in row['seats'].values():
                            seat_number = seat['number'].upper()
                            key = (parent_section_name, seat_number)

                            # 🔧 PRICE-ONLY mode: update all 'av' seats OR matched ones
                            if price_only_mode:
                                if (not seat_range_input and seat.get('status') == 'av') or (seat_range_input and key in all_available_seats):
                                    if price_input.strip():
                                        seat['price'] = price_input.strip()
                                        matched_seats_output.append(f"{section.get('section_name', '')} {seat_number}")
                            else:
                                # 🔧 AVAILABILITY update mode (range required)
                                if seat_range_input:
                                    if key in all_available_seats:
                                        seat['status'] = 'av'
                                        matched_seats_output.append(f"{section.get('section_name', '')} {seat_number}")
                                        if price_input.strip():
                                            seat['price'] = price_input.strip()
                                    else:
                                        seat['status'] = 'uav'

            # ✅ Output results
            updated_json = json.dumps(seat_data, indent=2)
            st.success("✅ Seat map updated successfully!")

            st.markdown("### ✅ Seats updated:")
            if matched_seats_output:
                st.write(", ".join(matched_seats_output))
            else:
                st.warning("No matching or available seats found to update.")

            st.download_button(
                label="Download Updated JSON",
                data=updated_json,
                file_name="updated_seatmap.json",
                mime="application/json"
            )

            if seat_range_input:
                st.markdown("### 🔍 Parsed Input Ranges")
                st.table(debug_table)

        except Exception as e:
            st.error(f"❌ Error: {e}")
