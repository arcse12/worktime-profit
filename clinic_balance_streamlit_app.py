import streamlit as st
import pandas as pd
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

# Optional Google Sheets imports
try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:
    gspread = None
    Credentials = None

st.set_page_config(page_title="诊所收支与工资核对", layout="wide")

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.6rem;
        padding-bottom: 3rem;
        max-width: 1380px;
    }
    div[data-testid="stMetric"] {
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 14px 16px;
        background: #ffffff;
    }
    div[data-testid="stMetric"] label {
        color: #475569;
    }
    .status-strip {
        border: 1px solid #dbe3ef;
        border-radius: 8px;
        padding: 12px 14px;
        background: #f8fafc;
        margin: 0.5rem 0 1rem;
    }
    .profit-positive {
        color: #047857;
        font-weight: 700;
    }
    .profit-negative {
        color: #b91c1c;
        font-weight: 700;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("诊所收支与工资核对")
st.caption("新增、修改、删除都会先进入缓存；确认无误后再统一提交到 Google Sheets。日期按 Calgary 时区。")

# -----------------------------
# 基础配置
# -----------------------------
PAYMENT_OPTIONS = ["pc", "pfp", "pbm", "pbi", "pbc"]
DURATION_RATE_MAP = {
    "30 min": 32.5,
    "45 min": 48.75,
    "60 min": 65.0,
    "75 min": 81.25,
    "90 min": 97.5,
    "105 min": 113.75,
    "120 min": 130.0,
}
DEFAULT_THERAPISTS = ["Jenny", "Janice", "Alex"]

SPREADSHEET_NAME = "massageprofit"
WORKSHEET_NAME = "transactions"
THERAPIST_WORKSHEET_NAME = "therapists"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

BASE_COLUMNS = [
    "date",
    "payment_type",
    "therapist_name",
    "client_name",
    "duration",
    "therapist_income",
    "tip",
    "total_revenue",
    "profit",
    "created_at",
]

CALGARY_TZ = ZoneInfo("America/Edmonton")


def calgary_now() -> datetime:
    return datetime.now(CALGARY_TZ)


def calgary_today() -> date:
    return calgary_now().date()


# -----------------------------
# Google Sheets 连接函数
# -----------------------------
@st.cache_resource(show_spinner=False, ttl=3600)
def connect_google_sheet_cached(creds_info_json, sheet_name, worksheet_name):
    creds_info = json.loads(creds_info_json)
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    client = gspread.authorize(creds)

    try:
        spreadsheet = client.open(sheet_name)
    except Exception:
        spreadsheet = client.create(sheet_name)

    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
    except Exception:
        worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows=3000, cols=30)
        worksheet.append_row(BASE_COLUMNS)

    try:
        first_row = worksheet.row_values(1)
        if not first_row:
            worksheet.append_row(BASE_COLUMNS)
    except Exception:
        pass

    return spreadsheet, worksheet


def connect_google_sheet():
    if gspread is None or Credentials is None:
        return None, None, "未安装 gspread / google-auth，当前使用本地模式。"

    try:
        if "gcp_service_account" not in st.secrets:
            return None, None, "未检测到 Google 凭证，当前使用本地模式。"

        sheet_name = st.secrets.get("google_sheet", {}).get("sheet_name", SPREADSHEET_NAME)
        worksheet_name = st.secrets.get("google_sheet", {}).get("worksheet_name", WORKSHEET_NAME)
        creds_info = dict(st.secrets["gcp_service_account"])
        creds_info_json = json.dumps(creds_info, sort_keys=True)
        spreadsheet, worksheet = connect_google_sheet_cached(creds_info_json, sheet_name, worksheet_name)

        return spreadsheet, worksheet, f"Google Sheets 已连接：{sheet_name} / {worksheet_name}"
    except Exception as e:
        return None, None, f"Google Sheets 连接失败：{e}"


def get_or_create_therapist_worksheet(spreadsheet):
    try:
        ws = spreadsheet.worksheet(THERAPIST_WORKSHEET_NAME)
    except Exception:
        ws = spreadsheet.add_worksheet(title=THERAPIST_WORKSHEET_NAME, rows=200, cols=5)
        ws.append_row(["therapist_name"])
        for name in DEFAULT_THERAPISTS:
            ws.append_row([name])
    return ws


def load_therapists_from_sheet(spreadsheet):
    try:
        ws = get_or_create_therapist_worksheet(spreadsheet)
        values = ws.col_values(1)
        if not values:
            return DEFAULT_THERAPISTS.copy()

        therapists = [v.strip() for v in values[1:] if str(v).strip()]
        return therapists if therapists else DEFAULT_THERAPISTS.copy()
    except Exception:
        return DEFAULT_THERAPISTS.copy()


def save_therapists_to_sheet(spreadsheet, therapists):
    ws = get_or_create_therapist_worksheet(spreadsheet)
    ws.clear()
    ws.append_row(["therapist_name"])
    for name in therapists:
        clean_name = str(name).strip()
        if clean_name:
            ws.append_row([clean_name])


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in BASE_COLUMNS:
        if col not in df.columns:
            if col in ["date", "payment_type", "therapist_name", "client_name", "duration", "created_at"]:
                df[col] = ""
            else:
                df[col] = 0.0
    return df[BASE_COLUMNS]


def therapist_select_options(include_blank=True, blank_text=""):
    therapists = [str(t).strip() for t in st.session_state.therapists if str(t).strip()]
    if include_blank:
        return [blank_text] + therapists
    return therapists


def load_data_from_sheet(worksheet):
    try:
        records = worksheet.get_all_records()
        if not records:
            return pd.DataFrame(columns=BASE_COLUMNS)
        df = pd.DataFrame(records)
        return ensure_columns(df)
    except Exception:
        return pd.DataFrame(columns=BASE_COLUMNS)


def append_row_to_sheet(worksheet, row_data):
    worksheet.append_row(row_data, value_input_option="USER_ENTERED")


def update_row_in_sheet(worksheet, row_number, row_data):
    cell_range = f"A{row_number}:J{row_number}"
    worksheet.update(cell_range, [row_data])


def delete_rows_from_sheet(worksheet, row_numbers):
    for row_num in sorted(row_numbers, reverse=True):
        worksheet.delete_rows(int(row_num))


def clean_text_cell(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()



def clean_numeric_cell(value) -> float:
    numeric_value = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric_value):
        return 0.0
    return float(numeric_value)



def overwrite_sheet_with_df(worksheet, df_local):
    df_to_save = ensure_columns(df_local.copy())

    rows = [BASE_COLUMNS]
    for _, row in df_to_save.iterrows():
        rows.append([
            clean_text_cell(row["date"]),
            clean_text_cell(row["payment_type"]),
            clean_text_cell(row["therapist_name"]),
            clean_text_cell(row["client_name"]),
            clean_text_cell(row["duration"]),
            clean_numeric_cell(row["therapist_income"]),
            clean_numeric_cell(row["tip"]),
            clean_numeric_cell(row["total_revenue"]),
            clean_numeric_cell(row["profit"]),
            clean_text_cell(row["created_at"]),
        ])

    worksheet.clear()
    worksheet.update(f"A1:J{len(rows)}", rows, value_input_option="USER_ENTERED")


def save_local_update(df_local, row_index, row_dict):
    for key, value in row_dict.items():
        df_local.at[row_index, key] = value
    return df_local


def delete_local_rows(df_local, row_ids):
    df_local = df_local.drop(index=row_ids, errors="ignore").reset_index(drop=True)
    return df_local


# -----------------------------
# 数据缓存 / 显示处理
# -----------------------------
def prepare_display_df(df_local, worksheet):
    if df_local.empty:
        df_local = pd.DataFrame(columns=BASE_COLUMNS)
    else:
        df_local = ensure_columns(df_local)

    if df_local.empty:
        out = df_local.copy()
        out["row_id"] = []
        out["sheet_row_number"] = []
        return out

    df_local = df_local.copy()
    df_local["date"] = pd.to_datetime(df_local["date"], errors="coerce")
    for col in ["therapist_income", "tip", "total_revenue", "profit"]:
        df_local[col] = pd.to_numeric(df_local[col], errors="coerce").fillna(0.0)

    df_local = df_local.reset_index(drop=True).copy()
    df_local["row_id"] = df_local.index
    if worksheet is not None:
        df_local["sheet_row_number"] = df_local.index + 2
    else:
        df_local["sheet_row_number"] = None

    if "date" in df_local.columns:
        df_local["day"] = df_local["date"].dt.date.astype(str)
        df_local["month"] = df_local["date"].dt.to_period("M").astype(str)
        df_local["year"] = df_local["date"].dt.year.astype("Int64").astype(str)

    return df_local


def init_data_cache(worksheet):
    if not st.session_state.data_loaded:
        if worksheet is not None:
            base_df = load_data_from_sheet(worksheet)
        else:
            base_df = st.session_state.local_data.copy()

        base_df = ensure_columns(base_df)
        st.session_state.server_data = base_df.copy()
        st.session_state.working_data = base_df.copy()
        st.session_state.data_loaded = True
        st.session_state.last_data_refresh_at = calgary_now().strftime("%Y-%m-%d %H:%M:%S")


def refresh_from_server(worksheet):
    if worksheet is not None:
        fresh_df = load_data_from_sheet(worksheet)
        fresh_df = ensure_columns(fresh_df)
        st.session_state.server_data = fresh_df.copy()
        st.session_state.working_data = fresh_df.copy()
    else:
        st.session_state.server_data = st.session_state.local_data.copy()
        st.session_state.working_data = st.session_state.local_data.copy()

    st.session_state.pending_changes = {
        "new_rows": [],
        "updated_rows": {},
        "deleted_row_ids": set()
    }
    st.session_state.edit_loaded_uid = None
    st.session_state.last_data_refresh_at = calgary_now().strftime("%Y-%m-%d %H:%M:%S")


def get_current_df(worksheet):
    return prepare_display_df(st.session_state.working_data.copy(), worksheet)


def get_record_uid(row):
    if pd.notna(row.get("sheet_row_number", None)):
        return f"gs_{int(row['sheet_row_number'])}"
    return f"local_{int(row['row_id'])}"


def money(value) -> str:
    return f"${float(value):,.2f}"


def pending_counts():
    changes = st.session_state.pending_changes
    return (
        len(changes["new_rows"]),
        len(changes["updated_rows"]),
        len(changes["deleted_row_ids"]),
    )


def summarize_money(df_local):
    if df_local.empty:
        return {
            "count": 0,
            "total_revenue": 0.0,
            "therapist_income": 0.0,
            "tip": 0.0,
            "profit": 0.0,
        }

    return {
        "count": int(len(df_local)),
        "total_revenue": float(df_local["total_revenue"].sum()),
        "therapist_income": float(df_local["therapist_income"].sum()),
        "tip": float(df_local["tip"].sum()),
        "profit": float(df_local["profit"].sum()),
    }


def render_money_metrics(summary, count_label="记录数"):
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(count_label, f"{summary['count']}")
    c2.metric("总收入", money(summary["total_revenue"]))
    c3.metric("治疗师工资", money(summary["therapist_income"]))
    c4.metric("小费", money(summary["tip"]))
    c5.metric("利润", money(summary["profit"]))


def format_display_table(df_local, columns):
    if df_local.empty:
        return df_local

    rename_map = {
        "date": "日期",
        "day": "日期",
        "month": "月份",
        "year": "年份",
        "payment_type": "付款方式",
        "therapist_name": "治疗师",
        "client_name": "客人",
        "duration": "时长",
        "therapist_income": "治疗师工资",
        "tip": "小费",
        "total_revenue": "总收入",
        "profit": "利润",
        "created_at": "创建时间",
        "client_count": "客人数",
    }
    return df_local[columns].rename(columns=rename_map)


def render_profit_text(label, value):
    css_class = "profit-positive" if value >= 0 else "profit-negative"
    st.markdown(f"### {label}: <span class='{css_class}'>{money(value)}</span>", unsafe_allow_html=True)


# -----------------------------
# 表单联动
# -----------------------------
def sync_entry_income():
    payment_type = st.session_state.get("entry_payment_type", PAYMENT_OPTIONS[0])
    duration = st.session_state.get("entry_duration", list(DURATION_RATE_MAP.keys())[0])

    if payment_type == "pc":
        st.session_state["entry_therapist_name"] = ""
        st.session_state["entry_therapist_income"] = 0.0
    else:
        st.session_state["entry_therapist_income"] = float(DURATION_RATE_MAP.get(duration, 0.0))


def load_selected_record_to_editor(selected_row):
    record_uid = get_record_uid(selected_row)
    if st.session_state.get("edit_loaded_uid") != record_uid:
        st.session_state["edit_loaded_uid"] = record_uid
        st.session_state["edit_date_value"] = pd.to_datetime(selected_row["date"]).date() if pd.notna(selected_row["date"]) else calgary_today()
        st.session_state["edit_payment_type_value"] = str(selected_row["payment_type"])
        st.session_state["edit_client_name_value"] = str(selected_row["client_name"])
        st.session_state["edit_duration_value"] = str(selected_row["duration"])
        st.session_state["edit_therapist_name_value"] = str(selected_row["therapist_name"]).strip()
        st.session_state["edit_total_revenue_value"] = float(selected_row["total_revenue"])
        st.session_state["edit_tip_value"] = float(selected_row["tip"])
        st.session_state["edit_therapist_income_value"] = float(selected_row["therapist_income"])


def sync_edit_income():
    payment_type = st.session_state.get("edit_payment_type_value", PAYMENT_OPTIONS[0])
    duration = st.session_state.get("edit_duration_value", list(DURATION_RATE_MAP.keys())[0])

    if payment_type == "pc":
        st.session_state["edit_therapist_name_value"] = ""
        st.session_state["edit_therapist_income_value"] = 0.0
    else:
        st.session_state["edit_therapist_income_value"] = float(DURATION_RATE_MAP.get(duration, 0.0))


# -----------------------------
# 初始化
# -----------------------------
spreadsheet, worksheet, gs_message = connect_google_sheet()

if "therapists" not in st.session_state:
    if spreadsheet is not None:
        st.session_state.therapists = load_therapists_from_sheet(spreadsheet)
    else:
        st.session_state.therapists = DEFAULT_THERAPISTS.copy()

if "local_data" not in st.session_state:
    st.session_state.local_data = pd.DataFrame(columns=BASE_COLUMNS)

if "server_data" not in st.session_state:
    st.session_state.server_data = pd.DataFrame(columns=BASE_COLUMNS)

if "working_data" not in st.session_state:
    st.session_state.working_data = pd.DataFrame(columns=BASE_COLUMNS)

if "pending_changes" not in st.session_state:
    st.session_state.pending_changes = {
        "new_rows": [],
        "updated_rows": {},
        "deleted_row_ids": set()
    }

if "data_loaded" not in st.session_state:
    st.session_state.data_loaded = False

if "edit_loaded_uid" not in st.session_state:
    st.session_state.edit_loaded_uid = None

if "last_data_refresh_at" not in st.session_state:
    st.session_state.last_data_refresh_at = ""

if "entry_date" not in st.session_state:
    st.session_state["entry_date"] = calgary_today()
if "entry_payment_type" not in st.session_state:
    st.session_state["entry_payment_type"] = PAYMENT_OPTIONS[0]
if "entry_client_name" not in st.session_state:
    st.session_state["entry_client_name"] = ""
if "entry_duration" not in st.session_state:
    st.session_state["entry_duration"] = list(DURATION_RATE_MAP.keys())[0]
if "entry_therapist_name" not in st.session_state:
    st.session_state["entry_therapist_name"] = ""
if "entry_total_revenue" not in st.session_state:
    st.session_state["entry_total_revenue"] = 0.0
if "entry_tip" not in st.session_state:
    st.session_state["entry_tip"] = 0.0
if "entry_therapist_income" not in st.session_state:
    st.session_state["entry_therapist_income"] = float(DURATION_RATE_MAP[st.session_state["entry_duration"]])

init_data_cache(worksheet)
df = get_current_df(worksheet)

# -----------------------------
# 全局状态与侧边栏
# -----------------------------
df = get_current_df(worksheet)
pending_new, pending_update, pending_delete = pending_counts()
pending_total = pending_new + pending_update + pending_delete

status_text = "Google Sheets 已连接" if worksheet is not None else "本地会话模式"
status_class = "success" if worksheet is not None else "warning"
st.markdown(
    f"""
    <div class="status-strip">
        <strong>{status_text}</strong>　{gs_message}<br>
        待提交：新增 {pending_new} 条，修改 {pending_update} 条，删除 {pending_delete} 条。
    </div>
    """,
    unsafe_allow_html=True,
)

today_key = str(calgary_today())
month_key = calgary_today().strftime("%Y-%m")
today_df = df[df["day"] == today_key].copy() if not df.empty and "day" in df.columns else pd.DataFrame(columns=df.columns)
month_df = df[df["month"] == month_key].copy() if not df.empty and "month" in df.columns else pd.DataFrame(columns=df.columns)

st.caption(f"今日概览 {today_key}")
render_money_metrics(summarize_money(today_df), count_label="今日记录")
st.caption(f"本月概览 {month_key}")
render_money_metrics(summarize_money(month_df), count_label="本月记录")

with st.sidebar:
    st.subheader("提交控制")
    if pending_total:
        st.warning(f"还有 {pending_total} 条缓存更改未提交。")
    else:
        st.success("当前没有待提交更改。")

    if st.session_state.last_data_refresh_at:
        st.caption(f"上次读取：{st.session_state.last_data_refresh_at}")

    submit_label = "提交缓存到 Google Sheets" if worksheet is not None else "保存到本地会话"
    if st.button(submit_label, type="primary", use_container_width=True, disabled=pending_total == 0):
        try:
            if worksheet is not None:
                overwrite_sheet_with_df(worksheet, st.session_state.working_data)
                refresh_from_server(worksheet)
                st.success("所有缓存更改已提交到 Google Sheets。")
                st.rerun()
            else:
                st.session_state.local_data = st.session_state.working_data.copy()
                refresh_from_server(worksheet)
                st.success("临时更改已正式保存到本地会话。")
                st.rerun()
        except Exception as e:
            st.error(f"提交失败：{e}")

    if st.button("放弃缓存更改", use_container_width=True, disabled=pending_total == 0):
        st.session_state.working_data = st.session_state.server_data.copy()
        st.session_state.pending_changes = {
            "new_rows": [],
            "updated_rows": {},
            "deleted_row_ids": set()
        }
        st.session_state.edit_loaded_uid = None
        st.success("已恢复为上次正式数据。")
        st.rerun()

    refresh_disabled = worksheet is None or pending_total > 0
    if st.button("从 Google Sheets 重新读取", use_container_width=True, disabled=refresh_disabled):
        with st.spinner("正在读取 Google Sheets..."):
            refresh_from_server(worksheet)
        st.success("已读取 Google Sheets 最新数据。")
        st.rerun()

    if pending_total > 0:
        st.caption("有缓存更改时，请先提交或放弃，再重新读取云端数据。")

    st.markdown("---")
    st.subheader("治疗师管理")
    new_therapist = st.text_input("新增治疗师", placeholder="输入姓名")

    if st.button("添加治疗师", use_container_width=True):
        name = new_therapist.strip()
        if name:
            if name not in st.session_state.therapists:
                st.session_state.therapists.append(name)
                if spreadsheet is not None:
                    try:
                        save_therapists_to_sheet(spreadsheet, st.session_state.therapists)
                    except Exception as e:
                        st.error(f"已更新本地名单，但保存到 Google Sheets 失败：{e}")
                st.success(f"已添加治疗师：{name}")
                st.rerun()
            else:
                st.info("该治疗师已存在")
        else:
            st.error("请输入治疗师姓名")

    therapist_to_remove = st.selectbox("删除治疗师", [""] + st.session_state.therapists)
    if st.button("删除选中治疗师", use_container_width=True):
        if therapist_to_remove:
            st.session_state.therapists.remove(therapist_to_remove)
            if spreadsheet is not None:
                try:
                    save_therapists_to_sheet(spreadsheet, st.session_state.therapists)
                except Exception as e:
                    st.error(f"已更新本地名单，但保存到 Google Sheets 失败：{e}")
            st.success(f"已删除治疗师：{therapist_to_remove}")
            st.rerun()
        else:
            st.error("请先选择治疗师")

    st.caption("当前名单")
    st.write("、".join(st.session_state.therapists) if st.session_state.therapists else "暂无")

entry_tab, manage_tab, summary_tab, payroll_tab, raw_tab = st.tabs([
    "录入",
    "修改 / 删除",
    "汇总",
    "工资核对",
    "原始记录",
])

with entry_tab:
    st.subheader("新增每日收支记录")
    left, right = st.columns([2, 1])

    with left:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.date_input("日期", key="entry_date")
            st.selectbox("付款方式", PAYMENT_OPTIONS, key="entry_payment_type", on_change=sync_entry_income)
        with c2:
            st.text_input("客人姓名", key="entry_client_name")
            st.selectbox("治疗时长", list(DURATION_RATE_MAP.keys()), key="entry_duration", on_change=sync_entry_income)
        with c3:
            therapist_options = therapist_select_options(include_blank=True, blank_text="")
            current_therapist = st.session_state.get("entry_therapist_name", "")
            if current_therapist not in therapist_options:
                current_therapist = ""
                st.session_state["entry_therapist_name"] = ""

            st.selectbox(
                "治疗师",
                therapist_options,
                index=therapist_options.index(current_therapist),
                key="entry_therapist_name",
            )
            st.number_input("总收入 ($)", min_value=0.0, step=1.0, format="%.2f", key="entry_total_revenue")

        fee_col, income_col = st.columns(2)
        with fee_col:
            st.number_input("小费 ($)", min_value=0.0, step=1.0, format="%.2f", key="entry_tip")

        entry_payment_type = st.session_state["entry_payment_type"]
        if entry_payment_type == "pc":
            display_therapist_income = 0.0
            with income_col:
                st.info("PC 类型不关联治疗师，治疗师工资为 0。")
        else:
            with income_col:
                st.number_input(
                    "治疗师工资 ($)",
                    min_value=0.0,
                    step=1.0,
                    format="%.2f",
                    key="entry_therapist_income",
                    help="默认按治疗时长自动带出，也可以手动调整。",
                )
            display_therapist_income = float(st.session_state["entry_therapist_income"])

    with right:
        entry_profit = (
            float(st.session_state["entry_total_revenue"])
            - float(display_therapist_income)
            - float(st.session_state["entry_tip"])
        )
        render_profit_text("本单利润", entry_profit)
        st.write(f"总收入：{money(st.session_state['entry_total_revenue'])}")
        st.write(f"治疗师工资：{money(display_therapist_income)}")
        st.write(f"小费：{money(st.session_state['entry_tip'])}")

        if st.button("加入缓存", key="save_entry_record", type="primary", use_container_width=True):
            payment_type = st.session_state["entry_payment_type"]

            if payment_type == "pc":
                therapist_name_to_save = ""
                therapist_income_to_save = 0.0
            else:
                therapist_name_to_save = str(st.session_state["entry_therapist_name"]).strip()
                therapist_income_to_save = float(st.session_state["entry_therapist_income"])

                if not therapist_name_to_save:
                    st.error("请选择治疗师姓名")
                    st.stop()

            row = {
                "date": str(st.session_state["entry_date"]),
                "payment_type": payment_type,
                "therapist_name": therapist_name_to_save,
                "client_name": str(st.session_state["entry_client_name"]).strip(),
                "duration": st.session_state["entry_duration"],
                "therapist_income": therapist_income_to_save,
                "tip": float(st.session_state["entry_tip"]),
                "total_revenue": float(st.session_state["entry_total_revenue"]),
                "profit": float(entry_profit),
                "created_at": calgary_now().strftime("%Y-%m-%d %H:%M:%S"),
            }

            st.session_state.working_data = pd.concat(
                [st.session_state.working_data, pd.DataFrame([row])],
                ignore_index=True,
            )
            st.session_state.pending_changes["new_rows"].append(row)
            st.success("已加入缓存。确认无误后，在左侧提交。")
            st.rerun()

    df = get_current_df(worksheet)
    if not today_df.empty:
        st.markdown("#### 今日记录")
        show_cols = ["day", "payment_type", "therapist_name", "client_name", "duration", "therapist_income", "tip", "total_revenue", "profit"]
        st.dataframe(format_display_table(today_df.sort_values("date", ascending=False), show_cols), use_container_width=True)

with manage_tab:
    st.subheader("修改或删除记录")
    df = get_current_df(worksheet)

    if df.empty:
        st.info("目前没有可修改或删除的数据。")
    else:
        filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
        with filter_col1:
            date_options = ["全部"] + sorted(df["day"].dropna().unique().tolist(), reverse=True)
            selected_manage_date = st.selectbox("日期", date_options, key="manage_date_filter")
        with filter_col2:
            therapist_values = sorted([x for x in df["therapist_name"].dropna().astype(str).unique().tolist() if x.strip()])
            selected_manage_therapist = st.selectbox("治疗师", ["全部"] + therapist_values, key="manage_therapist_filter")
        with filter_col3:
            selected_manage_payment = st.selectbox("付款方式", ["全部"] + PAYMENT_OPTIONS, key="manage_payment_filter")
        with filter_col4:
            manage_client_keyword = st.text_input("客人姓名", key="manage_client_keyword")

        manage_df = df.copy()
        if selected_manage_date != "全部":
            manage_df = manage_df[manage_df["day"] == selected_manage_date]
        if selected_manage_therapist != "全部":
            manage_df = manage_df[manage_df["therapist_name"] == selected_manage_therapist]
        if selected_manage_payment != "全部":
            manage_df = manage_df[manage_df["payment_type"] == selected_manage_payment]
        if manage_client_keyword.strip():
            manage_df = manage_df[manage_df["client_name"].astype(str).str.contains(manage_client_keyword.strip(), case=False, na=False)]

        edit_area, delete_area = st.tabs(["修改单条记录", "批量删除"])

        with edit_area:
            if manage_df.empty:
                st.warning("没有找到符合条件的记录。")
            else:
                edit_df = manage_df.sort_values(["date", "client_name"], ascending=[False, True]).copy()
                edit_df["record_label"] = edit_df.apply(
                    lambda r: f"{r['day']} | {r['client_name']} | {r['payment_type']} | {r['therapist_name'] or '无治疗师'} | {money(r['total_revenue'])}",
                    axis=1,
                )

                selected_label = st.selectbox("选择要修改的记录", edit_df["record_label"].tolist(), key="record_to_edit")
                selected_row = edit_df[edit_df["record_label"] == selected_label].iloc[0]
                load_selected_record_to_editor(selected_row)

                ec1, ec2, ec3 = st.columns(3)
                with ec1:
                    st.date_input("日期", key="edit_date_value")
                    current_payment = st.session_state.get("edit_payment_type_value", PAYMENT_OPTIONS[0])
                    payment_index = PAYMENT_OPTIONS.index(current_payment) if current_payment in PAYMENT_OPTIONS else 0
                    st.selectbox("付款方式", PAYMENT_OPTIONS, index=payment_index, key="edit_payment_type_value", on_change=sync_edit_income)
                with ec2:
                    st.text_input("客人姓名", key="edit_client_name_value")
                    duration_options = list(DURATION_RATE_MAP.keys())
                    current_duration = st.session_state.get("edit_duration_value", duration_options[0])
                    duration_index = duration_options.index(current_duration) if current_duration in duration_options else 0
                    st.selectbox("治疗时长", duration_options, index=duration_index, key="edit_duration_value", on_change=sync_edit_income)
                with ec3:
                    therapist_options = therapist_select_options(include_blank=True, blank_text="")
                    current_edit_therapist = st.session_state.get("edit_therapist_name_value", "")
                    if current_edit_therapist not in therapist_options:
                        current_edit_therapist = ""
                    st.selectbox("治疗师", therapist_options, index=therapist_options.index(current_edit_therapist), key="edit_therapist_name_value")
                    st.number_input("总收入 ($)", min_value=0.0, step=1.0, format="%.2f", key="edit_total_revenue_value")

                fee_col, income_col = st.columns(2)
                with fee_col:
                    st.number_input("小费 ($)", min_value=0.0, step=1.0, format="%.2f", key="edit_tip_value")

                edit_payment_type = st.session_state.get("edit_payment_type_value", PAYMENT_OPTIONS[0])
                if edit_payment_type == "pc":
                    display_edit_therapist_income = 0.0
                    with income_col:
                        st.info("PC 类型不关联治疗师，治疗师工资为 0。")
                else:
                    with income_col:
                        st.number_input(
                            "治疗师工资 ($)",
                            min_value=0.0,
                            step=1.0,
                            format="%.2f",
                            key="edit_therapist_income_value",
                            help="默认按治疗时长自动带出，也可以手动调整。",
                        )
                    display_edit_therapist_income = float(st.session_state.get("edit_therapist_income_value", 0.0))

                edit_profit = (
                    float(st.session_state.get("edit_total_revenue_value", 0.0))
                    - float(display_edit_therapist_income)
                    - float(st.session_state.get("edit_tip_value", 0.0))
                )
                render_profit_text("修改后利润", edit_profit)

                if st.button("保存修改到缓存", key="save_edit_record", type="primary"):
                    if edit_payment_type == "pc":
                        therapist_name_to_save = ""
                        therapist_income_to_save = 0.0
                    else:
                        therapist_name_to_save = str(st.session_state.get("edit_therapist_name_value", "")).strip()
                        therapist_income_to_save = float(st.session_state.get("edit_therapist_income_value", 0.0))
                        if not therapist_name_to_save:
                            st.error("请选择治疗师姓名")
                            st.stop()

                    updated_row = {
                        "date": str(st.session_state.get("edit_date_value", calgary_today())),
                        "payment_type": edit_payment_type,
                        "therapist_name": therapist_name_to_save,
                        "client_name": str(st.session_state.get("edit_client_name_value", "")).strip(),
                        "duration": st.session_state.get("edit_duration_value", list(DURATION_RATE_MAP.keys())[0]),
                        "therapist_income": therapist_income_to_save,
                        "tip": float(st.session_state.get("edit_tip_value", 0.0)),
                        "total_revenue": float(st.session_state.get("edit_total_revenue_value", 0.0)),
                        "profit": float(edit_profit),
                        "created_at": str(selected_row["created_at"]),
                    }

                    row_id = int(selected_row["row_id"])
                    st.session_state.working_data = save_local_update(st.session_state.working_data.copy(), row_id, updated_row)
                    st.session_state.pending_changes["deleted_row_ids"].discard(row_id)
                    st.session_state.pending_changes["updated_rows"][row_id] = updated_row
                    st.success("修改已保存到缓存。提交时会写入最终版本。")
                    st.rerun()

        with delete_area:
            if manage_df.empty:
                st.warning("没有找到可删除的记录。")
            else:
                delete_df = manage_df.sort_values(["date", "client_name"], ascending=[False, True]).copy()
                delete_df["选择删除"] = False
                delete_show_cols = [
                    "选择删除", "day", "payment_type", "therapist_name", "client_name",
                    "duration", "therapist_income", "tip", "total_revenue", "profit"
                ]

                edited_delete_df = st.data_editor(
                    delete_df[delete_show_cols + ["row_id", "sheet_row_number"]].copy(),
                    hide_index=True,
                    use_container_width=True,
                    disabled=[
                        "day", "payment_type", "therapist_name", "client_name",
                        "duration", "therapist_income", "tip", "total_revenue", "profit",
                        "row_id", "sheet_row_number",
                    ],
                    column_config={"row_id": None, "sheet_row_number": None},
                    key="delete_data_editor",
                )

                selected_rows = edited_delete_df[edited_delete_df["选择删除"] == True].copy()
                if not selected_rows.empty:
                    st.warning(f"已勾选 {len(selected_rows)} 条记录。加入缓存后，左侧提交才会正式删除。")

                if st.button("加入删除缓存", type="primary"):
                    if selected_rows.empty:
                        st.error("请先勾选要删除的记录。")
                    else:
                        row_ids = selected_rows["row_id"].astype(int).tolist()
                        st.session_state.working_data = delete_local_rows(st.session_state.working_data.copy(), row_ids)
                        for rid in row_ids:
                            st.session_state.pending_changes["deleted_row_ids"].add(rid)
                            st.session_state.pending_changes["updated_rows"].pop(rid, None)
                        st.success(f"已将 {len(row_ids)} 条记录加入删除缓存。")
                        st.rerun()

with summary_tab:
    st.subheader("收支汇总")
    df = get_current_df(worksheet)

    if df.empty:
        st.info("目前还没有数据。")
    else:
        daily_summary = df.groupby("day", as_index=False).agg(
            total_revenue=("total_revenue", "sum"),
            therapist_income=("therapist_income", "sum"),
            tip=("tip", "sum"),
            profit=("profit", "sum"),
        ).sort_values("day", ascending=False)

        monthly_summary = df.groupby("month", as_index=False).agg(
            total_revenue=("total_revenue", "sum"),
            therapist_income=("therapist_income", "sum"),
            tip=("tip", "sum"),
            profit=("profit", "sum"),
        ).sort_values("month", ascending=False)

        yearly_summary = df.groupby("year", as_index=False).agg(
            total_revenue=("total_revenue", "sum"),
            therapist_income=("therapist_income", "sum"),
            tip=("tip", "sum"),
            profit=("profit", "sum"),
        ).sort_values("year", ascending=False)

        st.markdown("#### 当前数据总览")
        render_money_metrics(summarize_money(df), count_label="总记录")

        tab1, tab2, tab3 = st.tabs(["每日", "每月", "每年"])
        summary_cols = ["day", "total_revenue", "therapist_income", "tip", "profit"]
        with tab1:
            st.dataframe(format_display_table(daily_summary, summary_cols), use_container_width=True)
        with tab2:
            st.dataframe(format_display_table(monthly_summary, ["month", "total_revenue", "therapist_income", "tip", "profit"]), use_container_width=True)
        with tab3:
            st.dataframe(format_display_table(yearly_summary, ["year", "total_revenue", "therapist_income", "tip", "profit"]), use_container_width=True)

with payroll_tab:
    st.subheader("工资核对与利润查询")
    df = get_current_df(worksheet)

    if df.empty:
        st.info("请先录入数据后再查询。")
    else:
        query_tab1, query_tab2, query_tab3 = st.tabs(["治疗师月工资", "工资单下载", "利润查询"])

        with query_tab1:
            therapists_for_query = therapist_select_options(include_blank=False)
            months_for_query = sorted(df["month"].dropna().unique().tolist(), reverse=True)

            if therapists_for_query and months_for_query:
                qc1, qc2 = st.columns(2)
                with qc1:
                    selected_therapist = st.selectbox("治疗师", therapists_for_query, key="salary_therapist")
                with qc2:
                    selected_month = st.selectbox("月份", months_for_query, key="salary_month")

                therapist_month_df = df[
                    (df["therapist_name"] == selected_therapist) &
                    (df["month"] == selected_month)
                ].copy().sort_values("date")

                render_money_metrics(summarize_money(therapist_month_df), count_label="治疗次数")
                detail_cols = ["day", "client_name", "payment_type", "duration", "therapist_income", "tip", "total_revenue"]
                st.dataframe(format_display_table(therapist_month_df, detail_cols), use_container_width=True)
            else:
                st.warning("暂无可供查询的治疗师数据。")

        with query_tab2:
            therapists_for_print = therapist_select_options(include_blank=False)
            months_for_print = sorted(df["month"].dropna().unique().tolist(), reverse=True)

            if therapists_for_print and months_for_print:
                pc1, pc2 = st.columns(2)
                with pc1:
                    print_therapist = st.selectbox("治疗师", therapists_for_print, key="print_therapist")
                with pc2:
                    print_month = st.selectbox("月份", months_for_print, key="print_month")

                print_df = df[
                    (df["therapist_name"] == print_therapist) &
                    (df["month"] == print_month)
                ].copy().sort_values(["date", "client_name"])

                if print_df.empty:
                    st.warning("该治疗师在该月份没有记录。")
                else:
                    grouped = print_df.groupby("day", as_index=False).agg(
                        client_count=("client_name", "count"),
                        therapist_income=("therapist_income", "sum"),
                        tip=("tip", "sum"),
                        total_revenue=("total_revenue", "sum"),
                    )

                    st.markdown(f"#### {print_therapist} - {print_month} 工资核对单")
                    render_money_metrics(summarize_money(print_df), count_label="客人数")

                    st.markdown("##### 每日汇总")
                    st.dataframe(format_display_table(grouped, ["day", "client_count", "therapist_income", "tip", "total_revenue"]), use_container_width=True)

                    st.markdown("##### 客人明细")
                    display_cols = ["day", "client_name", "payment_type", "duration", "therapist_income", "tip", "total_revenue"]
                    st.dataframe(format_display_table(print_df, display_cols), use_container_width=True)

                    summary_df = pd.DataFrame([
                        ["月份", print_month],
                        ["治疗师", print_therapist],
                        ["本月总收入 Total Revenue", float(print_df["total_revenue"].sum())],
                        ["本月治疗师收入 Therapist Income", float(print_df["therapist_income"].sum())],
                        ["本月小费 Tip", float(print_df["tip"].sum())],
                        ["本月客人数 Client Count", int(len(print_df))],
                    ], columns=["项目", "数值"])

                    detail_df = print_df[display_cols].copy()
                    csv_text = summary_df.to_csv(index=False) + "\n" + detail_df.to_csv(index=False)

                    dl1, dl2 = st.columns(2)
                    with dl1:
                        st.download_button(
                            label="下载 CSV 明细",
                            data=csv_text.encode("utf-8-sig"),
                            file_name=f"{print_therapist}_{print_month}_payroll_detail.csv",
                            mime="text/csv",
                            use_container_width=True,
                        )

                    printable_html = f"""
                    <html>
                    <head>
                        <meta charset='utf-8'>
                        <style>
                            body {{ font-family: Arial, sans-serif; padding: 20px; }}
                            h1, h2, h3 {{ margin-bottom: 8px; }}
                            table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
                            th, td {{ border: 1px solid #999; padding: 6px; text-align: left; font-size: 12px; }}
                        </style>
                    </head>
                    <body>
                        <h1>{print_therapist} - {print_month} 工资核对单</h1>
                        <p>月总收入 Total Revenue: {money(print_df["total_revenue"].sum())}</p>
                        <p>月工资合计 Therapist Income: {money(print_df["therapist_income"].sum())}</p>
                        <p>月小费合计 Tip: {money(print_df["tip"].sum())}</p>
                        <p>月客人数 Client Count: {len(print_df)}</p>
                        {print_df[display_cols].to_html(index=False)}
                    </body>
                    </html>
                    """
                    with dl2:
                        st.download_button(
                            label="下载打印 HTML",
                            data=printable_html.encode("utf-8"),
                            file_name=f"{print_therapist}_{print_month}_printable.html",
                            mime="text/html",
                            use_container_width=True,
                        )
            else:
                st.warning("暂无可供打印的治疗师数据。")

        with query_tab3:
            profit_mode = st.radio("查询方式", ["按月查询", "按年查询"], horizontal=True)

            if profit_mode == "按月查询":
                month_options = sorted(df["month"].dropna().unique().tolist(), reverse=True)
                selected_profit_month = st.selectbox("月份", month_options, key="profit_month_query")
                profit_df = df[df["month"] == selected_profit_month].copy()
                render_money_metrics(summarize_money(profit_df), count_label="记录数")

                month_daily_profit = profit_df.groupby("day", as_index=False).agg(
                    total_revenue=("total_revenue", "sum"),
                    therapist_income=("therapist_income", "sum"),
                    tip=("tip", "sum"),
                    profit=("profit", "sum"),
                ).sort_values("day")
                st.dataframe(format_display_table(month_daily_profit, ["day", "total_revenue", "therapist_income", "tip", "profit"]), use_container_width=True)
            else:
                year_options = sorted(df["year"].dropna().unique().tolist(), reverse=True)
                selected_profit_year = st.selectbox("年份", year_options, key="profit_year_query")
                profit_df = df[df["year"] == selected_profit_year].copy()
                render_money_metrics(summarize_money(profit_df), count_label="记录数")

                year_monthly_profit = profit_df.groupby("month", as_index=False).agg(
                    total_revenue=("total_revenue", "sum"),
                    therapist_income=("therapist_income", "sum"),
                    tip=("tip", "sum"),
                    profit=("profit", "sum"),
                ).sort_values("month")
                st.dataframe(format_display_table(year_monthly_profit, ["month", "total_revenue", "therapist_income", "tip", "profit"]), use_container_width=True)

with raw_tab:
    st.subheader("原始记录")
    df = get_current_df(worksheet)

    if df.empty:
        st.info("暂无原始记录。")
    else:
        raw_col1, raw_col2, raw_col3 = st.columns(3)
        with raw_col1:
            raw_therapist_options = ["全部"] + sorted([x for x in df["therapist_name"].dropna().astype(str).unique().tolist() if x.strip()])
            selected_raw_therapist = st.selectbox("治疗师", raw_therapist_options, key="raw_therapist_filter")
        with raw_col2:
            selected_raw_payment = st.selectbox("付款方式", ["全部"] + PAYMENT_OPTIONS, key="raw_payment_filter")
        with raw_col3:
            raw_client_keyword = st.text_input("客人姓名", key="raw_client_filter")

        raw_df = df.copy()
        if selected_raw_therapist != "全部":
            raw_df = raw_df[raw_df["therapist_name"] == selected_raw_therapist]
        if selected_raw_payment != "全部":
            raw_df = raw_df[raw_df["payment_type"] == selected_raw_payment]
        if raw_client_keyword.strip():
            raw_df = raw_df[raw_df["client_name"].astype(str).str.contains(raw_client_keyword.strip(), case=False, na=False)]

        show_cols = [
            "date", "payment_type", "therapist_name", "client_name", "duration",
            "therapist_income", "tip", "total_revenue", "profit", "created_at",
        ]
        st.dataframe(format_display_table(raw_df[show_cols].sort_values("date", ascending=False), show_cols), use_container_width=True)
