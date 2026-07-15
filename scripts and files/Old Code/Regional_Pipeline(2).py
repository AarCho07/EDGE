import os
import io
import zipfile
import requests
import pandas as pd
import numpy as np

# ── CONFIGURATION ─────────────────────────────────────────────────────────────
TARGET_DATE_STR = "20240701"  # Needs to be the 1st day of the month
DATA_TYPE = "pal"             # 'pal' tracks real-time electricity demand/load
SAVE_DIR = "analyzed_data"    # The new folder that will be created on your Mac

def download_monthly_load(date_str, data_type="pal"):
    """
    Downloads a single monthly zip file from NYISO for actual load data,
    extracts the CSVs directly into memory, and returns a unified DataFrame.
    """
    url = f"https://mis.nyiso.com/public/csv/{data_type}/{date_str}{data_type}_csv.zip"
    print(f"Starting bulk download for {date_str[:4]}-{date_str[4:6]}...")
    print(f"Requesting link: {url}")
    
    response = requests.get(url)
    if response.status_code != 200:
        raise RuntimeError(f"Download failed with status code {response.status_code}. Verify your date format.")
        
    csv_frames = []
    
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        for name in zf.namelist():
            if name.endswith(".csv"):
                content = zf.read(name)
                df_day = pd.read_csv(io.BytesIO(content))
                csv_frames.append(df_day)
                
    master_df = pd.concat(csv_frames, ignore_index=True)
    return master_df

# ── MAIN EXECUTION TRACKER ────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        # Step 1: Download data into memory
        df = download_monthly_load(TARGET_DATE_STR, DATA_TYPE)
        
        # Standardize column header types
        if "Time Stamp" in df.columns:
            df["Time Stamp"] = pd.to_datetime(df["Time Stamp"])
            time_col = "Time Stamp"
        elif "Timestamp" in df.columns:
            df["Timestamp"] = pd.to_datetime(df["Timestamp"])
            time_col = "Timestamp"
        else:
            time_col = df.columns[0]
            df[time_col] = pd.to_datetime(df[time_col])
        
        loc_col = "Name"
        if "Name" not in df.columns and "Zone Name" in df.columns:
            loc_col = "Zone Name"
            
        # Step 2: Get choices
        unique_locations = sorted(df[loc_col].dropna().unique())
        
        print("\n" + "="*50)
        print(f"AVAILABLE REGIONS DETECTED IN THIS DATASET ({len(unique_locations)} total):")
        print("="*50)
        for loc in unique_locations:
            print(f"  * {loc}")
            
        # Step 3: Prompt user via terminal
        print("\n" + "="*50)
        user_selection = input("Type or paste the exact regional zone you want to analyze: ").strip()
        print("="*50 + "\n")
        
        if user_selection not in unique_locations:
            print(f"Error: '{user_selection}' was not found.")
            exit()
            
        # Step 4: Filter rows for user selection only
        df_filtered = df[df[loc_col] == user_selection].sort_values(by=time_col)
        
        # Step 5: Save just this filtered location data onto your Mac
        os.makedirs(SAVE_DIR, exist_ok=True)
        
        # Clean up the location name so it doesn't contain bad characters like dots or spaces for the filename
        clean_name = user_selection.replace(".", "_").replace(" ", "_")
        year_month = f"{TARGET_DATE_STR[:4]}_{TARGET_DATE_STR[4:6]}"
        filename = f"{clean_name}_{DATA_TYPE}_{year_month}.csv"
        full_save_path = os.path.join(SAVE_DIR, filename)
        
        # Export to CSV
        df_filtered.to_csv(full_save_path, index=False)
        print(f"Saved filtered data to your Mac: {full_save_path}")
        
        # Step 6: Process 3-Sigma statistics for the report output
        val_col = "Integrated Load" if "Integrated Load" in df.columns else "Actual Load" if "Actual Load" in df.columns else df.select_dtypes(include=[np.number]).columns[0]
        mean_val = df_filtered[val_col].mean()
        std_val = df_filtered[val_col].std()
        upper_3s = mean_val + (3 * std_val)
        lower_3s = mean_val - (3 * std_val)
        anomalies = df_filtered[(df_filtered[val_col] > upper_3s) | (df_filtered[val_col] < lower_3s)]
        
        # Step 7: Print report
        print("="*60)
        print(f"STATISTICAL ANALYSIS REPORT FOR REGION: {user_selection}")
        print("="*60)
        print(f"Timespan Covered:  {df_filtered[time_col].min()} to {df_filtered[time_col].max()}")
        print(f"Data Point Rows:  {len(df_filtered)} records parsed for this zone")
        print(f"Average Demand:   {mean_val:.2f} MW")
        print(f"Standard Dev (σ): {std_val:.2f} MW")
        print(f"Upper 3-σ Limit:  {upper_3s:.2f} MW")
        print(f"Lower 3-σ Limit:  {lower_3s:.2f} MW")
        print("-"*60)
        print(f"HEATWAVE DEMAND ANOMALIES DETECTED: {len(anomalies)} events")
        print("-"*60)
        
        if not anomalies.empty:
            print(anomalies[[time_col, val_col]].head(20).to_string(index=False))
        else:
            print("No extreme load anomalies detected for this specific region.")
        print("="*60)
        
    except Exception as e:
        print(f"\nPipeline Error: {e}")