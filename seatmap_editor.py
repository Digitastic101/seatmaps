import streamlit as st
import json, re, itertools

st.title("🎭 Seat Map Availability Editor")

uploaded_file = st.file_uploader("Upload your seat map JSON file", type=["json"])

seat_range_input = st.text_input(
    "Enter seat ranges (e.g. Stalls C23-C28, Rausing Circle ROW 3 - 89-93)",
    placeholder="Stalls C23-C28, Rausing Circle ROW 3 - 89-93"
)

price_input = st.text_input(
    "Enter new price for all seats (optional)",
    placeholder="e.g. 65"
)

price_only_mode = st.checkbox("💸 Only update seat prices (leave availability unchanged)")

def extract_row_and_number(seat_label):
    # Try "ROW 3 - 67" format
    match = re.match(r"(ROW\s*\d+\s*-\s*)\s*(\d+)", seat_label.strip(), re.I)
    if match:
        return match.group(1).strip(), int(match.group(2))
    # Try classic format like C23
    match = re.match(r"([A-Z]+)(\d+)", seat_label.strip(), re.I)
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

def sort_key(row_prefix):
    match = re.search(r"(\d+)", row_prefix)
    if match:
        return (0, int(match.group(1)))  # numeric row (e.g. ROW 1 -)
    return (1, row_prefix.upper())       # text row (e.g. A, B, C)

if uploaded_file:
    try:
        seat_data = json.loads(uploaded_file.read().decode("utf-8"))

        st.success("✅ Seat map loaded successfully!")

        st.markdown("### 🪑 Copy-Paste Friendly Available Seat Ranges")

        output_lines = []
        row_map = {}

        for section in seat_data.values():
            section_name = section.get("section_name", "Unknown Section")
            if "rows" not in section:
                continue

            for row in section["rows"].values():
                for seat in row["seats"].values():
                    if seat.get("status", "").lower() == "av":
                        seat_label = seat.get("number", "").strip()
                        row_prefix, seat_number = extract_row_and_number(seat_label)
                        if row_prefix and seat_number:
                            row_map.setdefault((section_name, row_prefix), []).append(seat_number)

        sorted_rows = sorted(row_map.items(), key=lambda x: (x[0][0].lower(), sort_key(x[0][1])))

        for (section_name, row_prefix), seat_nums in sorted_rows:
            ranges = compress_ranges(seat_nums)
            for start, end in ranges:
                if start == end:
                    output_lines.append(f"{section_name} {row_prefix}{start}")
                else:
                    output_lines.append(f"{section_name} {row_prefix}{start}-{end}")

        if output_lines:
            copy_text = ", ".join(output_lines)
            st.text_area("📋 Paste this into 'Enter seat ranges':", value=copy_text, height=200)
        else:
            st.info("No available seats found.")

        # ─── Editing logic ─────
        if st.button("▶️ Go"):
            matched_seats_output = []
            requested_seats = set()
            found_seats = set()
            debug_table = []

            if seat_range_input:
                txt = seat_range_input
                txt = re.sub(r"\b([A-Za-z])\s+(\d+)\b", r"\1\2", txt)
                txt = re.sub(r"(\d+)\s*-\s*(\d+)", r"\1-\2", txt)

                pattern = re.compile(
                    r"(?P<section>[A-Za-z0-9 ]+?)\s+"
                    r"(?P<row_prefix>(ROW\s*\d+\s*-\s*)|[A-Z]+)?"
                    r"(?P<start>\d+)"
                    r"(?:\s*(?:to|-)\s*)"
                    r"(?P<end>\d+)?",
                    re.I
                )

                for match in pattern.finditer(txt):
                    section_name = match.group("section").strip().lower()
                    row_prefix = match.group("row_prefix") or ""
                    start = int(match.group("start"))
                    end = int(match.group("end") or start)

                    for seat_num in range(start, end + 1):
                        full_seat = f"{row_prefix.strip()}{seat_num}".strip()
                        norm = re.sub(r"\s*", "", full_seat).lower()
                        requested_seats.add((section_name, norm))
                        debug_table.append((section_name, full_seat))

                        for section in seat_data.values():
                section_key = section.get('section_name', '').strip().lower()
                if "rows" not in section:
                    continue

                for row in section["rows"].values():
                    for seat in row["seats"].values():
                        seat_label = seat.get("number", "").strip()
                        normalized_seat_label = re.sub(r"\s*", "", seat_label).lower()
                        key = (section_key, normalized_seat_label)

                        if price_input.strip():
                            seat['price'] = price_input.strip()

                        if not price_only_mode and seat_range_input:
                            if key in requested_seats:
                                seat['status'] = 'av'
                                found_seats.add(key)
                                matched_seats_output.append(f"{section['section_name']} {seat_label}")
                            else:
                                seat['status'] = 'uav'

                    if price_input.strip():
                        row['price'] = price_input.strip()
                if price_input.strip():
                    section['price'] = price_input.strip()

            not_found = requested_seats - found_seats

            st.markdown("### ✅ Seats Updated")
            if matched_seats_output:
                st.write(", ".join(sorted(matched_seats_output)))
            else:
                st.info("No seats were updated.")

            if not_found:
                missing = ", ".join(f"{s.title()} {n}" for s, n in sorted(not_found))
                st.warning(f"⚠️ The following seats were **not** found: {missing}")

            st.download_button(
                "Download Updated JSON",
                json.dumps(seat_data, indent=2),
                file_name="updated_seatmap.json",
                mime="application/json"
            )

            if seat_range_input:
                st.markdown("### 🔍 Parsed Seat Targets")
                st.table(debug_table)

    except Exception as e:
        st.error(f"❌ Error reading file: {e}")
