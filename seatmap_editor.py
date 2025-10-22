import streamlit as st
import json, re, itertools

st.title("🎭 Seat Map Availability Editor")

uploaded_file = st.file_uploader("Upload your seat map JSON file", type=["json"])

seat_range_input = st.text_input(
    "Enter seat ranges (e.g. Rausing Circle ROW 1 - 64-106, Rausing Circle ROW 2 - 34-87, Stalls C23-28)",
    placeholder="Rausing Circle ROW 1 - 64-106, Rausing Circle ROW 2 - 34-87"
)

price_input = st.text_input("Enter new price for all seats (optional)", placeholder="e.g. 65")
price_only_mode = st.checkbox("💸 Only update seat prices (leave availability unchanged)")

# ───────────────── helper functions ─────────────────

BRACKET_RX = re.compile(r"(\([^)]*\))")

def strip_brackets(s: str) -> str:
    return BRACKET_RX.sub("", s or "").strip()

def compress_ranges(nums):
    nums = sorted(set(nums))
    out = []
    for _, g in itertools.groupby(enumerate(nums), lambda x: x[1] - x[0]):
        block = list(g)
        s, e = block[0][1], block[-1][1]
        out.append((s, e))
    return out

def sort_key(pref):
    m = re.search(r"(\d+)", pref)
    return (0, int(m.group(1))) if m else (1, pref.upper())

def display_prefix(pref: str) -> str:
    if pref.startswith("row"):
        m = re.match(r"row(\d+)$", pref)
        if m:
            return f"ROW {m.group(1)} - "
    return pref.upper()

# Normalise any seat label string from JSON (or constructed)
def norm_label(s: str) -> str:
    s = strip_brackets(s or "")
    s = s.replace("–", "-").replace("—", "-")   # en/em dash → hyphen
    s = s.lower().replace("seat", "")
    s = re.sub(r"\s*-\s*", "-", s)              # tidy hyphens
    s = re.sub(r"\s+", "", s)                   # remove all remaining spaces
    s = re.sub(r"row0?(\d+)", r"row\1", s)      # drop leading zero in row number
    return s

# Split a normalised label into (prefix, number)
# Examples:
#   'row1-157'  → ('row1', 157)
#   'row1157'   → ('row1', 157)
#   'g11'       → ('g', 11)
#   'main-left15' → ('main-left', 15)
def split_norm_label(norm: str):
    norm = norm.replace("seat", "")
    m = re.match(r"(row\d+)-?(\d+)$", norm)     # allow with/without hyphen
    if m:
        return m.group(1), int(m.group(2))
    m = re.match(r"([a-z][a-z\-]{0,19})(\d+)$", norm)
    if m:
        return m.group(1), int(m.group(2))
    return None

def section_names_from_data(seat_data):
    return [re.sub(r"\s+", " ", sec.get("section_name", "").strip())
            for sec in seat_data.values()
            if isinstance(sec, dict) and sec.get("section_name")]

# ── NEW: parse to tuples (section_low, prefix, number) instead of strings
def parse_input_ranges(user_text: str, section_names):
    """
    Returns:
      requested_set: set[(section_low, prefix, number)]
      debug_rows   : list[(Section Display Name, 'prefix-number')]
    """
    requested = set()
    debug_rows = []
    if not user_text:
        return requested, debug_rows

    canon_sections = {s.lower(): s for s in section_names if s}
    chunks = [c.strip() for c in re.split(r"\s*,\s*", user_text) if c.strip()]

    rx = re.compile(
        r"(?:(row)\s*(\d+)\s*[-–]?\s*(\d+)\s*(?:to|–|-)\s*(\d+))"     # ROW X - a-b
        r"|(?:(row)\s*(\d+)\s*[-–]?\s*(\d+))"                         # ROW X - a
        r"|([a-z][a-z\-]{0,19})\s*(\d+)\s*(?:\s*(?:to|–|-)\s*(\d+))?",# G11-21, Yellow 1-12
        re.I
    )

    for chunk in chunks:
        # find section (longest matching name first)
        sec_match = None
        chunk_low = chunk.lower()
        for low_name, canon in sorted(canon_sections.items(), key=lambda x: len(x[0]), reverse=True):
            if chunk_low.startswith(low_name):
                after = chunk_low[len(low_name):]
                if after == "" or after[0].isspace():
                    sec_match = (low_name, canon)
                    break
        if not sec_match:
            continue

        sec_low, sec_canon = sec_match
        rest = chunk[len(sec_canon):].strip()

        for m in rx.finditer(rest):
            if m.group(1):  # ROW X - a-b
                rownum = int(m.group(2))
                a, b = int(m.group(3)), int(m.group(4))
                lo, hi = sorted((a, b))
                pref = f"row{rownum}"
                for n in range(lo, hi + 1):
                    requested.add((sec_low, pref, n))
                    debug_rows.append((sec_canon, f"{pref}-{n}"))
            elif m.group(5):  # ROW X - a
                rownum = int(m.group(6))
                n = int(m.group(7))
                pref = f"row{rownum}"
                requested.add((sec_low, pref, n))
                debug_rows.append((sec_canon, f"{pref}-{n}"))
            else:  # alpha/word prefix
                pref = m.group(8).lower()
                a = int(m.group(9))
                b = int(m.group(10) or m.group(9))
                lo, hi = sorted((a, b))
                for n in range(lo, hi + 1):
                    requested.add((sec_low, pref, n))
                    debug_rows.append((sec_canon, f"{pref}-{n}"))

    return requested, debug_rows

# ──────────────── main UI logic ────────────────
if uploaded_file:
    try:
        seat_data = json.loads(uploaded_file.read().decode("utf-8"))
        st.success("✅ Seat map loaded successfully!")

        # Normalise section names to prevent spacing issues
        for sec in seat_data.values():
            if isinstance(sec, dict) and "section_name" in sec:
                sec["section_name"] = re.sub(r"\s+", " ", sec["section_name"]).strip()

        # Build copy/paste helper from current AV seats
        row_map = {}
        available_count = 0
        for sec in seat_data.values():
            sec_name = sec.get("section_name", "Unknown Section")
            if "rows" not in sec:
                continue
            for row in sec["rows"].values():
                for seat in row.get("seats", {}).values():
                    if seat.get("status", "").lower() == "av":
                        available_count += 1
                        norm = norm_label(seat.get("number", ""))
                        split = split_norm_label(norm)
                        if not split:
                            continue
                        pref, num = split
                        row_map.setdefault((sec_name, pref), []).append(num)

        out_lines = []
        for (sec_name, pref), nums in sorted(row_map.items(), key=lambda x: (x[0][0].lower(), sort_key(x[0][1]))):
            for s, e in compress_ranges(nums):
                disp_pref = display_prefix(pref)
                out_lines.append(f"{sec_name} {disp_pref}{s}" if s == e else f"{sec_name} {disp_pref}{s}-{e}")

        st.markdown("### 🪑 Copy-Paste Friendly Available Seat Ranges")
        if out_lines:
            st.text_area("📋 Paste this into 'Enter seat ranges':", value=", ".join(out_lines), height=200)
            st.info(f"ℹ️ Total currently available seats in the list: **{available_count}**")
        else:
            st.info("No available seats found.")

        # Preview what the input will target (now as tuples)
        if seat_range_input:
            section_names = section_names_from_data(seat_data)
            requested_preview, debug_list = parse_input_ranges(seat_range_input, section_names)
            st.markdown("### 🔎 Parsed Seat Targets (Preview)")
            st.write(f"Targets parsed: **{len(requested_preview)}** seats")
            if debug_list:
                st.dataframe([{"Section": s, "Seat (normalised)": n} for s, n in debug_list])

        if st.button("▶️ Go"):
            price_value = price_input.strip() or None
            matched = []
            found = set()
            updated_seats = []
            row_price_map = {}

            section_names = section_names_from_data(seat_data)
            requested, debug_rows = parse_input_ranges(seat_range_input, section_names)

            # ── Walk the structure and apply updates using tuple comparisons ──
            for sec in seat_data.values():
                sec_key = sec.get("section_name", "").strip().lower()
                if "rows" not in sec:
                    continue

                if price_value:
                    sec["price"] = price_value

                for row_key, row in sec["rows"].items():
                    row_updated = False
                    for seat in row.get("seats", {}).values():
                        label_raw = seat.get("number", "")
                        norm = norm_label(label_raw)
                        split = split_norm_label(norm)
                        if not split:
                            continue
                        pref, num = split

                        key_tuple = (sec_key, pref, num)

                        should_update = False
                        current_status = seat.get("status", "").strip().lower()

                        if seat_range_input and not price_only_mode:
                            if key_tuple in requested:
                                found.add(key_tuple)
                                matched.append(f"{sec.get('section_name','')} {label_raw.strip()}")
                                if current_status != "av":
                                    seat["status"] = "av"
                                    should_update = True
                            else:
                                if current_status == "av":
                                    seat["status"] = "uav"
                                    should_update = True

                        if price_value and seat.get("price") != price_value:
                            seat["price"] = price_value
                            should_update = True

                        if should_update:
                            updated_seats.append({
                                "Section": sec.get("section_name",""),
                                "Seat": label_raw.strip(),
                                "Status": seat.get("status",""),
                                "Price": seat.get("price","")
                            })
                            row_updated = True

                    if (row_updated or price_only_mode) and price_value:
                        row["price"] = price_value
                        row["row_price"] = price_value
                        row_price_map[f"{sec.get('section_name','')} - {row_key}"] = price_value

            if price_value:
                st.success(f"💸 Prices updated to {price_value} across all matching seats, rows & sections.")

            if not price_only_mode and seat_range_input:
                st.markdown("### ✅ Availability Updated")
                st.write(", ".join(sorted(matched)) if matched else "No seat availability was changed.")
                missing = {k for k in requested if k not in found}
                if missing:
                    # pretty-print missing as Section PREFIX-N
                    sec_title = {s.lower(): s for s in section_names_from_data(seat_data)}
                    pretty = [f"{sec_title.get(sec,'?')} {pref.upper()}-{n}" for (sec, pref, n) in sorted(missing)]
                    st.warning("⚠️ Seats not found: " + ", ".join(pretty))

            if updated_seats:
                st.markdown("### 🎟️ Updated Seats with Prices")
                st.dataframe(updated_seats)
            else:
                st.info("No updated seat prices to display.")

            if row_price_map:
                st.markdown("### 📊 Row Price Summary")
                st.dataframe([{"Row": k, "Price": v} for k, v in sorted(row_price_map.items())])

            st.download_button(
                "Download Updated JSON",
                json.dumps(seat_data, indent=2),
                file_name="updated_seatmap.json",
                mime="application/json"
            )

    except Exception as e:
        st.error(f"❌ Error reading file: {e}")
