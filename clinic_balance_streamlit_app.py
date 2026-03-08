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
st.caption("Streamlit + Google Sheets | 支持每日、每月、每年汇总 | 治疗师工资核对 | 支持修改与删除错误记录")

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
DEFAULT_THERAPISTS = ["Jenny", "Bonnie", "Sophia","Nancy","Martha","Ammabelle","Le Ann","Domingo"]

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


# -----------------------------
# Google Sheets 连接函数
# -----------------------------
def connect_google_sheet():
    if gspread is None or Credentials is None:
        return None, None, "未安装 gspread / google-auth，当前使用本地模式。"

    try:
        if "gcp_service_account" not in st.secrets:
            return None, None, "未检测到 Google 凭证，当前使用本地模式。"

        creds_info = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        client = gspread.authorize(creds)

        sheet_name = st.secrets.get("google_sheet", {}).get("sheet_name", SPREADSHEET_NAME)
        worksheet_name = st.secrets.get("google_sheet", {}).get("worksheet_name", WORKSHEET_NAME)

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


def save_local_update(df_local, row_index, row_dict):
    for key, value in row_dict.items():
        df_local.at[row_index, key] = value
    return df_local


def delete_local_rows(df_local, row_ids):
    df_local = df_local.drop(index=row_ids, errors="ignore").reset_index(drop=True)
    return df_local


def refresh_data(worksheet):
    if worksheet is not None:
        df_local = load_data_from_sheet(worksheet)
    else:
        df_local = st.session_state.local_data.copy()

    if df_local.empty:
        df_local = pd.DataFrame(columns=BASE_COLUMNS)
    else:
        df_local = ensure_columns(df_local)

    if not df_local.empty:
        df_local["date"] = pd.to_datetime(df_local["date"], errors="coerce")
        for col in ["therapist_income", "tip", "total_revenue", "profit"]:
            df_local[col] = pd.to_numeric(df_local[col], errors="coerce").fillna(0.0)

        df_local = df_local.reset_index(drop=True).copy()
        df_local["row_id"] = df_local.index
        if worksheet is not None:
            df_local["sheet_row_number"] = df_local.index + 2
        else:
            df_local["sheet_row_number"] = None

        valid_df = df_local.dropna(subset=["date"]).copy()
        if not valid_df.empty:
            valid_df["day"] = valid_df["date"].dt.date.astype(str)
            valid_df["month"] = valid_df["date"].dt.to_period("M").astype(str)
            valid_df["year"] = valid_df["date"].dt.year.astype(str)
        return valid_df

    return df_local


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


# -----------------------------
# 侧边栏
# -----------------------------
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

    if st.session_state.therapists:
        therapist_to_remove = st.selectbox("删除治疗师", [""] + st.session_state.therapists)
        if st.button("删除选中的治疗师"):
            if therapist_to_remove:
                st.session_state.therapists.remove(therapist_to_remove)
                if spreadsheet is not None:
                    try:
                        save_therapists_to_sheet(spreadsheet, st.session_state.therapists)
                    except Exception as e:
                        st.error(f"已更新本地名单，但保存到 Google Sheets 失败：{e}")
                st.success(f"已删除治疗师：{therapist_to_remove}")
                st.rerun()

    st.markdown("---")
    st.write("当前治疗师名单：")
    for i, t in enumerate(st.session_state.therapists, start=1):
        st.write(f"{i}. {t}")


# -----------------------------
# 数据载入
# -----------------------------
df = refresh_data(worksheet)


# -----------------------------
# 新增记录
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
        therapist_name = st.selectbox(
            "治疗师姓名",
            therapist_select_options(include_blank=True, blank_text=""),
            index=0,
            key="entry_therapist_name",
        )
        total_revenue = st.number_input("总收入 ($)", min_value=0.0, step=1.0, format="%.2f")

    tip = st.number_input("小费 Tip ($)", min_value=0.0, step=1.0, format="%.2f")

    if payment_type == "pc":
        therapist_name = ""
        therapist_income = 0.0
        st.info("PC 类型不关联治疗师，治疗师收入自动为 0。")
    else:
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
        if payment_type != "pc" and not str(therapist_name).strip():
            st.error("请选择治疗师姓名")
        else:
            row = {
                "date": str(entry_date),
                "payment_type": payment_type,
                "therapist_name": therapist_name.strip(),
                "client_name": client_name.strip(),
                "duration": duration,
                "therapist_income": float(therapist_income),
                "tip": float(tip),
                "total_revenue": float(total_revenue),
                "profit": float(profit),
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
                row["created_at"],
            ]

            try:
                if worksheet is not None:
                    append_row_to_sheet(worksheet, row_list)
                    st.success("记录已保存到 Google Sheets。")
                else:
                    st.session_state.local_data = pd.concat(
                        [st.session_state.local_data, pd.DataFrame([row])],
                        ignore_index=True
                    )
                    st.success("记录已保存到本地会话。")
                st.rerun()
            except Exception as e:
                st.error(f"保存失败：{e}")


df = refresh_data(worksheet)


# -----------------------------
# 修改错误记录
# -----------------------------
st.header("修改错误记录")

if df.empty:
    st.info("目前没有可修改的数据。")
else:
    edit_filter_col1, edit_filter_col2, edit_filter_col3 = st.columns(3)

    with edit_filter_col1:
        edit_date_options = ["全部"] + sorted(df["day"].dropna().unique().tolist(), reverse=True) if "day" in df.columns else ["全部"]
        selected_edit_date = st.selectbox("按日期筛选", edit_date_options, key="edit_date_filter")

    with edit_filter_col2:
        therapist_values = sorted([x for x in df["therapist_name"].dropna().astype(str).unique().tolist() if x.strip()])
        edit_therapist_options = ["全部"] + therapist_values
        selected_edit_therapist = st.selectbox("按治疗师筛选", edit_therapist_options, key="edit_therapist_filter")

    with edit_filter_col3:
        client_keyword = st.text_input("按客人姓名搜索", key="edit_client_keyword")

    edit_df = df.copy()

    if selected_edit_date != "全部" and "day" in edit_df.columns:
        edit_df = edit_df[edit_df["day"] == selected_edit_date]

    if selected_edit_therapist != "全部":
        edit_df = edit_df[edit_df["therapist_name"] == selected_edit_therapist]

    if client_keyword.strip():
        edit_df = edit_df[
            edit_df["client_name"].astype(str).str.contains(client_keyword.strip(), case=False, na=False)
        ]

    if edit_df.empty:
        st.warning("没有找到符合条件的记录。")
    else:
        edit_df = edit_df.sort_values(["date", "client_name"], ascending=[False, True]).copy()
        edit_df["record_label"] = edit_df.apply(
            lambda r: f"{r['day']} | {r['client_name']} | {r['payment_type']} | {r['therapist_name']} | ${r['total_revenue']:.2f}",
            axis=1
        )

        selected_label = st.selectbox(
            "请选择要修改的记录",
            edit_df["record_label"].tolist(),
            key="record_to_edit"
        )

        selected_row = edit_df[edit_df["record_label"] == selected_label].iloc[0]

        with st.form("edit_record_form"):
            ec1, ec2, ec3 = st.columns(3)

            with ec1:
                default_date = pd.to_datetime(selected_row["date"]).date() if pd.notna(selected_row["date"]) else date.today()
                new_date = st.date_input("日期", value=default_date, key="edit_date")
                payment_index = PAYMENT_OPTIONS.index(selected_row["payment_type"]) if selected_row["payment_type"] in PAYMENT_OPTIONS else 0
                new_payment_type = st.selectbox("付款类型", PAYMENT_OPTIONS, index=payment_index, key="edit_payment_type")

            with ec2:
                new_client_name = st.text_input("客人姓名 / Client Name", value=str(selected_row["client_name"]), key="edit_client_name")
                duration_options = list(DURATION_RATE_MAP.keys())
                duration_index = duration_options.index(selected_row["duration"]) if selected_row["duration"] in duration_options else 0
                new_duration = st.selectbox("治疗师工作时间", duration_options, index=duration_index, key="edit_duration")

            with ec3:
                therapist_options = therapist_select_options(include_blank=True, blank_text="")
                old_therapist = str(selected_row["therapist_name"]).strip()
                default_therapist_index = therapist_options.index(old_therapist) if old_therapist in therapist_options else 0
                new_therapist_name = st.selectbox(
                    "治疗师姓名",
                    therapist_options,
                    index=default_therapist_index,
                    key="edit_therapist_name"
                )
                new_total_revenue = st.number_input(
                    "总收入 ($)",
                    min_value=0.0,
                    value=float(selected_row["total_revenue"]),
                    step=1.0,
                    format="%.2f",
                    key="edit_total_revenue"
                )

            new_tip = st.number_input(
                "小费 Tip ($)",
                min_value=0.0,
                value=float(selected_row["tip"]),
                step=1.0,
                format="%.2f",
                key="edit_tip"
            )

            if new_payment_type == "pc":
                new_therapist_name = ""
                new_therapist_income = 0.0
                st.info("PC 类型不关联治疗师，治疗师收入自动为 0。")
            else:
                auto_income = DURATION_RATE_MAP.get(new_duration, 0.0)
                default_income = float(selected_row["therapist_income"]) if pd.notna(selected_row["therapist_income"]) else float(auto_income)
                new_therapist_income = st.number_input(
                    "治疗师收入 ($)",
                    min_value=0.0,
                    value=default_income,
                    step=1.0,
                    format="%.2f",
                    key="edit_therapist_income"
                )

            new_profit = float(new_total_revenue) - float(new_therapist_income) - float(new_tip)
            st.markdown(f"### 修改后利润 Profit: **${new_profit:.2f}**")

            update_submitted = st.form_submit_button("保存修改")

            if update_submitted:
                if new_payment_type != "pc" and not str(new_therapist_name).strip():
                    st.error("请选择治疗师姓名")
                else:
                    updated_row = {
                        "date": str(new_date),
                        "payment_type": new_payment_type,
                        "therapist_name": str(new_therapist_name).strip(),
                        "client_name": new_client_name.strip(),
                        "duration": new_duration,
                        "therapist_income": float(new_therapist_income),
                        "tip": float(new_tip),
                        "total_revenue": float(new_total_revenue),
                        "profit": float(new_profit),
                        "created_at": str(selected_row["created_at"]),
                    }

                    updated_row_list = [
                        updated_row["date"],
                        updated_row["payment_type"],
                        updated_row["therapist_name"],
                        updated_row["client_name"],
                        updated_row["duration"],
                        updated_row["therapist_income"],
                        updated_row["tip"],
                        updated_row["total_revenue"],
                        updated_row["profit"],
                        updated_row["created_at"],
                    ]

                    try:
                        if worksheet is not None:
                            sheet_row_number = int(selected_row["sheet_row_number"])
                            update_row_in_sheet(worksheet, sheet_row_number, updated_row_list)
                            st.success("Google Sheets 记录已修改。")
                        else:
                            local_row_id = int(selected_row["row_id"])
                            st.session_state.local_data = save_local_update(
                                st.session_state.local_data.copy(),
                                local_row_id,
                                updated_row
                            )
                            st.success("本地记录已修改。")
                        st.rerun()
                    except Exception as e:
                        st.error(f"修改失败：{e}")


# -----------------------------
# 删除错误记录
# -----------------------------
st.header("删除错误记录")

if df.empty:
    st.info("目前没有可删除的数据。")
else:
    del_col1, del_col2, del_col3 = st.columns(3)

    with del_col1:
        delete_date_options = ["全部"] + sorted(df["day"].dropna().unique().tolist(), reverse=True)
        selected_delete_date = st.selectbox("按日期筛选删除", delete_date_options, key="delete_date_filter")

    with del_col2:
        delete_therapist_values = sorted([x for x in df["therapist_name"].dropna().astype(str).unique().tolist() if x.strip()])
        delete_therapist_options = ["全部"] + delete_therapist_values
        selected_delete_therapist = st.selectbox("按治疗师筛选删除", delete_therapist_options, key="delete_therapist_filter")

    with del_col3:
        delete_client_keyword = st.text_input("按客人姓名搜索删除", key="delete_client_keyword")

    delete_df = df.copy()

    if selected_delete_date != "全部":
        delete_df = delete_df[delete_df["day"] == selected_delete_date]

    if selected_delete_therapist != "全部":
        delete_df = delete_df[delete_df["therapist_name"] == selected_delete_therapist]

    if delete_client_keyword.strip():
        delete_df = delete_df[
            delete_df["client_name"].astype(str).str.contains(delete_client_keyword.strip(), case=False, na=False)
        ]

    if delete_df.empty:
        st.warning("没有找到可删除的记录。")
    else:
        delete_df = delete_df.sort_values(["date", "client_name"], ascending=[False, True]).copy()
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
                "row_id", "sheet_row_number"
            ],
            column_config={
                "row_id": None,
                "sheet_row_number": None,
            },
            key="delete_data_editor"
        )

        selected_rows = edited_delete_df[edited_delete_df["选择删除"] == True].copy()

        if not selected_rows.empty:
            st.warning(f"已勾选 {len(selected_rows)} 条记录，删除后无法恢复。")

        if st.button("删除勾选记录", type="primary"):
            if selected_rows.empty:
                st.error("请先勾选要删除的记录。")
            else:
                try:
                    if worksheet is not None:
                        row_numbers = selected_rows["sheet_row_number"].dropna().astype(int).tolist()
                        delete_rows_from_sheet(worksheet, row_numbers)
                        st.success(f"已删除 {len(row_numbers)} 条 Google Sheets 记录。")
                    else:
                        row_ids = selected_rows["row_id"].astype(int).tolist()
                        st.session_state.local_data = delete_local_rows(
                            st.session_state.local_data.copy(),
                            row_ids
                        )
                        st.success(f"已删除 {len(row_ids)} 条本地记录。")
                    st.rerun()
                except Exception as e:
                    st.error(f"删除失败：{e}")


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
        therapists_for_query = therapist_select_options(include_blank=False)
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
                "therapist_income", "tip", "total_revenue"
            ]
            st.dataframe(therapist_month_df[detail_cols], use_container_width=True)
        else:
            st.warning("暂无可供查询的治疗师数据。")

    with query_tab2:
        st.subheader("打印该月每天该治疗师的客人名单与收入")
        therapists_for_print = therapist_select_options(include_blank=False)
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

                monthly_total_revenue = float(print_df["total_revenue"].sum())
                monthly_total_income = float(print_df["therapist_income"].sum())
                monthly_total_tip = float(print_df["tip"].sum())
                monthly_total_clients = int(len(print_df))

                st.markdown(f"### {print_therapist} - {print_month} 工资核对单")
                st.write(f"月总收入 Total Revenue：${monthly_total_revenue:,.2f}")
                st.write(f"月工资合计 Therapist Income：${monthly_total_income:,.2f}")
                st.write(f"月小费合计 Tip：${monthly_total_tip:,.2f}")
                st.write(f"月客人数 Client Count：{monthly_total_clients}")

                st.markdown("#### 每日汇总")
                st.dataframe(grouped, use_container_width=True)

                st.markdown("#### 每日客人明细")
                display_cols = [
                    "day", "client_name", "payment_type", "duration",
                    "therapist_income", "tip", "total_revenue"
                ]
                st.dataframe(print_df[display_cols], use_container_width=True)

                summary_df = pd.DataFrame([
                    ["月份", print_month],
                    ["治疗师", print_therapist],
                    ["本月总收入 Total Revenue", monthly_total_revenue],
                    ["本月治疗师收入 Therapist Income", monthly_total_income],
                    ["本月小费 Tip", monthly_total_tip],
                    ["本月客人数 Client Count", monthly_total_clients],
                ], columns=["项目", "数值"])

                detail_df = print_df[display_cols].copy()

                csv_text = summary_df.to_csv(index=False) + "\n" + detail_df.to_csv(index=False)
                csv_data = csv_text.encode("utf-8-sig")

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
                    <p>月总收入 Total Revenue: ${monthly_total_revenue:,.2f}</p>
                    <p>月工资合计 Therapist Income: ${monthly_total_income:,.2f}</p>
                    <p>月小费合计 Tip: ${monthly_total_tip:,.2f}</p>
                    <p>月客人数 Client Count: {monthly_total_clients}</p>
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
# 原始记录
# -----------------------------
st.header("原始记录")
if not df.empty:
    show_cols = [
        "date", "payment_type", "therapist_name", "client_name", "duration",
        "therapist_income", "tip", "total_revenue", "profit", "created_at"
    ]
    st.dataframe(df[show_cols].sort_values("date", ascending=False), use_container_width=True)
else:
    st.info("暂无原始记录。")