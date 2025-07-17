import streamlit as st
import json, re, itertools

st.title("🎭 Seat Map Availability Editor")

uploaded_file = st.file_uploader("Upload your seat map JSON file", type=["json"])

seat_range_input = st.text_input(
    "Enter seat ranges (e.g. Rausing Circle ROW 3 - 89-93, Rausing Circle ROW 7 - 128)",
    placeholder="Rausing Circle ROW 3 - 89-93, Rausing Circle ROW 7 - 128"
)

price_input = st.text_input(
    "Enter new price for all seats (optional)",
    placeholder="e.g. 65"
)

price_only_mode = st.checkbox("💸 Only update seat prices (leave availability unchanged)")

if st.button("▶️ Go"):
    matched_seats_output = []

    if not uploaded_file:
        st.error("Please upload a seat map JSON file.")
    elif not seat_range_input and not price_only_mode and not price_input.strip():
        st.error("Please enter seat ranges or price, or tick 'Only update seat prices'.")
    else:
        try:
            seat_data = json.loads(uploaded_file.read().decode("utf-8"))

            requested_seats = set()
            found_seats = set()
            debug_table = []

            # ─── Parse the seat-range text ─────────────────────────────
            if seat_range_input:
                txt = seat_range_input
                txt = re.sub(r"\b([A-Za-z])\s+(\d+)\b", r"\1\2", txt)
                txt = re.sub(r"(\d+)\s*-\s*(\d+)", r"\1-\2", txt)

                pattern = re.compile(
                    r"(?P<section>[A-Za-z0-9 ]+?)\s+"
                    r"(?P<row_prefix>ROW\s*\d+\s*-\s*)?"
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
                        requested_seats.add((section_name, full_seat))
                        debug_table.append((section_name, full_seat))

            # ─── Update seat statuses and prices ──────────────────────
            for section in seat_data.values():
                if 'rows' not in section:
                    continue
                section_key = section.get('section_name', '').strip().lower()

                for row in section['rows'].values():
                    for seat in row['seats'].values():
                        seat_label = seat.get("number", "").strip()
                        key = (section_key, seat_label)

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

            not_found_seats = requested_seats - found_seats

            st.success("✅ Seat map updated successfully!")

            st.markdown("### ✅ Seats updated:")
            if matched_seats_output:
                st.write(", ".join(sorted(matched_seats_output)))
            else:
                st.info("No seats were updated for availability.")

            if not_found_seats:
                missing = ", ".join(
                    f"{sec.title()} {num}" for sec, num in sorted(not_found_seats)
                )
                st.warning(f"⚠️ The following seats were **not** found in the seat map: {missing}")

            st.download_button(
                "Download Updated JSON",
                json.dumps(seat_data, indent=2),
                file_name="updated_seatmap.json",
                mime="application/json",
            )

            if seat_range_input:
                st.markdown("### 🔍 Parsed Input Ranges")
                st.table(debug_table)

            # ─── Available Seats Output (copy-paste friendly) ──────────────

            def extract_row_and_number(seat_label):
                match = re.match(r"(ROW \d+\s*-\s*)\s*(\d+)", seat_label.strip())
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

            st.markdown("### 🪑 Copy-Paste Available Seat Ranges")

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
            st.error(f"❌ Error: {e}")
