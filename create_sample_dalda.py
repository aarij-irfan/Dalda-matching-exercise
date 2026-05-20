"""Create a small sample Dalda file from census for testing the matcher."""

import os

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
census_path = os.path.join(BASE, "Census Database", "Dalda Census Data Base V2.csv")
out_path = os.path.join(BASE, "sample_dalda_outlets.xlsx")

df = pd.read_csv(census_path, nrows=20)
sample = pd.DataFrame(
    {
        "Shop_ID": range(10001, 10001 + len(df)),
        "Outlet_Name": df["Name of Outlet"],
        "Full_Address": df["Complete Address Field"],
        "Channel": df["Type of Outlet"],
        "GPS": df["GPS Coordinates"],
    }
)
sample.to_excel(out_path, index=False)
print(f"Wrote {len(sample)} rows to {out_path}")
