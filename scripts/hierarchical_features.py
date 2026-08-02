import pandas as pd
import numpy as np

def generate_hierarchical_features(df):
    """
    Generate hierarchical time-series features at the brand and category level.
    Ensures zero target leakage by applying shift(1) before rolling and cumulative calculations.
    """
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    
    # --- 1. BRAND-DATE LEVEL FEATURES ---
    print("Tổng hợp và tính toán đặc trưng cấp Brand...")
    # Group by brand & date, sort chronologically
    df_brand = df.groupby(['brand', 'date'])['quantity'].sum().reset_index()
    df_brand = df_brand.sort_values(by=['brand', 'date']).reset_index(drop=True)
    
    # Calculate lags
    df_brand['brand_lag_1'] = df_brand.groupby('brand')['quantity'].shift(1)
    df_brand['brand_lag_7'] = df_brand.groupby('brand')['quantity'].shift(7)
    
    # Calculate rolling and cumulative stats on brand_lag_1 (prevent leakage)
    groupby_brand_lag1 = df_brand.groupby('brand')['brand_lag_1']
    df_brand['brand_roll_mean_7'] = groupby_brand_lag1.transform(lambda x: x.rolling(7, min_periods=1).mean())
    df_brand['brand_roll_mean_30'] = groupby_brand_lag1.transform(lambda x: x.rolling(30, min_periods=1).mean())
    df_brand['brand_cumulative_sales'] = groupby_brand_lag1.transform(lambda x: x.expanding(min_periods=1).sum())
    
    # --- 2. CATEGORY-DATE LEVEL FEATURES ---
    print("Tổng hợp và tính toán đặc trưng cấp Category...")
    # Group by categoryId & date, sort chronologically
    df_cat = df.groupby(['categoryId', 'date'])['quantity'].sum().reset_index()
    df_cat = df_cat.sort_values(by=['categoryId', 'date']).reset_index(drop=True)
    
    # Calculate lags
    df_cat['category_lag_1'] = df_cat.groupby('categoryId')['quantity'].shift(1)
    df_cat['category_lag_7'] = df_cat.groupby('categoryId')['quantity'].shift(7)
    
    # Calculate rolling and cumulative stats on category_lag_1 (prevent leakage)
    groupby_cat_lag1 = df_cat.groupby('categoryId')['category_lag_1']
    df_cat['category_roll_mean_7'] = groupby_cat_lag1.transform(lambda x: x.rolling(7, min_periods=1).mean())
    df_cat['category_roll_mean_30'] = groupby_cat_lag1.transform(lambda x: x.rolling(30, min_periods=1).mean())
    df_cat['category_cumulative_sales'] = groupby_cat_lag1.transform(lambda x: x.expanding(min_periods=1).sum())
    
    # --- 3. JOIN BACK TO DAILY SKU GRID ---
    print("Đang ghép nối các đặc trưng phân cấp trở lại lưới Daily SKU Grid...")
    # Select columns to merge
    brand_cols = ['brand', 'date', 'brand_lag_1', 'brand_lag_7', 'brand_roll_mean_7', 'brand_roll_mean_30', 'brand_cumulative_sales']
    cat_cols = ['categoryId', 'date', 'category_lag_1', 'category_lag_7', 'category_roll_mean_7', 'category_roll_mean_30', 'category_cumulative_sales']
    
    # Merge brand features
    df_merged = pd.merge(df, df_brand[brand_cols], on=['brand', 'date'], how='left')
    
    # Merge category features
    df_final = pd.merge(df_merged, df_cat[cat_cols], on=['categoryId', 'date'], how='left')
    
    return df_final
