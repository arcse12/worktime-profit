from datetime import date, datetime
from io import BytesIO

import pandas as pd
import streamlit as st
<<<<<<< HEAD
=======

>>>>>>> ea96d3306d47bcc36646269610add2639f8d14af

# Optional Google Sheets imports
try:
    import gspread
    from google.oauth2.service_account import Credentials
    from gspread.exceptions import SpreadsheetNotFound, APIError
except Exception:
    gspread = None
    Credentials = None
    SpreadsheetNotFound = Exception
    APIError = Exception

st.set_page_config(page_title="Clinic Balance System", layout="wide")

# =============================
# 基础配置（参考 app.py 结构）
# =============================
SPREADSHEET_NAME = "Massage_Work_Profit"
SHEET_RECORD = "transactions"
SHEET_STAFF = "therapists"
OWNER_EMAIL = "arcse12@gmail.com"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

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

RECORD_COLUMNS = [
    "ID",
    "date",
    "payment_type",
    "therapist_name",
    "client_name",
    "duration",
    "therapist_income",
    "tip",
    "total_revenue",
    "profit",
    "notes",
    "created_at",
]

STAFF_COLUMNS = ["therapist_name"]

# =============================
# Session State
# =============================
if "local_records" not in st.session_state:
    st.session_state.local_records = pd.DataFrame(columns=RECORD_COLUMNS)

if "local_staff" not in st.session_state:
    st.session_state.local_staff = pd.DataFrame({"therapist_name": DEFAULT_THERAPISTS})


# =============================
# 通用函数
# =============================
def ensure_record_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=RECORD_COLUMNS)

    df = df.copy()
    for col in RECORD_COLUMNS:
        if col not in df.columns:
            if col in ["ID"]:
                df[col] = 0
            elif col in ["therapist_income", "tip", "total_revenue", "profit"]:
                df[col] = 0.0
            else:
                df[col] = ""

    df["ID"] = pd.to_numeric(df["ID"], errors="coerce")
    if df["ID"].isna().all():
        df["ID"] = range(1, len(df) + 1)
    else:
        max_id = int(df["ID"].dropna().max()) if not df["ID"].dropna().empty else 0
        for idx, val in df["ID"].items():
            if pd.isna(val):
                max_id += 1
                df.at[idx, "ID"] = max_id
    df["ID"] = df["ID"].astype(int)

    for col in ["therapist_income", "tip", "total_revenue", "profit"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    return df[RECORD_COLUMNS]


def ensure_staff_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=STAFF_COLUMNS)

    df = df.copy()
    if "therapist_name" not in df.columns:
        df["therapist_name"] = ""

    df["therapist_name"] = df["therapist_name"].astype(str).str.strip()
    df = df[df["therapist_name"] != ""].drop_duplicates().reset_index(drop=True)
    return df[STAFF_COLUMNS]


def calc_auto_income(duration: str) -> float:
    return float(DURATION_RATE_MAP.get(duration, 0.0))


def therapist_options(include_blank=True, blank_text="请选择治疗师"):
    staff_df = load_staff()
    names = staff_df["therapist_name"].astype(str).str.strip().tolist() if not staff_df.empty else []
    if include_blank:
        return [blank_text] + names
    return names


def prepare_display_df(df: pd.DataFrame) -> pd.DataFrame:
    df = ensure_record_columns(df)
    if df.empty:
        return df

    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = out.dropna(subset=["date"]).copy()

    if out.empty:
        return out

    out["day"] = out["date"].dt.strftime("%Y-%m-%d")
    out["month"] = out["date"].dt.strftime("%Y-%m")
    out["year"] = out["date"].dt.strftime("%Y")
    return out


# =============================
# Google Sheets
# =============================
@st.cache_resource

def get_gsheet_client():
    if gspread is None or Credentials is None:
        return None
    if "gcp_service_account" not in st.secrets:
        return None

    creds_info = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    return gspread.authorize(creds)


def get_or_create_worksheet(title: str):
    client = get_gsheet_client()
    if client is None:
        return None

    try:
        sheet_name = st.secrets.get("google_sheet", {}).get("sheet_name", SPREADSHEET_NAME)
        sh = client.open(sheet_name)
    except SpreadsheetNotFound:
        sh = client.create(sheet_name)
        try:
            if OWNER_EMAIL:
                sh.share(OWNER_EMAIL, perm_type="user", role="writer", notify=False)
        except Exception:
            pass
    except Exception as e:
        st.error(f"打开 Google Sheets 失败：{e}")
        return None

    worksheet_name = title
    if title == SHEET_RECORD:
        worksheet_name = st.secrets.get("google_sheet", {}).get("worksheet_name", SHEET_RECORD)

    try:
        ws = sh.worksheet(worksheet_name)
    except Exception:
        ws = sh.add_worksheet(title=worksheet_name, rows="3000", cols="30")
        if title == SHEET_RECORD:
            ws.append_row(RECORD_COLUMNS)
        elif title == SHEET_STAFF:
            ws.append_row(STAFF_COLUMNS)
    return ws


@st.cache_data(ttl=30)
def load_records() -> pd.DataFrame:
    ws = get_or_create_worksheet(SHEET_RECORD)
    if ws is None:
        return ensure_record_columns(st.session_state.local_records)

    try:
        rows = ws.get_all_records()
        df = pd.DataFrame(rows)
        return ensure_record_columns(df)
    except Exception:
        return ensure_record_columns(pd.DataFrame(columns=RECORD_COLUMNS))


def save_all_records(df: pd.DataFrame):
    df = ensure_record_columns(df)
    ws = get_or_create_worksheet(SHEET_RECORD)
    if ws is None:
        st.session_state.local_records = df.copy()
        load_records.clear()
        return

    ws.clear()
    ws.append_row(RECORD_COLUMNS)
    if not df.empty:
        rows = df[RECORD_COLUMNS].astype(object).values.tolist()
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    load_records.clear()


@st.cache_data(ttl=30)
def load_staff() -> pd.DataFrame:
    ws = get_or_create_worksheet(SHEET_STAFF)
    if ws is None:
        return ensure_staff_columns(st.session_state.local_staff)

    try:
        rows = ws.get_all_records()
        df = pd.DataFrame(rows)
        if df.empty:
            df = pd.DataFrame({"therapist_name": DEFAULT_THERAPISTS})
        return ensure_staff_columns(df)
    except Exception:
        return ensure_staff_columns(pd.DataFrame({"therapist_name": DEFAULT_THERAPISTS}))


def save_staff(df: pd.DataFrame):
    df = ensure_staff_columns(df)
    ws = get_or_create_worksheet(SHEET_STAFF)
    if ws is None:
        st.session_state.local_staff = df.copy()
        load_staff.clear()
        return

    ws.clear()
    ws.append_row(STAFF_COLUMNS)
    if not df.empty:
        ws.append_rows(df[STAFF_COLUMNS].astype(object).values.tolist(), value_input_option="USER_ENTERED")
    load_staff.clear()


def ensure_staff_exists(name: str):
    name = str(name).strip()
    if not name:
        return
    df = load_staff()
    if name not in df["therapist_name"].astype(str).tolist():
        df = pd.concat([df, pd.DataFrame([{"therapist_name": name}])], ignore_index=True)
        save_staff(df)


# =============================
# 导出 Excel
# =============================
def to_excel_bytes(detail_df: pd.DataFrame, summary_df: pd.DataFrame, sheet1_name="Detail", sheet2_name="Summary") -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        detail_df.to_excel(writer, index=False, sheet_name=sheet1_name)
        summary_df.to_excel(writer, index=False, sheet_name=sheet2_name)
    return output.getvalue()


# =============================
# 页面标题 / 状态
# =============================
st.title("诊所每日收支平衡系统")
st.caption("以 app.py 为蓝本重构 | 支持 Google Sheets / 本地模式 | 收支、利润、工资核对")

client = get_gsheet_client()
with st.sidebar:
    st.subheader("系统状态")
    if client is None:
        st.warning("当前为本地模式（未检测到 Google Sheets 凭证）")
    else:
        st.success("Google Sheets 已连接")

# =============================
# 读取数据
# =============================
records_df = load_records()
staff_df = load_staff()
display_df = prepare_display_df(records_df)

# =============================
# 页面导航（参考 app.py）
# =============================
page = st.sidebar.radio(
    "选择页面",
    [
        "新增记录",
        "汇总统计",
<<<<<<< HEAD
        "修改记录",
=======
>>>>>>> ea96d3306d47bcc36646269610add2639f8d14af
        "删除记录",
        "治疗师管理",
        "工资核对 / 打印",
    ],
)

# =============================
# 新增记录
# =============================
if page == "新增记录":
    st.header("新增每日收支记录")

    with st.form("entry_form", clear_on_submit=False):
        c1, c2, c3 = st.columns(3)

        with c1:
            entry_date = st.date_input("日期", value=date.today())
            payment_type = st.selectbox("付款类型", PAYMENT_OPTIONS)

        with c2:
            client_name = st.text_input("客人姓名 / Client Name")
            duration = st.selectbox("治疗师工作时间", list(DURATION_RATE_MAP.keys()))

        with c3:
            total_revenue = st.number_input("总收入 ($)", min_value=0.0, step=1.0, format="%.2f")
            tip = st.number_input("小费 Tip ($)", min_value=0.0, step=1.0, format="%.2f")

        notes = st.text_input("备注")

        if payment_type == "pc":
            st.info("PC 类型默认不关联治疗师，治疗师收入为 0。")
            therapist_name = ""
            therapist_income = 0.0
        else:
            options = therapist_options(include_blank=True)
            therapist_name = st.selectbox("治疗师姓名", options, key="entry_therapist_name")
            if therapist_name == "请选择治疗师":
                therapist_name = ""
            auto_income = calc_auto_income(duration)
            therapist_income = st.number_input(
                "治疗师收入 ($)",
                min_value=0.0,
                value=float(auto_income),
                step=1.0,
                format="%.2f",
                help="默认按时长自动带出，也可手动修改。",
            )

        profit = float(total_revenue) - float(therapist_income) - float(tip)
        st.markdown(f"### 利润 Profit: **${profit:.2f}**")

        submitted = st.form_submit_button("保存记录")

        if submitted:
            if payment_type != "pc" and not therapist_name:
                st.error("请选择治疗师姓名")
            else:
                if therapist_name:
                    ensure_staff_exists(therapist_name)

                next_id = int(records_df["ID"].max()) + 1 if not records_df.empty else 1
                row = {
                    "ID": next_id,
                    "date": str(entry_date),
                    "payment_type": payment_type,
                    "therapist_name": therapist_name,
                    "client_name": client_name.strip(),
                    "duration": duration,
                    "therapist_income": float(therapist_income),
                    "tip": float(tip),
                    "total_revenue": float(total_revenue),
                    "profit": float(profit),
                    "notes": notes.strip(),
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                new_df = pd.concat([records_df, pd.DataFrame([row])], ignore_index=True)
                save_all_records(new_df)
                st.success("记录已保存")
                st.rerun()

# =============================
# 汇总统计
# =============================
elif page == "汇总统计":
    st.header("收支汇总")

    if display_df.empty:
        st.info("目前还没有数据。")
    else:
        daily_summary = display_df.groupby("day", as_index=False).agg(
            total_revenue=("total_revenue", "sum"),
            therapist_income=("therapist_income", "sum"),
            tip=("tip", "sum"),
            profit=("profit", "sum"),
        ).sort_values("day", ascending=False)

        monthly_summary = display_df.groupby("month", as_index=False).agg(
            total_revenue=("total_revenue", "sum"),
            therapist_income=("therapist_income", "sum"),
            tip=("tip", "sum"),
            profit=("profit", "sum"),
        ).sort_values("month", ascending=False)

        yearly_summary = display_df.groupby("year", as_index=False).agg(
            total_revenue=("total_revenue", "sum"),
            therapist_income=("therapist_income", "sum"),
            tip=("tip", "sum"),
            profit=("profit", "sum"),
        ).sort_values("year", ascending=False)

        tab1, tab2, tab3, tab4 = st.tabs(["每日收支", "每月收支", "每年总收支", "原始记录"])

        with tab1:
            st.dataframe(daily_summary, use_container_width=True)
        with tab2:
            st.dataframe(monthly_summary, use_container_width=True)
        with tab3:
            st.dataframe(yearly_summary, use_container_width=True)
        with tab4:
            show_cols = [
                "ID", "date", "payment_type", "therapist_name", "client_name", "duration",
                "therapist_income", "tip", "total_revenue", "profit", "notes", "created_at"
            ]
            raw_df = records_df.copy()
            raw_df["date"] = pd.to_datetime(raw_df["date"], errors="coerce")
            st.dataframe(raw_df[show_cols].sort_values("date", ascending=False), use_container_width=True)

# =============================
<<<<<<< HEAD
# 修改记录
# =============================
elif page == "修改记录":
    st.header("修改错误记录")

    if records_df.empty:
        st.info("目前没有可修改的记录。")
    else:
        work_df = records_df.copy()
        work_df["date"] = pd.to_datetime(work_df["date"], errors="coerce")
        work_df = work_df.sort_values(["date", "ID"], ascending=[False, False]).copy()
        work_df["date_str"] = work_df["date"].dt.strftime("%Y-%m-%d").fillna("")

        st.caption("先筛选，再选择一条记录进行修改。")
        f1, f2, f3 = st.columns(3)
        with f1:
            date_options = ["全部"] + sorted([d for d in work_df["date_str"].dropna().unique().tolist() if d], reverse=True)
            selected_date = st.selectbox("按日期筛选", date_options, key="edit_filter_date")
        with f2:
            therapist_values = work_df["therapist_name"].fillna("").astype(str).str.strip()
            therapist_list = sorted([x for x in therapist_values.unique().tolist() if x])
            therapist_options_edit = ["全部", "空白"] + therapist_list
            selected_therapist_filter = st.selectbox("按治疗师筛选", therapist_options_edit, key="edit_filter_therapist")
        with f3:
            client_keyword = st.text_input("按客人姓名搜索", key="edit_filter_client").strip().lower()

        filtered_df = work_df.copy()
        if selected_date != "全部":
            filtered_df = filtered_df[filtered_df["date_str"] == selected_date]
        if selected_therapist_filter == "空白":
            filtered_df = filtered_df[filtered_df["therapist_name"].fillna("").astype(str).str.strip() == ""]
        elif selected_therapist_filter != "全部":
            filtered_df = filtered_df[filtered_df["therapist_name"].fillna("").astype(str).str.strip() == selected_therapist_filter]
        if client_keyword:
            filtered_df = filtered_df[
                filtered_df["client_name"].fillna("").astype(str).str.lower().str.contains(client_keyword, na=False)
            ]

        if filtered_df.empty:
            st.warning("没有找到符合条件的记录。")
        else:
            filtered_df["display_label"] = filtered_df.apply(
                lambda r: f"ID {int(r['ID'])} | {r['date_str']} | {str(r['client_name']) or '-'} | {str(r['therapist_name']) or '无治疗师'} | {str(r['payment_type'])} | {str(r['duration'])}",
                axis=1,
            )
            selected_label = st.selectbox("选择要修改的记录", filtered_df["display_label"].tolist(), key="edit_record_select")
            selected_row = filtered_df.loc[filtered_df["display_label"] == selected_label].iloc[0]

            st.dataframe(pd.DataFrame([selected_row[RECORD_COLUMNS]]), use_container_width=True)

            selected_payment_type = str(selected_row["payment_type"])
            selected_duration = str(selected_row["duration"]) if str(selected_row["duration"]) in DURATION_RATE_MAP else list(DURATION_RATE_MAP.keys())[0]
            row_date = pd.to_datetime(selected_row["date"], errors="coerce")
            default_date = row_date.date() if pd.notna(row_date) else date.today()
            therapist_raw = str(selected_row["therapist_name"] or "").strip()

            with st.form(f"edit_form_{int(selected_row['ID'])}"):
                c1, c2, c3 = st.columns(3)
                with c1:
                    edit_date = st.date_input("日期", value=default_date, key=f"edit_date_{int(selected_row['ID'])}")
                    edit_payment_type = st.selectbox(
                        "付款类型",
                        PAYMENT_OPTIONS,
                        index=PAYMENT_OPTIONS.index(selected_payment_type) if selected_payment_type in PAYMENT_OPTIONS else 0,
                        key=f"edit_payment_{int(selected_row['ID'])}",
                    )
                with c2:
                    edit_client_name = st.text_input("客人姓名 / Client Name", value=str(selected_row["client_name"] or ""), key=f"edit_client_{int(selected_row['ID'])}")
                    duration_keys = list(DURATION_RATE_MAP.keys())
                    edit_duration = st.selectbox(
                        "治疗师工作时间",
                        duration_keys,
                        index=duration_keys.index(selected_duration),
                        key=f"edit_duration_{int(selected_row['ID'])}",
                    )
                with c3:
                    edit_total_revenue = st.number_input(
                        "总收入 ($)", min_value=0.0, value=float(selected_row["total_revenue"]), step=1.0, format="%.2f", key=f"edit_revenue_{int(selected_row['ID'])}"
                    )
                    edit_tip = st.number_input(
                        "小费 Tip ($)", min_value=0.0, value=float(selected_row["tip"]), step=1.0, format="%.2f", key=f"edit_tip_{int(selected_row['ID'])}"
                    )

                edit_notes = st.text_input("备注", value=str(selected_row["notes"] or ""), key=f"edit_notes_{int(selected_row['ID'])}")

                if edit_payment_type == "pc":
                    st.info("PC 类型默认不关联治疗师，治疗师收入为 0。")
                    edit_therapist_name = ""
                    edit_therapist_income = 0.0
                else:
                    options = therapist_options(include_blank=True)
                    therapist_index = options.index(therapist_raw) if therapist_raw in options else 0
                    edit_therapist_name = st.selectbox(
                        "治疗师姓名",
                        options,
                        index=therapist_index,
                        key=f"edit_therapist_{int(selected_row['ID'])}",
                    )
                    if edit_therapist_name == "请选择治疗师":
                        edit_therapist_name = ""
                    edit_therapist_income = st.number_input(
                        "治疗师收入 ($)",
                        min_value=0.0,
                        value=float(selected_row["therapist_income"]),
                        step=1.0,
                        format="%.2f",
                        help="可直接改成正确金额。",
                        key=f"edit_income_{int(selected_row['ID'])}",
                    )

                edit_profit = float(edit_total_revenue) - float(edit_therapist_income) - float(edit_tip)
                st.markdown(f"### 修改后利润 Profit: **${edit_profit:.2f}**")

                updated = st.form_submit_button("保存修改", type="primary")
                if updated:
                    if edit_payment_type != "pc" and not edit_therapist_name:
                        st.error("请选择治疗师姓名")
                    else:
                        if edit_therapist_name:
                            ensure_staff_exists(edit_therapist_name)

                        updated_row = {
                            "ID": int(selected_row["ID"]),
                            "date": str(edit_date),
                            "payment_type": edit_payment_type,
                            "therapist_name": edit_therapist_name,
                            "client_name": edit_client_name.strip(),
                            "duration": edit_duration,
                            "therapist_income": float(edit_therapist_income),
                            "tip": float(edit_tip),
                            "total_revenue": float(edit_total_revenue),
                            "profit": float(edit_profit),
                            "notes": edit_notes.strip(),
                            "created_at": str(selected_row["created_at"]),
                        }
                        new_df = records_df.copy()
                        new_df.loc[new_df["ID"] == int(selected_row["ID"]), RECORD_COLUMNS] = pd.Series(updated_row)
                        save_all_records(new_df)
                        st.success(f"记录 ID {int(selected_row['ID'])} 已更新")
                        st.rerun()

# =============================
=======
>>>>>>> ea96d3306d47bcc36646269610add2639f8d14af
# 删除记录
# =============================
elif page == "删除记录":
    st.header("删除记录")

    if records_df.empty:
        st.info("目前没有可删除的数据。")
    else:
        work_df = records_df.copy()
        work_df["date"] = pd.to_datetime(work_df["date"], errors="coerce")
        work_df["display_label"] = (
            "ID=" + work_df["ID"].astype(str)
            + " | " + work_df["date"].dt.strftime("%Y-%m-%d").fillna("")
            + " | " + work_df["therapist_name"].fillna("")
            + " | " + work_df["client_name"].fillna("")
            + " | $" + work_df["total_revenue"].astype(float).map(lambda x: f"{x:.2f}")
        )

        selected_label = st.selectbox("选择要删除的记录", work_df["display_label"].tolist())
        selected_row = work_df.loc[work_df["display_label"] == selected_label].iloc[0]

        st.dataframe(pd.DataFrame([selected_row[RECORD_COLUMNS]]), use_container_width=True)

        if st.button("确认删除", type="primary"):
            new_df = records_df[records_df["ID"] != int(selected_row["ID"])].copy()
            save_all_records(new_df)
            st.success("记录已删除")
            st.rerun()

# =============================
# 治疗师管理
# =============================
elif page == "治疗师管理":
    st.header("治疗师管理")

    col1, col2 = st.columns(2)
    with col1:
        new_name = st.text_input("新增治疗师")
        if st.button("添加治疗师"):
            name = new_name.strip()
            if not name:
                st.error("请输入治疗师姓名")
            elif name in staff_df["therapist_name"].astype(str).tolist():
                st.info("该治疗师已存在")
            else:
                new_staff = pd.concat([staff_df, pd.DataFrame([{"therapist_name": name}])], ignore_index=True)
                save_staff(new_staff)
                st.success(f"已添加治疗师：{name}")
                st.rerun()

    with col2:
        if staff_df.empty:
            st.info("目前没有治疗师")
        else:
            remove_name = st.selectbox("删除治疗师", [""] + staff_df["therapist_name"].astype(str).tolist())
            if st.button("删除选中的治疗师"):
                if remove_name:
                    new_staff = staff_df[staff_df["therapist_name"] != remove_name].copy()
                    save_staff(new_staff)
                    st.success(f"已删除治疗师：{remove_name}")
                    st.rerun()

    st.markdown("---")
    st.subheader("当前治疗师名单")
    st.dataframe(staff_df, use_container_width=True)

# =============================
# 工资核对 / 打印
# =============================
elif page == "工资核对 / 打印":
    st.header("治疗师工资核对 / 打印")

    if display_df.empty:
        st.info("请先录入数据后再查询。")
    else:
        query_tab1, query_tab2, query_tab3 = st.tabs([
            "治疗师月工资查询",
            "治疗师客人名单 / 打印",
            "利润查询",
        ])

        with query_tab1:
            therapists_for_query = therapist_options(include_blank=False)
            months_for_query = sorted(display_df["month"].dropna().unique().tolist(), reverse=True)

            if therapists_for_query and months_for_query:
                selected_therapist = st.selectbox("选择治疗师", therapists_for_query, key="salary_therapist")
                selected_month = st.selectbox("选择月份", months_for_query, key="salary_month")

                therapist_month_df = display_df[
                    (display_df["therapist_name"] == selected_therapist)
                    & (display_df["month"] == selected_month)
                ].copy().sort_values("date")

                total_salary = therapist_month_df["therapist_income"].sum()
                total_tip = therapist_month_df["tip"].sum()
                total_count = len(therapist_month_df)
                total_revenue = therapist_month_df["total_revenue"].sum()

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("治疗次数", total_count)
                c2.metric("治疗师工资", f"${total_salary:,.2f}")
                c3.metric("小费合计", f"${total_tip:,.2f}")
                c4.metric("相关总收入", f"${total_revenue:,.2f}")

                detail_cols = [
                    "day", "client_name", "payment_type", "duration",
                    "therapist_income", "tip", "total_revenue", "notes"
                ]
                st.dataframe(therapist_month_df[detail_cols], use_container_width=True)
            else:
                st.warning("暂无可供查询的治疗师数据。")

        with query_tab2:
            therapists_for_print = therapist_options(include_blank=False)
            months_for_print = sorted(display_df["month"].dropna().unique().tolist(), reverse=True)

            if therapists_for_print and months_for_print:
                print_therapist = st.selectbox("选择治疗师用于打印", therapists_for_print, key="print_therapist")
                print_month = st.selectbox("选择月份用于打印", months_for_print, key="print_month")

                print_df = display_df[
                    (display_df["therapist_name"] == print_therapist)
                    & (display_df["month"] == print_month)
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

                    st.markdown(f"### {print_therapist} - {print_month} 工资核对单")
                    st.write(f"月工资合计：${print_df['therapist_income'].sum():,.2f}")
                    st.write(f"月小费合计：${print_df['tip'].sum():,.2f}")
                    st.write(f"月客人数：{len(print_df)}")

                    st.markdown("#### 每日汇总")
                    st.dataframe(grouped, use_container_width=True)

                    st.markdown("#### 每日客人明细")
                    display_cols = [
                        "day", "client_name", "payment_type", "duration",
                        "therapist_income", "tip", "total_revenue", "notes"
                    ]
                    st.dataframe(print_df[display_cols], use_container_width=True)

                    csv_data = print_df[display_cols].to_csv(index=False).encode("utf-8-sig")
                    st.download_button(
                        label="下载该治疗师该月明细 CSV",
                        data=csv_data,
                        file_name=f"{print_therapist}_{print_month}_payroll_detail.csv",
                        mime="text/csv",
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
                        <p>月工资合计: ${print_df['therapist_income'].sum():,.2f}</p>
                        <p>月小费合计: ${print_df['tip'].sum():,.2f}</p>
                        <p>月客人数: {len(print_df)}</p>
                        {print_df[display_cols].to_html(index=False)}
                    </body>
                    </html>
                    """
                    st.download_button(
                        label="下载打印版 HTML",
                        data=printable_html.encode("utf-8"),
                        file_name=f"{print_therapist}_{print_month}_printable.html",
                        mime="text/html",
                    )

                    export_bytes = to_excel_bytes(print_df[display_cols], grouped, "Detail", "Daily Summary")
                    st.download_button(
                        label="下载 Excel",
                        data=export_bytes,
                        file_name=f"{print_therapist}_{print_month}_payroll.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
            else:
                st.warning("暂无可供打印的治疗师数据。")

        with query_tab3:
            profit_mode = st.radio("选择查询方式", ["按月查询", "按年查询"], horizontal=True)

            if profit_mode == "按月查询":
                month_options = sorted(display_df["month"].dropna().unique().tolist(), reverse=True)
                selected_profit_month = st.selectbox("选择月份", month_options, key="profit_month_query")
                month_df = display_df[display_df["month"] == selected_profit_month].copy()

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("总收入", f"${month_df['total_revenue'].sum():,.2f}")
                c2.metric("治疗师工资", f"${month_df['therapist_income'].sum():,.2f}")
                c3.metric("小费", f"${month_df['tip'].sum():,.2f}")
                c4.metric("总利润", f"${month_df['profit'].sum():,.2f}")

                month_daily_profit = month_df.groupby("day", as_index=False).agg(
                    total_revenue=("total_revenue", "sum"),
                    therapist_income=("therapist_income", "sum"),
                    tip=("tip", "sum"),
                    profit=("profit", "sum"),
                ).sort_values("day")
                st.dataframe(month_daily_profit, use_container_width=True)

            else:
                year_options = sorted(display_df["year"].dropna().unique().tolist(), reverse=True)
                selected_profit_year = st.selectbox("选择年份", year_options, key="profit_year_query")
                year_df = display_df[display_df["year"] == selected_profit_year].copy()

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("总收入", f"${year_df['total_revenue'].sum():,.2f}")
                c2.metric("治疗师工资", f"${year_df['therapist_income'].sum():,.2f}")
                c3.metric("小费", f"${year_df['tip'].sum():,.2f}")
                c4.metric("总利润", f"${year_df['profit'].sum():,.2f}")

                year_monthly_profit = year_df.groupby("month", as_index=False).agg(
                    total_revenue=("total_revenue", "sum"),
                    therapist_income=("therapist_income", "sum"),
                    tip=("tip", "sum"),
                    profit=("profit", "sum"),
                ).sort_values("month")
                st.dataframe(year_monthly_profit, use_container_width=True)
