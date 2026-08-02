import pandas as pd
import numpy as np

def generate_time_series_features(df):
    """
    Generate historical lag and rolling statistics features from quantity.
    Ensures zero target leakage by applying shift(1) before any rolling or EMA calculations.
    """
    # 1. Sắp xếp chuỗi thời gian theo itemId và date
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(by=['itemId', 'date']).reset_index(drop=True)
    
    # 2. Tính toán Lags lịch sử
    print("Đang tính toán các lags lịch sử...")
    df['lag_1'] = df.groupby('itemId')['quantity'].shift(1)
    df['lag_7'] = df.groupby('itemId')['quantity'].shift(7)
    df['lag_14'] = df.groupby('itemId')['quantity'].shift(14)
    df['lag_30'] = df.groupby('itemId')['quantity'].shift(30)
    
    # 3. Tính toán Rolling Statistics trên lag_1 (để đảm bảo không bị rò rỉ dữ liệu)
    print("Đang tính toán các thống kê trượt (rolling statistics) trên lag_1...")
    groupby_lag1 = df.groupby('itemId')['lag_1']
    
    windows = [7, 14, 30]
    for w in windows:
        df[f'rolling_mean_{w}'] = groupby_lag1.transform(lambda x: x.rolling(window=w, min_periods=1).mean())
        df[f'rolling_std_{w}'] = groupby_lag1.transform(lambda x: x.rolling(window=w, min_periods=1).std())
        df[f'rolling_median_{w}'] = groupby_lag1.transform(lambda x: x.rolling(window=w, min_periods=1).median())
        df[f'rolling_sum_{w}'] = groupby_lag1.transform(lambda x: x.rolling(window=w, min_periods=1).sum())
        
        # zero sales ratio (tỷ lệ ngày không bán được hàng)
        df[f'zero_sales_ratio_{w}'] = groupby_lag1.transform(
            lambda x: (x == 0).astype(float).where(x.notna()).rolling(window=w, min_periods=1).mean()
        )
        
    # 4. Exponential Moving Average (EMA) trên lag_1
    print("Đang tính toán các chỉ số trung bình động lũy thừa (EMA) trên lag_1...")
    df['ema_7'] = groupby_lag1.transform(lambda x: x.ewm(span=7, min_periods=1, adjust=False).mean())
    df['ema_30'] = groupby_lag1.transform(lambda x: x.ewm(span=30, min_periods=1, adjust=False).mean())
    
    # 5. Days Since Last Sale (Số ngày kể từ lần bán gần nhất)
    print("Đang tính toán số ngày kể từ lần bán gần nhất (days_since_last_sale)...")
    def compute_days_since_last_sale_group(group_quantity):
        n = len(group_quantity)
        last_sale_idx = np.empty(n)
        last_sale_idx[:] = np.nan
        
        idx = np.where(group_quantity > 0)[0]
        last_sale_idx[idx] = idx
        
        # Shift 1 và ffill để đảm bảo không bị rò rỉ dữ liệu của ngày hiện tại
        s_idx = pd.Series(last_sale_idx).shift(1).ffill().values
        days_since = np.arange(n) - s_idx
        days_since[np.isnan(days_since)] = 999.0
        return days_since

    df['days_since_last_sale'] = df.groupby('itemId')['quantity'].transform(compute_days_since_last_sale_group)
    
    # Điền khuyết rolling std bằng 0.0 (khi cửa sổ trượt chỉ chứa 1 giá trị hoặc giá trị hằng số)
    for w in windows:
        df[f'rolling_std_{w}'] = df[f'rolling_std_{w}'].fillna(0.0)
        
    return df
