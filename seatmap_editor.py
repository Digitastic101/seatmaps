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

# ───────────────── helper functions ─────────────────

# Remove any (…) parts before comparing labels (e.g. "(VIP) C12" -> "C12")
BRACKET_RX = re.compile(r"(\([^)]*\))")

def strip_brackets(s: str) -> str:
    return BRACKET_RX.sub("", s or "").strip()

def extract_row_and_number(label: str):
    """
    Returns a tuple (prefix, number) where:
      - prefix is either 'row<digits>' or 1–3 alpha letters (lowercased, no spaces)
      - number is an int
    Bracketed parts in the label are ignored for parsing.
    """
    label = strip_brackets(label)
    label = label.strip().lower().replace(" ", "")

    # ROW-style like "row3-23" or "row3 23" or "row3_23" etc.: we accept optional dash
    row_match = re.match(r"(row\d+)-?(\d+)", label)
    if row_match:
        return row_match.group(1), int(row_match.group(2))

    # Alpha style like "c23", "aa17"
    alpha_match = re.match(r"([a-z]{1,3})(\d+)", label)
    if alpha_match:
        return alpha_match.group(1), int(alpha_match.group(2))

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

def display_prefix(pref: str) -> str:
    """
    Convert internal prefix ('row3' or 'c') into display form expected by the parser.
    - 'row3' -> 'ROW 3 - '  (note trailing ' - ')
    - 'c'    -> 'C'
    """
    if pref.startswith("row"):
        m = re.match(r"row(\d+)", pref)
        if m:
            return f"ROW {m.group(1)} - "
    return pref.upper()

# ──────────────── main UI logic ────────────────
if uploaded_file:
    try:
        seat_data = json.loads(uploaded_file.read().decode("utf-8"))
        st.success("✅ Seat map loaded successfully!")

        # Build a map of currently available seats for quick copy
        row_map = {}
        for sec in seat_data.values():
            sec_name = sec.get("section_name", "Unknown Section")
            if "rows" not in sec:
                continue
            for row in sec["rows"].values():
                for seat in row["seats"].values():
                    if seat.get("status", "").lower() == "av":
                        pref, num = extract_row_and_number(seat.get("number", ""))
                        if pref and num is not None:
                            row_map.setdefault((sec_name, pref), []).append(num)

        out_lines = []
        for (sec_name, pref), nums in sorted(row_map.items(), key=lambda x: (x[0][0].lower(), sort_key(x[0][1]))):
            for s, e in compress_ranges(nums):
                disp_pref = display_prefix(pref)
                if pref.startswith("row"):
                    # For ROW-style we produce: "<Section> ROW <n> - <start>-<end>"
                    out_lines.append(
                        f"{sec_name} {disp_pref}{s}" if s == e else f"{sec_name} {disp_pref}{s}-{e}"
                    )
                else:
                    # For alpha prefix we produce: "<Section> C<start>-<end>"
                    out_lines.append(
                        f"{sec_name} {disp_pref}{s}" if s == e else f"{sec_name} {disp_pref}{s}-{e}"
                    )

        st.markdown("### 🪑 Copy-Paste Friendly Available Seat Ranges")
        if out_lines:
            st.text_area("📋 Paste this into 'Enter seat ranges':", value=", ".join(out_lines), height=200)
        else:
            st.info("No available seats found.")

        if st.button("▶️ Go"):
            price_value = price_input.strip() or None
            matched, requested, found, debug = [], set(), set(), []
            updated_seats = []
            row_price_map = {}

            # ── Parse target ranges from user input ──
            if seat_range_input:
                txt = seat_range_input
                rx = re.compile(
                    r"(?P<section>[A-Za-z0-9 ]+?)\s+"
                    r"(?P<pref>(row\s*\d+\s*-\s*|[a-z]{1,3}))?"
                    r"\s*(?P<start>\d+)"
                    r"(?:\s*(?:to|–|-)+\s*(?P<end>\d+))?",
                    re.I
                )
                for m in rx.finditer(txt):
                    sec = (m.group("section") or "").strip().lower()

                    # Clean the prefix from brackets & spaces, then lowercase for matching
                    raw_pref = m.group("pref") or ""
                    pref = re.sub(r"\s*", "", strip_brackets(raw_pref)).lower()

                    a, b = int(m.group("start")), int(m.group("end") or m.group("start"))
                    for n in range(a, b + 1):
                        full = f"{pref}{n}".lower()
                        requested.add((sec, full))
                        debug.append((sec, full))

            # ── Walk the structure and apply updates ──
            for sec in seat_data.values():
                sec_key = sec.get("section_name", "").strip().lower()
                if "rows" not in sec:
                    continue

                # Optional: section-level price
                if price_value:
                    sec["price"] = price_value

                for row_key, row in sec["rows"].items():
                    row_updated = False

                    for seat in row["seats"].values():
                        label_raw = seat.get("number", "")
                        # Ignore everything in brackets for comparisons
                        label = strip_brackets(label_raw)
                        norm = re.sub(r"\s*", "", label).lower()
                        key = (sec_key, norm)

                        should_update = False
                        current_status = seat.get("status", "").strip().lower()

                        # Availability updates (only if not in price-only mode)
                        if seat_range_input and not price_only_mode:
                            if key in requested:
                                # Ensure ON
                                found.add(key)
                                matched.append(f"{sec.get('section_name','')} {label_raw.strip()}")
                                if current_status != "av":
                                    seat["status"] = "av"
                                    should_update = True
                            else:
                                # Only turn OFF if currently ON
                                if current_status == "av":
                                    seat["status"] = "uav"
                                    should_update = True

                        # Price updates (independent of availability)
                        if price_value:
                            if seat.get("price") != price_value:
                                seat["price"] = price_value
                                should_update = True

                        if should_update:
                            updated_seats.append({
                                "Section": sec.get("section_name", ""),
                                "Seat": label_raw.strip(),
                                "Status": seat.get("status", ""),
                                "Price": seat.get("price", "")
                            })
                            row_updated = True

                    # Row-level price propagation if anything changed or in price-only mode
                    if row_updated or price_only_mode:
                        if price_value:
                            row["price"] = price_value
                            row["row_price"] = price_value
                            row_price_map[f"{sec.get('section_name','')} - {row_key}"] = price_value

            # ── UI feedback ──
            if price_value:
                st.success(f"💸 Prices updated to {price_value} across all matching seats, rows & sections.")

            if not price_only_mode and seat_range_input:
                st.markdown("### ✅ Availability Updated")
                st.write(", ".join(sorted(matched)) if matched else "No seat availability was changed.")
                missing = requested - found
                if missing:
                    st.warning("⚠️ Seats not found: " + ", ".join(f"{s.title()} {n}" for s, n in sorted(missing)))

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
                st.markdown("### 🔍 Parsed Seat Targets")
                st.table(debug)

    except Exception as e:
        st.error(f"❌ Error reading file: {e}")
