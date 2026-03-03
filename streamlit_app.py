import re
from pathlib import Path

import pandas as pd
import streamlit as st
import altair as alt

# -----------------------------
# Page config
# -----------------------------
st.set_page_config(
    page_title="EnergyTag — Eurostat Prices Explorer",
    layout="wide",
)



st.markdown(
    """
    <style>
      /* Wider sidebar so long sheet names fit */
      
      

      /* Slightly smaller selectbox text so more characters fit */
      
    </style>
    """,
    unsafe_allow_html=True
)

APP_DIR = Path(__file__).parent
DATA_FILE = APP_DIR / "Eurostat- Natural gas & electricity prices (2007 onwards).xlsx"
LOGO_FILE = APP_DIR / "energytag.png"  # put energytag.png next to this file

TIME_RE = re.compile(r"^\d{4}-(S1|S2)$")  # 2007-S1 etc
YEAR_RE = re.compile(r"^\d{4}$")         # 2023 etc


# -----------------------------
# Auth
# -----------------------------
def get_credentials():
    # Requires .streamlit/secrets.toml
    # [auth]
    # user = "admin"
    # pass = "energytagorg"
    try:
        auth = st.secrets.get("auth", {})
        return auth.get("user", ""), auth.get("pass", "")
    except Exception:
        return "", ""




def login_screen():
    # Force no-scroll, true-center login card
    st.markdown(
        """
        <style>
          /* Hide Streamlit chrome on login */
          header[data-testid="stHeader"] {display:none !important;}
          #MainMenu {visibility: hidden;}
          footer {visibility: hidden;}
          section[data-testid="stSidebar"] {display:none !important;}

          /* Remove ALL padding/margins that can create blank space */
          html, body {height: 100%; overflow: hidden;}
          .stApp {height: 100vh; overflow: hidden;}
          .block-container {padding: 0 !important; margin: 0 !important; max-width: 100% !important;}

          /* Make the MAIN content area full height + centered */
          section.main > div {height: 100vh; display:flex; align-items:center; justify-content:center;}

          /* Card */
          .et-card{
            width: 420px;
            max-width: calc(100vw - 48px);
            background: rgba(255,255,255,0.045);
            border: 1px solid rgba(255,255,255,0.10);
            border-radius: 18px;
            padding: 28px 26px 22px 26px;
            box-shadow: 0 22px 60px rgba(0,0,0,0.45);
            backdrop-filter: blur(10px);
          }
          .et-logo{display:flex; justify-content:center; margin-bottom: 14px;}
          .et-title{text-align:center; font-size: 22px; font-weight: 700; margin: 6px 0 2px 0;}
          .et-subtitle{text-align:center; font-size: 13px; opacity: 0.8; margin: 0 0 14px 0;}

          .stTextInput > div > div input {border-radius: 12px;}
          .stButton button {border-radius: 12px; width: 100%;}
        </style>
        """,
        unsafe_allow_html=True,
    )

    # One centered container; no extra markdown above it.
    st.markdown('<div class="et-card">', unsafe_allow_html=True)

    st.markdown('<div class="et-logo">', unsafe_allow_html=True)
    if LOGO_FILE.exists():
        st.image(str(LOGO_FILE), width=260)
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="et-title">Welcome back</div>', unsafe_allow_html=True)
    st.markdown('<div class="et-subtitle">Sign in to your account</div>', unsafe_allow_html=True)

    with st.form("login_form", clear_on_submit=False):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")

    if submitted:
        valid_user, valid_pass = get_credentials()
        if not valid_user or not valid_pass:
            st.error("No secrets found. Create .streamlit/secrets.toml with [auth].")
        elif u == valid_user and p == valid_pass:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Invalid username or password.")

    st.markdown("</div>", unsafe_allow_html=True)


if "authed" not in st.session_state:
    st.session_state["authed"] = False

if not st.session_state["authed"]:
    login_screen()
    st.stop()


# -----------------------------
# Helpers
# -----------------------------
@st.cache_data(show_spinner=False)
def list_sheets(xlsx_path: str):
    xls = pd.ExcelFile(xlsx_path)
    return xls.sheet_names


@st.cache_data(show_spinner=False)
def load_sheet(xlsx_path: str, sheet_name: str) -> pd.DataFrame:
    return pd.read_excel(xlsx_path, sheet_name=sheet_name, dtype=str)


@st.cache_data(show_spinner=False)
def load_codebook_if_exists(xlsx_path: str):
    sheets = list_sheets(xlsx_path)
    for candidate in ["Reference codebook", "Reference_Codebook", "Reference_Codebook "]:
        if candidate in sheets:
            cb = pd.read_excel(xlsx_path, sheet_name=candidate, dtype=str)
            cb.columns = [c.strip() for c in cb.columns]
            for c in ["Dimension", "Code", "Label", "Notes"]:
                if c not in cb.columns:
                    cb[c] = ""
            cb["Dimension"] = cb["Dimension"].fillna("").str.strip()
            cb["Code"] = cb["Code"].fillna("").str.strip()
            cb["Label"] = cb["Label"].fillna("").str.strip()
            cb["Notes"] = cb["Notes"].fillna("").str.strip()
            return candidate, cb
    return None, None


def build_code_maps(codebook: pd.DataFrame):
    label_map = {}
    notes_map = {}
    for dim, sub in codebook.groupby("Dimension"):
        label_map[dim] = dict(zip(sub["Code"], sub["Label"]))
        notes_map[dim] = dict(zip(sub["Code"], sub["Notes"]))
    return label_map, notes_map


def is_time_col(col: str) -> bool:
    c = str(col).strip()
    return bool(TIME_RE.match(c) or YEAR_RE.match(c))


def time_sort_key(t: str):
    t = str(t)
    if "-" in t:
        y, s = t.split("-")
        return (int(y), 1 if s == "S1" else 2)
    return (int(t), 0)


def tidy_from_wide(df: pd.DataFrame) -> pd.DataFrame:
    """
    Wide Eurostat-like sheet -> tidy:
      dims... + time_period + value + flag

    Handles:
    - ':' missing
    - separate flag columns named like flag / flag.1 / ...
      assumed to correspond to the immediately preceding time column
    - inline flags like '0.1398 e' or '0.1398 (d)'
    """
    cols = list(df.columns)
    time_cols = [c for c in cols if is_time_col(c)]
    if not time_cols:
        return df.copy()

    time_to_flag = {}
    for i, c in enumerate(cols):
        if is_time_col(c):
            if i + 1 < len(cols) and str(cols[i + 1]).lower().startswith("flag"):
                time_to_flag[c] = cols[i + 1]

    dim_cols = [c for c in cols if (c not in time_cols) and (not str(c).lower().startswith("flag"))]

    long = df.melt(id_vars=dim_cols, value_vars=time_cols, var_name="time_period", value_name="value_raw")

    if time_to_flag:
        flag_cols = sorted(set(time_to_flag.values()), key=lambda x: cols.index(x))
        flags_long = df.melt(id_vars=dim_cols, value_vars=flag_cols, var_name="flag_col", value_name="flag_raw")
        flag_to_time = {v: k for k, v in time_to_flag.items()}
        flags_long["time_period"] = flags_long["flag_col"].map(flag_to_time)
        flags_long = flags_long.drop(columns=["flag_col"])
        long = long.merge(flags_long, on=dim_cols + ["time_period"], how="left")
    else:
        long["flag_raw"] = None

    long["value_raw"] = long["value_raw"].astype(str).str.strip()
    long.loc[long["value_raw"].isin([":", "nan", "NaN", ""]), "value_raw"] = None

    def split_inline(v):
        if v is None:
            return (None, None)
        s = str(v).strip()
        m = re.match(r"^([+-]?\d+(?:\.\d+)?)(?:\s*\(?([A-Za-z]+)\)?)?$", s)
        if m:
            return (m.group(1), m.group(2))
        return (s, None)

    parsed = long["value_raw"].apply(split_inline)
    long["value_num_str"] = [p[0] for p in parsed]
    long["flag_inline"] = [p[1] for p in parsed]

    long["flag"] = long["flag_raw"]
    long.loc[(long["flag"].isna()) | (long["flag"].astype(str).str.strip() == ""), "flag"] = long["flag_inline"]

    long["value"] = pd.to_numeric(long["value_num_str"], errors="coerce")

    out = long.drop(columns=["value_raw", "flag_raw", "value_num_str", "flag_inline"])
    return out


# -----------------------------
# Friendly column names (display)
# -----------------------------
FRIENDLY_COLS = {
    "time_period": "Time period",
    "value": "Value",
    "flag": "Flag",
    "geo": "Country / region",
    "siec": "Energy carrier",
    "nrg_cons": "Consumption band",
    "nrg_prc": "Price component",
    "tax": "Tax treatment",
    "currency": "Currency basis",
    "unit": "Unit",
    "freq": "Frequency",
    "customer": "Customer type",
}

# Also, if codebook exists and show_labels=True, we add these label columns:
LABEL_FRIENDLY_SUFFIX = " (label)"


def apply_friendly_headers(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    new_cols = {}
    for c in out.columns:
        if c.endswith("_label"):
            base = c.replace("_label", "")
            base_name = FRIENDLY_COLS.get(base, base)
            new_cols[c] = f"{base_name}{LABEL_FRIENDLY_SUFFIX}"
        else:
            new_cols[c] = FRIENDLY_COLS.get(c, c)
    out = out.rename(columns=new_cols)
    return out


# -----------------------------
# Load data
# -----------------------------
if not DATA_FILE.exists():
    st.error(f"Missing data file: {DATA_FILE.name}. Put it next to streamlit_app.py.")
    st.stop()

sheets = list_sheets(str(DATA_FILE))
codebook_sheet, codebook = load_codebook_if_exists(str(DATA_FILE))

label_map, notes_map = ({}, {})
if codebook is not None:
    label_map, notes_map = build_code_maps(codebook)

data_sheets = [s for s in sheets if s != codebook_sheet]

# -----------------------------
# Sheet display titles (full) and ordering
# Excel sheet names are limited to 31 chars, so we map full titles -> actual sheet tabs.
# -----------------------------
FULL_SHEET_TITLES = ['Gas prices for household consumers - bi-annual data', 'Gas prices for non-household consumers - bi-annual data', 'Electricity prices for household consumers - bi-annual data', 'Electricity prices for non-household consumers - bi-annual data', 'Household consumption volumes of gas by consumption bands', 'Non-household consumption volumes of gas by consumption bands', 'Household consumption volumes of electricity by consumption bands', 'Non-household consumption volumes of electricity by consumption bands', 'Gas prices components for household consumers - annual data', 'Gas prices components for non-household consumers - annual data', 'Electricity prices components for non-household consumers - annual data', 'Electricity prices components for household consumers - annual data', 'Share for transmission and distribution in the network cost for gas and electricity - annual data']

def build_sheet_title_maps(actual_sheets, full_titles):
    # Map by Excel's 31-char limit: match each full title to an actual sheet whose name is the first 31 chars.
    actual_set = set(actual_sheets)
    title_to_sheet = {}
    sheet_to_title = {}

    for t in full_titles:
        key = t[:31]
        # Prefer exact match on truncated name
        if key in actual_set:
            title_to_sheet[t] = key
            sheet_to_title[key] = t
        else:
            # Fallback: find any actual sheet that starts with the same prefix (rare)
            cand = [s for s in actual_sheets if s.startswith(key[:20])]
            if cand:
                title_to_sheet[t] = cand[0]
                sheet_to_title[cand[0]] = t

    return title_to_sheet, sheet_to_title



# -----------------------------
# Sidebar: dataset + definitions + logout
# -----------------------------
st.sidebar.markdown("##")
if LOGO_FILE.exists():
    st.sidebar.image(str(LOGO_FILE), width=160)

st.sidebar.markdown("### Dataset")

title_to_sheet, sheet_to_title = build_sheet_title_maps(data_sheets, FULL_SHEET_TITLES)

display_title = st.sidebar.selectbox(
    "Choose sheet",
    FULL_SHEET_TITLES,
    index=0
)
sheet = title_to_sheet.get(display_title, data_sheets[0])


st.sidebar.markdown("---")
show_labels = st.sidebar.toggle("Show labels next to codes", value=True)
view_mode = st.sidebar.radio("View", ["Table", "Charts"], index=0)

st.sidebar.markdown("---")
st.sidebar.markdown("### Definitions")
if codebook is None:
    st.sidebar.info("No reference codebook sheet found.")
else:
    dim_pick = st.sidebar.selectbox("Dimension", sorted(codebook["Dimension"].unique().tolist()))
    code_pick = st.sidebar.selectbox("Code", sorted(codebook.loc[codebook["Dimension"] == dim_pick, "Code"].unique().tolist()))
    st.sidebar.write("**Label:**", label_map.get(dim_pick, {}).get(code_pick, ""))
    notes = notes_map.get(dim_pick, {}).get(code_pick, "")
    if notes:
        st.sidebar.write("**Notes:**", notes)

st.sidebar.markdown("---")
if st.sidebar.button("Logout"):
    st.session_state["authed"] = False
    st.rerun()


# -----------------------------
# Header bar: title LEFT, logo RIGHT (fixed)
# -----------------------------
# Reduce top whitespace + tighter header
st.markdown(
    """
    <style>
      .block-container {padding-top: 1.2rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

h1, h2 = st.columns([6, 1], vertical_alignment="center")
with h1:
    st.markdown("## Eurostat — Natural gas & electricity prices (2007 onwards)")
    st.caption("Filter, chart, and export tables across sheets.")
with h2:
    if LOGO_FILE.exists():
        st.image(str(LOGO_FILE), width=120)

# Sheet title on page
st.markdown(f"## {display_title}")


# -----------------------------
# Prepare data (tidy + optional labels)
# -----------------------------
raw = load_sheet(str(DATA_FILE), sheet)
tidy = tidy_from_wide(raw)

if show_labels and codebook is not None:
    # add *_label columns for any dimension present in codebook
    for c in list(tidy.columns):
        if c in ["time_period", "value", "flag"]:
            continue
        if c in label_map:
            tidy[f"{c}_label"] = tidy[c].map(label_map[c]).fillna("")


# -----------------------------
# Filters (TOP)
# - dropdowns (multiselect) with default = all
# -----------------------------
times = sorted(tidy["time_period"].dropna().astype(str).unique().tolist(), key=time_sort_key)

# Identify dimension columns (exclude value/time/flag + label columns)
reserved = {"time_period", "value", "flag"}
dim_cols = [c for c in tidy.columns if c not in reserved and not c.endswith("_label")]

with st.container():
    with st.expander("Filters", expanded=True):

        

            st.markdown("#### Filters")
# Safe defaults (avoid NameError)
auto_apply = False
apply_clicked = False


        

            # 1) Time + Geo in first row

            f1, f2, f3 = st.columns([2, 3, 2], gap="large")

        

            with f1:

                time_sel = st.multiselect("Time period", times, default=[])

        

            with f2:

                geo_sel = None

                if "geo" in tidy.columns:

                    geos = sorted(tidy["geo"].dropna().astype(str).unique().tolist())

                    geo_sel = st.multiselect("Country / region (geo)", geos, default=[])

        

                    # Requirement: if all selected, show "All countries"

                    if not geo_sel:
                        st.caption("All countries")
            with f3:

                # Optional quick toggle: show/hide code columns (if you want later)

                st.write("")

        

            # 2) Remaining filters as dropdown multiselects

            other_cols = [c for c in dim_cols if c not in {"geo"}]

            if other_cols:

                grid = st.columns(3, gap="large")

                other_filters = {}

                for i, colname in enumerate(other_cols):

                    vals = sorted(tidy[colname].dropna().astype(str).unique().tolist())

                    label_col = f"{colname}_label" if show_labels and f"{colname}_label" in tidy.columns else None

        

                    with grid[i % 3]:

                        if label_col:

                            display = []

                            for v in vals:

                                lab = tidy.loc[tidy[colname].astype(str) == v, label_col].dropna().astype(str).unique()

                                lab = lab[0] if len(lab) else ""

                                display.append(f"{v} — {lab}" if lab else v)

                            display_to_code = dict(zip(display, vals))

                            chosen = st.multiselect(FRIENDLY_COLS.get(colname, colname), display, default=display)

                            other_filters[colname] = [display_to_code[x] for x in chosen] if chosen else []

                        else:

                            chosen = st.multiselect(FRIENDLY_COLS.get(colname, colname), vals, default=vals)

                            other_filters[colname] = chosen if chosen else []

            else:

                other_filters = {}

        

        

        # Apply filters
filt = tidy.copy()

# Apply filters only if user chose something AND (auto_apply or Apply clicked)
apply_now = auto_apply or apply_clicked

if apply_now:
    # Time: only filter if user selected some
    if time_sel:
        filt = filt[filt["time_period"].astype(str).isin([str(x) for x in time_sel])]

    # Geo: only filter if user selected some
    if geo_sel is not None and geo_sel:
        filt = filt[filt["geo"].astype(str).isin([str(x) for x in geo_sel])]

    # Other dimensions: only filter if user selected some
    for colname, chosen in other_filters.items():
        if chosen:
            filt = filt[filt[colname].astype(str).isin([str(x) for x in chosen])]


# -----------------------------
# Summary + Download
# -----------------------------
m1, m2, m3, m4 = st.columns(4)
m1.metric("Rows", f"{len(filt):,}")
m2.metric("Countries", f"{filt['geo'].nunique():,}" if "geo" in filt.columns else "—")
m3.metric("Time periods", f"{filt['time_period'].nunique():,}")
m4.metric("Flags", f"{(filt['flag'].notna() & (filt['flag'].astype(str).str.strip()!='')).sum():,}" if "flag" in filt.columns else "—")

st.download_button(
    "Download filtered CSV",
    data=filt.to_csv(index=False).encode("utf-8"),
    file_name=f"{sheet}_filtered.csv",
    mime="text/csv",
)


# -----------------------------
# Display: Table or Charts
# -----------------------------
# Prepare a friendlier view dataframe (rename columns)
display_df = apply_friendly_headers(filt)

if view_mode == "Table":
    st.markdown("#### Results")
    st.dataframe(
        display_df.sort_values(["Time period"] + (["Country / region"] if "Country / region" in display_df.columns else [])),
        use_container_width=True,
        height=600,
    )

else:
    st.markdown("#### Charts")

    if filt.empty:
        st.info("No data after filters.")
    else:
        # Choose grouping column for color
        possible_group = [c for c in ["geo", "tax", "currency", "nrg_cons", "customer", "siec", "unit", "nrg_prc"] if c in filt.columns]
        group_col = st.selectbox("Group / color by", possible_group, index=0 if possible_group else 0)

        chart_df = filt.copy()
        chart_df["time_period"] = chart_df["time_period"].astype(str)

        # Eurostat-like styling (clean, subtle grid, line+points)
        base = (
            alt.Chart(chart_df)
            .encode(
                x=alt.X("time_period:N", sort=times, title="Time period"),
                y=alt.Y("value:Q", title="Value"),
                tooltip=[
                    alt.Tooltip("time_period:N", title="Time"),
                    alt.Tooltip("value:Q", title="Value"),
                    alt.Tooltip("flag:N", title="Flag"),
                    alt.Tooltip(f"{group_col}:N", title=FRIENDLY_COLS.get(group_col, group_col)),
                ],
            )
            .properties(height=420)
        )

        line = base.mark_line(point=True).encode(
            color=alt.Color(f"{group_col}:N", title=FRIENDLY_COLS.get(group_col, group_col))
        )

        st.altair_chart(
            line.configure_view(strokeWidth=0)
                .configure_axis(grid=True, gridColor="#E6E6E6", domain=False, tickColor="#999999", labelColor="#444444", titleColor="#444444")
                .configure_legend(titleColor="#444444", labelColor="#444444")
                .configure_title(color="#222222"),
            use_container_width=True,
        )
