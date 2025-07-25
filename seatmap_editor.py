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

# ────────────────── helper functions ──────────────────
def extract_row_and_number(label: str):
    m = re.match(r"(ROW\s*\d+\s*-\s*)(\d+)", label.strip(), re.I)
    if m:
        return m.group(1).strip(), int(m.group(2))
    m = re.match(r"([A-Z]+)(\d+)", label.strip(), re.I)
    if m:
        return m.group(1).strip(), int(m.group(2))
    return None, None

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

# ────────────────── main UI logic ─────────────────────
if uploaded_file:
    try:
        seat_data = json.loads(uploaded_file.read().decode("utf-8"))
        st.success("✅ Seat map loaded successfully!")

        # --------- build copy-paste list of available seats ---------
        row_map = {}
        row_prices = []

        for sec in seat_data.values():
            sec_name = sec.get("section_name", "Unknown Section")
            if "rows" not in sec:
                continue
            for row_label, row in sec["rows"].items():
                # Track row-level prices
                row_price = row.get("price", "❌ Missing")
                row_prices.append({
                    "Section": sec_name,
                    "Row": row_label,
                    "Row Price": row_price
                })

                for seat in row["seats"].values():
                    if seat.get("status", "").lower() == "av":
                        pref, num = extract_row_and_number(seat.get("number", ""))
                        if pref and num:
                            row_map.setdefault((sec_name, pref), []).append(num)

        out_lines = []
        for (sec_name, pref), nums in sorted(row_map.items(),
                                             key=lambda x: (x[0][0].lower(), sort_key(x[0][1]))):
            for s, e in compress_ranges(nums):
                out_lines.append(f"{sec_name} {pref}{s}" if s == e
                                 else f"{sec_name} {pref}{s}-{e}")

        st.markdown("### 🪑 Copy-Paste Friendly Available Seat Ranges")
        if out_lines:
            st.text_area("📋 Paste this into 'Enter seat ranges':",
                         value=", ".join(out_lines), height=200)
        else:
            st.info("No available seats found.")

        # --------- show row prices ---------
        if row_prices:
            st.markdown("### 💷 Existing Row Prices")
            st.dataframe(row_prices)
        else:
            st.info("No row-level prices found.")

        # ---------------- run updates -----------------
        if st.button("▶️ Go"):
            price_value = price_input.strip() or None
            matched, requested, found = [], set(), set()
            updated_seats = []

            # ---- parse seat_range_input (if any) ----
            if seat_range_input:
                txt = re.sub(r"\b([A-Za-z])\s+(\d+)\b", r"\1\2", seat_range_input)
                txt = re.sub(r"(\d+)\s*-\s*(\d+)", r"\1-\2", txt)
                rx = re.compile(r"(?P<section>[A-Za-z0-9 ]+?)\s+"
                                r"(?P<pref>(ROW\s*\d+\s*-\s*)|[A-Z]+)?"
                                r"(?P<start>\d+)"
                                r"(?:\s*(?:to|-)\s*)?"
                                r"(?P<end>\d+)?", re.I)
                for m in rx.finditer(txt):
                    sec = m.group("section").strip().lower()
                    pref = m.group("pref") or ""
                    a, b = int(m.group("start")), int(m.group("end") or m.group("start"))
                    for n in range(a, b + 1):
                        full = f"{pref.strip()}{n}".strip()
                        requested.add((sec, re.sub(r"\s*", "", full).lower()))

            # ---- apply updates ----
            for sec in seat_data.values():
                sec_key = sec.get("section_name", "").strip().lower()
                if "rows" not in sec:
                    continue
                for row_label, row in sec["rows"].items():
                    for seat in row["seats"].values():
                        label = seat.get("number", "").strip()
                        norm = re.sub(r"\s*", "", label).lower()
                        key = (sec_key, norm)

                        should_update = False

                        if seat_range_input:
                            if key in requested:
                                if not price_only_mode:
                                    seat["status"] = "av"
                                found.add(key)
                                matched.append(f"{sec['section_name']} {label}")
                                should_update = True
                            elif not price_only_mode:
                                seat["status"] = "uav"
                                should_update = True
                        elif price_only_mode and price_value:
                            should_update = True

                        if should_update and price_value:
                            seat["price"] = price_value

                        if should_update:
                            updated_seats.append({
                                "Section": sec.get("section_name", ""),
                                "Row": row_label,
                                "Seat": label,
                                "Status": seat.get("status", ""),
                                "Price": seat.get("price", "")
                            })

                    if price_value:
                        row["price"] = price_value
                if price_value:
                    sec["price"] = price_value

            # ---- messaging ----
            if price_value:
                st.success(f"💸 Prices updated to {price_value} on applicable seats, rows & sections.")

            if not price_only_mode and seat_range_input:
                st.markdown("### ✅ Availability Updated")
                st.write(", ".join(sorted(matched)) if matched else "No seat availability was changed.")
                missing = requested - found
                if missing:
                    st.warning("⚠️ Seats not found: " + ", ".join(f"{s.title()} {n}" for s, n in sorted(missing)))

            # ---- show updated seat prices ----
            if updated_seats:
                st.markdown("### 🎟️ Updated Seats with Prices")
                st.dataframe(updated_seats)
            else:
                st.info("No updated seat prices to display.")

            # ---- download ----
            st.download_button("Download Updated JSON",
                               json.dumps(seat_data, indent=2),
                               file_name="updated_seatmap.json",
                               mime="application/json")

    except Exception as e:
        st.error(f"❌ Error reading file: {e}")
