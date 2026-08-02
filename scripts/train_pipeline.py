import os
import json
import math
import joblib
import pandas as pd
import numpy as np

# Try importing ML libraries, fallback gracefully if not installed
try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False

try:
    from sklearn.model_selection import train_test_split
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import classification_report, roc_auc_score
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

try:
    import shap
    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False


class SupplyForgeTrainPipeline:
    """
    Production-grade training framework for SupplyForge AI 2.0 ML model (Phase 2 to 7).
    Deals with high-volume datasets (like 3.1 GB orders.csv) using memory-efficient chunking streams.
    """

    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.products_json_path = os.path.join(data_dir, "products.json")
        self.orders_csv_path = os.path.join(data_dir, "orders.csv")
        self.output_model_path = os.path.join(data_dir, "stockout_model.pkl")
        self.master_dataset_path = os.path.join(data_dir, "master_dataset.csv")

    def run_data_audit_and_profiling(self):
        """
        Phase 2: Data Understanding.
        Loads product metadata and profiles data distributions and quality metrics.
        """
        print("\n--- PHASE 2: Data Audit & Profiling ---")
        if not os.path.exists(self.products_json_path):
            raise FileNotFoundError(f"Missing products file: {self.products_json_path}")
            
        print(f"Loading products metadata from {self.products_json_path}...")
        df_prod = pd.read_json(self.products_json_path)
        print(f"Loaded {len(df_prod)} products.")
        
        # Profile fields
        print("\n[Product Columns Profile]:")
        for col in ['price', 'stock', 'cost']:
            if col in df_prod.columns:
                print(f" - {col}: mean={df_prod[col].mean():.2f}, median={df_prod[col].median():.2f}, std={df_prod[col].std():.2f}, missing={df_prod[col].isnull().sum()}")

        # Data quality checks
        duplicates = df_prod['_id'].duplicated().sum() if '_id' in df_prod.columns else 0
        print(f"Duplicate product IDs: {duplicates}")
        
        return df_prod

    def run_data_engineering(self):
        """
        Phase 3: Data Engineering.
        Aggregates the large 3.1 GB orders.csv using chunking to prevent Out-Of-Memory (OOM) failures.
        Merges aggregated sales data with products metadata into a Master Dataset.
        """
        print("\n--- PHASE 3: Data Engineering (Chunked Processing) ---")
        if not os.path.exists(self.orders_csv_path):
            print(f"Warning: orders.csv not found at {self.orders_csv_path}. Using fallback mocked sales data.")
            return self._run_data_engineering_fallback()

        print(f"Processing large sales file: {self.orders_csv_path}...")
        
        # Dictionary to store sales count and quantity by SKU/itemId
        # key: item_sku or item_id -> [total_quantity, total_orders, total_revenue]
        sales_agg = {}

        chunksize = 100000  # Process 100k rows at a time
        total_rows_processed = 0

        # Read denormalized orders in chunks
        for chunk in pd.read_csv(self.orders_csv_path, chunksize=chunksize, low_memory=False):
            # Normalise columns (lowercasing to handle potential headers variation)
            chunk.columns = [c.lower() for c in chunk.columns]
            
            # Identify columns for identification and quantities
            sku_col = next((c for c in chunk.columns if 'sku' in c), None)
            qty_col = next((c for c in chunk.columns if 'qty' in c or 'quantity' in c), None)
            price_col = next((c for c in chunk.columns if 'price' in c or 'amount' in c), None)

            if not sku_col or not qty_col:
                # Fallback to standard column mapping if named exactly
                sku_col = 'sku'
                qty_col = 'quantity'

            for _, row in chunk.iterrows():
                sku = str(row.get(sku_col, ''))
                if not sku or sku == 'nan':
                    continue
                
                qty = float(row.get(qty_col, 0.0) or 0.0)
                price = float(row.get(price_col, 0.0) or 0.0)
                revenue = qty * price

                if sku not in sales_agg:
                    sales_agg[sku] = [0.0, 0, 0.0]
                
                sales_agg[sku][0] += qty
                sales_agg[sku][1] += 1
                sales_agg[sku][2] += revenue

            total_rows_processed += len(chunk)
            print(f"Processed {total_rows_processed} sales records...")

        print(f"Finished chunk processing. Aggregated {len(sales_agg)} unique SKUs.")

        # Convert aggregates to DataFrame
        df_sales = pd.DataFrame.from_dict(
            sales_agg, orient='index', 
            columns=['aggregated_qty_sold', 'aggregated_orders_count', 'aggregated_revenue']
        ).reset_index().rename(columns={'index': 'item_sku'})

        # Load products json and merge
        df_prod = pd.read_json(self.products_json_path)
        
        # Merge on itemSku / sku
        master_df = pd.merge(df_prod, df_sales, left_on='itemSku', right_on='item_sku', how='left')
        
        # Fill missing sales with zero
        master_df['aggregated_qty_sold'] = master_df['aggregated_qty_sold'].fillna(0.0)
        master_df['aggregated_orders_count'] = master_df['aggregated_orders_count'].fillna(0)
        master_df['aggregated_revenue'] = master_df['aggregated_revenue'].fillna(0.0)

        # Save master dataset
        master_df.to_csv(self.master_dataset_path, index=False)
        print(f"Saved master dataset to {self.master_dataset_path}")
        return master_df

    def _run_data_engineering_fallback(self):
        """Fallback mock database generator if orders.csv is absent."""
        df_prod = pd.read_json(self.products_json_path)
        # Mock historical sales
        np.random.seed(42)
        df_prod['aggregated_qty_sold'] = np.random.randint(0, 100, size=len(df_prod))
        df_prod['aggregated_orders_count'] = np.random.randint(0, 50, size=len(df_prod))
        df_prod['aggregated_revenue'] = df_prod['aggregated_qty_sold'] * df_prod['price'].astype(float)
        
        df_prod.to_csv(self.master_dataset_path, index=False)
        print("Generated mock fallback master dataset.")
        return df_prod

    def run_feature_engineering(self, df):
        """
        Phase 4: Feature Engineering.
        Generates indicators for stock ratios, velocity indices, trend coefficients, and supplier risk metrics.
        """
        print("\n--- PHASE 4: Feature Engineering ---")
        
        # 1. Sales velocity: sold quantity annualized over 30 days
        df['sales_velocity'] = df['aggregated_qty_sold'] / 30.0

        # 2. Coverage days: stock left divided by daily velocity
        df['inventory_coverage_days'] = np.where(
            df['sales_velocity'] > 0, 
            df['stock'].astype(float) / df['sales_velocity'], 
            999.0
        )

        # 3. Sales trend (mocked ratio of fast sales to historical mean for training)
        np.random.seed(123)
        df['sales_trend'] = np.random.uniform(0.5, 2.0, size=len(df))

        # 4. Supplier delay rate
        df['delay_rate'] = np.random.uniform(0.0, 0.25, size=len(df))

        # 5. Inventory Ratio (SKU cost value over total shop inventory cost value)
        df['sku_cost_value'] = df['stock'].astype(float) * df['cost'].astype(float).fillna(50000.0)
        total_shop_cost = df['sku_cost_value'].sum()
        df['inventory_ratio'] = df['sku_cost_value'] / total_shop_cost if total_shop_cost > 0 else 0.0

        # 6. Expiration days (mocked near-expiration date for training)
        df['expiration_days_left'] = np.random.choice([20.0, 45.0, 90.0, 999.0], size=len(df), p=[0.1, 0.1, 0.2, 0.6])

        print(f"Generated features. Total features matrix shape: {df.shape}")
        return df

    def run_label_engineering(self, df):
        """
        Phase 5: Label Engineering.
        Labels target variables for stockouts (stock <= 7 days sales) or overstocks.
        """
        print("\n--- PHASE 5: Label Engineering ---")
        
        # Label: 1 if inventory coverage days is less than 7 days (Critical stockout hazard), else 0
        df['stockout_occurred'] = np.where(df['inventory_coverage_days'] <= 7.0, 1, 0)
        
        # Label: 1 if coverage exceeds 60 days (Capital frozen hazard), else 0
        df['overstock_occurred'] = np.where(df['inventory_coverage_days'] >= 60.0, 1, 0)

        print(f"Target label distributions (Stockout): {df['stockout_occurred'].value_counts(normalize=True).to_dict()}")
        return df

    def run_machine_learning(self, df):
        """
        Phase 6: Machine Learning Training.
        Trains a classification model using XGBoost or RandomForest.
        """
        print("\n--- PHASE 6: Model Training ---")
        
        features_list = [
            'inventory_coverage_days', 'sales_trend', 'delay_rate', 
            'expiration_days_left', 'inventory_ratio', 'sales_velocity'
        ]
        
        X = df[features_list].copy()
        y = df['stockout_occurred'].copy()

        # Handle missing values
        X = X.fillna(0.0)

        if not SKLEARN_AVAILABLE:
            print("Warning: scikit-learn is not installed. Saving mathematical proxy weights.")
            joblib.dump({"model_type": "proxy_linear"}, self.output_model_path)
            return

        # Train/Test Split
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
        
        if XGB_AVAILABLE:
            print("Training XGBoost Classifier...")
            model = xgb.XGBClassifier(
                n_estimators=100, 
                max_depth=4, 
                learning_rate=0.05, 
                random_state=42
            )
            model.fit(X_train, y_train)
            model_type = "xgb"
        else:
            print("XGBoost not available. Training RandomForest Classifier fallback...")
            model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
            model.fit(X_train, y_train)
            model_type = "random_forest"

        # Evaluate
        preds = model.predict(X_test)
        probs = model.predict_proba(X_test)[:, 1]
        print("\n[Evaluation Report]:")
        print(classification_report(y_test, preds))
        try:
            print(f"ROC AUC Score: {roc_auc_score(y_test, probs):.4f}")
        except Exception:
            pass

        # Save model
        pipeline_package = {
            "model_type": model_type,
            "features": features_list,
            "model": model,
            "trained_at": pd.Timestamp.now().isoformat()
        }
        joblib.dump(pipeline_package, self.output_model_path)
        print(f"Saved trained model to {self.output_model_path}")
        
        # Phase 7: SHAP Explainability
        self.run_explainability(model, X_train, features_list)

    def run_explainability(self, model, X_train, features_list):
        """
        Phase 7: Explainable AI (SHAP).
        Calculates and outputs global feature importance attributes.
        """
        print("\n--- PHASE 7: Explainable AI (SHAP) ---")
        if not SHAP_AVAILABLE:
            print("SHAP package not installed. Skipping direct tree explainer computation.")
            # Simple fallback feature importance calculation
            if hasattr(model, 'feature_importances_'):
                print("\n[Global Feature Importances (Model Internal)]:")
                for name, imp in zip(features_list, model.feature_importances_):
                    print(f" - {name}: {imp:.4f}")
            return

        print("Computing SHAP values on training subset...")
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_train.head(100))
        
        print("SHAP explainer built successfully. Sample SHAP shape:", shap_values.shape)
        # In a real environment, you can plot shap summary or log summaries.


if __name__ == "__main__":
    # Standard location check
    default_dir = "/home/nguyen-dai-tung/supplyforge-ai/test-data/Database - NCKH"
    if not os.path.exists(default_dir):
        print(f"Folder not found: {default_dir}. Creating mock data directory.")
        os.makedirs(default_dir, exist_ok=True)
        # Mock empty database structure
        with open(os.path.join(default_dir, "products.json"), "w") as f:
            json.dump([
                {"_id": f"p_{i}", "productName": f"Product {i}", "itemSku": f"SKU_{i}", "price": 100000, "cost": 60000, "stock": 20}
                for i in range(1, 20)
            ], f)

    pipeline = SupplyForgeTrainPipeline(default_dir)
    df_prod = pipeline.run_data_audit_and_profiling()
    df_master = pipeline.run_data_engineering()
    df_feat = pipeline.run_feature_engineering(df_master)
    df_labeled = pipeline.run_label_engineering(df_feat)
    pipeline.run_machine_learning(df_labeled)
