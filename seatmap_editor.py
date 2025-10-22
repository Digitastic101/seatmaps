import streamlit as st
import json, re, itertools
from collections import defaultdict

st.title("🎭 Seat Map Availability Editor ")

uploaded_file = st.file_uploader("Upload your seat map JSON file", type=["json"])

# ---- global UI controls ----
multi_price_mode = st.checkbox("💰 Enable multiple price groups (Price 1 + Range 1, Price 2 + Range 2)")
price_only_mode = st.checkbox("💸 Only update seat prices (leave availability unchanged)")

# New: availability limiter (irrelevant when price-only is on)
limit_to_ranges = st.checkbox(
    "🔒 Limit availability to selected ranges (set others to UAV)",
    value=True,
    help="When updating availability, only seats in your selected ranges will be AV; everything else becomes UAV.",
    disabled=price_only_mode
)

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

# Parse ranges (prices are provided by group fields or global; global disabled in price-only mode)
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

def to_price_float(v):
    s = (str(v) if v is not None else "").strip()
    if not s:
        return None
    m = re.match(r"^\d+(?:\.\d+)?$", s)
    return float(s) if m else None

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
            if sec.get("type", "def") == "aoi":  # skip areas of interest (e.g., Stage)
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

        # Build copy/paste helper of current AV seats
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

        # ---------- Price inputs (global price is disabled when tiers are active: price-only mode) ----------
        if multi_price_mode:
            st.markdown("#### Price Group 1")
            price1 = st.text_input("Price 1", placeholder="e.g. 60", key="price1")
            range1 = st.text_input("Seat ranges for Price 1", placeholder="e.g. Stalls A1-A4, A5-A8", key="range1")

            st.markdown("#### Price Group 2")
            price2 = st.text_input("Price 2", placeholder="e.g. 45", key="price2")
            range2 = st.text_input("Seat ranges for Price 2", placeholder="e.g. Rausing Circle ROW 1 - 1-6", key="range2")

            if price_only_mode:
                price_input = None
                st.info("Tier editing is active (price-only mode). Global price is disabled.")
            else:
                price_input = st.text_input("Optional global price for targeted seats (fallback)", placeholder="e.g. 65")
        else:
            seat_range_input = st.text_input(
                "Enter seat ranges",
                placeholder="Rausing Circle ROW 1 - 1-6, Stalls A1-A5"
            )
            if price_only_mode:
                price_input = None
                st.info("Tier editing is active (price-only mode). Global price is disabled.")
            else:
                price_input = st.text_input("Enter new price", placeholder="e.g. 65")

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
        overlap = set()

        if multi_price_mode:
            if range1:
                requested_group1 = parse_ranges(range1, section_names)
            if range2:
                requested_group2 = parse_ranges(range2, section_names)

            # Overlap detection: seats appearing in both groups
            overlap = requested_group1 & requested_group2
            if overlap:
                # Pretty-print a small sample
                sec_title = {s.lower(): s for s in section_names}
                def pretty_key(k):
                    sec_low, pref, n = k
                    sec_disp = sec_title.get(sec_low, "?")
                    pp = "ROW " + pref[3:] if pref.startswith("row") else pref.upper()
                    return f"{sec_disp} {pp}-{n}"
                sample = ", ".join(pretty_key(k) for k in list(sorted(overlap))[:10])
                st.error(
                    f"⚠️ {len(overlap)} overlapping seats appear in both groups. "
                    f"Group 1 takes precedence; these will be ignored in Group 2. "
                    f"Sample: {sample}{' …' if len(overlap)>10 else ''}"
                )

            st.markdown("### 🔎 Parsed Seat Targets (Preview)")
            st.write(f"Group 1 seats: **{len(requested_group1)}** | Group 2 seats: **{len(requested_group2)}** "
                     f"(overlap: {len(overlap)})")
        else:
            if 'seat_range_input' in locals() and seat_range_input:
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

                # Apply per-group prices, with Group 1 precedence (remove overlaps from Group 2)
                requested_group2_effective = requested_group2 - overlap

                if 'price1' in locals() and price1:
                    for key in requested_group1:
                        if key in seat_index:
                            seat, _ = seat_index[key]
                            seat["price"] = str(price1)

                if 'price2' in locals() and price2:
                    for key in requested_group2_effective:
                        if key in seat_index:
                            seat, _ = seat_index[key]
                            seat["price"] = str(price2)

                # Optional global fallback for targeted seats w/o group price
                # (Note: price_input is None if price_only_mode=True, so this won't run during tier edits)
                if 'price_input' in locals() and price_input:
                    targeted = (requested_group1 | requested_group2_effective)
                    for key in targeted:
                        if key in seat_index:
                            seat, _ = seat_index[key]
                            if not str(seat.get("price","")).strip():
                                seat["price"] = str(price_input)

                # Limit availability to selected ranges (UAV everything else)
                if not price_only_mode and limit_to_ranges:
                    targeted = requested_group1 | requested_group2_effective
                    turned_off = 0
                    for key, (seat, _) in seat_index.items():
                        if key not in targeted:
                            if (seat.get("status","") or "").lower() != "uav":
                                seat["status"] = "uav"
                                turned_off += 1
                    if turned_off:
                        st.info(f"🔕 Set {turned_off} non-targeted seats to UAV.")

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

                # Apply global price ONLY when tiers are NOT active
                if 'price_input' in locals() and price_input and not price_only_mode:
                    for key in requested_single:
                        if key in seat_index:
                            seat, _ = seat_index[key]
                            seat["price"] = str(price_input)

                # Limit availability to selected ranges (UAV everything else)
                if not price_only_mode and limit_to_ranges and requested_single:
                    turned_off = 0
                    for key, (seat, _) in seat_index.items():
                        if key not in requested_single:
                            if (seat.get("status","") or "").lower() != "uav":
                                seat["status"] = "uav"
                                turned_off += 1
                    if turned_off:
                        st.info(f"🔕 Set {turned_off} non-targeted seats to UAV.")

            # Post-ops messaging
            if not price_only_mode and (requested_single or requested_group1 or requested_group2):
                st.markdown("### ✅ Availability Updated")
                st.write(", ".join(sorted(matched)) if matched else "No seat availability was changed.")

                if missing:
                    # pretty print missing
                    sec_title = {s.lower(): s for s in section_names}
                    pretty = [f"{sec_title.get(sec,'?')} {pref.upper()}-{n}" for (sec, pref, n) in sorted(missing)]
                    st.warning("⚠️ Seats not found: " + ", ".join(pretty))

            if updated_seats:
                st.markdown("### 🎟️ Updated Seats")
                st.dataframe(updated_seats, use_container_width=True)

            # --- Normalise row-level price to the highest seat price in that row ---
            rows_updated = 0
            for sec in seat_data.values():
                if not isinstance(sec, dict) or sec.get("type") == "aoi":
                    continue
                rows = (sec.get("rows") or {})
                for row in rows.values():
                    seats = (row.get("seats") or {})
                    max_price = None
                    for seat in seats.values():
                        p = to_price_float(seat.get("price"))
                        if p is not None:
                            max_price = p if max_price is None else max(max_price, p)
                    if max_price is not None:
                        row["price"] = str(max_price)
                        rows_updated += 1
            if rows_updated:
                st.info(f"📏 Row prices set to the highest seat price in {rows_updated} rows.")

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
