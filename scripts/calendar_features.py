import pandas as pd
import numpy as np

def generate_calendar_features(df):
    """
    Extract calendar and promotion features from date column.
    All features are ex-ante (known beforehand) so there is zero target leakage.
    """
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    
    # 1. Đặc trưng lịch cơ bản
    print("Đang trích xuất các đặc trưng lịch cơ bản...")
    df['day_of_week'] = df['date'].dt.dayofweek
    df['day_of_month'] = df['date'].dt.day
    df['week_of_year'] = df['date'].dt.isocalendar().week.astype(int)
    df['month'] = df['date'].dt.month
    df['quarter'] = df['date'].dt.quarter
    df['is_weekend'] = df['day_of_week'].isin([5, 6]).astype(int)
    df['is_month_start'] = df['date'].dt.is_month_start.astype(int)
    df['is_month_end'] = df['date'].dt.is_month_end.astype(int)
    
    # 2. Ngày nghỉ lễ Việt Nam (2021-2024)
    print("Đang gán cờ ngày lễ Việt Nam (is_holiday)...")
    vietnam_holidays = {
        # 2021
        2021: [
            '2021-01-01',  # Tết Dương Lịch
            '2021-02-10', '2021-02-11', '2021-02-12', '2021-02-13', '2021-02-14', '2021-02-15', '2021-02-16', # Tết Âm Lịch
            '2021-04-21',  # Giỗ Tổ Hùng Vương
            '2021-04-30', '2021-05-01',  # Giải Phóng & Lao Động
            '2021-09-02', '2021-09-03'   # Quốc Khánh
        ],
        # 2022
        2022: [
            '2022-01-01',
            '2022-01-29', '2022-01-30', '2022-01-31', '2022-02-01', '2022-02-02', '2022-02-03', '2022-02-04', '2022-02-05', '2022-02-06',
            '2022-04-10', '2022-04-11',
            '2022-04-30', '2022-05-01', '2022-05-02', '2022-05-03',
            '2022-09-01', '2022-09-02'
        ],
        # 2023
        2023: [
            '2023-01-01', '2023-01-02',
            '2023-01-20', '2023-01-21', '2023-01-22', '2023-01-23', '2023-01-24', '2023-01-25', '2023-01-26',
            '2023-04-29', '2023-04-30', '2023-05-01', '2023-05-02', '2023-05-03',
            '2023-09-01', '2023-09-02', '2023-09-03', '2023-09-04'
        ],
        # 2024
        2024: [
            '2024-01-01',
            '2024-02-08', '2024-02-09', '2024-02-10', '2024-02-11', '2024-02-12', '2024-02-13', '2024-02-14',
            '2024-04-18',
            '2024-04-30', '2024-05-01',
            '2024-08-31', '2024-09-01', '2024-09-02', '2024-09-03'
        ]
    }
    
    all_holidays = set()
    for year, dates in vietnam_holidays.items():
        all_holidays.update(pd.to_datetime(dates))
        
    df['is_holiday'] = df['date'].isin(all_holidays).astype(int)
    
    # 3. Chiến dịch khuyến mại định kỳ e-commerce (Double Day, Mid-Month, Salary Day)
    print("Đang gán cờ chiến dịch e-commerce định kỳ (campaign)...")
    campaign_names = np.full(len(df), "No Campaign", dtype=object)
    campaign_types = np.full(len(df), "No Campaign", dtype=object)
    promotion_levels = np.zeros(len(df), dtype=int)
    
    day_arr = df['day_of_month'].values
    month_arr = df['month'].values
    
    double_day_mask = (day_arr == month_arr)
    mid_month_mask = (day_arr == 15)
    salary_day_mask = (day_arr == 25)
    
    # Áp dụng Salary Day
    campaign_names[salary_day_mask] = "Salary Day Sale"
    campaign_types[salary_day_mask] = "Normal Sale"
    promotion_levels[salary_day_mask] = 1
    
    # Áp dụng Mid Month
    campaign_names[mid_month_mask] = "Mid-Month Sale"
    campaign_types[mid_month_mask] = "Normal Sale"
    promotion_levels[mid_month_mask] = 1
    
    # Áp dụng Double Day (Mega Sales)
    for m in range(1, 13):
        m_mask = (double_day_mask) & (month_arr == m)
        campaign_names[m_mask] = f"Mega Sale {m}.{m}"
        campaign_types[m_mask] = "Mega Sale"
        promotion_levels[m_mask] = 2
        
    df['campaign_name'] = campaign_names
    df['campaign_type'] = campaign_types
    df['promotion_level'] = promotion_levels
    df['is_sale_campaign'] = (df['promotion_level'] > 0).astype(int)
    
    return df
