import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, datetime
import calendar
import base64
import io
from matplotlib import pyplot as plt
import seaborn as sns
from st_aggrid import AgGrid, GridOptionsBuilder
import math
from dateutil.relativedelta import relativedelta

# Initialize page config
st.set_page_config(page_title="Retirement Corpus Calculator", layout="wide")

# CSS to improve table display
st.markdown("""
<style>
    .dataframe {
        font-size: 12px !important;
    }
    .stDownloadButton button {
        background-color: #4CAF50;
        color: white;
        padding: 10px 24px;
        border-radius: 8px;
        font-weight: bold;
    }
    .summary-box {
        background-color: #DAF7A6;
        padding: 20px;
        border-radius: 10px;
        margin-bottom: 20px;
    }
    .header-text {
        color: #1E88E5;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# Main title and description
st.title("PF Retirement Corpus Value Calculator")
st.markdown("""
This application calculates your projected PF corpus at retirement based on:
- Your current age and retirement age (60 years)
- Current PF pay, contribution rates, and corpus balance
- Annual increments and DA increases
- Pay commission revisions in 2030 and 2040
""")

def round_up_to_10(value):
    return math.ceil(value / 10) * 10

def calculate_age_and_retirement_date(dob):
    today = date.today()
    retirement_age = 60
    retirement_date = date(dob.year + retirement_age, dob.month, dob.day)
    
    if retirement_date < today:
        return None, None
    
    current_age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return current_age, retirement_date

# Initialize session state
if 'calculated' not in st.session_state:
    st.session_state.calculated = False
if 'projection_df' not in st.session_state:
    st.session_state.projection_df = None

# Input form
with st.form("input_form"):
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Personal Information")
        dob = st.date_input("Date of Birth", value=date(1980, 1, 1), 
                          min_value=date(1950, 1, 1), max_value=date.today().replace(year=date.today().year-18))
        
        st.subheader("Current Salary Details")
        current_basic = st.number_input("Current Basic Pay (₹)", value=80000, min_value=1000, step=1000)
        current_da = st.number_input("Current DA (₹)", value=30000, min_value=0, step=1000)
        
        st.subheader("Current PF Corpus")
        current_own_pf = st.number_input("Current PF Corpus (Own Side) (₹)", value=2148242, min_value=0, step=10000)
        current_company_pf = st.number_input("Current PF Corpus (Company Side) (₹)", value=1637688, min_value=0, step=10000)
        current_epfo_balance = st.number_input("Current EPFO Demand Amt (₹)", value=0, min_value=0, step=10000)
        st.subheader("EPFO Higher Pension Calculation")
        highest_pf_pay_aug2014 = st.number_input("Highest PF Pay till August 2014 (₹)", 
                                           value=0, min_value=0, step=1000)
        date_of_joining = st.date_input("Date of Joining", 
                                  value=date(2000, 1, 1), 
                                  min_value=date(1950, 1, 1), 
                                  max_value=date(2014, 8, 31))
    with col2:
        st.subheader("Increment Details")
        increment_month = st.selectbox("Annual Increment Month", options=list(range(1, 13)), 
                                     format_func=lambda x: calendar.month_name[x], index=6)
        
        st.subheader("Contribution & Interest Rates")
        own_pf_percent = st.number_input("Own PF Contribution (%)", value=12.0, min_value=1.0, max_value=100.0, step=0.1)
        company_pf_percent = st.number_input("Company PF Contribution (%)", value=12.0, min_value=1.0, max_value=100.0, step=0.1)
        pf_interest_rate = st.number_input("Annual PF Interest Rate (%)", value=8.25, min_value=1.0, max_value=20.0, step=0.25)
        
        st.subheader("Pay commission Multiplying Factor")
        pc_2030_factor = st.number_input("2030 Pay Commission Factor", value=1.86)
        pc_2040_factor = st.number_input("2040 Pay Commission Factor", value=1.4)
        st.subheader("Promotion Details")
    
        # Calculate maximum possible promotion year (retirement year - 1)
        retirement_year = dob.year + 60
        max_promo_year = retirement_year - 1
        
        num_promotions = st.number_input("Number of expected promotions before retirement", 
                                    min_value=0, max_value=10, value=2)
        
        promotion_details = []
        for i in range(num_promotions):
            with st.expander(f"Promotion {i+1} Details"):
                # Default year spreads promotions evenly between current year and retirement
                default_year = date.today().year + int((retirement_year - date.today().year) * (i+1)/(num_promotions+1))
                
                promo_year = st.number_input(
                    f"Year of Promotion {i+1}", 
                    min_value=date.today().year, 
                    max_value=max_promo_year,
                    value=min(default_year, max_promo_year)
                )
                
                promo_month = st.selectbox(
                    f"Month of Promotion {i+1}", 
                    options=list(range(1,13)),
                    format_func=lambda x: calendar.month_name[x]
                )
                
                promo_hike = st.number_input(
                    f"Basic Pay Hike (%) for Promotion {i+1}", 
                    min_value=5.0, 
                    max_value=30.0, 
                    value=10.0, 
                    step=0.5
                )
                
                promotion_details.append({
                    'year': promo_year,
                    'month': promo_month,
                    'hike_percent': promo_hike/100 + 1  # Convert to multiplication factor
                })

                
        
        

    calculate_button = st.form_submit_button("Calculate Retirement Corpus")
def create_monthly_projection(dob, current_basic, current_da, current_own_pf, current_company_pf,
                            increment_month, own_pf_percent, company_pf_percent, pf_interest_rate,
                            pc_2030_factor, pc_2040_factor, current_epfo_balance,promotion_details=[]):
    """Calculate monthly PF projection with promotions, increments, and pay commissions"""
    
    # Calculate retirement date
    current_age, retirement_date = calculate_age_and_retirement_date(dob)
    if not retirement_date:
        st.error("Retirement date is in the past. Please check your date of birth.")
        return None

    # Start from the current month
    current_date = date.today().replace(day=1)
    end_date = retirement_date.replace(day=1)
    first_year = current_date.year

    # Initialize dataframe
    date_range = pd.date_range(start=current_date, end=end_date, freq='MS')
    df = pd.DataFrame(index=date_range)

    # Initialize columns
    df['Month_Year'] = df.index.strftime('%b-%Y')
    df['Basic'] = 0.0
    df['DA'] = 0.0
    df['PF_Pay'] = 0.0
    df['Own_Contribution'] = 0.0
    df['Company_Contribution'] = 0.0
    df['EPFO_Outflow_Contribution'] = 0.0
    df['Own_Opening_Balance'] = 0.0
    df['Own_Monthly_Interest'] = 0.0
    df['Own_Closing_Balance'] = 0.0
    df['Company_Opening_Balance'] = 0.0
    df['Company_Monthly_Interest'] = 0.0
    df['Company_Closing_Balance'] = 0.0
    df['EPFO_Opening_Balance'] = 0.0
    df['EPFO_Monthly_Interest'] = 0.0
    df['EPFO_Closing_Balance'] = 0.0
    df['Total_Corpus'] = 0.0
    df['Event'] = ""
    df['Financial_Year'] = df.index.strftime('%Y') + "-" + (df.index + pd.DateOffset(years=1)).strftime('%y')

    # Set initial values
    df.loc[df.index[0], 'Basic'] = current_basic
    df.loc[df.index[0], 'DA'] = current_da
    df.loc[df.index[0], 'Own_Opening_Balance'] = current_own_pf
    df.loc[df.index[0], 'Company_Opening_Balance'] = current_company_pf
    df.loc[df.index[0], 'PF_Pay'] = df.loc[df.index[0], 'Basic'] + df.loc[df.index[0], 'DA']
    df.loc[df.index[0], 'Own_Contribution'] = df.loc[df.index[0], 'PF_Pay'] * (own_pf_percent / 100)
    df.loc[df.index[0], 'Company_Contribution'] = df.loc[df.index[0], 'PF_Pay'] * (company_pf_percent / 100)
    df.loc[df.index[0], 'EPFO_Opening_Balance'] = current_epfo_balance
    # Calculate initial EPFO Outflow Contribution
    pf_pay = df.loc[df.index[0], 'PF_Pay']
    if pf_pay <= 15000:
        df.loc[df.index[0], 'EPFO_Outflow_Contribution'] = pf_pay * 0.0833  # 8.33% of PF Pay
        
    else:
        df.loc[df.index[0], 'EPFO_Outflow_Contribution'] = (pf_pay * 0.0833) + ((pf_pay - 15000) * 0.0116) - 1250
        

    monthly_interest_rate = pf_interest_rate / (12 * 100)
    current_da_percentage = current_da / current_basic if current_basic > 0 else 0
    
    for i in range(len(df)):
        month = df.index[i].month
        year = df.index[i].year
        
        # Carry forward balances from previous month (except first month)
        if i > 0:
            df.loc[df.index[i], 'Basic'] = df.loc[df.index[i-1], 'Basic']
            df.loc[df.index[i], 'DA'] = df.loc[df.index[i-1], 'DA']
            df.loc[df.index[i], 'Own_Opening_Balance'] = df.loc[df.index[i-1], 'Own_Closing_Balance']
            df.loc[df.index[i], 'Company_Opening_Balance'] = df.loc[df.index[i-1], 'Company_Closing_Balance']
            df.loc[df.index[i], 'EPFO_Opening_Balance'] = df.loc[df.index[i-1], 'EPFO_Closing_Balance']

        # Check for promotions
        promotion_applied = False
        for promo in promotion_details:
            if year == promo['year'] and month == promo['month']:
                old_basic = df.loc[df.index[i], 'Basic']
                df.loc[df.index[i], 'Basic'] = old_basic * promo['hike_percent']
                df.loc[df.index[i], 'DA'] = df.loc[df.index[i], 'Basic'] * current_da_percentage
                df.loc[df.index[i], 'Event'] = f"Promotion: Basic +{int((promo['hike_percent']-1)*100)}%"
                promotion_applied = True
                break

        # Apply annual increment
        if month == increment_month and not promotion_applied:
            df.loc[df.index[i], 'Event'] = f"{df.loc[df.index[i], 'Event']} Annual 3% Increment".strip()
            previous_basic = df.loc[df.index[i], 'Basic']
            df.loc[df.index[i], 'Basic'] = previous_basic * 1.03
            
            if year == first_year:
                df.loc[df.index[i], 'DA'] = df.loc[df.index[i], 'DA'] + (previous_basic * 0.04)
                current_da_percentage = df.loc[df.index[i], 'DA'] / df.loc[df.index[i], 'Basic']
            else:
                df.loc[df.index[i], 'DA'] = df.loc[df.index[i], 'Basic'] * current_da_percentage

        # Apply DA hikes in January
        if month == 1:
            if year < 2030:
                current_da_percentage += 0.04
                df.loc[df.index[i], 'DA'] = df.loc[df.index[i], 'Basic'] * current_da_percentage
                df.loc[df.index[i], 'Event'] = f"{df.loc[df.index[i], 'Event']} Annual DA Revision (4% of Basic)".strip()
            elif year == 2030:
                current_da_percentage = 0.0
                df.loc[df.index[i], 'DA'] = 0
                df.loc[df.index[i], 'Event'] = f"{df.loc[df.index[i], 'Event']} Pay Commission 2030, DA Reset".strip()
                df.loc[df.index[i], 'Basic'] = df.loc[df.index[i], 'Basic'] * pc_2030_factor * (1.03 ** 3)
            elif 2031 <= year <= 2039:
                current_da_percentage += 0.02
                df.loc[df.index[i], 'DA'] = df.loc[df.index[i], 'Basic'] * current_da_percentage
                df.loc[df.index[i], 'Event'] = f"{df.loc[df.index[i], 'Event']} Annual DA Revision (2% of Basic)".strip()
            elif year == 2040:
                current_da_percentage = 0.0
                df.loc[df.index[i], 'DA'] = 0
                df.loc[df.index[i], 'Event'] = f"{df.loc[df.index[i], 'Event']} Pay Commission 2040, DA Reset".strip()
                df.loc[df.index[i], 'Basic'] = df.loc[df.index[i], 'Basic'] * pc_2040_factor * (1.03 ** 3)
            elif year >= 2041:
                current_da_percentage += 0.01
                df.loc[df.index[i], 'DA'] = df.loc[df.index[i], 'Basic'] * current_da_percentage
                df.loc[df.index[i], 'Event'] = f"{df.loc[df.index[i], 'Event']} Annual DA Revision (1% of Basic)".strip()

        # Calculate PF Pay and contributions
        df.loc[df.index[i], 'PF_Pay'] = df.loc[df.index[i], 'Basic'] + df.loc[df.index[i], 'DA']
        df.loc[df.index[i], 'Own_Contribution'] = df.loc[df.index[i], 'PF_Pay'] * (own_pf_percent / 100)
        df.loc[df.index[i], 'Company_Contribution'] = df.loc[df.index[i], 'PF_Pay'] * (company_pf_percent / 100)
        
        # Calculate EPFO Outflow Contribution
        pf_pay = df.loc[df.index[i], 'PF_Pay']
        if pf_pay <= 15000:
            df.loc[df.index[i], 'EPFO_Outflow_Contribution'] = pf_pay * 0.0833
            
        else:
            df.loc[df.index[i], 'EPFO_Outflow_Contribution'] = (pf_pay * 0.0833) + ((pf_pay - 15000) * 0.0116) - 1250
            

        # Calculate interest (special handling for March)
        if month != 3:
            if i > 0:
                df.loc[df.index[i], 'Own_Monthly_Interest'] = df.loc[df.index[i-1], 'Own_Closing_Balance'] * monthly_interest_rate
                df.loc[df.index[i], 'Company_Monthly_Interest'] = df.loc[df.index[i-1], 'Company_Closing_Balance'] * monthly_interest_rate
                df.loc[df.index[i], 'EPFO_Monthly_Interest'] = df.loc[df.index[i-1], 'EPFO_Closing_Balance'] * monthly_interest_rate
        else:
            # March - calculate interest but don't add to current month's balance
            if i > 0:
                march_own_interest = df.loc[df.index[i-1], 'Own_Closing_Balance'] * monthly_interest_rate
                march_company_interest = df.loc[df.index[i-1], 'Company_Closing_Balance'] * monthly_interest_rate
                march_epfo_interest = df.loc[df.index[i-1], 'EPFO_Closing_Balance'] * monthly_interest_rate
                
                # Show zero interest for March
                df.loc[df.index[i], 'Own_Monthly_Interest'] = 0
                df.loc[df.index[i], 'Company_Monthly_Interest'] = 0
                df.loc[df.index[i], 'EPFO_Monthly_Interest'] = 0
                
                # Add March interest to April's opening balance
                if i+1 < len(df):  # If there is an April
                    df.loc[df.index[i+1], 'Own_Opening_Balance'] += march_own_interest
                    df.loc[df.index[i+1], 'Company_Opening_Balance'] += march_company_interest
                    df.loc[df.index[i+1], 'EPFO_Opening_Balance'] += march_epfo_interest
                    
                    # Mark that this includes March interest
                    if not df.loc[df.index[i+1], 'Event']:
                        df.loc[df.index[i+1], 'Event'] = "Previous FY Interest Credited"
                    else:
                        df.loc[df.index[i+1], 'Event'] = f"{df.loc[df.index[i+1], 'Event']}, Previous FY Interest Credited"

        # Calculate closing balances
        if i == 0:
            # First month calculation
            df.loc[df.index[i], 'Own_Closing_Balance'] = (df.loc[df.index[i], 'Own_Opening_Balance'] +
                                                        df.loc[df.index[i], 'Own_Contribution'] +
                                                        df.loc[df.index[i], 'Own_Monthly_Interest'])

            df.loc[df.index[i], 'Company_Closing_Balance'] = (df.loc[df.index[i], 'Company_Opening_Balance'] +
                                                            df.loc[df.index[i], 'Company_Contribution'] +
                                                            df.loc[df.index[i], 'Company_Monthly_Interest'])
            
            df.loc[df.index[i], 'EPFO_Closing_Balance'] = (df.loc[df.index[i], 'EPFO_Opening_Balance'] +
                                                         df.loc[df.index[i], 'EPFO_Outflow_Contribution'] +
                                                         df.loc[df.index[i], 'EPFO_Monthly_Interest'])
        else:
            # For April, the opening balance already includes March interest
            if month == 4:
                df.loc[df.index[i], 'Own_Closing_Balance'] = (df.loc[df.index[i], 'Own_Opening_Balance'] +
                                                            df.loc[df.index[i], 'Own_Contribution'])
                
                df.loc[df.index[i], 'Company_Closing_Balance'] = (df.loc[df.index[i], 'Company_Opening_Balance'] +
                                                                df.loc[df.index[i], 'Company_Contribution'])
                
                df.loc[df.index[i], 'EPFO_Closing_Balance'] = (df.loc[df.index[i], 'EPFO_Opening_Balance'] +
                                                             df.loc[df.index[i], 'EPFO_Outflow_Contribution'])
            else:
                # Normal month calculation
                df.loc[df.index[i], 'Own_Closing_Balance'] = (df.loc[df.index[i], 'Own_Opening_Balance'] +
                                                            df.loc[df.index[i], 'Own_Contribution'] +
                                                            df.loc[df.index[i], 'Own_Monthly_Interest'])
                
                df.loc[df.index[i], 'Company_Closing_Balance'] = (df.loc[df.index[i], 'Company_Opening_Balance'] +
                                                                df.loc[df.index[i], 'Company_Contribution'] +
                                                                df.loc[df.index[i], 'Company_Monthly_Interest'])
                
                df.loc[df.index[i], 'EPFO_Closing_Balance'] = (df.loc[df.index[i], 'EPFO_Opening_Balance'] +
                                                             df.loc[df.index[i], 'EPFO_Outflow_Contribution'] +
                                                             df.loc[df.index[i], 'EPFO_Monthly_Interest'])

        df.loc[df.index[i], 'Total_Corpus'] = df.loc[df.index[i], 'Own_Closing_Balance'] + df.loc[df.index[i], 'Company_Closing_Balance']
                                             

    # Round all values
    numeric_cols = ['Basic', 'DA', 'PF_Pay', 'Own_Contribution', 'Company_Contribution',
                   'EPFO_Outflow_Contribution', 'Own_Opening_Balance', 'Own_Monthly_Interest', 
                   'Own_Closing_Balance', 'Company_Opening_Balance', 'Company_Monthly_Interest', 
                   'Company_Closing_Balance', 'EPFO_Opening_Balance', 'EPFO_Monthly_Interest',
                   'EPFO_Closing_Balance', 'Total_Corpus']
    df[numeric_cols] = df[numeric_cols].round(2)

    return df



def create_downloadable_excel(df):
    """Generate a link to download the dataframe as an Excel file"""
    # Create a copy of the dataframe to avoid modifying the original
    export_df = df.copy()
    
    # Apply rounding to specific columns
    columns_to_round = ['Basic', 'DA', 'PF_Pay', 'Own_Contribution', 'Company_Contribution']
    for col in columns_to_round:
        if col in export_df.columns:
            export_df[col] = export_df[col].apply(round_up_to_10)
    
    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    export_df.to_excel(writer, sheet_name='PF_Projection', index=False)
    
    # Add formatting
    workbook = writer.book
    worksheet = writer.sheets['PF_Projection']
    
    # Add currency format
    money_fmt = workbook.add_format({'num_format': '₹#,##0'})  # Changed to 0 decimal places
    
    # Updated list of columns to include EPFO columns
    money_columns = [
        'Basic', 'DA', 'PF_Pay', 'Own_Contribution', 'Company_Contribution',
        'EPFO_Outflow_Contribution', 'Own_Opening_Balance', 'Own_Monthly_Interest', 
        'Own_Closing_Balance', 'Company_Opening_Balance', 'Company_Monthly_Interest', 
        'Company_Closing_Balance', 'EPFO_Opening_Balance', 'EPFO_Monthly_Interest',
        'EPFO_Closing_Balance', 'Total_Corpus'
    ]
    
    for col_num, col in enumerate(export_df.columns):
        if col in money_columns:
            worksheet.set_column(col_num, col_num, 18, money_fmt)
    
    writer.close()
    
    output.seek(0)
    excel_data = output.read()
    b64 = base64.b64encode(excel_data).decode()
    return f'<a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" download="PF_Projection.xlsx" class="download-button">Download Excel</a>'




def create_downloadable_pdf(df, dob, final_row):
    """Generate a PDF report of the retirement projection"""
    buffer = io.BytesIO()
    
    # Setup PDF with matplotlib - use constrained_layout to prevent overlap
    plt.figure(figsize=(11.7, 8.27), constrained_layout=True)  # A4 size
    
    # Title and header information
    plt.suptitle('PF Retirement Corpus Projection Report', fontsize=16, fontweight='bold')
    
    # Create gridspec for better layout control
    gs = plt.GridSpec(4, 3, figure=plt.gcf(), height_ratios=[0.5, 2, 2, 2])
    
    # Summary Information
    ax0 = plt.subplot(gs[0, :])
    ax0.axis('off')
    
    retirement_date = date(dob.year + 60, dob.month, dob.day)
    summary_text = (
        f"Date of Birth: {dob.strftime('%d-%m-%Y')}\n"
        f"Retirement Date: {retirement_date.strftime('%d-%m-%Y')}\n"
        f"Final Own PF Balance: ₹{final_row['Own_Closing_Balance']:,.2f}\n"
        f"Final Company PF Balance: ₹{final_row['Company_Closing_Balance']:,.2f}\n"
        f"Total Retirement Corpus: ₹{final_row['Total_Corpus']:,.2f}"
    )
    ax0.text(0.1, 0.5, summary_text, fontsize=10, va='center')
    
    # Plot corpus growth
    ax1 = plt.subplot(gs[1, :])
    yearly_data = df.resample('Y').last()
    yearly_data.plot(y=['Own_Closing_Balance', 'Company_Closing_Balance', 'Total_Corpus'], 
                    ax=ax1, style=['-', '-', '-'], 
                    color=['blue', 'green', 'red'])
    ax1.set_title('Yearly Corpus Growth', pad=20)
    ax1.set_ylabel('Amount (₹)')
    ax1.legend(['Own PF', 'Company PF', 'Total Corpus'])
    ax1.grid(True)
    
    # Format y-axis to show in lakhs/crores
    def format_amount(x, pos):
        if x >= 10000000:  # More than 1 crore
            return f'₹{x/10000000:.1f}Cr'
        elif x >= 100000:  # More than 1 lakh
            return f'₹{x/100000:.1f}L'
        else:
            return f'₹{x:.0f}'
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(format_amount))
    
    # Plot annual contribution and interest
    ax2 = plt.subplot(gs[2, 0])
    annual_contrib = df.resample('Y').sum()[['Own_Contribution', 'Company_Contribution']]
    annual_contrib.plot(kind='bar', ax=ax2, width=0.8)
    ax2.set_title('Annual Contributions', pad=15)
    ax2.set_ylabel('Amount (₹)')
    ax2.set_xticklabels([x.year for x in annual_contrib.index], rotation=45)
    ax2.legend(['Own', 'Company'])
    
    ax3 = plt.subplot(gs[2, 1])
    annual_interest = df.resample('Y').sum()[['Own_Monthly_Interest', 'Company_Monthly_Interest']]
    annual_interest.plot(kind='bar', ax=ax3, width=0.8)
    ax3.set_title('Annual Interest Earned', pad=15)
    ax3.set_ylabel('Amount (₹)')
    ax3.set_xticklabels([x.year for x in annual_interest.index], rotation=45)
    ax3.legend(['Own', 'Company'])
    
    # Plot PF Pay growth
    ax4 = plt.subplot(gs[2, 2])
    yearly_data['PF_Pay'].plot(ax=ax4, marker='o', color='purple')
    ax4.set_title('PF Pay Growth', pad=15)
    ax4.set_ylabel('Amount (₹)')
    ax4.grid(True)
    
    # Key milestones table
    ax5 = plt.subplot(gs[3, :])
    ax5.axis('off')
    
    milestones = df[df['Event'].str.len() > 0].copy()
    if len(milestones) > 10:
        milestones = milestones.iloc[::len(milestones)//10 + 1]  # Sample key events
    
    milestone_text = 'Key Financial Milestones:\n\n'
    for idx, row in milestones.iterrows():
        milestone_text += f"• {row['Month_Year']}: {row['Event']} - PF Pay: ₹{row['PF_Pay']:,.2f}, Corpus: ₹{row['Total_Corpus']:,.2f}\n"
    
    ax5.text(0.05, 0.5, milestone_text, fontsize=9, va='center')
    
    # Add footer
    plt.figtext(0.5, 0.01, f"Report generated on {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}", 
               ha='center', fontsize=8)
    
    # Save figure to PDF
    plt.savefig(buffer, format='pdf', bbox_inches='tight')
    plt.close()
    
    buffer.seek(0)
    pdf_data = buffer.read()
    b64 = base64.b64encode(pdf_data).decode()
    return f'<a href="data:application/pdf;base64,{b64}" download="PF_Retirement_Report.pdf" class="download-button">Download PDF Report</a>'


def convert_to_excel(df):
    """Convert dataframe to Excel with rounding"""
    # Create a copy of the dataframe to avoid modifying the original
    export_df = df.copy()
    
    # Make sure all EPFO columns are included
    # If the display columns didn't include EPFO columns, we need to add them back from the original dataframe
    epfo_columns = ['EPFO_Outflow_Contribution', 'EPFO_Opening_Balance', 'EPFO_Monthly_Interest', 'EPFO_Closing_Balance']
    for col in epfo_columns:
        if col not in export_df.columns and col in projection_df.columns:
            export_df[col] = projection_df[col]
    
    # Apply rounding to specific columns
    columns_to_round = ['Basic', 'DA', 'PF_Pay', 'Own_Contribution', 'Company_Contribution', 'EPFO_Outflow_Contribution']
    for col in columns_to_round:
        if col in export_df.columns:
            export_df[col] = export_df[col].apply(round_up_to_10)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        export_df.to_excel(writer, index=False, sheet_name='PF_Projection')
        
        # Add formatting
        workbook = writer.book
        worksheet = writer.sheets['PF_Projection']
        
        # Add currency format
        money_fmt = workbook.add_format({'num_format': '₹#,##0'})  # Changed to 0 decimal places
        
        # Include EPFO columns in the formatting
        money_columns = [
            'Basic', 'DA', 'PF_Pay', 'Own_Contribution', 'Company_Contribution',
            'EPFO_Outflow_Contribution', 'Own_Opening_Balance', 'Own_Monthly_Interest', 
            'Own_Closing_Balance', 'Company_Opening_Balance', 'Company_Monthly_Interest', 
            'Company_Closing_Balance', 'EPFO_Opening_Balance', 'EPFO_Monthly_Interest',
            'EPFO_Closing_Balance', 'Total_Corpus'
        ]
        
        for col_num, col in enumerate(export_df.columns):
            if col in money_columns:
                worksheet.set_column(col_num, col_num, 18, money_fmt)
                    
    return output.getvalue()
def display_monthly_ledger(projection_df):
    """Display monthly PF ledger with filtering options"""
    st.subheader("Month-wise PF Ledger")
    
    # Add critical CSS fixes (works for both local and cloud)
    st.markdown("""
    <style>
        [data-testid="stDataFrame-container"] {
            width: 100% !important;
        }
        [data-testid="stDataFrame"] {
            background-color: white;
            z-index: 1;
        }
        table {
            visibility: visible !important;
            position: relative !important;
        }
        .stDataFrame > div {
            max-height: 600px;
            overflow: auto;
        }
    </style>
    """, unsafe_allow_html=True)
    
    # Add filters
    col1, col2, col3 = st.columns(3)
    
    with col1:
        selected_year = st.selectbox("Filter by Financial Year", 
                                  ["All Years"] + sorted(projection_df['Financial_Year'].unique()))
    
    with col2:
        event_filter = st.checkbox("Show only months with events", value=False)
    
    with col3:
        min_year = projection_df.index.min().year
        max_year = projection_df.index.max().year
        year_range = st.slider("Year Range", min_year, max_year, (min_year, max_year))
    
    # Apply filters
    filtered_df = projection_df.copy()
    if selected_year != "All Years":
        filtered_df = filtered_df[filtered_df['Financial_Year'] == selected_year]
    if event_filter:
        filtered_df = filtered_df[filtered_df['Event'].str.len() > 0]
    filtered_df = filtered_df[(filtered_df.index.year >= year_range[0]) & 
                            (filtered_df.index.year <= year_range[1])]
    
    # Display columns - keep only what's needed for display
    display_cols = ['Month_Year', 'Basic', 'DA', 'PF_Pay', 'Own_Contribution',
                  'Company_Contribution', 'Own_Opening_Balance', 'Own_Monthly_Interest',
                  'Own_Closing_Balance', 'Company_Opening_Balance', 'Company_Monthly_Interest',
                  'Company_Closing_Balance', 'Total_Corpus', 'Event']
    
    if not filtered_df.empty:
        # Create a container to force rendering
        table_container = st.container()
        
        with table_container:
            # Method 1: Try basic dataframe with formatting
            try:
                st.dataframe(
                    filtered_df[display_cols].style.format({
                        'Basic': '₹{:,.2f}',
                        'DA': '₹{:,.2f}',
                        'PF_Pay': '₹{:,.2f}',
                        'Own_Contribution': '₹{:,.2f}',
                        'Company_Contribution': '₹{:,.2f}',
                        'Own_Opening_Balance': '₹{:,.2f}',
                        'Own_Monthly_Interest': '₹{:,.2f}',
                        'Own_Closing_Balance': '₹{:,.2f}',
                        'Company_Opening_Balance': '₹{:,.2f}',
                        'Company_Monthly_Interest': '₹{:,.2f}',
                        'Company_Closing_Balance': '₹{:,.2f}',
                        'Total_Corpus': '₹{:,.2f}'
                    }),
                    height=min(600, 35 + 35 * len(filtered_df)),
                    width=1200,
                    use_container_width=True
                )
            except Exception as e:
                # Method 2: Fallback to unstyled dataframe
                try:
                    st.dataframe(
                        filtered_df[display_cols],
                        height=min(600, 35 + 35 * len(filtered_df)),
                        width=1200
                    )
                except:
                    # Method 3: Ultimate fallback - HTML table
                    st.markdown(
                        filtered_df[display_cols].to_html(escape=False, float_format=lambda x: f'₹{x:,.2f}'),
                        unsafe_allow_html=True
                    )
        
        # Download button with EPFO columns
        @st.cache_data
        def get_excel_data(df):
            # Create a copy that includes all columns from the original projection_df
            # This ensures EPFO columns are included in the Excel file
            full_df = projection_df.copy()
            
            # Filter to match the current view
            if selected_year != "All Years":
                full_df = full_df[full_df['Financial_Year'] == selected_year]
            if event_filter:
                full_df = full_df[full_df['Event'].str.len() > 0]
            full_df = full_df[(full_df.index.year >= year_range[0]) & 
                              (full_df.index.year <= year_range[1])]
            
            # Make sure all columns are included for Excel
            all_cols = display_cols + ['EPFO_Outflow_Contribution', 'EPFO_Opening_Balance', 
                                      'EPFO_Monthly_Interest', 'EPFO_Closing_Balance']
            # Remove duplicates while preserving order
            all_cols = list(dict.fromkeys(all_cols))
            
            # Filter columns that exist in the dataframe
            excel_cols = [col for col in all_cols if col in full_df.columns]
            
            return convert_to_excel(full_df[excel_cols])
        
        st.download_button(
            label="📥 Download Excel",
            data=get_excel_data(filtered_df),
            file_name="PF_Projection.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.warning("No data matches your filter criteria.")

def create_downloadable_excel(df):
    """Generate a link to download the dataframe as an Excel file"""
    # Create a copy of the dataframe to avoid modifying the original
    export_df = df.copy()
    
    # Make sure all EPFO columns are included
    epfo_columns = ['EPFO_Outflow_Contribution', 'EPFO_Opening_Balance', 'EPFO_Monthly_Interest', 'EPFO_Closing_Balance']
    for col in epfo_columns:
        if col not in export_df.columns and col in df.columns:
            export_df[col] = df[col]
    
    # Apply rounding to specific columns
    columns_to_round = ['Basic', 'DA', 'PF_Pay', 'Own_Contribution', 'Company_Contribution', 'EPFO_Outflow_Contribution']
    for col in columns_to_round:
        if col in export_df.columns:
            export_df[col] = export_df[col].apply(round_up_to_10)
    
    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    export_df.to_excel(writer, sheet_name='PF_Projection', index=False)
    
    # Add formatting
    workbook = writer.book
    worksheet = writer.sheets['PF_Projection']
    
    # Add currency format
    money_fmt = workbook.add_format({'num_format': '₹#,##0'})  # Changed to 0 decimal places
    
    # Updated list of columns to include EPFO columns
    money_columns = [
        'Basic', 'DA', 'PF_Pay', 'Own_Contribution', 'Company_Contribution',
        'EPFO_Outflow_Contribution', 'Own_Opening_Balance', 'Own_Monthly_Interest', 
        'Own_Closing_Balance', 'Company_Opening_Balance', 'Company_Monthly_Interest', 
        'Company_Closing_Balance', 'EPFO_Opening_Balance', 'EPFO_Monthly_Interest',
        'EPFO_Closing_Balance', 'Total_Corpus'
    ]
    
    for col_num, col in enumerate(export_df.columns):
        if col in money_columns:
            worksheet.set_column(col_num, col_num, 18, money_fmt)
    
    writer.close()
    
    output.seek(0)
    excel_data = output.read()
    b64 = base64.b64encode(excel_data).decode()
    return f'<a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" download="PF_Projection.xlsx" class="download-button">Download Excel</a>'


def calculate_epfo_pension(dob, date_of_joining, highest_pf_pay_aug2014, projection_df):
    """
    Calculate EPFO higher pension based on the formula:
    [(Service Days + 2 bonus years if service >20yrs) × Highest PF Pay Till August 2014) + 
     (Days After August 2014 × Average monthly PF Pay of last 60 months till age 58)] 
     / (70 × 365)
    """
    # Calculate key dates
    age_58_date = dob + relativedelta(years=58)
    # Make sure we go to the end of the month for age 58
    age_58_date = age_58_date.replace(day=1) + relativedelta(months=1) - relativedelta(days=1)
    
    aug_2014_end = date(2014, 8, 31)
    sep_2014_start = date(2014, 9, 1)
    
    # --- Calculate Total Service Years (from joining to retirement at 58) ---
    total_service_days = (age_58_date - date_of_joining).days
    total_service_years = total_service_days / 365.25  # Accurate year count including leap years
    print(f"Total service years from joining to age 58: {total_service_years:.2f}")
    
    # Determine if bonus years are applicable (>20 years total service)
    bonus_days = 730 if total_service_years > 20 else 0
    is_bonus_applied = bonus_days > 0
    
    # --- First Component: Service Days (with bonus) × Highest PF Pay ---
    # Service days only till August 2014 for this component
    service_days_till_aug2014 = (aug_2014_end - date_of_joining).days
    print(f"Service days till Aug 2014: {service_days_till_aug2014}")
    
    # Add bonus days to service days for component 1 calculation
    adjusted_service_days = service_days_till_aug2014 + bonus_days
    print(f"Adjusted service days (with bonus): {adjusted_service_days}")
    
    component1 = adjusted_service_days * highest_pf_pay_aug2014
    
    # --- Second Component: Days After Aug 2014 × Last 60 Months Avg PF Pay ---
    # Get exact 60-month window (Age 53 to 58)
    last_60_months_start = age_58_date - relativedelta(months=60)
    last_60_months_df = projection_df[
        (projection_df.index >= pd.to_datetime(last_60_months_start)) & 
        (projection_df.index <= pd.to_datetime(age_58_date))
    ]
    
    # Validate we have full 60 months of data
    if len(last_60_months_df) < 60:
        missing_months = 60 - len(last_60_months_df)
        st.warning(f"Missing {missing_months} months of data for 60-month average (need until {age_58_date.strftime('%d-%b-%Y')})")
        return None
    
    avg_pf_pay = last_60_months_df['PF_Pay'].mean()
    days_after_aug2014 = (age_58_date - sep_2014_start).days
    print("Days after 2014-",days_after_aug2014)
    component2 = days_after_aug2014 * avg_pf_pay
    
    # --- Final Calculation ---
    monthly_pension = (component1 + component2) / (70 * 365)
    
    return {
        'service_days': service_days_till_aug2014,  # Service days till Aug 2014
        'bonus_days_added': bonus_days,
        'adjusted_service_days': adjusted_service_days,
        'highest_pf_pay': highest_pf_pay_aug2014,
        'component1': component1,
        'days_after_aug2014': days_after_aug2014,
        'avg_pf_pay_last_60_months': avg_pf_pay,
        'component2': component2,
        'monthly_pension': monthly_pension,
        'age_58_date': age_58_date,
        'last_60_months_start': last_60_months_start,
        'total_service_years': total_service_years,  # Total service from joining to age 58
        'is_bonus_applied': is_bonus_applied
    }   
    
    

def display_yearly_summary(projection_df):
    """Display yearly summary of PF growth"""
    st.subheader("Yearly Summary")
    
    # Create yearly summary
    yearly_df = projection_df.resample('Y').last()
    yearly_df['Year'] = yearly_df.index.year
    yearly_df['Annual_Own_Contribution'] = projection_df.resample('Y').sum()['Own_Contribution']
    yearly_df['Annual_Company_Contribution'] = projection_df.resample('Y').sum()['Company_Contribution']
    yearly_df['Annual_Own_Interest'] = projection_df.resample('Y').sum()['Own_Monthly_Interest']
    yearly_df['Annual_Company_Interest'] = projection_df.resample('Y').sum()['Company_Monthly_Interest']
    
    # Display columns
    display_cols = ['Year', 'PF_Pay', 'Annual_Own_Contribution', 'Annual_Company_Contribution',
                   'Annual_Own_Interest', 'Annual_Company_Interest', 'Own_Closing_Balance',
                   'Company_Closing_Balance', 'Total_Corpus']
    
    # Format the display
    styled_df = yearly_df[display_cols].style.format({
        'PF_Pay': '₹{:,.2f}',
        'Annual_Own_Contribution': '₹{:,.2f}',
        'Annual_Company_Contribution': '₹{:,.2f}',
        'Annual_Own_Interest': '₹{:,.2f}',
        'Annual_Company_Interest': '₹{:,.2f}',
        'Own_Closing_Balance': '₹{:,.2f}',
        'Company_Closing_Balance': '₹{:,.2f}',
        'Total_Corpus': '₹{:,.2f}'
    }).background_gradient(subset=['Total_Corpus'], cmap='Blues')
    
    st.dataframe(styled_df, height=300)
    
    # Visualize yearly growth
    st.subheader("Corpus Growth Visualization")
    
    tab1, tab2, tab3 = st.tabs(["Total Corpus Growth", "Contributions & Interest", "PF Pay Growth"])
    
    with tab1:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(yearly_df.index, yearly_df['Own_Closing_Balance'], marker='o', label='Own PF')
        ax.plot(yearly_df.index, yearly_df['Company_Closing_Balance'], marker='s', label='Company PF')
        ax.plot(yearly_df.index, yearly_df['Total_Corpus'], marker='^', linewidth=2, label='Total Corpus')
        ax.set_title('Yearly Corpus Growth')
        ax.set_xlabel('Year')
        ax.set_ylabel('Amount (₹)')
        ax.legend()
        ax.grid(True)
        
        def format_amount(x, pos):
            if x >= 10000000:
                return f'₹{x/10000000:.2f}Cr'
            elif x >= 100000:
                return f'₹{x/100000:.2f}L'
            else:
                return f'₹{x:.0f}'
                
        ax.yaxis.set_major_formatter(plt.FuncFormatter(format_amount))
        plt.xticks(rotation=45)
        
        st.pyplot(fig)
    
    with tab2:
        fig, ax = plt.subplots(figsize=(10, 6))
        
        width = 0.35
        x = np.arange(len(yearly_df))
        
        ax.bar(x - width/2, yearly_df['Annual_Own_Contribution'], width, label='Own Contribution')
        ax.bar(x + width/2, yearly_df['Annual_Company_Contribution'], width, label='Company Contribution')
        
        ax.set_title('Yearly Contributions')
        ax.set_xlabel('Year')
        ax.set_ylabel('Amount (₹)')
        ax.set_xticks(x)
        ax.set_xticklabels(yearly_df['Year'], rotation=45)
        ax.legend()
        
        ax2 = ax.twinx()
        ax2.plot(x, yearly_df['Annual_Own_Interest'], 'r-', marker='o', label='Own Interest')
        ax2.plot(x, yearly_df['Annual_Company_Interest'], 'g-', marker='s', label='Company Interest')
        ax2.set_ylabel('Interest Amount (₹)')
        ax2.legend(loc='upper right')
        
        st.pyplot(fig)
    
    with tab3:
        fig, ax = plt.subplots(figsize=(10, 6))
        sns.lineplot(x=yearly_df.index, y=yearly_df['PF_Pay'], marker='o', linewidth=2)
        
        # Annotate key events - safely handle None values
        events_df = projection_df[projection_df['Event'].notna() & projection_df['Event'].str.contains('Pay Commission|DA Hike', na=False)]
        events_df = events_df.resample('Y').first()  # Take first event of each year
        
        for idx, row in events_df.iterrows():
            if row['Event'] and 'Pay Commission' in row['Event']:
                ax.annotate(row['Event'], 
                           xy=(idx, row['PF_Pay']),
                           xytext=(15, 15),
                           textcoords='offset points',
                           arrowprops=dict(arrowstyle='->', color='red'),
                           fontsize=8,
                           color='red')
        
        ax.set_title('PF Pay Growth Over Time')
        ax.set_xlabel('Year')
        ax.set_ylabel('PF Pay Amount (₹)')
        ax.grid(True)
        
        st.pyplot(fig)

def display_summary_metrics(projection_df, dob):
    if hasattr(st.session_state, 'date_of_joining') and hasattr(st.session_state, 'highest_pf_pay_aug2014'):
        if st.session_state.highest_pf_pay_aug2014 > 0:
            pension_result = calculate_epfo_pension(
                dob=dob,
                date_of_joining=st.session_state.date_of_joining,
                highest_pf_pay_aug2014=st.session_state.highest_pf_pay_aug2014,
                projection_df=projection_df
            )
            
            if pension_result:
                st.subheader("EPFO Higher Pension Calculation")
                
                # Create columns for better layout
                col1, col2 = st.columns([1, 1])
                
                with col1:
                    st.markdown("### 1. Service Period Calculation")
                    st.metric("Service Days", f"{pension_result['service_days']:,} days")
                    st.metric("Bonus Days", f"{pension_result['bonus_days_added']:,} days")
                    st.metric("Highest PF Pay", f"₹{pension_result['highest_pf_pay']:,.2f}")
                    st.metric("Component Value", f"₹{pension_result['component1']:,.2f}")
                
                with col2:
                    st.markdown("### 2. Salary Average Calculation")
                    st.metric("Days After Aug 2014", f"{pension_result['days_after_aug2014']:,} days")
                    st.metric("60-Month Avg PF Pay", f"₹{pension_result['avg_pf_pay_last_60_months']:,.2f}")
                    st.metric("Component Value", f"₹{pension_result['component2']:,.2f}")
                
                # Final calculation
                st.markdown("---")
                st.markdown("### Final Calculation")
                st.markdown(f"""
                **Formula:** (₹{pension_result['component1']:,.2f} + ₹{pension_result['component2']:,.2f}) ÷ (70 × 365)
                """)
                
                # Get the final EPFO closing balance from the projection dataframe
                final_epfo_balance = projection_df.iloc[-1]['EPFO_Closing_Balance']
                
                # Display monthly pension and EPFO balance in a prominent layout
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown(
                        f"""
                        <div style="
                            background: linear-gradient(135deg, #28a745, #20c997);
                            padding: 20px;
                            border-radius: 15px;
                            text-align: center;
                            margin: 10px 0;
                            box-shadow: 0 8px 16px rgba(0,0,0,0.1);
                            border: 2px solid #ffffff;
                        ">
                            <h2 style="
                                color: white;
                                font-size: 2.5rem;
                                font-weight: bold;
                                margin: 0;
                                text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
                            ">
                                ₹{pension_result['monthly_pension']:,.2f}
                            </h2>
                            <h4 style="
                                color: white;
                                font-size: 1.2rem;
                                margin: 10px 0 0 0;
                                font-weight: 600;
                            ">
                                Monthly Pension
                            </h4>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                
                with col2:
                    st.markdown(
                        f"""
                        <div style="
                            background: linear-gradient(135deg, #1E88E5, #0D47A1);
                            padding: 20px;
                            border-radius: 15px;
                            text-align: center;
                            margin: 10px 0;
                            box-shadow: 0 8px 16px rgba(0,0,0,0.1);
                            border: 2px solid #ffffff;
                        ">
                            <h2 style="
                                color: white;
                                font-size: 2.5rem;
                                font-weight: bold;
                                margin: 0;
                                text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
                            ">
                                ₹{final_epfo_balance:.2f}
                            </h2>
                            <h4 style="
                                color: white;
                                font-size: 1.2rem;
                                margin: 10px 0 0 0;
                                font-weight: 600;
                            ">
                                EPFO - Total outflow
                            </h4>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                
                # Service period info
                st.info(f"""
                **Service Period:** {st.session_state.date_of_joining.strftime('%d-%b-%Y')} to 31-Aug-2014
                **60-Month Average:** {pension_result['last_60_months_start'].strftime('%d-%b-%Y')} to {pension_result['age_58_date'].strftime('%d-%b-%Y')}
                """)





    
    # Display summary metrics and retirement projection
    final_row = projection_df.iloc[-1]
    retirement_date = date(dob.year + 60, dob.month, dob.day)
    
    st.markdown("---")
    st.subheader("Retirement Projection Summary")
    st.write("Based on your current data and the applied assumptions, your projected retirement details are:")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        st.metric("Date of Birth", dob.strftime('%d-%b-%Y'))
    with col2:
        st.metric("Expected Retirement Date", retirement_date.strftime('%d-%b-%Y'))

    
    
    
    
    
    
    
    
    """Display summary metrics and retirement projection"""
    final_row = projection_df.iloc[-1]
    retirement_date = date(dob.year + 60, dob.month, dob.day)
    
    st.markdown(f"""
    <div class="summary-box">
        <h3 class="header-text">Retirement Projection Summary</h3>
        <p>Based on your current data and the applied assumptions, your projected retirement details are:</p>
        <p><strong>Date of Birth:</strong> {dob.strftime('%d-%b-%Y')}</p>
        <p><strong>Expected Retirement Date:</strong> {retirement_date.strftime('%d-%b-%Y')}</p>
    </div>
    """, unsafe_allow_html=True)
    
    
    
    
    
    
    
    
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Final Own PF Balance", f"₹{final_row['Own_Closing_Balance']:,.2f}")
    with col2:
        st.metric("Final Company PF Balance", f"₹{final_row['Company_Closing_Balance']:,.2f}")
    with col3:
        st.metric("Total Retirement Corpus", f"₹{final_row['Total_Corpus']:,.2f}")
    
    # Additional metrics
    st.subheader("Additional Metrics")
    
    col1, col2 = st.columns(2)
    
    with col1:
        total_own_contribution = projection_df['Own_Contribution'].sum()
        total_own_interest = projection_df['Own_Monthly_Interest'].sum()
        
        st.metric("Total Own Contributions", f"₹{total_own_contribution:,.2f}")
        st.metric("Total Interest Earned (Own)", f"₹{total_own_interest:,.2f}")
        st.metric("Interest-to-Contribution Ratio (Own)", f"{total_own_interest/total_own_contribution:.2f}")
    
    with col2:
        total_company_contribution = projection_df['Company_Contribution'].sum()
        total_company_interest = projection_df['Company_Monthly_Interest'].sum()
        
        st.metric("Total Company Contributions", f"₹{total_company_contribution:,.2f}")
        st.metric("Total Interest Earned (Company)", f"₹{total_company_interest:,.2f}")
        st.metric("Interest-to-Contribution Ratio (Company)", f"{total_company_interest/total_company_contribution:.2f}")
        
    # Show key events
    st.subheader("Key Financial Events")
    
    events_df = projection_df[projection_df['Event'].str.len() > 0].copy()
    
    if not events_df.empty:
        for idx, row in events_df.iterrows():
            if 'Pay Commission' in row['Event']:
                with st.expander(f"{row['Month_Year']} - {row['Event']}", expanded=True):
                    prev_month = idx - pd.DateOffset(months=1)
                    if prev_month in projection_df.index:
                        prev_row = projection_df.loc[prev_month]
                        st.write(f"- PF Pay increased from ₹{prev_row['PF_Pay']:,.2f} to ₹{row['PF_Pay']:,.2f}")
                        st.write(f"- Basic Pay increased from ₹{prev_row['Basic']:,.2f} to ₹{row['Basic']:,.2f}")
                        st.write(f"- Monthly contribution increased from ₹{prev_row['Own_Contribution'] + prev_row['Company_Contribution']:,.2f} to ₹{row['Own_Contribution'] + row['Company_Contribution']:,.2f}")
            elif 'DA Hike' in row['Event']:
                with st.expander(f"{row['Month_Year']} - {row['Event']}"):
                    prev_month = idx - pd.DateOffset(months=1)
                    if prev_month in projection_df.index:
                        prev_row = projection_df.loc[prev_month]
                        st.write(f"- DA increased from ₹{prev_row['DA']:,.2f} to ₹{row['DA']:,.2f}")
                        st.write(f"- PF Pay increased from ₹{prev_row['PF_Pay']:,.2f} to ₹{row['PF_Pay']:,.2f}")
    else:
        st.write("No significant financial events found in the projection period.")
        
    # Generate downloadable PDF report
    st.markdown(create_downloadable_pdf(projection_df, dob, final_row), unsafe_allow_html=True)

# When form is submitted
if calculate_button:
    with st.spinner('Calculating your retirement corpus...'):
        
        st.session_state.date_of_joining = date_of_joining
        st.session_state.highest_pf_pay_aug2014 = highest_pf_pay_aug2014
        projection_df = create_monthly_projection(
            dob=dob,
            current_basic=current_basic,
            current_da=current_da,
            current_own_pf=current_own_pf,
            current_company_pf=current_company_pf,
            increment_month=increment_month,
            own_pf_percent=own_pf_percent,
            company_pf_percent=company_pf_percent,
            pf_interest_rate=pf_interest_rate,
            promotion_details=promotion_details,
            pc_2030_factor=pc_2030_factor,
            pc_2040_factor=pc_2040_factor,
            current_epfo_balance=current_epfo_balance
        )
        
        if projection_df is not None:
            st.session_state.projection_df = projection_df
            st.session_state.calculated = True

# Display results if calculation is done
if st.session_state.get('calculated', False) and st.session_state.projection_df is not None:
    display_summary_metrics(st.session_state.projection_df, dob)
    
    tab1, tab2 = st.tabs(["Monthly Ledger", "Yearly Summary"])
    
    with tab1:
        display_monthly_ledger(st.session_state.projection_df)
    
    with tab2:
        display_yearly_summary(st.session_state.projection_df)