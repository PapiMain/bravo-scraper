from dotenv import load_dotenv
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import TimeoutException
from datetime import datetime
import time
import pytz
from tabulate import tabulate
import traceback
import sys
import json
import requests
from py_appsheet import AppSheetClient # Ensure this is installed: pip install py-appsheet
# from collections import defaultdict

# Load .env file
load_dotenv(".env")

# Read credentials
USER1_EMAIL = os.getenv("USER1_EMAIL")
USER1_PASSWORD = os.getenv("USER1_PASSWORD")
USER2_EMAIL = os.getenv("USER2_EMAIL")
USER2_PASSWORD = os.getenv("USER2_PASSWORD")

# Optional: Validate credentials are present
def create_driver():
    options = Options()
    
    # Headless with modern implementation
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    # Stealth flags
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # Realistic user-agent
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(options=options)

    # Extra stealth tweak (removes navigator.webdriver)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
        Object.defineProperty(navigator, 'webdriver', {
          get: () => undefined
        })
        """
    })

    return driver

# 🔐 Login and navigate to shows page
def login_and_navigate(driver, username, password):
    print(f"🔐 Logging in as {username}")
    driver.get("https://kb.israelinfo.co.il")
    driver.execute_script("window.location.hash = '#login';")


    try:
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.NAME, "login")))
        time.sleep(2)
        driver.find_element(By.NAME, "login").send_keys(username)
        driver.find_element(By.NAME, "password").send_keys(password)
        driver.find_element(By.CSS_SELECTOR, "button.btn.btn-primary").click()

        # Wait for redirect
        WebDriverWait(driver, 30).until(lambda d: "kupatbarzel.co.il" in d.current_url)
        redirected_url = driver.current_url
        print(f"🌐 Redirected to: {redirected_url}")

        # Build target URL
        if "index.cgi" in redirected_url:
            base_url = redirected_url.split("index.cgi")[0]
        else:
            base_url = redirected_url

        target_url = f"{base_url}index.cgi#!/kassy/shows"
        print(f"🚀 Navigating to Bravo Shows page: {target_url}")
        driver.get(target_url)

        WebDriverWait(driver, 15).until(
            EC.frame_to_be_available_and_switch_to_it((By.ID, "frmKassa"))
        )

        return extract_main_table_data(driver)

    except TimeoutException:
        screenshot_path = f"login_failed_{username.replace('@', '_at_')}.png"
        driver.save_screenshot(screenshot_path)
        print(f"❌ Timeout for user {username}. Screenshot saved to {screenshot_path}")
        raise

# 📄 Extract show names and details links from the main table
def extract_main_table_data(driver):
    print("📄 Extracting main show table rows...")
    shows = []

    WebDriverWait(driver, 10).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'tr[role="row"]'))
    )
    rows = driver.find_elements(By.CSS_SELECTOR, 'tr[role="row"]')

    for row in rows:
        try:
            if row.find_elements(By.TAG_NAME, "th"):
                print("ℹ️ Skipping header row.")
                continue

            name = row.find_element(By.CSS_SELECTOR, 'td[data-title="שם ההופעה"] a').text.strip()

            # ✅ This is the correct "עריכת המועדים" link
            details_link = row.find_element(By.XPATH, './/a[contains(@href, "?Tab=details")]').get_attribute("href")
            # ✅ Prevent double-prefixing:
            if details_link.startswith("http"):
                full_link = details_link
            else:
                full_link = "https://68.kupatbarzel.co.il" + details_link

            shows.append({
                "name": name,
                "link": full_link
            })

        except Exception as e:
            print("⚠️ Skipped a row:", e)
            print("🔍 HTML of skipped row:", row.get_attribute("outerHTML"))

    return shows

# 🎟️ Extract seance details from the show page
def extract_seances(driver, show_url, show_name):
    print(f"🌐 Opening seance page: {show_url}")
    driver.get(show_url)
    time.sleep(2)

    try:
        WebDriverWait(driver, 5).until(
            EC.frame_to_be_available_and_switch_to_it((By.ID, "frmKassa"))
        )
    except:
        print("⚠️ No iframe found on seance page. Trying without it.")

    seances = []
    skipped_missing_field = 0
    skipped_other_errors = 0

    rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")

    for row in rows:
        try:
            cells = row.find_elements(By.TAG_NAME, "td")
            if not cells:
                continue

            city = row.find_element(By.CSS_SELECTOR, 'td[data-title="עיר"]').text.strip()
            org = "בראבו" 
            producer = row.find_element(By.CSS_SELECTOR, 'td[data-title="מפיק"]').text.strip() 
            hall = row.find_element(By.CSS_SELECTOR, 'td[data-title="אולם"]').text.strip()
            raw_date = row.find_element(By.CSS_SELECTOR, 'td[data-title="תאריך"]').text.strip()
            date = raw_date.replace(".", "/")
            time_ = row.find_element(By.CSS_SELECTOR, 'td[data-title="שעה"]').text.strip()
            sold = row.find_element(By.CSS_SELECTOR, 'td[data-title="נמכר"]').text.strip()
            available = row.find_element(By.CSS_SELECTOR, 'td[data-title="נשאר למכירה"]').text.strip()

            seances.append({
                "הפקה": show_name,
                "עיר": city,
                "ארגון": org,        # this is now the correct "בראבו"
                "מפיק": producer,     # optional for later
                "אולם": hall,
                "תאריך": date,
                "שעה": time_,
                "נמכרו": sold,
                "נשאר למכירה": available,  # optional, not used in update for now
            })

        except NoSuchElementException:
            skipped_missing_field += 1
        except Exception as e:
            skipped_other_errors += 1
            # Optional: print(f"⚠️ Skipped a seance row due to unexpected error: {e}")

    if skipped_missing_field > 0:
        print(f"⚠️ Skipped {skipped_missing_field} seance rows due to missing required fields.")
    if skipped_other_errors > 0:
        print(f"⚠️ Skipped {skipped_other_errors} seance rows due to unexpected errors.")

    # ✅ Duplicate (name+date) detection
    seen = set()
    duplicates = []

    for s in seances:
        key = (s["הפקה"], s["תאריך"])
        if key in seen:
            duplicates.append(key)
        else:
            seen.add(key)

    if duplicates:
        print("⚠️ Found duplicate seances with the same name and date:")
        for name, date in set(duplicates):
            print(f"   • {name} on {date}")

    try:
        driver.switch_to.default_content()
    except:
        pass

    return seances

# 🚀 Main function to run the scraper for a given user
def run_for_user(username, password):
    driver = create_driver()
    all_data = []

    try:
        shows = login_and_navigate(driver, username, password)

        for show in shows:
            print(f"\n📌 {show['name']}")
            seances = extract_seances(driver, show["link"], show["name"])
            all_data.extend(seances)

    finally:
        driver.quit()

    return all_data

# 📊 Fetch existing AppSheet data for matching
def get_appsheet_data(table_name):
    """Uses the py-appsheet library to fetch data."""
    client = AppSheetClient(
        app_id=os.environ.get("APPSHEET_APP_ID"),
        api_key=os.environ.get("APPSHEET_APP_KEY"),
    )
    try:
        print(f"⏳ Fetching all rows from table: {table_name}")
        # Using selector="true" is the standard way to say "Give me everything"
        rows = client.find_items(table_name, "")
        
        if rows:
            print(f"✅ Successfully retrieved {len(rows)} rows from {table_name}")
            return rows
        return []
    except Exception as e:
        print(f"❌ py-appsheet error: {e}")
        return []

# 🔄 Update AppSheet with scraped data
def update_appsheet_with_bravo_data(scraped_data):
    print("📥 Processing data for AppSheet API...")
    
    app_id = os.getenv("APPSHEET_APP_ID")
    app_key = os.getenv("APPSHEET_APP_KEY")
    
    """Main logic: Matches scraped data against AppSheet records and updates them."""
    table_name = "הופעות עתידיות"
    records = get_appsheet_data(table_name)
    
    if not records:
        print("❌ No records found to update.")
        return

    israel_tz = pytz.timezone("Asia/Jerusalem")
    now_israel = datetime.now(israel_tz).strftime('%d/%m/%Y %H:%M')
    
    batch_updates = []
    not_found = []
    updated_rows_count = 0

    # 2. Re-implement your exact matching logic
    for seance in scraped_data:
        if seance["ארגון"] != "בראבו":
            continue

        found = False
        seance_name = seance["הפקה"].strip()
        
        # Your specific Simba logic preserved
        if "סימבה" in seance_name and "סוואנה" not in seance_name and "אפריקה" not in seance_name:
            seance_name = "סימבה מלך"

        for row in records:
            row_name = str(row.get("הפקה", "")).strip()
            row_date_raw = str(row.get("תאריך", "")).strip()
            row_org = str(row.get("ארגון", "")).strip()

            app_date_obj = row_date_raw
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
                try:
                    # Convert to a date object (removes time if present)
                    app_date_obj =  datetime.strptime(row_date_raw, fmt).date()
                except ValueError:
                    continue

            # Your exact matching conditions
            title_match = (seance_name in row_name or row_name in seance_name)
            
            if (
                title_match
                and app_date_obj == seance["תאריך"].strip()
                and row_org in seance["ארגון"].strip()
            ):
                # הכנת העדכון - חובה לכלול את ה-ID (או ה-Key של הטבלה שלך)
                # אם ה-Key שלך הוא לא "ID", שנה את השורה למטה לשם העמודה הנכון (למשל "_RowNumber")

                batch_updates.append({
                    "ID": row["ID"], 
                    "נמכרו": int(seance["נמכרו"]) if str(seance["נמכרו"]).isdigit() else 0,
                    "עודכן לאחרונה": now_israel
                })
                
                updated_rows_count += 1
                found = True
                print(f"✅ נמצאה התאמה: {seance_name} בתאריך {seance['תאריך']}")
                break
            elif app_date_obj == seance["תאריך"].strip():
                not_found.append((seance["הפקה"], row_name, app_date_obj))
        
        # if not found:
        #     not_found.append((seance["הפקה"], seance["תאריך"]))

    # 3. Send the batch update
    if batch_updates:
        print(f"📤 שולח {len(batch_updates)} שורות לעדכון ב-AppSheet...")

        url = f"https://api.appsheet.com/api/v1/apps/{app_id}/tables/{table_name}/Action"
        
        body = {
            "Action": "Edit",
            "Properties": {"Locale": "en-US"},
            "Rows": batch_updates
        }

        try:
            response = requests.post(url, headers={"ApplicationAccessKey": app_key}, json=body)
            print(f"🚀 AppSheet API Status: {response.status_code}")
            if response.status_code == 200:
                print(f"🎉 העדכון הסתיים בהצלחה! עודכנו {updated_rows_count} שורות.")
            else:
                print(f"❌ שגיאת API (סטטוס {response.status_code}): {response.text}")
        except Exception as e:
            print(f"❌ נכשל בשליחת הבקשה: {e}")

    # if not_found:
    #     print("⚠️ These Bravo seances were not found in AppSheet:")
    #     for name, date in not_found:
    #         print(f"   • {name} בתאריך {date}")
    if not_found:
        print("\n⚠️ Near-misses or Mismatches found (Date matched, Name didn't):")
        # Fixed the unpacking here (3 variables instead of 2)
        for s_name, r_name, r_date in not_found:
            print(f"   • Scraped: '{s_name}' | AppSheet Row: '{r_name}' | Date: {r_date}")

# Main execution
if __name__ == "__main__":
    try:
        combined_data = []

        combined_data += run_for_user(USER2_EMAIL, USER2_PASSWORD)
        combined_data += run_for_user(USER1_EMAIL, USER1_PASSWORD)

        print("\n📊 כל המופעים משני המשתמשים:\n")

        if combined_data:
            # ✅ Remove duplicates (same name + date), keep first
            unique_data = []
            seen = set()
            duplicate_keys = []

            for s in combined_data:
                key = (s["הפקה"], s["תאריך"])
                if key not in seen:
                    seen.add(key)
                    unique_data.append(s)
                else:
                    duplicate_keys.append(key)

            removed_count = len(combined_data) - len(unique_data)
            if duplicate_keys:
                print(f"⚠️ הוסרו {len(duplicate_keys)} שורות כפולות עם שם ותאריך זהים:")
                for name, date in set(duplicate_keys):
                    print(f"   • {name} בתאריך {date}")
                print()

            # 🧾 Print table with only unique seances
            headers = unique_data[0].keys()
            rows = [row.values() for row in unique_data]
            print(tabulate(rows, headers=headers, tablefmt="grid", stralign="center"))

            # ✅ Update Google Sheet
            update_appsheet_with_bravo_data(unique_data)
        else:
            print("❌ לא נמצאו מופעים.")
    
    except Exception as e:
        print("❌ ERROR encountered:")
        traceback.print_exc()
        sys.exit(1)
