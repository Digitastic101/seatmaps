import streamlit as st
import json, re, itertools

st.title("🎭 Seat Map Availability Editor")

uploaded_file = st.file_uploader("Upload your seat map JSON file", type=["json"])

seat_range_input = st.text_input(
    "Enter seat ranges (e.g. Stalls C23-C28, Dress Circle ROW 1 - 5-12, Yellow A3-5, Platform 1 F8-19)",
    placeholder="Platform 1 E8-14, Platform 1 F8-19, Platform 1 G11-21"
)

price_input = st.text_input(
    "Enter new price for all seats (optional)",
    placeholder="e.g. 65"
)

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
        m = re.match(r"row(\d+)", pref)
        if m:
            return f"ROW {m.group(1)} - "
    return pref.upper()

def norm_label(s: str) -> str:
    """Normalise a seat label like '(VIP) E 12' -> 'e12' or 'main-left12'."""
    s = strip_brackets(s)
    return re.sub(r"\s+", "", s).lower()

def section_names_from_data(seat_data):
    return [sec.get("section_name","").strip() for sec in seat_data.values() if isinstance(sec, dict) and sec.get("section_name")]

def parse_input_ranges(user_text: str, section_names):
    """
    Robust, section-aware parser.
    Returns:
      requested -> set[(section_lower, seat_norm 'a12'|'main-left12'|'row3<seatnum>')]
      debug_rows -> list of (SectionDisplay, seat_norm) for UI preview
    """
    requested = set()
    debug_rows = []
    if not user_text:
        return requested, debug_rows

    # Map lowercase section_name -> canonical display
    canon_sections = {s.lower(): s for s in section_names if s}
    # Split by commas into chunks; each chunk should begin with a section name
    chunks = [c.strip() for c in re.split(r"\s*,\s*", user_text) if c.strip()]
    for chunk in chunks:
        # Find section by longest prefix match (case-insensitive, must be word boundary or space after)
        sec_match = None
        chunk_low = chunk.lower()
        for low_name, canon in sorted(canon_sections.items(), key=lambda x: len(x[0]), reverse=True):
            if chunk_low.startswith(low_name):
                after = chunk_low[len(low_name):]
                if after == "" or after[0].isspace():
                    sec_match = (low_name, canon)
                    break
        if not sec_match:
            # No recognizable section at the start; skip this chunk
            continue

        sec_low, sec_canon = sec_match
        rest = chunk[len(sec_canon):].strip()

        # Accept:
        #  1) ROW-style range: "ROW 3 - 21-30", "row3 - 21-30"
        #  2) ROW-style single: "ROW 3 - 21"
        #  3) Alpha/word prefix: "E8-14", "AA10-22", "Yellow 1-12" (if Yellow is row label), "Main-Left 3-9"
        rx = re.compile(
            r"(?:(row)\s*(\d+)\s*-\s*(\d+)\s*(?:to|–|-)\s*(\d+))"         # ROW X - a-b
            r"|(?:(row)\s*(\d+)\s*-\s*(\d+))"                             # ROW X - a
            r"|([a-z][a-z\-]{0,19})\s*(\d+)\s*(?:\s*(?:to|–|-)\s*(\d+))?",# prefix a-b
            re.I
        )

        for m in rx.finditer(rest):
            if m.group(1):  # full ROW with range
                rownum = int(m.group(2))
                start, end = int(m.group(3)), int(m.group(4))
                a, b = sorted((start, end))
                for n in range(a, b + 1):
                    key = (sec_low, f"row{rownum}{n}")
                    requested.add(key)
                    debug_rows.append((sec_canon, key[1]))
            elif m.group(5):  # ROW with single number
                rownum = int(m.group(6))
                n = int(m.group(7))
                key = (sec_low, f"row{rownum}{n}")
                requested.add(key)
                debug_rows.append((sec_canon, key[1]))
            else:  # alpha/word prefix
                pref = m.group(8).lower()
                a = int(m.group(9))
                b = int(m.group(10) or m.group(9))
                lo, hi = sorted((a, b))
                for n in range(lo, hi + 1):
                    key = (sec_low, f"{pref}{n}")
                    requested.add(key)
                    debug_rows.append((sec_canon, key[1]))

    return requested, debug_rows

# ──────────────── main UI logic ────────────────
if uploaded_file:
    try:
        seat_data = json.loads(uploaded_file.read().decode("utf-8"))
        st.success("✅ Seat map loaded successfully!")

        # Build current-availability map for copy/paste helper + count
        row_map = {}
        available_count = 0
        for sec in seat_data.values():
            sec_name = sec.get("section_name", "Unknown Section")
            if "rows" not in sec:
                continue
            for row in sec["rows"].values():
                for seat in row["seats"].values():
                    if seat.get("status","").lower() == "av":
                        available_count += 1
                        label = norm_label(seat.get("number",""))
                        # Accept word prefixes up to 20 chars, letters + hyphens
                        m = re.match(r"([a-z][a-z\-]{0,19})(\d+)", label)
                        if not m:
                            continue
                        pref, num = m.group(1), int(m.group(2))
                        row_map.setdefault((sec_name, pref), []).append(num)

        out_lines = []
        for (sec_name, pref), nums in sorted(row_map.items(), key=lambda x: (x[0][0].lower(), sort_key(x[0][1]))):
            for s, e in compress_ranges(nums):
                disp_pref = display_prefix(pref)
                out_lines.append(
                    f"{sec_name} {disp_pref}{s}" if s == e else f"{sec_name} {disp_pref}{s}-{e}"
                )

        st.markdown("### 🪑 Copy-Paste Friendly Available Seat Ranges")
        if out_lines:
            st.text_area(
                "📋 Paste this into 'Enter seat ranges':",
                value=", ".join(out_lines),
                height=200
            )
            st.info(f"ℹ️ Total currently available seats in the list: **{available_count}**")
        else:
            st.info("No available seats found.")

        # Preview what the input will target
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

            # Build requested set using the robust parser
            section_names = section_names_from_data(seat_data)
            requested, debug_rows = parse_input_ranges(seat_range_input, section_names)

            # ── Walk the structure and apply updates ──
            for sec in seat_data.values():
                sec_key = sec.get("section_name","").strip().lower()
                if "rows" not in sec:
                    continue

                # Optional: section-level price
                if price_value:
                    sec["price"] = price_value

                for row_key, row in sec["rows"].items():
                    row_updated = False
                    for seat in row["seats"].values():
                        label_raw = seat.get("number","")
                        norm = norm_label(label_raw)

                        # alpha/word prefixes up to 20 chars + seat number
                        mrow = re.match(r"([a-z][a-z\-]{0,19})(\d+)", norm)
                        key_alpha = (sec_key, norm) if mrow else None

                        should_update = False
                        current_status = seat.get("status", "").strip().lower()

                        # Availability updates (only if not in price-only mode)
                        if seat_range_input and not price_only_mode:
                            if key_alpha in requested:
                                # Turn ON
                                found.add(key_alpha)
                                matched.append(f"{sec.get('section_name','')} {label_raw.strip()}")
                                if current_status != "av":
                                    seat["status"] = "av"
                                    should_update = True
                            else:
                                # Turn OFF all others that are currently AV
                                if current_status == "av":
                                    seat["status"] = "uav"
                                    should_update = True

                        # Price updates (independent of availability)
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

                    # Row-level price propagation if anything changed or in price-only mode
                    if (row_updated or price_only_mode) and price_value:
                        row["price"] = price_value
                        row["row_price"] = price_value
                        row_price_map[f"{sec.get('section_name','')} - {row_key}"] = price_value

            # ── UI feedback ──
            if price_value:
                st.success(f"💸 Prices updated to {price_value} across all matching seats, rows & sections.")

            if not price_only_mode and seat_range_input:
                st.markdown("### ✅ Availability Updated")
                st.write(", ".join(sorted(matched)) if matched else "No seat availability was changed.")
                # Missing seats warning
                missing = {k for k in requested if k not in found}
                if missing:
                    pretty = [f"{sec.title()} {seat.upper()}" for sec, seat in sorted(missing)]
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

            if seat_range_input:
                st.markdown("### 🔍 Parsed Seat Targets (after run)")
                st.table(debug_rows if 'debug_rows' in locals() else [])

    except Exception as e:
        st.error(f"❌ Error reading file: {e}")
