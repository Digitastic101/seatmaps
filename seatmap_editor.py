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

# ───────────────────── Helpers ─────────────────────

def normalize_key(section, label):
    return (
        section.strip().lower(),
        re.sub(r"\s+", "", label.strip().lower())
    )

def parse_requested_seats(text):
    requested = set()
    # Normalize: "AA 14" → "AA14"
    text = re.sub(r"([A-Z]{1,3})\s+(\d+)", r"\1\2", text, flags=re.I)

    # Match each seat or range
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

        sp, sn = parts(start)
        ep, en = parts(end)
        if sp != ep:
            continue  # Skip mixed prefix ranges

        for num in range(sn, en + 1):
            seat_id = f"{sp}{num}"
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

# ───────────────────── Main Logic ─────────────────────

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
            st.text_area("Copy this for reuse:", value=", ".join(out_lines), height=150)
        else:
            st.info("No currently available seats.")

        # ────────── GO BUTTON ──────────
        if st.button("▶️ Go"):
            price_value = price_input.strip() or None
            requested = parse_requested_seats(seat_range_input)
            found = set()
            updated_seats, updated_rows = [], []

            for sec in seat_data.values():
                sec_name = sec.get("section_name", "")
                sec_key = sec_name.strip().lower()
                if "rows" not in sec:
                    continue

                for row_label, row in sec["rows"].items():
                    row_changed = False
                    for seat in row.get("seats", {}).values():
                        seat_label = seat.get("number", "")
                        seat_key = normalize_key(sec_name, seat_label)
                        is_target = seat_key in requested

                        if not price_only_mode:
                            seat["status"] = "av" if is_target else "uav"
                        if is_target:
                            found.add(seat_key)

                        if price_value and (not price_only_mode or is_target):
                            seat["price"] = price_value
                            row_changed = True

                        if is_target or price_value:
                            updated_seats.append({
                                "Section": sec_name,
                                "Row": row_label,
                                "Seat": seat_label,
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

            # ────────── Output Results ──────────
            if price_value:
                st.success(f"💸 Price set to {price_value} on matching seats/rows.")

            if updated_seats:
                st.markdown("### 🎟️ Updated Seats")
                st.dataframe(updated_seats)

            if updated_rows:
                st.markdown("### 🧾 Updated Rows")
                st.dataframe(updated_rows)

            not_found = requested - found
            if not_found:
                st.warning("⚠️ Some seats were not found: " + ", ".join(f"{s.title()} {n.upper()}" for s, n in sorted(not_found)))

            st.download_button("⬇️ Download Updated JSON",
                               data=json.dumps(seat_data, indent=2),
                               file_name="updated_seatmap.json",
                               mime="application/json")

    except Exception as e:
        st.error(f"❌ Error reading file: {e}")
