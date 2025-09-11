from dotenv import load_dotenv
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import TimeoutException
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time
import pytz
from tabulate import tabulate
import traceback
import sys
import json
from google.oauth2.service_account import Credentials
# from collections import defaultdict

# Load .env file
load_dotenv(".env")

# Read credentials
USER1_EMAIL = os.getenv("USER1_EMAIL")
USER1_PASSWORD = os.getenv("USER1_PASSWORD")
USER2_EMAIL = os.getenv("USER2_EMAIL")
USER2_PASSWORD = os.getenv("USER2_PASSWORD")

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

# Get the Google Sheets worksheet
def get_worksheet(sheet_name: str, tab_name: str):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# 🟢 Load JSON from env var, not file
    json_creds = os.environ["GOOGLE_CREDS_JSON"]
    service_account_info = json.loads(json_creds)
    service_account_info["private_key"] = service_account_info["private_key"].replace("\\n", "\n")

    creds = Credentials.from_service_account_info(service_account_info, scopes=scope)
    client = gspread.authorize(creds)
    sheet = client.open(sheet_name)
    return sheet.worksheet(tab_name)


def update_sheet_with_bravo_data(sheet, scraped_data):
    print("📥 Updating Google Sheet with scraped Bravo data...")

    records = sheet.get_all_records()
    headers = sheet.row_values(1)
    
    # Uncomment to see the first few rows of the sheet (debugging)
    # print("📄 First few sheet rows:")
    # for row in records[:5]:
    #     print(f"   • {row['הפקה']} | {row['תאריך']} | {row['ארגון']}")


    # ✅ Make sure header names match your sheet exactly
    name_col = headers.index("הפקה")
    date_col = headers.index("תאריך")
    org_col = headers.index("ארגון")
    sold_col = headers.index("נמכרו")
    updated_col = headers.index("עודכן לאחרונה")

    updated_rows = 0
    not_found = []


    for seance in scraped_data:
        # Uncomment to see each seance being checked (debugging)
        # print(f"🔍 Checking seance: {seance['הפקה']} | {seance['תאריך']} | {seance['ארגון']}")
        if seance["ארגון"] != "בראבו":
            continue  # ✅ Skip non-Bravo entries
            
        israel_tz = pytz.timezone("Asia/Jerusalem")
        now_israel = datetime.now(israel_tz).strftime('%d/%m/%Y %H:%M:%S')
        
        found = False
        for i, row in enumerate(records):
            title_match = (seance["הפקה"].strip() in row["הפקה"].strip()
                or row["הפקה"].strip() in seance["הפקה"].strip())
            if (
                title_match
                and row["תאריך"].strip() == seance["תאריך"].strip()
                and row["ארגון"].strip() in seance["ארגון"].strip()
            ):
                sheet.update_cell(i + 2, sold_col + 1, seance["נמכרו"])
                sheet.update_cell(i + 2, updated_col + 1, now_israel)
                updated_rows += 1
                print(f"✅ Row {i + 2} updated for '{seance['הפקה']}' בתאריך {seance['תאריך']}")
                found = True
                break

        if not found:
            not_found.append((seance["הפקה"], seance["תאריך"]))

    print(f"\n✅ Total updated rows: {updated_rows}")
    if not_found:
        print("⚠️ These Bravo seances were not found in the sheet:")
        for name, date in not_found:
            print(f"   • {name} בתאריך {date}")


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
            worksheet = get_worksheet("דאטה אפשיט אופיס", "כרטיסים")
            update_sheet_with_bravo_data(worksheet, unique_data)
        else:
            print("❌ לא נמצאו מופעים.")
    
    except Exception as e:
        print("❌ ERROR encountered:")
        traceback.print_exc()
        sys.exit(1)
