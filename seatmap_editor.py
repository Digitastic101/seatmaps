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

# Helper to normalize seat key
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
            continue  # skip mixed prefix ranges

        for n in range(start_num, end_num + 1):
            seat_id = f"{start_pref}{n}"
            requested.add((section, seat_id.lower()))
    return requested

if uploaded_file:
    try:
        seat_data = json.loads(uploaded_file.read().decode("utf-8"))
        st.success("✅ Seat map loaded successfully!")

        if st.button("▶️ Go"):
            price_value = price_input.strip() or None
            requested = extract_requested_seats(seat_range_input)
            updated_seats, updated_rows = [], []

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

                        should_update = False
                        is_included = seat_key in requested

                        if not price_only_mode:
                            seat["status"] = "av" if is_included else "uav"
                            should_update = True
                        elif is_included:
                            should_update = True

                        if should_update and price_value:
                            seat["price"] = price_value
                            row_changed = True
                            updated_seats.append({
                                "Section": sec_name,
                                "Row": row_label,
                                "Seat": label,
                                "Status": seat.get("status", ""),
                                "Price": seat.get("price", "")
                            })

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

            if updated_seats:
                st.markdown("### 🎟️ Updated Seats")
                st.dataframe(updated_seats)
            if updated_rows:
                st.markdown("### 🧾 Updated Rows")
                st.dataframe(updated_rows)
            if not updated_seats and not updated_rows:
                st.info("No seats were updated.")

            st.download_button("⬇️ Download Updated JSON",
                               data=json.dumps(seat_data, indent=2),
                               file_name="updated_seatmap.json",
                               mime="application/json")

    except Exception as e:
        st.error(f"❌ Error: {e}")
