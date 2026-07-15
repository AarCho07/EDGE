import os
import io
import zipfile
import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ── CONFIGURATION ─────────────────────────────────────────────────────────────
# Pulling both June and July to capture the transition and baseline data
TARGET_MONTHS = ["20260601", "20260701"]  
DATA_TYPE = "pal" #Srt the code string for the specific NYISO. data type            
SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "NYISO - analyzed_data") #Create a path to save outputs inside the script's folder  

# Define the specific heatwave window
HEATWAVE_START = "2026-06-30"
HEATWAVE_END = "2026-07-05" # Up to midnight July 4th not July 5th, and NYISO had posted these dates as the heatwave window

# ── WEATHER INTEGRATION ───────────────────────────────────────────────────────
# Maps NYISO regions to approximate latitude/longitude for weather API queries
ZONE_COORDS = {
    "CAPITL": (42.65, -73.75), "CENTRL": (43.04, -76.14),
    "DUNWOD": (40.93, -73.89), "GENESE": (43.15, -77.61),
    "HUD VL": (41.70, -73.92), "LONGIL": (40.78, -73.13),
    "MHK VL": (43.10, -75.23), "MILLWD": (41.19, -73.79),
    "N.Y.C.": (40.71, -74.00), "NORTH": (44.69, -73.45),
    "WEST":   (42.88, -78.87)
}

def fetch_real_temperature(zone, start_date, end_date):
    """Fetches real historical hourly temperature data from Open-Meteo (No API Key needed)"""
    print(f"\nFetching real historical weather data for {zone}...")
    lat, lon = ZONE_COORDS.get(zone, (42.65, -73.75)) # Defaults to Albany if zone isn't in map
    url = f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={start_date}&end_date={end_date}&hourly=temperature_2m&temperature_unit=fahrenheit&timezone=America%2FNew_York"
    
    res = requests.get(url)
    if res.status_code != 200:
        raise RuntimeError("Failed to fetch weather data. Check your internet connection.")
        
    data = res.json()
    temp_df = pd.DataFrame({
        "Weather_Time": pd.to_datetime(data["hourly"]["time"]),
        "Real_Temperature_F": data["hourly"]["temperature_2m"]
    })
    return temp_df

# ── DATA DOWNLOAD FUNCTION ───────────────────────────────────────────────────
def download_multiple_months(months_list, data_type="pal"):

    #Downloads multiple monthly zip files, extracts the CSVs into memory, 
    #and combines them into one massive DataFrame. 
    
    csv_frames = [] #initialize an empty list to store dataframes for each month
    
    for date_str in months_list: #Loop through each date string provided in the list
        url = f"https://mis.nyiso.com/public/csv/{data_type}/{date_str}{data_type}_csv.zip" #construct the URL for the specific month and data type
        print(f"Requesting data for {date_str[:4]}-{date_str[4:6]}...")
        
        response = requests.get(url) 
        if response.status_code != 200: #check if download failed
            print(f"Warning: Could not fetch data for {date_str}. It may not be published yet.")
            continue #stops this loops and restarts it with the next month in the list
            
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:#open the dowloaded zip file in memory
            for name in zf.namelist():#loops through each file in the zip archive
                if name.endswith(".csv"): #only process CSV files
                    content = zf.read(name)
                    df_day = pd.read_csv(io.BytesIO(content)) #convert the CSV content into a DataFrame
                    csv_frames.append(df_day) 
                    
    if not csv_frames:
        raise RuntimeError("No data was downloaded. Check your connection or target dates.") #crash the program if no data was downloaded
        
    master_df = pd.concat(csv_frames, ignore_index=True) #Merge all the individual DataFrames into one large DataFrame
    return master_df


# ── MAIN EXECUTION TRACKER ────────────────────────────────────────────────────
if __name__ == "__main__": 
    try:
        print("Starting bulk download for historical comparison...")
        df = download_multiple_months(TARGET_MONTHS, DATA_TYPE)
        
        # Standardize column headers
        if "Time Stamp" in df.columns: #Checks if Time Stamp, or Timestamp exists in the DataFrame and sets the time_col variable accordingly
            time_col = "Time Stamp"
        elif "Timestamp" in df.columns:
            time_col = "Timestamp"
        else:
            time_col = df.columns[0]
            
        df[time_col] = pd.to_datetime(df[time_col]) #Convert the time column to datetime format for easier manipulation
        
        loc_col = "Name" #initalize 'Name' as the default location column, but will check for alternatives below
        if "Name" not in df.columns and "Zone Name" in df.columns:
            loc_col = "Zone Name"
            
        # Extract unique regions
        unique_locations = sorted(df[loc_col].dropna().unique()) #Extract a sorted list of unique, non-blank regional names 
        
        print("\n" + "="*50) 
        print(f"AVAILABLE REGIONS DETECTED ({len(unique_locations)} total):")
        print("="*50)
        for loc in unique_locations: #loop through and print each individual region for the user to see
            print(f"  * {loc}") #print the current region name as a bulleted list item
            
        
        print("\n" + "="*50)
        user_selection = input("Type or paste the exact regional zone you want to analyze: ").strip() #pauses the program, and prompts user for input, which is then stripped of whitespace and stored in the variable user_selection
        print("="*50 + "\n")
        
        if user_selection not in unique_locations: #check if the suer's typed input is missing from our list of unique locations, and if so, print an error message and exit the program
            print(f"Error: '{user_selection}' was not found.")
            print("Check spelling or copy-paste directly from the list above. Re-run the program to try again.")
            exit()
            
        # Filter rows for user selection and sort chronologically
        df_filtered = df[df[loc_col] == user_selection].sort_values(by=time_col).copy() 
                
        val_col = next(
            (c for c in ["Load", "Integrated Load", "Actual Load"] if c in df.columns),#locate the first matching standard power load column name from the list, and store it in val_col. If none are found, set val_col to None.
            None
        ) 
        if val_col is None: #If no standard load column names were found, we will attempt to find the most appropriate numeric column to use as a load metric.
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) == 0:
                raise RuntimeError("No numeric columns found to use as a load metric.") #It can't run the analysis without a numeric load column, so we will crash the program with an error message.
            val_col = df[numeric_cols].std().idxmax() #guess the most appropriate load column by selecting the numeric column with the highest standard deviation, which is likely to be the load metric.

        print(f"Using load column: {val_col}")

        # Define Heatwave vs Normal Masks
        hw_mask = (df_filtered[time_col] >= HEATWAVE_START) & (df_filtered[time_col] < HEATWAVE_END)
        df_heatwave = df_filtered[hw_mask]
        df_normal = df_filtered[~hw_mask]

        if df_heatwave.empty:
            raise RuntimeError("No rows found for the selected heatwave window.")
        if df_normal.empty:
            raise RuntimeError("No baseline rows found outside the heatwave window.")

        # Generate Real Temperature Data via Open-Meteo API
        start_dt = df_filtered[time_col].min().strftime('%Y-%m-%d')
        end_dt = df_filtered[time_col].max().strftime('%Y-%m-%d')
        temp_df = fetch_real_temperature(user_selection, start_dt, end_dt)

        # Merge the real temperatures with our 5-minute load data based on the nearest hour
        df_filtered = df_filtered.sort_values(by=time_col)
        temp_df = temp_df.sort_values(by="Weather_Time")
        df_filtered = pd.merge_asof(df_filtered, temp_df, left_on=time_col, right_on="Weather_Time", direction="nearest")

        # Rebuild the heatwave and normal subsets after temperature merge
        hw_mask = (df_filtered[time_col] >= HEATWAVE_START) & (df_filtered[time_col] < HEATWAVE_END)
        df_heatwave = df_filtered.loc[hw_mask].copy()
        df_normal = df_filtered.loc[~hw_mask].copy()

        # Calculate Comparative Statistics
        hw_mean = df_heatwave[val_col].mean()
        hw_var = df_heatwave[val_col].var()
        hw_std = df_heatwave[val_col].std()
        hw_max = df_heatwave[val_col].max()

        norm_mean = df_normal[val_col].mean()
        norm_var = df_normal[val_col].var()
        norm_std = df_normal[val_col].std()
        norm_max = df_normal[val_col].max()

        norm_temp_mean = df_normal["Real_Temperature_F"].mean()
        hw_temp_mean = df_heatwave["Real_Temperature_F"].mean()

        # Calculate percentage increases
        percent_increase = float("inf") if norm_mean == 0 else ((hw_mean - norm_mean) / norm_mean) * 100
        max_percent_increase = float("inf") if norm_max == 0 else ((hw_max - norm_max) / norm_max) * 100
        temp_percent_increase = float("inf") if norm_temp_mean == 0 else ((hw_temp_mean - norm_temp_mean) / norm_temp_mean) * 100
        
        # Print Statistical Report
        print("="*60)
        print(f"STATISTICAL COMPARISON REPORT: {user_selection}")
        print(f"Comparing Heatwave ({HEATWAVE_START} to {HEATWAVE_END}) vs Baseline")
        print("="*60)
        print("NORMAL CONDITIONS (Baseline):")
        print(f"  Average Temperature: {norm_temp_mean:.2f} °F")
        print(f"  Average Load: {norm_mean:.2f} MW")
        print(f"  Max Load: {norm_max:.2f} MW")
        print(f"  Variance: {norm_var:.2f} MW^2")        
        print("-" * 60)
        print("HEATWAVE CONDITIONS:")
        print(f"  Average Temperature: {hw_temp_mean:.2f} °F")
        print(f"  Average Load: {hw_mean:.2f} MW")
        print(f"  Max Load: {hw_max:.2f} MW")
        print(f"  Variance: {hw_var:.2f} MW^2")
        print("-" * 60)
        print(f"The heatwave caused a {temp_percent_increase:.2f}% average temperature increase.")
        print("-" * 60)
        print(f"IMPACT: The heatwave caused a {percent_increase:.2f}% average load increase.")
        print(f"IMPACT: The heatwave caused a {max_percent_increase:.2f}% max load increase.")
        

        print("="*60)

        # Save Data locally
        os.makedirs(SAVE_DIR, exist_ok=True)
        clean_name = user_selection.replace(".", "_").replace(" ", "_")
        csv_filename = f"{clean_name}_Heatwave_Analysis_2026.csv"
        full_csv_path = os.path.join(SAVE_DIR, csv_filename)
        df_filtered.to_csv(full_csv_path, index=False)
        print(f"\nSaved raw analytical data to: {full_csv_path}")

        # Visualization
        fig, ax1 = plt.subplots(figsize=(14, 7))

        # Plot Load
        color1 = 'tab:blue'
        ax1.set_xlabel('Date')
        ax1.set_ylabel(f'Electricity Load ({val_col} in MW)', color=color1, fontweight='bold')
        ax1.plot(df_filtered[time_col], df_filtered[val_col], color=color1, alpha=0.8, linewidth=1.5, label='Grid Load (MW)')
        ax1.tick_params(axis='y', labelcolor=color1)
        
        # Shade the Heatwave Region
        ax1.axvspan(pd.to_datetime(HEATWAVE_START), pd.to_datetime(HEATWAVE_END), color='red', alpha=0.15, label='Heatwave Duration')

        # Plot Temperature on secondary Y axis
        ax2 = ax1.twinx()  
        color2 = 'tab:orange'
        ax2.set_ylabel('Real Ambient Temperature (°F)', color=color2, fontweight='bold')
        ax2.plot(df_filtered[time_col], df_filtered['Real_Temperature_F'], color=color2, alpha=0.6, linewidth=1.5, label='Temperature (°F)')
        ax2.tick_params(axis='y', labelcolor=color2)
        
        

        # Formatting the x-axis to look clean
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
        plt.title(f'Power Grid Stress Analysis: 2026 Summer Heatwave\nRegion: {user_selection}', fontsize=15, fontweight='bold')
        fig.tight_layout()
        
        # Legend configuration
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', framealpha=0.9)

        # Save and show plot
        plot_filename = f"{clean_name}_heatwave_visual_2026.png"
        full_plot_path = os.path.join(SAVE_DIR, plot_filename)
        plt.savefig(full_plot_path, dpi=300, bbox_inches='tight')
        print(f"Saved visualization to: {full_plot_path}")
        
        plt.show()

    except Exception as e:
        print(f"\nPipeline Error: {e}")