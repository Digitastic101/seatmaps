import streamlit as st
import json, re, itertools
from collections import defaultdict

st.title("🎭 Seat Map Availability Editor — Tuple Index (Deep Debug removed)")

uploaded_file = st.file_uploader("Upload your seat map JSON file", type=["json"])

# ── Core seat-range input (used for AV updates in single-price mode)
seat_range_input = st.text_input(
    "Enter seat ranges for availability (e.g. Rausing Circle ROW 1 - 1-6, Stalls A1-A5)",
    placeholder="Rausing Circle ROW 1 - 1-6, Stalls A1-A5"
)

# Pricing mode
multi_price_mode = st.checkbox("Enable multiple price tiers")

if not multi_price_mode:
    price_input = st.text_input("Enter price for requested seats (optional)", placeholder="e.g. 65")
else:
    tier_count = st.number_input("How many price tiers?", min_value=2, max_value=6, value=2, step=1)
    tier_prices = []
    tier_ranges = []
    for i in range(int(tier_count)):
        col1, col2 = st.columns([1, 3])
        with col1:
            p = st.text_input(f"Price {i+1}", placeholder="e.g. 60", key=f"tier_price_{i}")
        with col2:
            r = st.text_input(
                f"Seat ranges for Price {i+1}",
                placeholder="e.g. Stalls A1-A4, Rausing Circle ROW 1 - 3-6",
                key=f"tier_ranges_{i}"
            )
        tier_prices.append(p.strip())
        tier_ranges.append(r.strip())

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

def norm_label(s: str) -> str:
    s = strip_brackets(s or "")
    s = s.replace("–", "-").replace("—", "-")
    s = s.replace("\u00a0", " ").replace("\u202f", " ")
    s = s.lower().replace("seat", "")
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"row0?(\d+)", r"row\1", s)
    return s

def split_norm_label(norm: str):
    norm = norm.replace("seat", "")
    m = re.match(r"(row\d+)-?(\d+)$", norm)     # row1-23 or row1 23
    if m:
        return m.group(1), int(m.group(2))
    m = re.match(r"([a-z][a-z\-]{0,19})(\d+)$", norm)  # a23, aa23, yellow12
    if m:
        return m.group(1), int(m.group(2))
    return None

def section_names_from_data(seat_data):
    names = []
    for sec in seat_data.values():
        if isinstance(sec, dict) and sec.get("section_name") and sec.get("type","def") != "aoi":
            names.append(re.sub(r"\s+", " ", sec["section_name"].strip()))
    return names

# Parse ranges (no @price; pricing handled by UI tiers)
# Returns: requested_keys set[(sec_low,pref,num)], debug_list [(SectionDisp, "pref-num")]
def parse_input_ranges(user_text: str, section_names):
    requested = set()
    debug_rows = []
    if not user_text:
        return requested, debug_rows

    canon_sections = {s.lower(): s for s in section_names if s}
    chunks = [c.strip() for c in re.split(r"\s*,\s*", user_text) if c.strip()]

    RX = re.compile(
        r"(?:(row)\s*(\d+)\s*(?:-|–)?\s*(\d+)\s*(?:to|–|-)\s*(\d+))"   # ROW X - a-b
        r"|(?:(row)\s*(\d+)\s*(?:-|–)?\s*(\d+))"                       # ROW X - a
        r"|([a-z][a-z\-]{0,19})\s*(\d+)\s*(?:\s*(?:to|–|-)\s*(\d+))?", # A11-21, Yellow 1-12
        re.I
    )

    for chunk in chunks:
        # find section (longest name match)
        sec_match = None
        chunk_low = chunk.lower()
        for low_name, canon in sorted(canon_sections.items(), key=lambda x: len(x[0]), reverse=True):
            if chunk_low.startswith(low_name):
                after = chunk_low[len(low_name):]
                if after == "" or (after and after[0].isspace()):
                    sec_match = (low_name, canon)
                    break
        if not sec_match:
            continue

        sec_low, sec_canon = sec_match
        rest = chunk[len(sec_canon):].strip()

        for m in RX.finditer(rest):
            if m.group(1):  # ROW X - a-b
                rownum = int(m.group(2)); a = int(m.group(3)); b = int(m.group(4))
                lo, hi = sorted((a, b)); pref = f"row{rownum}"
                for n in range(lo, hi + 1):
                    requested.add((sec_low, pref, n))
                    debug_rows.append((sec_canon, f"{pref}-{n}"))
            elif m.group(5):  # ROW X - a
                rownum = int(m.group(6)); n = int(m.group(7)); pref = f"row{rownum}"
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

        # Normalise section names (and skip AOIs when indexing)
        for sec in seat_data.values():
            if isinstance(sec, dict) and "section_name" in sec:
                sec["section_name"] = re.sub(r"\s+", " ", sec["section_name"]).strip()

        # Build seat index: (section_low, prefix, number) -> (seat_obj, display_section)
        seat_index = {}
        per_section_counts = defaultdict(int)

        for sec in seat_data.values():
            if not isinstance(sec, dict):
                continue
            if sec.get("type", "def") == "aoi":  # skip non-seat areas like Stage
                continue
            sec_disp = sec.get("section_name", "Unknown Section").strip()
            sec_low = sec_disp.lower()
            rows = sec.get("rows", {}) or {}
            for row in rows.values():
                seats = (row or {}).get("seats", {}) or {}
                for seat in seats.values():
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

        # Copy-Paste helper of current AV seats
        row_map = defaultdict(list)
        available_count = 0
        for (sec_low, pref, num), (seat, sec_disp) in seat_index.items():
            if (seat.get("status","") or "").lower() == "av":
                available_count += 1
                row_map[(sec_disp, pref)].append(num)

        out_lines = []
        for (sec_disp, pref), nums in sorted(row_map.items(), key=lambda x: (x[0][0].lower(), sort_key(x[0][1]))):
            for s, e in compress_ranges(nums):
                disp_pref = display_prefix(pref)
                out_lines.append(f"{sec_disp} {disp_pref}{s}" if s == e else f"{sec_disp} {disp_pref}{s}-{e}")

        st.markdown("### 🪑 Copy-Paste Friendly Available Seat Ranges")
        if out_lines:
            st.text_area("📋 Paste this back into the seat ranges box if needed:", value=", ".join(out_lines), height=200)
            st.info(f"ℹ️ Total currently available seats in the list: **{available_count}**")
        else:
            st.info("No available seats found.")

        # Parse input(s)
        section_names = section_names_from_data(seat_data)

        # Availability targets (single-price mode uses this; multi-price mode uses union of tier ranges)
        requested_av = set()
        debug_list_av = []
        if seat_range_input:
            requested_av, debug_list_av = parse_input_ranges(seat_range_input, section_names)

        # Multi-price: build price_rules from tiers; also compute union of all tier seat targets
        price_rules = {}
        requested_union_from_tiers = set()
        if multi_price_mode:
            for p, r in zip(tier_prices, tier_ranges):
                if not r:
                    continue
                seats_for_price, _dbg = parse_input_ranges(r, section_names)
                for key in seats_for_price:
                    price_rules[key] = p  # explicit per-seat price override
                requested_union_from_tiers |= seats_for_price

        # Apply updates
        if st.button("▶️ Go"):
            matched = []
            updated_seats = []
            missing = []

            # Choose availability targets:
            if price_only_mode:
                # leave availability alone
                targets_for_av = set()
            else:
                if multi_price_mode:
                    targets_for_av = requested_union_from_tiers
                else:
                    targets_for_av = requested_av

            # Toggle availability for requested seats
            for key in targets_for_av:
                if key in seat_index:
                    seat, sec_disp = seat_index[key]
                    if (seat.get("status","") or "").lower() != "av":
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

            # Apply prices
            if multi_price_mode:
                # Set prices from tier rules only (no section-level)
                for key, p in price_rules.items():
                    if key in seat_index and p:
                        seat, _ = seat_index[key]
                        seat["price"] = str(p)
                st.success("💸 Tiered prices applied.")
            else:
                # Single-price mode (optional global price)
                global_price = (st.session_state.get('single_price_value') 
                                if 'single_price_value' in st.session_state else None)
                # To keep compatibility with prior UI, read directly:
                # (we're not storing to session_state; just read the widget value)
                global_price = None  # reset each click
                # Re-fetch the current widget value:
                # (Streamlit passes it via closure; easiest is to look it up again if exists)
                try:
                    global_price = st.session_state["Enter price for requested seats (optional)"]
                except Exception:
                    pass
                # If that lookup is awkward across versions, fall back to local variable:
                # In practice, price_input above is still in scope when not multi mode:
                if 'price_input' in locals() and (price_input or "").strip():
                    global_price = (price_input or "").strip()

                if global_price:
                    # apply to requested seats if not price-only; else apply to ALL seats
                    if price_only_mode:
                        for key, (seat
