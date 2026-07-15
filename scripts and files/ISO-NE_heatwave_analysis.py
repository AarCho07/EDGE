import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import gridstatus

# ── CONFIGURATION ─────────────────────────────────────────────────────────────
# We define our data window to capture the baseline and the event
START_DATE = "2026-06-01"
END_DATE = "2026-07-10"
SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analyzed_data(ISO-NE_Heatwave_2026)")    

# Define the specific 2026 heatwave window
HEATWAVE_START = "2026-06-30"
HEATWAVE_END = "2026-07-05" 

def download_isone_history(start, end):
    """
    Uses the GridStatus library to securely ping ISO-NE's database for 
    historical bulk data, avoiding the need to unpack zip files.
    """
    print(f"Connecting to ISO-NE servers to fetch records from {start} to {end}...")
    iso = gridstatus.ISONE()
    
    # This automatically handles the API requests and returns a clean DataFrame
    df = iso.get_load(start=start, end=end)
    return df

# ── MAIN EXECUTION TRACKER ────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        # Step 1: Download the historical chunk
        df = download_isone_history(START_DATE, END_DATE)
        
        # Gridstatus standardizes the time column to 'Time' and load to 'Load'
        time_col = "Time"
        val_col = "Load"
        
        # Convert timezone-aware datetimes so our heatwave mask works properly
        df[time_col] = pd.to_datetime(df[time_col], utc=True).dt.tz_convert('US/Eastern').dt.tz_localize(None)
        
        # Since ISO-NE system load via gridstatus usually pulls the total grid, 
        # we will set the location dynamically. 
        loc_col = "Location"
        if "Location" not in df.columns:
            df["Location"] = "ISO-NE System Total"
            
        unique_locations = sorted(df[loc_col].dropna().unique())
        
        print("\n" + "="*50)
        print(f"AVAILABLE REGIONS DETECTED ({len(unique_locations)} total):")
        print("="*50)
        for loc in unique_locations:
            print(f"  * {loc}")
            
        # Step 2: Prompt user
        print("\n" + "="*50)
        user_selection = input("Type or paste the exact regional zone you want to analyze: ").strip()
        print("="*50 + "\n")
        
        if user_selection not in unique_locations:
            print(f"Error: '{user_selection}' was not found. Check spelling.")
            exit()
            
        # Filter for user selection and sort chronologically
        df_filtered = df[df[loc_col] == user_selection].sort_values(by=time_col).copy()
        
        # Step 3: Define Heatwave vs Normal Masks
        hw_mask = (df_filtered[time_col] >= HEATWAVE_START) & (df_filtered[time_col] < HEATWAVE_END)
        df_heatwave = df_filtered[hw_mask]
        df_normal = df_filtered[~hw_mask]
        
        # Step 4: Calculate Comparative Statistics
        hw_mean = df_heatwave[val_col].mean()
        hw_var = df_heatwave[val_col].var()
        
        norm_mean = df_normal[val_col].mean()
        norm_var = df_normal[val_col].var()
        
        percent_increase = ((hw_mean - norm_mean) / norm_mean) * 100
        
        # Print Statistical Report
        print("="*60)
        print(f"STATISTICAL COMPARISON REPORT: {user_selection}")
        print(f"Comparing Heatwave ({HEATWAVE_START} to {HEATWAVE_END}) vs Baseline")
        print("="*60)
        print("NORMAL CONDITIONS (Baseline):")
        print(f"  Average Load: {norm_mean:.2f} MW")
        print(f"  Variance:     {norm_var:.2f} MW^2")
        print("-" * 60)
        print("HEATWAVE CONDITIONS:")
        print(f"  Average Load: {hw_mean:.2f} MW")
        print(f"  Variance:     {hw_var:.2f} MW^2")
        print("-" * 60)
        print(f"IMPACT: The heatwave caused a {percent_increase:.2f}% average load increase.")
        print("="*60)
        
        # Step 5: Generate Estimated Temperature Curve
        normalized_load = (df_filtered[val_col] - df_filtered[val_col].min()) / (df_filtered[val_col].max() - df_filtered[val_col].min())
        hour_of_day = df_filtered[time_col].dt.hour
        diurnal_cycle = np.sin((hour_of_day - 6) * np.pi / 12)
        
        # Boost estimated temperature slightly during the masked heatwave dates
        heatwave_boost = np.where(hw_mask, 12, 0) 
        df_filtered["Estimated_Temperature_F"] = 70 + (12 * normalized_load) + (8 * diurnal_cycle) + heatwave_boost

        # Step 6: Save Data locally
        os.makedirs(SAVE_DIR, exist_ok=True)
        clean_name = user_selection.replace(".", "_").replace(" ", "_")
        csv_filename = f"{clean_name}_ISONE_Heatwave_Analysis_2026.csv"
        full_csv_path = os.path.join(SAVE_DIR, csv_filename)
        df_filtered.to_csv(full_csv_path, index=False)
        print(f"\nSaved raw analytical data to: {full_csv_path}")

        # Step 7: Visualization
        fig, ax1 = plt.subplots(figsize=(14, 7))

        # Plot Load
        color1 = 'tab:blue'
        ax1.set_xlabel('Date (June - July 2026)')
        ax1.set_ylabel(f'Electricity Load (MW)', color=color1, fontweight='bold')
        ax1.plot(df_filtered[time_col], df_filtered[val_col], color=color1, alpha=0.8, linewidth=1.5, label='Grid Load (MW)')
        ax1.tick_params(axis='y', labelcolor=color1)
        
        # Shade the Heatwave Region visually
        ax1.axvspan(pd.to_datetime(HEATWAVE_START), pd.to_datetime(HEATWAVE_END), color='red', alpha=0.15, label='Heatwave Duration')

        # Plot Temperature on secondary Y axis
        ax2 = ax1.twinx()  
        color2 = 'tab:orange'
        ax2.set_ylabel('Estimated Ambient Temperature (°F)', color=color2, fontweight='bold')
        ax2.plot(df_filtered[time_col], df_filtered['Estimated_Temperature_F'], color=color2, alpha=0.6, linewidth=1.5, label='Temperature (°F)')
        ax2.tick_params(axis='y', labelcolor=color2)

        # Formatting the x-axis to look clean
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
        plt.title(f'ISO-NE Power Grid Stress Analysis: 2026 Summer Heatwave\nRegion: {user_selection}', fontsize=15, fontweight='bold')
        fig.tight_layout()
        
        # Legend configuration
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', framealpha=0.9)

        # Save and show plot
        plot_filename = f"{clean_name}_ISONE_heatwave_visual_2026.png"
        full_plot_path = os.path.join(SAVE_DIR, plot_filename)
        plt.savefig(full_plot_path, dpi=300, bbox_inches='tight')
        print(f"Saved visualization to: {full_plot_path}")
        
        plt.show()

    except Exception as e:
        print(f"\nPipeline Error: {e}")