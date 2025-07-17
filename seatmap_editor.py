import streamlit as st
import json, re

st.title("🎭 Seat Map Availability Editor")

uploaded_file = st.file_uploader("Upload your seat map JSON file", type=["json"])

seat_range_input = st.text_input(
    "Enter seat ranges (e.g. Stalls O23-O51, Dress Circle D3-D6)",
    placeholder="Stalls O23-O51, Dress Circle D3-D6"
)

price_input = st.text_input(
    "Enter new price for all seats (optional)",
    placeholder="e.g. 65"
)

price_only_mode = st.checkbox("💸 Only update seat prices (leave availability unchanged)")

if st.button("▶️ Go"):
    matched_seats_output = []

    def generate_seat_range(start, end):
        row = re.match(r"(\D+)", start).group(1)   # row letters
        start_num = int(re.search(r"\d+", start).group())
        end_num   = int(re.search(r"\d+", end).group())
        return [f"{row}{i}" for i in range(start_num, end_num + 1)]

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

            # ─── Parse the seat-range text ──────────────────────────────────
            if seat_range_input:
                txt = seat_range_input
                txt = re.sub(r"\b([A-Za-z])\s+(\d+)\b", r"\1\2", txt)       # kill spaces in "O 23"
                txt = re.sub(r"(\d+)\s*-\s*(\d+)", r"\1-\2", txt)           # normalise hyphens
                txt = re.sub(r"([A-Za-z]+)(\d+)-(\d+)",
                             lambda m: f"{m.group(1)}{m.group(2)}-{m.group(1)}{m.group(3)}", txt)

                pattern = re.compile(
                    r"(?P<section>[A-Za-z0-9 ]+?)\s+"
                    r"(?P<start>[A-Za-z]\d+)"
                    r"(?:\s*(?:to|-)\s*|-\s*)"
                    r"(?P<end>[A-Za-z]?\d+)",
                    re.I
                )

                for section_name, start_seat, end_seat in pattern.findall(txt):
                    section_key = section_name.strip().lower()
                    for s in generate_seat_range(start_seat.upper(), end_seat.upper()):
                        requested_seats.add((section_key, s))
                        debug_table.append((section_key, s))

            # ─── Walk the JSON and update ALL seats & rows prices ───────────────
            for section in seat_data.values():
                if 'rows' not in section:
                    continue
                section_key = section.get('section_name', '').strip().lower()

                for row_key, row in section['rows'].items():
                    for seat_key, seat in row['seats'].items():
                        seat_num = seat['number'].upper()
                        key = (section_key, seat_num)

                        # 💸 Update all seat prices no matter what
                        if price_input.strip():
                            seat['price'] = price_input.strip()

                        # 🔧 AVAILABILITY updates only apply if we're not in price-only mode
                        if not price_only_mode and seat_range_input:
                            if key in requested_seats:
                                seat['status'] = 'av'
                                found_seats.add(key)
                                matched_seats_output.append(f"{section['section_name']} {seat_num}")
                            else:
                                seat['status'] = 'uav'

                    # 💸 After seat loop, set row-level price
                    if price_input.strip():
                        row['price'] = price_input.strip()

                # 💸 Set section-level price too, if desired
                if price_input.strip():
                    section['price'] = price_input.strip()

            # ─── NEW: what did we fail to find? ────────────────────────────
            not_found_seats = requested_seats - found_seats

            st.success("✅ Seat map updated successfully!")

            # Updated seats
            st.markdown("### ✅ Seats updated:")
            if matched_seats_output:
                st.write(", ".join(sorted(matched_seats_output)))
            else:
                st.info("No seats were updated for availability.")

            # Missing seats
            if not_found_seats:
                missing = ", ".join(
                    f"{sec.title()} {num}" for sec, num in sorted(not_found_seats)
                )
                st.warning(f"⚠️ The following seats were **not** found in the seat map: {missing}")

            # Download
            st.download_button(
                "Download Updated JSON",
                json.dumps(seat_data, indent=2),
                file_name="updated_seatmap.json",
                mime="application/json",
            )

            # Debug table (optional)
            if seat_range_input:
                st.markdown("### 🔍 Parsed Input Ranges")
                st.table(debug_table)

        except Exception as e:
            st.error(f"❌ Error: {e}")

import itertools

# ─── Helper: Convert list of seat numbers into compact ranges ─────────────
def compress_seat_numbers(seat_numbers, row_prefix):
    nums = sorted([int(re.search(r'\d+', s).group()) for s in seat_numbers])
    ranges = []
    for k, g in itertools.groupby(enumerate(nums), lambda x: x[1] - x[0]):
        group = list(g)
        start = group[0][1]
        end = group[-1][1]
        if start == end:
            ranges.append(f"{row_prefix}{start}")
        else:
            ranges.append(f"{row_prefix}{start}-{row_prefix}{end}")
    return ranges

# ─── Generate copy-pasteable section for seat input ───────────────────────
st.markdown("### 📋 Copy-Paste Seat Range Input (Available Only)")

seat_range_snippets = []

for section in seat_data.values():
    section_name = section.get("section_name", "Unknown Section").strip()
    if "rows" not in section:
        continue

    for row_label, row in section["rows"].items():
        available_seats = [
            seat["number"].upper()
            for seat in row["seats"].values()
            if seat.get("status", "").lower() == "av"
        ]

        if available_seats:
            compressed_ranges = compress_seat_numbers(available_seats, row_label.upper())
            for r in compressed_ranges:
                seat_range_snippets.append(f"{section_name} {r}")

if seat_range_snippets:
    seat_input_format = ", ".join(seat_range_snippets)
    st.text_area("🧾 Use this format in 'Enter seat ranges':", value=seat_input_format, height=200)
else:
    st.info("No available seats found to format.")
