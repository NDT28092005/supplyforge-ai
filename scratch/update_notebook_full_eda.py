import os
import sys
import json
import nbformat
import pandas as pd
import numpy as np

notebook_path = '/home/nguyen-dai-tung/supplyforge-ai/notebooks/EDA_Diagnosis_v2.ipynb'

with open(notebook_path, 'r', encoding='utf-8') as f:
    nb = nbformat.read(f, as_version=4)

# 1. Update Cell 1 Markdown
nb.cells[0].source = """# SupplyForge AI 2.0: Chương 1. Data Audit & Readiness Assessment (v2 — Full Dataset Parquet)

Tài liệu Jupyter Notebook này thực hiện kiểm toán chất lượng dữ liệu chuyên sâu và đánh giá mức độ sẵn sàng của **Toàn bộ Bộ dữ liệu Silver Parquet (Full Dataset - 352,981 đơn hàng, 559,254 items, 1,335 SKUs)** phục vụ huấn luyện mô hình dự báo nhu cầu (Demand Forecasting) và cảnh báo đứt hàng (Stockout) bằng LightGBM + SHAP xAI.

Quy trình kiểm toán tuân thủ các nguyên tắc nghiêm ngặt của **Data Engineering** và **Data Quality Assurance** nhằm đảm bảo dữ liệu đầu vào sạch, nhất quán và không có rò rỉ (Data Leakage) trên toàn bộ kho dữ liệu lịch sử sản xuất."""

# 2. Update Cell 1 Markdown header
nb.cells[1].source = """## PHẦN I — Dataset Snapshot (Full Dataset Parquet)

Bảng Dataset Snapshot dạng text/dataframe tóm tắt các thông số kỹ thuật và chỉ số vận hành cốt lõi của toàn bộ dữ liệu hóa đơn `orders_clean.parquet`, `order_items_clean.parquet` và danh mục sản phẩm `products_clean.parquet`."""

# 3. Update Cell 2 Code (Data Loading)
cell2_code = """import pandas as pd
import numpy as np
import json
import os
import datetime
from scipy import stats
import matplotlib.pyplot as plt
import seaborn as sns
from statsmodels.tsa.stattools import adfuller
from statsmodels.tsa.stattools import kpss
import warnings
warnings.filterwarnings('ignore')

# Thiết lập giao diện biểu đồ
sns.set_theme(style='whitegrid')
plt.rcParams['figure.figsize'] = (12, 6)

SILVER_DIR = '/home/nguyen-dai-tung/supplyforge-ai/data/silver'

# 1. Load Full Silver Parquet Data
df_orders = pd.read_parquet(os.path.join(SILVER_DIR, 'orders_clean.parquet'))
df_order_items = pd.read_parquet(os.path.join(SILVER_DIR, 'order_items_clean.parquet'))
df_prod = pd.read_parquet(os.path.join(SILVER_DIR, 'products_clean.parquet'))

# Ép kiểu thời gian
df_orders['time'] = pd.to_datetime(df_orders['time'], errors='coerce')
df_order_items['time'] = pd.to_datetime(df_order_items['time'], errors='coerce')

# Tính toán snapshot
rows_orders = len(df_orders)
rows_items = len(df_order_items)
cols_orders = len(df_orders.columns)
min_t = df_orders['time'].min()
max_t = df_orders['time'].max()
time_span = f"{min_t.date()} to {max_t.date()}" if pd.notna(min_t) else 'N/A'
days = (max_t - min_t).days + 1 if pd.notna(min_t) else 1
orders_per_day = rows_orders / days
cancel_rate = (df_orders['status'].isin(['CANCELLED', 'TO_RETURN', 'IN_CANCEL'])).mean() * 100
duplicates = df_orders.duplicated(subset=['_id']).sum()

snapshot_data = {
    'Metric': ['Total Orders', 'Total Order Items', 'Total Columns', 'Time Span', 'Total Days', 'Orders per Day', 'Overall Cancel Rate (%)', 'Duplicate PKs'],
    'Value': [rows_orders, rows_items, cols_orders, time_span, days, f"{orders_per_day:.2f}", f"{cancel_rate:.2f}%", duplicates]
}
df_snapshot = pd.DataFrame(snapshot_data)
print("=== DATASET SNAPSHOT (FULL DATASET) ===")
print(df_snapshot.to_string(index=False))"""

nb.cells[2].source = cell2_code

# 4. Update Cell 4 Code (Data Quality Scorecard)
cell4_code = """# 1. Completeness
null_key_cells = df_orders['_id'].isnull().sum() + df_orders['time'].isnull().sum() + df_orders['amount'].isnull().sum()
completeness = (1 - (null_key_cells / (len(df_orders) * 3))) * 100

# 2. Consistency
df_orders['createdAt'] = pd.to_datetime(df_orders['createdAt'], errors='coerce')
df_orders['updatedAt'] = pd.to_datetime(df_orders['updatedAt'], errors='coerce')
consistency_violations = ((df_orders['createdAt'] > df_orders['updatedAt']) | (df_orders['amount'] < 0)).sum()
consistency = (1 - (consistency_violations / len(df_orders))) * 100

# 3. Uniqueness
uniqueness = (1 - (df_orders['_id'].duplicated().sum() / len(df_orders))) * 100

# 4. Validity
valid_statuses = ['COMPLETED', 'CANCELLED', 'READY_TO_SHIP', 'RETRY_SHIPPING', 'SHIPPED', 'TO_RETURN', 'IN_CANCEL', 'TO_SHIP', 'PROCESSED', 'CREATED', 'UNPAID', 'TO_CONFIRM_RECEIVE', 'RETURNED']
invalid_status = (~df_orders['status'].isin(valid_statuses)).sum()
invalid_id_len = df_orders['_id'].apply(lambda x: len(str(x)) != 24).sum()
validity = (1 - ((invalid_status + invalid_id_len) / (len(df_orders) * 2))) * 100

# 5. Timeliness
daily_cnt = df_orders.groupby(df_orders['time'].dt.date).size()
timeliness = (len(daily_cnt) / days) * 100

# 6. Integrity
df_prod_clean = df_prod[['itemId', 'categoryId', 'brand']].dropna(subset=['itemId']).copy()
df_prod_clean['itemId'] = df_prod_clean['itemId'].astype(str)

if 'categoryId' not in df_order_items.columns:
    df_order_items = pd.merge(df_order_items, df_prod_clean, on='itemId', how='left')

orphans = (~df_order_items['orderId'].astype(str).isin(df_orders['_id'].astype(str))).sum()
integrity = (1 - (orphans / len(df_order_items))) * 100

scorecard = {
    'Data Quality Dimension': ['Completeness', 'Consistency', 'Uniqueness', 'Validity', 'Timeliness', 'Integrity'],
    'Score (%)': [f'{completeness:.2f}%', f'{consistency:.2f}%', f'{uniqueness:.2f}%', f'{validity:.2f}%', f'{timeliness:.2f}%', f'{integrity:.2f}%']
}
df_scorecard = pd.DataFrame(scorecard)
print("=== DATA QUALITY SCORECARD (FULL DATASET) ===")
print(df_scorecard.to_string(index=False))"""

nb.cells[4].source = cell4_code

with open(notebook_path, 'w', encoding='utf-8') as f:
    nbformat.write(nb, f)

print("Notebook updated with Full Parquet loading code!")
