import streamlit as st
import json, re, itertools

st.title("🎭 Seat Map Availability Editor (Debug Version)")

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

def norm_label(s: str) -> str:
    """Normalise seat labels (handles en/em dashes, spacing, seat text, leading zeros)."""
    s = strip_brackets(s or "")
    s = s.replace("–", "-").replace("—", "-")  # replace fancy dashes
    s = s.replace("\u00a0", " ").replace("\u202f", " ")  # replace non-breaking spaces
    s = s.lower().replace("seat", "")
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"row0?(\d+)", r"row\1", s)
    return s

def split_norm_label(norm: str):
    norm = norm.replace("seat", "")
    m = re.match(r"(row\d+)-?(\d+)$", norm)
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

def parse_input_ranges(user_text: str, section_names):
    """Parse seat-range text into canonical keys (section, prefix, seatnum)."""
    requested = set()
    debug_rows = []
    if not user_text:
        return requested, debug_rows

    canon_sections = {s.lower(): s for s in section_names if s}
    chunks = [c.strip() for c in re.split(r"\s*,\s*", user_text) if c.strip()]

    rx = re.compile(
        r"(?:(row)\s*(\d+)\s*[-–]?\s*(\d+)\s*(?:to|–|-)\s*(\d+))"
        r"|(?:(row)\s*(\d+)\s*[-–]?\s*(\d+))"
        r"|([a-z][a-z\-]{0,19})\s*(\d+)\s*(?:\s*(?:to|–|-)\s*(\d+))?",
        re.I
    )

    for chunk in chunks:
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
                for n in range(min(a, b), max(a, b) + 1):
                    requested.add((sec_low, f"row{rownum}", n))
                    debug_rows.append((sec_canon, f"row{rownum}-{n}"))
            elif m.group(5):  # ROW X - a
                rownum = int(m.group(6))
                n = int(m.group(7))
                requested.add((sec_low, f"row{rownum}", n))
                debug_rows.append((sec_canon, f"row{rownum}-{n}"))
            else:  # alpha/word prefix
                pref = m.group(8).lower()
                a = int(m.group(9))
                b = int(m.group(10) or m.group(9))
                for n in range(min(a, b), max(a, b) + 1):
                    requested.add((sec_low, pref, n))
                    debug_rows.append((sec_canon, f"{pref}-{n}"))
    return requested, debug_rows

# ──────────────── main UI logic ────────────────
if uploaded_file:
    try:
        seat_data = json.loads(uploaded_file.read().decode("utf-8"))
        st.success("✅ Seat map loaded successfully!")

        # 🔍 DEBUG BLOCK: list all Row 1 seats found
        row1_list = []
        for sec in seat_data.values():
            sec_name = sec.get("section_name", "Unknown")
            if "rows" in sec:
                for row_key, row in sec["rows"].items():
                    if row_key.strip().lower() in ["1", "row1", "row 1"]:
                        for seat in row.get("seats", {}).values():
                            row1_list.append({
                                "Section": sec_name,
                                "Row Key": repr(row_key),
                                "Seat Label": seat.get("number", ""),
                                "Norm (bytes)": seat.get("number", "").encode("utf-8", "replace"),
                                "Normalised": norm_label(seat.get("number", "")),
                                "Status": seat.get("status", "")
                            })
        if row1_list:
            st.markdown("### 🧩 Debug: Raw Row 1 seats from JSON")
            st.dataframe(row1_list)
        else:
            st.warning("No rows found with key '1', 'row1', or 'row 1'!")

        # ─────────── continue normal logic ───────────
        for sec in seat_data.values():
            if isinstance(sec, dict) and "section_name" in sec:
                sec["section_name"] = re.sub(r"\s+", " ", sec["section_name"]).strip()

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

        if seat_range_input:
            section_names = section_names_from_data(seat_data)
            requested_preview, debug_list = parse_input_ranges(seat_range_input, section_names)
            st.markdown("### 🔎 Parsed Seat Targets (Preview)")
            st.write(f"Targets parsed: **{len(requested_preview)}** seats")
            if debug_list:
                st.dataframe([{"Section": s, "Seat (normalised)": n} for s, n in debug_list])

    except Exception as e:
        st.error(f"❌ Error reading file: {e}")
