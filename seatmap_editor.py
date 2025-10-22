import streamlit as st
import json, re, itertools
from collections import defaultdict

st.title("🎭 Seat Map Availability Editor — Seamless Tier Edits")

uploaded_file = st.file_uploader("Upload your seat map JSON file", type=["json"])

# ---- global UI controls ----
multi_price_mode = st.checkbox("💰 Enable multiple price groups (Price 1 + Range 1, Price 2 + Range 2)")
price_only_mode = st.checkbox("💸 Only update seat prices (leave availability unchanged)")

# ---- price inputs ----
if multi_price_mode:
    st.markdown("#### Price Group 1")
    price1 = st.text_input("Price 1", placeholder="e.g. 60", key="price1")
    range1 = st.text_input("Seat ranges for Price 1", placeholder="e.g. Stalls A1-A4, A5-A8", key="range1")

    st.markdown("#### Price Group 2")
    price2 = st.text_input("Price 2", placeholder="e.g. 45", key="price2")
    range2 = st.text_input("Seat ranges for Price 2", placeholder="e.g. Rausing Circle ROW 1 - 1-6", key="range2")

    # Optional global fallback price for targeted seats without a group price
    price_input = st.text_input("Optional global price for targeted seats (fallback)", placeholder="e.g. 65")
else:
    seat_range_input = st.text_input(
        "Enter seat ranges",
        placeholder="Rausing Circle ROW 1 - 1-6, Stalls A1-A5"
    )
    price_input = st.text_input("Enter new price", placeholder="e.g. 65")

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
    s = re.sub(r"\s*-\s*", "-", s)   # tidy hyphen spacing
    s = re.sub(r"\s+", "", s)        # drop remaining spaces
    s = re.sub(r"row0?(\d+)", r"row\1", s)  # drop leading zero in row
    return s

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
    names = []
    for sec in seat_data.values():
        if isinstance(sec, dict) and sec.get("section_name") and sec.get("type","def") != "aoi":
            names.append(re.sub(r"\s+", " ", sec["section_name"].strip()))
    return names

# Parse ranges (prices are managed via group fields or global)
# Returns: set[(sec_low,pref,num)]
def parse_ranges(user_text: str, section_names):
    requested = set()
    if not user_text:
        return requested

    canon_sections = {s.lower(): s for s in section_names if s}
    chunks = [c.strip() for c in re.split(r"\s*,\s*", user_text) if c.strip()]

    rx = re.compile(
        r"(?:(row)\s*(\d+)\s*(?:-|–)?\s*(\d+)\s*(?:to|–|-)\s*(\d+))"     # ROW X - a-b
        r"|(?:(row)\s*(\d+)\s*(?:-|–)?\s*(\d+))"                         # ROW X - a
        r"|([a-z][a-z\-]{0,19})\s*(\d+)\s*(?:\s*(?:to|–|-)\s*(\d+))?",   # A11-21, Yellow 1-12
        re.I
    )

    for chunk in chunks:
        sec_match = None
        chunk_low = chunk.lower()
        # longest section match
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
                rownum = int(m.group(2)); a = int(m.group(3)); b = int(m.group(4))
                lo, hi = sorted((a, b)); pref = f"row{rownum}"
                for n in range(lo, hi + 1):
                    requested.add((sec_low, pref, n))
            elif m.group(5):  # ROW X - a
                rownum = int(m.group(6)); n = int(m.group(7)); pref = f"row{rownum}"
                requested.add((sec_low, pref, n))
            else:  # alpha/word prefix
                pref = m.group(8).lower()
                a = int(m.group(9)); b = int(m.group(10) or m.group(9))
                lo, hi = sorted((a, b))
                for n in range(lo, hi + 1):
                    requested.add((sec_low, pref, n))
    return requested

# ──────────────── main UI logic ────────────────
if uploaded_file:
    try:
        seat_data = json.loads(uploaded_file.read().decode("utf-8"))
        st.success("✅ Seat map loaded successfully!")

        # Normalise section names
        for sec in seat_data.values():
            if isinstance(sec, dict) and "section_name" in sec:
                sec["section_name"] = re.sub(r"\s+", " ", sec["section_name"]).strip()

        # Build seat index: (section_low, prefix, number) -> (seat_obj, display_section)
        seat_index = {}
        per_section_counts = defaultdict(int)

        for sec in seat_data.values():
            if not isinstance(sec, dict): 
                continue
            if sec.get("type", "def") == "aoi":  # skip areas of interest (no seats)
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

        # Copy/paste helper of current AV seats
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
            st.text_area("📋 Paste this into 'Enter seat ranges':", value=", ".join(out_lines), height=200)
            st.info(f"ℹ️ Total currently available seats in the list: **{available_count}**")
        else:
            st.info("No available seats found.")

        # ----- Seamless Tier Detection UI (auto when price-only mode is on) -----
        tier_new_values = {}   # { (sec_disp, current_price) -> new_price_string }
        tier_listing = []
        tier_keys_order = []

        if price_only_mode:
            tiers = defaultdict(list)  # (sec_disp, price) -> [ (sec_disp, pref, num, seat) ]
            for (sec_low, pref, num), (seat, sec_disp) in seat_index.items():
                if (seat.get("status","") or "").lower() != "av":
                    continue
                seat_price = str(seat.get("price","")).strip() or "∅"
                key = (sec_disp, seat_price)
                tiers[key].append((sec_disp, pref, num, seat))

            st.markdown("### 🧮 Price tiers (AV seats, grouped by section)")
            if not tiers:
                st.info("No AV tiers found.")
            else:
                # build listing + inline inputs
                for i, (key, seats) in enumerate(sorted(tiers.items(), key=lambda kv: (kv[0][0].lower(), kv[0][1]))):
                    sec_disp, price = key
                    tier_label = f"{sec_disp} — £{price}" if price != "∅" else f"{sec_disp} — (no price)"
                    count = len(seats)
                    # sample locations
                    sample_locs = []
                    for (sdisp, pref, num, _seat) in seats[:6]:
                        pp = "ROW " + pref[3:] if pref.startswith("row") else pref.upper()
                        sample_locs.append(f"{sdisp} {pp}-{num}")

                    tier_listing.append({
                        "Tier": tier_label,
                        "Seats (count)": count,
                        "Sample": ", ".join(sample_locs) + (" …" if count > 6 else "")
                    })
                    tier_keys_order.append(key)

                st.dataframe(tier_listing, use_container_width=True)
                st.markdown("#### ✏️ Update each tier (leave blank to skip)")
                for i, key in enumerate(tier_keys_order):
                    sec_disp, price = key
                    caption = f"New price for **{sec_disp}** where current price = **{price if price!='∅' else '∅ (no price)'}**"
                    val = st.text_input(f"→ {caption}", key=f"tier_new_{i}", placeholder="leave blank to skip")
                    val = (val or "").strip()
                    if val:
                        if not re.match(r"^\d+(?:\.\d+)?$", val):
                            st.warning(f"'{val}' doesn’t look like a number — this tier will be skipped unless corrected.")
                        else:
                            tier_new_values[key] = val

        # ----- Parse input ranges (single or multi mode) -----
        section_names = section_names_from_data(seat_data)
        requested_group1 = set()
        requested_group2 = set()
        requested_single = set()

        if multi_price_mode:
            if range1:
                requested_group1 = parse_ranges(range1, section_names)
            if range2:
                requested_group2 = parse_ranges(range2, section_names)
            st.markdown("### 🔎 Parsed Seat Targets (Preview)")
            st.write(f"Group 1 seats: **{len(requested_group1)}** | Group 2 seats: **{len(requested_group2)}**")
        else:
            if seat_range_input:
                requested_single = parse_ranges(seat_range_input, section_names)
                st.markdown("### 🔎 Parsed Seat Targets (Preview)")
                st.write(f"Targets parsed: **{len(requested_single)}** seats")

        # ----- Apply updates -----
        if st.button("▶️ Go"):
            matched = []
            updated_seats = []
            missing = []

            # 1) Apply Tier Price Edits FIRST (so later logic won't clobber)
            if price_only_mode and tier_new_values:
                changed = 0
                for (sec_low, pref, num), (seat, sec_disp) in seat_index.items():
                    if (seat.get("status","") or "").lower() != "av":
                        continue
                    cur_price = str(seat.get("price","")).strip() or "∅"
                    new_p = tier_new_values.get((sec_disp, cur_price))
                    if new_p:
                        seat["price"] = str(new_p)
                        changed += 1
                if changed:
                    st.success(f"💸 Updated {changed} AV seats via tier edits.")

            # 2) Multiple price groups mode
            if multi_price_mode:
                # Availability change (unless price-only)
                if not price_only_mode:
                    for req_set in (requested_group1, requested_group2):
                        for key in req_set:
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

                # Per-group prices
                if price1:
                    for key in requested_group1:
                        if key in seat_index:
                            seat, _ = seat_index[key]
                            seat["price"] = str(price1)

                if price2:
                    for key in requested_group2:
                        if key in seat_index:
                            seat, _ = seat_index[key]
                            seat["price"] = str(price2)

                # Optional global fallback for targeted seats w/o group price
                if price_input:
                    targeted = (requested_group1 | requested_group2)
                    for key in targeted:
                        if key in seat_index:
                            seat, _ = seat_index[key]
                            if not str(seat.get("price","")).strip():
                                seat["price"] = str(price_input)

            # 3) Single range + price mode
            else:
                # Availability change (unless price-only)
                if not price_only_mode and requested_single:
                    for key in requested_single:
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

                # Apply price input if present
                if price_input:
                    if price_only_mode:
                        # Price-only: update ALL seats to global price
                        for (sec_low, pref, num), (seat, _) in seat_index.items():
                            seat["price"] = str(price_input)
                    else:
                        # Only requested seats
                        for key in requested_single:
                            if key in seat_index:
                                seat, _ = seat_index[key]
                                seat["price"] = str(price_input)

            # Post-ops messaging
            if not price_only_mode and (requested_single or requested_group1 or requested_group2):
                st.markdown("### ✅ Availability Updated")
                st.write(", ".join(sorted(matched)) if matched else "No seat availability was changed.")

                if missing:
                    sec_title = {s.lower(): s for s in section_names}
                    pretty = [f"{sec_title.get(sec,'?')} {pref.upper()}-{n}" for (sec, pref, n) in sorted(missing)]
                    st.warning("⚠️ Seats not found: " + ", ".join(pretty))

            if updated_seats:
                st.markdown("### 🎟️ Updated Seats")
                st.dataframe(updated_seats, use_container_width=True)

            # Sample price summary
            st.markdown("### 📊 Seat Price Summary (sample)")
            sample = []
            for i, ((sec_low, pref, num), (seat, sec_disp)) in enumerate(sorted(seat_index.items())[:300]):
                sample.append({"Section": sec_disp, "Seat": seat.get("number",""), "Price": seat.get("price","")})
            st.dataframe(sample, use_container_width=True)

            st.download_button(
                "Download Updated JSON",
                json.dumps(seat_data, indent=2),
                file_name="updated_seatmap.json",
                mime="application/json"
            )

    except Exception as e:
        st.error(f"❌ Error reading file: {e}")
