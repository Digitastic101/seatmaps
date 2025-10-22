import streamlit as st
import json, re, itertools
from collections import defaultdict

st.title("🎭 Seat Map Availability Editor — Tuple Index + Deep Debug")

uploaded_file = st.file_uploader("Upload your seat map JSON file", type=["json"])

seat_range_input = st.text_input(
    "Enter seat ranges (e.g. Rausing Circle ROW 1 - 64-106, Rausing Circle ROW 2 - 34-87, Stalls C23-28)",
    placeholder="Rausing Circle ROW 1 - 64-106, Rausing Circle ROW 2 - 34-87"
)

debug_section_name = st.text_input(
    "Optional: debug a specific section name (helps inspect Row 1)",
    value="Rausing Circle",
    help="Type a section name exactly as it appears in the Copy-Paste list (case-insensitive)."
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

# Normalise any seat label string
def norm_label(s: str) -> str:
    s = strip_brackets(s or "")
    # normalise odd punctuation / spaces
    s = s.replace("–", "-").replace("—", "-")        # en/em dash → hyphen
    s = s.replace("\u00a0", " ").replace("\u202f", " ")  # non-breaking spaces
    s = s.lower().replace("seat", "")
    s = re.sub(r"\s*-\s*", "-", s)   # tidy hyphen spacing
    s = re.sub(r"\s+", "", s)        # drop remaining spaces
    s = re.sub(r"row0?(\d+)", r"row\1", s)  # drop leading zero in row
    return s

# Split a normalised label into (prefix, number)
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

# Parse the user input into tuples (section_low, prefix, number)
def parse_input_ranges(user_text: str, section_names):
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
        # find section (longest name match)
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
                rownum = int(m.group(6)); n = int(m.group(7))
                pref = f"row{rownum}"
                requested.add((sec_low, pref, n))
                debug_rows.append((sec_canon, f"{pref}-{n}"))
            else:  # alpha/word prefix
                pref = m.group(8).lower()
                a = int(m.group(9)); b = int(m.group(10) or m.group(9))
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

        # Normalise section names (trim + collapse spaces)
        for sec in seat_data.values():
            if isinstance(sec, dict) and "section_name" in sec:
                sec["section_name"] = re.sub(r"\s+", " ", sec["section_name"]).strip()

        # ── Build an INDEX of every seat: (section_low, prefix, number) -> (seat_obj, display_section)
        seat_index = {}
        per_section_counts = defaultdict(int)

        for sec in seat_data.values():
            sec_disp = sec.get("section_name", "Unknown Section")
            sec_low = sec_disp.strip().lower()
            rows = sec.get("rows", {})
            for row in rows.values():
                for seat in row.get("seats", {}).values():
                    raw = seat.get("number", "")
                    norm = norm_label(raw)
                    split = split_norm_label(norm)
                    if not split:
                        continue
                    pref, num = split
                    key = (sec_low, pref, num)
                    seat_index[key] = (seat, sec_disp)
                    per_section_counts[sec_low] += 1

        st.caption(f"Indexed seats: {len(seat_index)} across {len(per_section_counts)} sections.")

        # ── Build copy/paste helper of current AV seats (uses index to read)
        row_map = defaultdict(list)
        available_count = 0
        for (sec_low, pref, num), (seat, sec_disp) in seat_index.items():
            if seat.get("status","").lower() == "av":
                available_count += 1
                row_map[(sec_disp, pref)].append(num)

        out_lines = []
        for (sec_disp, pref), nums in sorted(row_map.items(), key=lambda x: (x[0][0].lower(), sort_key(x[0][1]))):
            for s, e in compress_ranges(nums):
                disp_pref = display_prefix(pref)
                out_lines.append(f"{sec_disp} {disp_pref}{s}" if s == e else f"{sec_disp} {disp_pref}{s}-{e}")

        st.markdown("### 🪑 Copy-Paste Friendly Available Seat Ranges")
        if out_lines:
            st.text_area("📋 Paste this into 'Enter seat ranges':", value=", ".join(out_lines), height=200)
            st.info(f"ℹ️ Total currently available seats in the list: **{available_count}**")
        else:
            st.info("No available seats found.")

        # ── Parse input into tuples
        requested = set()
        debug_list = []
        section_names = section_names_from_data(seat_data)
        if seat_range_input:
            requested, debug_list = parse_input_ranges(seat_range_input, section_names)
            st.markdown("### 🔎 Parsed Seat Targets (Preview)")
            st.write(f"Targets parsed: **{len(requested)}** seats")
            if debug_list:
                st.dataframe([{"Section": s, "Seat (normalised)": n} for s, n in debug_list])

        # ── Deep debug for Row 1 in a chosen section
        if debug_section_name:
            sec_key = debug_section_name.strip().lower()
            have_row1 = sorted([n for (sec, pref, n) in seat_index.keys() if sec == sec_key and pref == "row1"])
            want_row1 = sorted([n for (sec, pref, n) in requested if sec == sec_key and pref == "row1"])
            st.markdown("### 🧩 Deep Debug for Row 1")
            st.write(f"Section: **{debug_section_name}**")
            st.write(f"Row 1 seats IN FILE (count {len(have_row1)}):", have_row1[:50], "..." if len(have_row1) > 50 else "")
            st.write(f"Row 1 seats REQUESTED (count {len(want_row1)}):", want_row1[:50], "..." if len(want_row1) > 50 else "")
            missing_from_file = sorted(set(want_row1) - set(have_row1))
            st.write(f"Row 1 seats requested but MISSING in file (first 50):", missing_from_file[:50], "..." if len(missing_from_file) > 50 else "")

        # ── Apply updates via the index (MUCH more reliable)
        if st.button("▶️ Go"):
            price_value = price_input.strip() or None

            matched = []
            updated_seats = []
            missing = []

            # Set price at section level if given
            if price_value:
                for sec in seat_data.values():
                    sec["price"] = price_value

            # Toggle availability ONLY for the requested keys
            if not price_only_mode and requested:
                for key in requested:
                    if key in seat_index:
                        seat, sec_disp = seat_index[key]
                        if seat.get("status","").lower() != "av":
                            seat["status"] = "av"
                            updated_seats.append({
                                "Section": sec_disp,
                                "Seat": seat.get("number",""),
                                "Status": "av",
                                "Price": seat.get("price","")
                            })
                        matched.append(f"{sec_disp} {seat.get('number','').strip()}")
                    else:
                        missing.append(key)

                # If you want to turn everything else off, do it explicitly (optional)
                # else: leave as-is
                for key, (seat, _) in seat_index.items():
                    if key not in requested and not price_only_mode:
                        # Do NOT force 'uav' unless that's intended.
                        pass

            # Row/seat-level price update
            if price_value:
                for (sec_low, pref, num), (seat, sec_disp) in seat_index.items():
                    if price_only_mode:
                        # in price-only mode, update all seats
                        seat["price"] = price_value
                    else:
                        # only update price for requested seats
                        if (sec_low, pref, num) in requested:
                            seat["price"] = price_value

            if price_value:
                st.success(f"💸 Prices updated to {price_value} (see summary tables below).")

            if not price_only_mode and requested:
                st.markdown("### ✅ Availability Updated")
                st.write(", ".join(sorted(matched)) if matched else "No seat availability was changed.")

                if missing:
                    # pretty print missing
                    sec_title = {s.lower(): s for s in section_names}
                    pretty = [f"{sec_title.get(sec,'?')} {pref.upper()}-{n}" for (sec, pref, n) in sorted(missing)]
                    st.warning("⚠️ Seats not found: " + ", ".join(pretty))

            if updated_seats:
                st.markdown("### 🎟️ Updated Seats")
                st.dataframe(updated_seats)

            # Summaries (optional)
            if price_value:
                st.markdown("### 📊 Seat Price Summary (sample)")
                sample = []
                for i, ((sec_low, pref, num), (seat, sec_disp)) in enumerate(sorted(seat_index.items())[:300]):
                    sample.append({"Section": sec_disp, "Seat": seat.get("number",""), "Price": seat.get("price","")})
                st.dataframe(sample)

            st.download_button(
                "Download Updated JSON",
                json.dumps(seat_data, indent=2),
                file_name="updated_seatmap.json",
                mime="application/json"
            )

    except Exception as e:
        st.error(f"❌ Error reading file: {e}")
