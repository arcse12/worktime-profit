import streamlit as st
import pandas as pd
from datetime import date, datetime

# Optional Google Sheets imports
try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:
    gspread = None
    Credentials = None

st.set_page_config(page_title="Clinic Income & Expense Tracker", layout="wide")

st.title("诊所每日收支平衡系统")
st.caption("Streamlit + Google Sheets | 支持每日、每月、每年汇总 | 治疗师工资核对")

# -----------------------------
# 基础配置
# -----------------------------
PAYMENT_OPTIONS = ["pc", "pfp", "pbm", "pbi", "pbc"]
DURATION_RATE_MAP = {
    "30 min": 32.5,
    "60 min": 65.0,
    "75 min": 81.25,
    "90 min": 97.5,
    "105 min": 113.75,
    "120 min": 130.0,
}
DEFAULT_THERAPISTS = ["Jenny", "Janice", "Alex"]
SPREADSHEET_NAME = "Massage_Work_Profit"
WORKSHEET_NAME = "transactions"
OWNER_EMAIL = "arcse12@gmail.com"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# -----------------------------
# Session State 初始化
# -----------------------------
if "therapists" not in st.session_state:
    st.session_state.therapists = DEFAULT_THERAPISTS.copy()

if "local_data" not in st.session_state:
    st.session_state.local_data = pd.DataFrame(columns=[
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
    ])

# -----------------------------
# Google Sheets 连接函数
# -----------------------------
def connect_google_sheet():
    if gspread is None or Credentials is None:
        return None, "未安装 gspread / google-auth，当前使用本地模式。"

    try:
        if "gcp_service_account" not in st.secrets:
            return None, "未检测到 Google 凭证，当前使用本地模式。"

        creds_info = dict(st.secrets["gcp_service_account"])
        scopes = SCOPES
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        client = gspread.authorize(creds)

        sheet_name = st.secrets.get("google_sheet", {}).get("sheet_name", SPREADSHEET_NAME)
        worksheet_name = st.secrets.get("google_sheet", {}).get("worksheet_name", WORKSHEET_NAME)

        try:
            spreadsheet = client.open(sheet_name)
        except Exception:
            spreadsheet = client.create(sheet_name)
            try:
                if OWNER_EMAIL:
                    spreadsheet.share(OWNER_EMAIL, perm_type="user", role="writer", notify=False)
            except Exception:
                pass
        try:
            worksheet = spreadsheet.worksheet(worksheet_name)
        except Exception:
            worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows=3000, cols=30)
            worksheet.append_row([
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
            ])
        return worksheet, "Google Sheets 已连接。"
    except Exception as e:
        return None, f"Google Sheets 连接失败：{e}"


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    required_columns = [
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
    for col in required_columns:
        if col not in df.columns:
            df[col] = "" if col in ["payment_type", "therapist_name", "client_name", "duration", "notes", "created_at"] else 0.0
    return df[required_columns]


def load_data_from_sheet(worksheet):
    try:
        records = worksheet.get_all_records()
        if not records:
            return pd.DataFrame(columns=[
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
            ])
        df = pd.DataFrame(records)
        return ensure_columns(df)
    except Exception:
        return pd.DataFrame(columns=[
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
        ])


def append_row_to_sheet(worksheet, row_data):
    worksheet.append_row(row_data, value_input_option="USER_ENTERED")


worksheet, gs_message = connect_google_sheet()

with st.sidebar:
    st.subheader("系统状态")
    if worksheet is not None:
        st.success(gs_message)
    else:
        st.warning(gs_message)

    st.subheader("治疗师名单管理")
    new_therapist = st.text_input("新增治疗师")
    if st.button("添加治疗师"):
        name = new_therapist.strip()
        if name:
            if name not in st.session_state.therapists:
                st.session_state.therapists.append(name)
                st.success(f"已添加治疗师：{name}")
            else:
                st.info("该治疗师已存在")
        else:
            st.error("请输入治疗师姓名")

    if st.session_state.therapists:
        therapist_to_remove = st.selectbox("删除治疗师", [""] + st.session_state.therapists)
        if st.button("删除选中的治疗师"):
            if therapist_to_remove:
                st.session_state.therapists.remove(therapist_to_remove)
                st.success(f"已删除治疗师：{therapist_to_remove}")

    st.markdown("---")
    st.write("当前治疗师名单：")
    for i, t in enumerate(st.session_state.therapists, start=1):
        st.write(f"{i}. {t}")

# -----------------------------
# 数据载入
# -----------------------------
if worksheet is not None:
    df = load_data_from_sheet(worksheet)
else:
    df = st.session_state.local_data.copy()

if df.empty:
    df = pd.DataFrame(columns=[
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
    ])
else:
    df = ensure_columns(df)

if not df.empty:
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ["therapist_income", "tip", "total_revenue", "profit"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

# -----------------------------
# 录入区
# -----------------------------
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
        therapist_mode = st.radio("PC 是否关联治疗师", ["不关联治疗师", "关联治疗师"], horizontal=True)
        if therapist_mode == "关联治疗师":
            therapist_name = st.selectbox("治疗师姓名", st.session_state.therapists, key="pc_therapist_name")
            auto_income = DURATION_RATE_MAP[duration]
            therapist_income = st.number_input(
                "治疗师收入 ($)",
                min_value=0.0,
                value=float(auto_income),
                step=1.0,
                format="%.2f",
                help="PC 也可以手动选择治疗师并记录工资。"
            )
        else:
            st.info("PC 类型当前设置为不关联治疗师。")
            therapist_name = ""
            therapist_income = 0.0
    else:
        therapist_name = st.selectbox("治疗师姓名", st.session_state.therapists)
        auto_income = DURATION_RATE_MAP[duration]
        therapist_income = st.number_input(
            "治疗师收入 ($)",
            min_value=0.0,
            value=float(auto_income),
            step=1.0,
            format="%.2f",
            help="默认按时长自动带出，也可手动修改。"
        )

    profit = float(total_revenue) - float(therapist_income) - float(tip)
    st.markdown(f"### 利润 Profit: **${profit:.2f}**")

    submitted = st.form_submit_button("保存记录")

    if submitted:
        if payment_type != "pc" and not therapist_name:
            st.error("请选择治疗师姓名")
        else:
            row = {
                "date": str(entry_date),
                "payment_type": payment_type,
                "therapist_name": therapist_name,
                "client_name": client_name.strip(),
                "duration": duration,
                "therapist_income": float(therapist_income),
                "tip": float(tip),
                "total_revenue": float(total_revenue),
                "profit": float(profit),
                "notes": notes,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

            row_list = [
                row["date"],
                row["payment_type"],
                row["therapist_name"],
                row["client_name"],
                row["duration"],
                row["therapist_income"],
                row["tip"],
                row["total_revenue"],
                row["profit"],
                row["notes"],
                row["created_at"],
            ]

            try:
                if worksheet is not None:
                    append_row_to_sheet(worksheet, row_list)
                    st.success("记录已保存到 Google Sheets。")
                else:
                    st.session_state.local_data = pd.concat([
                        st.session_state.local_data,
                        pd.DataFrame([row])
                    ], ignore_index=True)
                    st.success("记录已保存到本地会话（未连接 Google Sheets）。")
            except Exception as e:
                st.error(f"保存失败：{e}")

# 重新读取最新数据
if worksheet is not None:
    df = load_data_from_sheet(worksheet)
else:
    df = st.session_state.local_data.copy()

if not df.empty:
    df = ensure_columns(df)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ["therapist_income", "tip", "total_revenue", "profit"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

# -----------------------------
# 衍生字段
# -----------------------------
if not df.empty and not df["date"].isna().all():
    df = df.dropna(subset=["date"]).copy()
    df["day"] = df["date"].dt.date.astype(str)
    df["month"] = df["date"].dt.to_period("M").astype(str)
    df["year"] = df["date"].dt.year.astype(str)

# -----------------------------
# 汇总显示
# -----------------------------
st.header("收支汇总")

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

    tab1, tab2, tab3 = st.tabs(["每日收支", "每月收支", "每年总收支"])

    with tab1:
        st.dataframe(daily_summary, use_container_width=True)

    with tab2:
        st.dataframe(monthly_summary, use_container_width=True)

    with tab3:
        st.dataframe(yearly_summary, use_container_width=True)

# -----------------------------
# 查询功能
# -----------------------------
st.header("查询与工资核对")

if df.empty:
    st.info("请先录入数据后再查询。")
else:
    query_tab1, query_tab2, query_tab3 = st.tabs([
        "治疗师月工资查询",
        "治疗师客人名单 / 打印",
        "利润查询"
    ])

    with query_tab1:
        st.subheader("查询该治疗师这个月工资总共多少")
        therapists_for_query = sorted([t for t in df["therapist_name"].dropna().unique().tolist() if str(t).strip() != ""])
        months_for_query = sorted(df["month"].dropna().unique().tolist(), reverse=True)

        if therapists_for_query and months_for_query:
            selected_therapist = st.selectbox("选择治疗师", therapists_for_query, key="salary_therapist")
            selected_month = st.selectbox("选择月份", months_for_query, key="salary_month")

            therapist_month_df = df[
                (df["therapist_name"] == selected_therapist) &
                (df["month"] == selected_month)
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
        st.subheader("打印该月每天该治疗师的客人名单与收入")
        therapists_for_print = sorted([t for t in df["therapist_name"].dropna().unique().tolist() if str(t).strip() != ""])
        months_for_print = sorted(df["month"].dropna().unique().tolist(), reverse=True)

        if therapists_for_print and months_for_print:
            print_therapist = st.selectbox("选择治疗师用于打印", therapists_for_print, key="print_therapist")
            print_month = st.selectbox("选择月份用于打印", months_for_print, key="print_month")

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
                    mime="text/csv"
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
                    mime="text/html"
                )
        else:
            st.warning("暂无可供打印的治疗师数据。")

    with query_tab3:
        st.subheader("查询每个月甚至每一年的总利润")
        profit_mode = st.radio("选择查询方式", ["按月查询", "按年查询"], horizontal=True)

        if profit_mode == "按月查询":
            month_options = sorted(df["month"].dropna().unique().tolist(), reverse=True)
            selected_profit_month = st.selectbox("选择月份", month_options, key="profit_month_query")
            month_df = df[df["month"] == selected_profit_month].copy()

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
            year_options = sorted(df["year"].dropna().unique().tolist(), reverse=True)
            selected_profit_year = st.selectbox("选择年份", year_options, key="profit_year_query")
            year_df = df[df["year"] == selected_profit_year].copy()

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

# -----------------------------
# 修改记录
# -----------------------------
st.header("修改记录")
if df.empty:
    st.info("目前没有可修改的记录。")
else:
    edit_df = df.copy().sort_values(["date", "created_at"], ascending=[False, False]).reset_index(drop=True)
    edit_df["record_label"] = edit_df.apply(
        lambda r: f"{str(r['date'])[:10]} | {r['client_name']} | {r['payment_type']} | {r['therapist_name']} | ${float(r['total_revenue']):.2f}",
        axis=1
    )

    selected_label = st.selectbox("选择要修改的记录", edit_df["record_label"].tolist())
    selected_row = edit_df[edit_df["record_label"] == selected_label].iloc[0]
    selected_index = int(selected_row.name)

    with st.form("edit_form"):
        ec1, ec2, ec3 = st.columns(3)
        with ec1:
            edit_date = st.date_input("修改日期", value=pd.to_datetime(selected_row["date"]).date(), key="edit_date")
            edit_payment_type = st.selectbox("修改付款类型", PAYMENT_OPTIONS, index=PAYMENT_OPTIONS.index(selected_row["payment_type"]) if selected_row["payment_type"] in PAYMENT_OPTIONS else 0, key="edit_payment_type")
        with ec2:
            edit_client_name = st.text_input("修改客人姓名", value=str(selected_row["client_name"]), key="edit_client_name")
            duration_options = list(DURATION_RATE_MAP.keys())
            edit_duration = st.selectbox("修改治疗时长", duration_options, index=duration_options.index(selected_row["duration"]) if selected_row["duration"] in duration_options else 0, key="edit_duration")
        with ec3:
            edit_total_revenue = st.number_input("修改总收入 ($)", min_value=0.0, value=float(selected_row["total_revenue"]), step=1.0, format="%.2f", key="edit_total_revenue")
            edit_tip = st.number_input("修改小费 ($)", min_value=0.0, value=float(selected_row["tip"]), step=1.0, format="%.2f", key="edit_tip")

        edit_notes = st.text_input("修改备注", value=str(selected_row["notes"]), key="edit_notes")

        if edit_payment_type == "pc":
            edit_therapist_mode = st.radio(
                "PC 是否关联治疗师",
                ["不关联治疗师", "关联治疗师"],
                horizontal=True,
                index=1 if str(selected_row["therapist_name"]).strip() else 0,
                key="edit_pc_mode"
            )
            if edit_therapist_mode == "关联治疗师":
                therapist_options = st.session_state.therapists
                default_idx = therapist_options.index(selected_row["therapist_name"]) if selected_row["therapist_name"] in therapist_options else 0
                edit_therapist_name = st.selectbox("修改治疗师姓名", therapist_options, index=default_idx, key="edit_pc_therapist_name")
                default_income = float(selected_row["therapist_income"])
                edit_therapist_income = st.number_input("修改治疗师收入 ($)", min_value=0.0, value=default_income, step=1.0, format="%.2f", key="edit_pc_therapist_income")
            else:
                edit_therapist_name = ""
                edit_therapist_income = 0.0
        else:
            therapist_options = st.session_state.therapists
            default_idx = therapist_options.index(selected_row["therapist_name"]) if selected_row["therapist_name"] in therapist_options else 0
            edit_therapist_name = st.selectbox("修改治疗师姓名", therapist_options, index=default_idx, key="edit_therapist_name")
            edit_therapist_income = st.number_input(
                "修改治疗师收入 ($)",
                min_value=0.0,
                value=float(selected_row["therapist_income"]),
                step=1.0,
                format="%.2f",
                key="edit_therapist_income"
            )

        edit_profit = float(edit_total_revenue) - float(edit_therapist_income) - float(edit_tip)
        st.markdown(f"### 修改后利润 Profit: **${edit_profit:.2f}**")

        save_edit = st.form_submit_button("保存修改")

        if save_edit:
            updated_row = {
                "date": str(edit_date),
                "payment_type": edit_payment_type,
                "therapist_name": edit_therapist_name,
                "client_name": edit_client_name.strip(),
                "duration": edit_duration,
                "therapist_income": float(edit_therapist_income),
                "tip": float(edit_tip),
                "total_revenue": float(edit_total_revenue),
                "profit": float(edit_profit),
                "notes": edit_notes,
                "created_at": str(selected_row["created_at"]),
            }

            if worksheet is None:
                local_df = st.session_state.local_data.copy()
                if not local_df.empty:
                    local_df = ensure_columns(local_df)
                    local_df = local_df.reset_index(drop=True)
                    if selected_index < len(local_df):
                        for col, val in updated_row.items():
                            local_df.at[selected_index, col] = val
                        st.session_state.local_data = local_df
                        st.success("记录已修改。")
                        st.rerun()
            else:
                st.warning("当前版本 Google Sheets 已支持新增记录。修改已先在界面准备好；如你需要，我可以继续帮你加上同步修改 Google Sheets 原记录功能。")

# -----------------------------
# 原始记录
# -----------------------------
st.header("原始记录")
if not df.empty:
    show_cols = [
        "date", "payment_type", "therapist_name", "client_name", "duration",
        "therapist_income", "tip", "total_revenue", "profit", "notes", "created_at"
    ]
    st.dataframe(df[show_cols].sort_values(["date", "created_at"], ascending=[False, False]), use_container_width=True)

# -----------------------------
# 底部说明
# -----------------------------
st.markdown("---")
st.subheader("Google Sheets 配置说明")
st.code('''
1. 程序会自动打开或创建 Google Sheet，例如：Massage_Work_Profit
2. 建立 worksheet：transactions
3. Google Cloud 创建 Service Account，并下载 JSON key
4. 把 JSON 内容放进 .streamlit/secrets.toml
5. 把该 service account 的 client_email 分享到你的 Google Sheet 编辑权限
6. 安装依赖：
   pip install streamlit pandas gspread google-auth
7. 运行：
   streamlit run clinic_balance_streamlit_app.py
''')

st.subheader("当前利润算法")
st.write("利润 = 总收入 - 治疗师工资 - 小费")

st.subheader("已实现的规则")
st.write("1. 付款类型固定为 pc / pfp / pbm / pbi / pbc")
st.write("2. pc 不需要填写治疗师姓名，且治疗师收入默认为 0")
st.write("3. 治疗师姓名为可编辑菜单，可在左侧新增或删除")
st.write("4. 治疗师收入按时间自动带出，也支持手动修改")
st.write("5. 表格显示每日收支、每月收支、每年总收支")
st.write("6. 支持治疗师小费录入")
st.write("7. 支持按治疗师查询月工资总额")
st.write("8. 支持打印某治疗师某月份的每日客人名单与收入")
st.write("9. 支持按月、按年查询总利润")
