import streamlit as st
import json, re, itertools

st.title("🎭 Seat Map Availability Editor")

uploaded_file = st.file_uploader("Upload your seat map JSON file", type=["json"])

def extract_row_and_number(seat_label):
    match = re.match(r"(ROW\s*\d+\s*-\s*)\s*(\d+)", seat_label.strip(), re.I)
    if match:
        return match.group(1).strip(), int(match.group(2))
    return None, None

def compress_ranges(seat_numbers):
    seat_numbers.sort()
    grouped = []
    for _, group in itertools.groupby(enumerate(seat_numbers), lambda x: x[1] - x[0]):
        block = list(group)
        start = block[0][1]
        end = block[-1][1]
        grouped.append((start, end))
    return grouped

# ─── Show available seats immediately on upload ─────────────
if uploaded_file:
    try:
        seat_data = json.loads(uploaded_file.read().decode("utf-8"))

        st.success("✅ Seat map loaded successfully!")

        st.markdown("### 🪑 Copy-Paste Friendly Available Seat Ranges")

        output_lines = []

        for section in seat_data.values():
            section_name = section.get("section_name", "Unknown Section")
            if "rows" not in section:
                continue

            row_map = {}

            for row in section["rows"].values():
                for seat in row["seats"].values():
                    if seat.get("status", "").lower() == "av":
                        seat_label = seat.get("number", "").strip()
                        row_prefix, seat_number = extract_row_and_number(seat_label)
                        if row_prefix and seat_number:
                            row_map.setdefault((section_name, row_prefix), []).append(seat_number)

            for (section_name, row_prefix), seat_nums in row_map.items():
                ranges = compress_ranges(seat_nums)
                for start, end in ranges:
                    if start == end:
                        output_lines.append(f"{section_name} {row_prefix} {start}")
                    else:
                        output_lines.append(f"{section_name} {row_prefix} {start}-{end}")

        if output_lines:
            copy_text = ", ".join(output_lines)
            st.text_area("📋 Paste this into 'Enter seat ranges':", value=copy_text, height=200)
        else:
            st.info("No available seats found.")

    except Exception as e:
        st.error(f"❌ Error reading file: {e}")
