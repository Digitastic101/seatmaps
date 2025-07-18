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
def extract_row_and_number(label:str):
    m = re.match(r"(ROW\s*\d+\s*-\s*)(\d+)", label.strip(), re.I)
    if m:
        return m.group(1).strip(), int(m.group(2))
    m = re.match(r"([A-Z]+)(\d+)", label.strip(), re.I)
    if m:
        return m.group(1).strip(), int(m.group(2))
    return None, None

def compress_ranges(nums):
    nums.sort()
    out=[]
    for _, g in itertools.groupby(enumerate(nums), lambda x: x[1]-x[0]):
        block=list(g); s,e=block[0][1],block[-1][1]
        out.append((s,e))
    return out

def sort_key(pref):
    m=re.search(r"(\d+)", pref)
    return (0,int(m.group(1))) if m else (1,pref.upper())

# ────────────────── main UI logic ─────────────────────
if uploaded_file:
    try:
        seat_data=json.loads(uploaded_file.read().decode("utf-8"))
        st.success("✅ Seat map loaded successfully!")

        # --------- build copy-paste list of available seats ---------
        row_map={}
        for sec in seat_data.values():
            sec_name=sec.get("section_name","Unknown Section")
            if "rows" not in sec: continue
            for row in sec["rows"].values():
                for seat in row["seats"].values():
                    if seat.get("status","").lower()=="av":
                        pref,num=extract_row_and_number(seat.get("number",""))
                        if pref and num:
                            row_map.setdefault((sec_name,pref),[]).append(num)

        out_lines=[]
        for (sec_name,pref),nums in sorted(row_map.items(),
                                           key=lambda x:(x[0][0].lower(),sort_key(x[0][1]))):
            for s,e in compress_ranges(nums):
                out_lines.append(f"{sec_name} {pref}{s}" if s==e
                                 else f"{sec_name} {pref}{s}-{e}")

        st.markdown("### 🪑 Copy-Paste Friendly Available Seat Ranges")
        if out_lines:
            st.text_area("📋 Paste this into 'Enter seat ranges':",
                         value=", ".join(out_lines), height=200)
        else:
            st.info("No available seats found.")

        # ---------------- run updates -----------------
        if st.button("▶️ Go"):
            price_value = price_input.strip() or None
            matched, requested, found, debug = [], set(), set(), []

            # ---- parse seat_range_input (if any) ----
            if seat_range_input:
                txt=re.sub(r"\b([A-Za-z])\s+(\d+)\b",r"\1\2",seat_range_input)
                txt=re.sub(r"(\d+)\s*-\s*(\d+)",r"\1-\2",txt)
                rx=re.compile(r"(?P<section>[A-Za-z0-9 ]+?)\s+"
                              r"(?P<pref>(ROW\s*\d+\s*-\s*)|[A-Z]+)?"
                              r"(?P<start>\d+)"
                              r"(?:\s*(?:to|-)\s*)"
                              r"(?P<end>\d+)?",re.I)
                for m in rx.finditer(txt):
                    sec=m.group("section").strip().lower()
                    pref=m.group("pref") or ""
                    a,b=int(m.group("start")),int(m.group("end") or m.group("start"))
                    for n in range(a,b+1):
                        full=f"{pref.strip()}{n}".strip()
                        requested.add((sec,re.sub(r"\s*","",full).lower()))
                        debug.append((sec,full))

            # ---- apply updates ----
            for sec in seat_data.values():
                sec_key=sec.get("section_name","").strip().lower()
                if "rows" not in sec: continue
                for row in sec["rows"].values():
                    for seat in row["seats"].values():
                        label=seat.get("number","").strip()
                        norm=re.sub(r"\s*","",label).lower()
                        key=(sec_key,norm)

                        if price_value:
                            seat["price"]=price_value
                        if not price_only_mode and seat_range_input:
                            if key in requested:
                                seat["status"]="av"; found.add(key); matched.append(f"{sec['section_name']} {label}")
                            else:
                                seat["status"]="uav"
                    if price_value:
                        row["price"]=price_value
                if price_value:
                    sec["price"]=price_value

            # ---- messaging ----
            if price_value:
                st.success(f"💸 Prices updated to {price_value} on all seats, rows & sections.")
            if not price_only_mode:
                st.markdown("### ✅ Availability Updated")
                st.write(", ".join(sorted(matched)) if matched else "No seat availability was changed.")

                missing=requested-found
                if missing:
                    st.warning("⚠️ Seats not found: "+", ".join(f"{s.title()} {n}" for s,n in sorted(missing)))

            # ---- download ----
            st.download_button("Download Updated JSON",
                               json.dumps(seat_data,indent=2),
                               file_name="updated_seatmap.json",
                               mime="application/json")

            if seat_range_input:
                st.markdown("### 🔍 Parsed Seat Targets")
                st.table(debug)

    except Exception as e:
        st.error(f"❌ Error reading file: {e}")
