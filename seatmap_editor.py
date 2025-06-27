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

# ✅ Checkbox to update price only
price_only_mode = st.checkbox("💸 Only update seat prices (leave availability unchanged)")

# ✅ Button to run the logic
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

            # Step 1: Normalise seat range input
            cleaned_input = re.sub(r"\b([A-Za-z])\s+(\d+)\b", r"\1\2", seat_range_input.strip())
            cleaned_input = re.sub(r"(\d+)\s*-\s*(\d+)", r"\1-\2", cleaned_input)
            cleaned_input = re.sub(r"([A-Za-z]+)(\d+)-(\d+)", lambda m: f"{m.group(1)}{m.group(2)}-{m.group(1)}{m.group(3)}", cleaned_input)

            # ✅ Fixed regex pattern
            pattern = re.compile(r"(?P<section>[A-Za-z0-9 ]+?)\s+(?P<start>[A-Za-z]\d+)(?:\s*to\s*|\s*-\s*|-)(?P<end>[A-Za-z]?[0-9]+)", re.IGNORECASE)
            matches = pattern.findall(cleaned_input)

            all_available_seats = set()
            debug_table = []

            if not matches:
                st.error("Please enter valid seat ranges like 'Stalls O23 to O51', 'Stalls O23-O51', or 'Stalls O 23-51'.")
            else:
                for section_name, start_seat, end_seat in matches:
                    normalized_section = section_name.strip().lower()
                    seat_range = generate_seat_range(start_seat.upper(), end_seat.upper())
                    for s in seat_range:
                        all_available_seats.add((normalized_section, s.upper()))
                        debug_table.append((normalized_section, s.upper()))

                # 🔁 Process each seat
                for section in seat_data.values():
                    if 'rows' in section:
                        parent_section_name = section.get('section_name', '').strip().lower()
                        for row in section['rows'].values():
                            for seat in row['seats'].values():
                                seat_number = seat['number'].upper()
                                key = (parent_section_name, seat_number)
                                if price_only_mode:
                                    if price_input.strip() and key in all_available_seats:
                                        seat['price'] = price_input.strip()
                                        matched_seats_output.append(f"{section.get('section_name', '')} {seat_number}")
                                else:
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

                st.markdown("### ✅ Seats marked as available or updated:")
                if matched_seats_output:
                    st.write(", ".join(matched_seats_output))
                else:
                    st.warning("No matching seats found for the provided input.")

                st.download_button(
                    label="Download Updated JSON",
                    data=updated_json,
                    file_name="updated_seatmap.json",
                    mime="application/json"
                )

                st.markdown("### 🔍 Parsed Input Ranges")
                st.table(debug_table)

        except Exception as e:
            st.error(f"❌ Error: {e}")
