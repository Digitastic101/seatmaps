import streamlit as st
import json, re, itertools

st.title("🎭 Seat Map Availability Editor")

uploaded_file = st.file_uploader("Upload your seat map JSON file", type=["json"])

seat_range_input = st.text_area(
    "Enter seat ranges (e.g. Dress Circle B 1-4, Dress Circle AA 14-15)",
    placeholder="Dress Circle B 1-4, Dress Circle AA 14-15"
)

price_input = st.text_input(
    "Enter new price for all seats (optional)",
    placeholder="e.g. 65"
)

price_only_mode = st.checkbox("💸 Only update seat prices (leave availability unchanged)")

# Helper functions
def normalise_key(section, label):
    return (section.strip().lower(), re.sub(r"\s*", "", label).lower())

def extract_requested_seats(text):
    requested = set()
    text = re.sub(r"([A-Z]{1,3})\s+(\d+)", r"\1\2", text, flags=re.I)

    pattern = re.compile(
        r"(?P<section>[A-Za-z0-9 ]+?)\s+"
        r"(?P<start>[A-Z]*\d+)"
        r"(?:\s*[-to]+\s*(?P<end>[A-Z]*\d+))?",
        re.IGNORECASE
    )

    for match in pattern.finditer(text):
        section = match.group("section").strip().lower()
        start = match.group("start").upper()
        end = match.group("end").upper() if match.group("end") else start

        def parts(label):
            m = re.match(r"([A-Z]+)(\d+)", label)
            return (m.group(1), int(m.group(2))) if m else ("", 0)

        start_pref, start_num = parts(start)
        end_pref, end_num = parts(end)
        if start_pref != end_pref:
            continue

        for n in range(start_num, end_num + 1):
            seat_id = f"{start_pref}{n}"
            requested.add((section, seat_id.lower()))
    return requested

def compress_ranges(nums):
    nums.sort()
    out = []
    for _, g in itertools.groupby(enumerate(nums), lambda x: x[1] - x[0]):
        block = list(g)
        s, e = block[0][1], block[-1][1]
        out.append((s, e))
    return out

def sort_key(pref):
    m = re.search(r"(\d+)", pref)
    return (0, int(m.group(1))) if m else (1, pref.upper())

# ────────── MAIN ──────────
if uploaded_file:
    try:
        seat_data = json.loads(uploaded_file.read().decode("utf-8"))
        st.success("✅ Seat map loaded successfully!")

        # Show currently available seats
        row_map = {}
        for sec in seat_data.values():
            sec_name = sec.get("section_name", "Unknown Section")
            if "rows" not in sec:
                continue
            for row in sec["rows"].values():
                for seat in row["seats"].values():
                    if seat.get("status", "").lower() == "av":
                        m = re.match(r"([A-Z]+)(\d+)", seat.get("number", ""))
                        if m:
                            row_map.setdefault((sec_name, m.group(1)), []).append(int(m.group(2)))

        out_lines = []
        for (sec_name, row_prefix), nums in sorted(row_map.items(), key=lambda x: (x[0][0].lower(), sort_key(x[0][1]))):
            for s, e in compress_ranges(nums):
                out_lines.append(f"{sec_name} {row_prefix}{s}" if s == e else f"{sec_name} {row_prefix}{s}-{e}")

        if out_lines:
            st.markdown("### 🪑 Currently Available Seats")
            st.text_area("Copy this if you want to paste back in:", value=", ".join(out_lines), height=150)
        else:
            st.info("No available seats found.")

        # GO BUTTON
        if st.button("▶️ Go"):
            price_value = price_input.strip() or None
            requested = extract_requested_seats(seat_range_input) if seat_range_input else set()
            updated_seats, updated_rows, found = [], [], set()

            for sec in seat_data.values():
                sec_name = sec.get("section_name", "")
                sec_key = sec_name.strip().lower()

                if "rows" not in sec:
                    continue

                for row_label, row in sec["rows"].items():
                    row_changed = False
                    for seat in row.get("seats", {}).values():
                        label = seat.get("number", "").strip()
                        seat_key = normalise_key(sec_name, label)

                        is_target = seat_key in requested
                        should_update = False

                        if not price_only_mode:
                            seat["status"] = "av" if is_target else "uav"
                            should_update = True
                        elif is_target:
                            should_update = True

                        if should_update and price_value:
                            seat["price"] = price_value
                            row_changed = True

                        if should_update:
                            updated_seats.append({
                                "Section": sec_name,
                                "Row": row_label,
                                "Seat": label,
                                "Status": seat.get("status", ""),
                                "Price": seat.get("price", "")
                            })

                        if is_target:
                            found.add(seat_key)

                    if price_value and row_changed:
                        row["price"] = price_value
                        row["row_price"] = price_value
                        updated_rows.append({
                            "Section": sec_name,
                            "Row": row_label,
                            "Row Price": price_value
                        })

                if price_value:
                    sec["price"] = price_value

            # Results
            if price_value:
                st.success(f"💸 Prices updated to {price_value}")

            if updated_seats:
                st.markdown("### 🎟️ Updated Seats")
                st.dataframe(updated_seats)

            if updated_rows:
                st.markdown("### 🧾 Updated Row Prices")
                st.dataframe(updated_rows)

            if requested:
                not_found = requested - found
                if not_found:
                    st.warning("⚠️ Some seats were not found: " + ", ".join(f"{s.title()} {n.upper()}" for s, n in sorted(not_found)))

            if not updated_seats and not updated_rows:
                st.info("No seats or rows were updated.")

            st.download_button("⬇️ Download Updated JSON",
                               data=json.dumps(seat_data, indent=2),
                               file_name="updated_seatmap.json",
                               mime="application/json")

    except Exception as e:
        st.error(f"❌ Error: {e}")
