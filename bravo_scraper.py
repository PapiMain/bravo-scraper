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
from papi_sync_guard import (MISSING, RunReport, VolumeGuard, build_alias_index,
                             find_single_match, safe_int, titles_match,
                             verify_appsheet_response)
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

def consolidate_duplicate_shows(data):
    print("🔄 Consolidating duplicates (summing 'נמכרו' and 'נשאר למכירה')...")
    consolidated = {}

    for row in data:
        # 1. Define the unique key: (Show Name, Hall, Date)
        key = (
            row.get("הפקה", "").strip(), 
            row.get("אולם", "").strip(), 
            row.get("תאריך", "").strip(),
            row.get("שעה", "").strip()
        )

        # 2. Safely parse the numbers (defaults to 0 if empty or invalid text)
        try:
            sold = int(str(row.get("נמכרו", "0")).strip() or 0)
        except ValueError:
            sold = 0

        try:
            available = int(str(row.get("נשאר למכירה", "0")).strip() or 0)
        except ValueError:
            available = 0

        # 3. Check if we already have this show/hall/date combo
        if key in consolidated:
            # Add to the existing totals
            consolidated[key]["נמכרו"] += sold
            consolidated[key]["נשאר למכירה"] += available
        else:
            # First time seeing this combo, add it to our dictionary
            new_row = row.copy()
            new_row["נמכרו"] = sold
            new_row["נשאר למכירה"] = available
            consolidated[key] = new_row

    # Return the consolidated dictionary as a simple list
    result = list(consolidated.values())
    print(f"✅ Consolidated list from {len(data)} rows down to {len(result)} unique shows.")
    return result

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

    consolidated_data = consolidate_duplicate_shows(all_data)

    return consolidated_data

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
# ─────────────────────────────────────────────────────────────────────
# כינויים מוצהרים. כל מיזוג שמות חייב להופיע כאן במפורש.
# אין הכלה חלקית: "אלאדין" אינו "אלאדין ומנורת נס החנוכה".
# ─────────────────────────────────────────────────────────────────────
SHOW_ALIASES = build_alias_index({
    "simba": ["סימבה", "סימבה מלך"],
})

# טבלת היעד ועמודת המפתח — ניתנות להגדרה בלי שינוי קוד.
# ברירת המחדל נשארת כפי שהיה עד לאימות הגדרת הטבלאות ב-AppSheet.
TARGET_TABLE = os.getenv("PAPI_APPSHEET_TARGET_TABLE", "כרטיסים")
KEY_COLUMN = os.getenv("PAPI_APPSHEET_KEY_COLUMN", "ID")
SOURCE_TABLE = os.getenv("PAPI_APPSHEET_SOURCE_TABLE", "הופעות עתידיות")
DRY_RUN = os.getenv("PAPI_DRY_RUN", "").strip().lower() in ("1", "true", "yes")


def _parse_appsheet_date(raw):
    """AppSheet עשוי להחזיר כמה פורמטים. מחזיר date או None."""
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def update_appsheet_with_bravo_data(scraped_data):
    """
    מתאים את הנתונים שנסרקו לשורות ב-AppSheet ומעדכן אותן.

    ארבעת הכללים (ראה papi_sync_guard):
      1. נתון חסר נפסל ואינו נכתב כאפס.
      2. הצלחה נקבעת לפי גוף התגובה ומספר השורות שאושרו.
      3. התאמה לפי שם מנורמל מדויק או כינוי מוצהר; ריבוי התאמות נפסל.
      4. ירידה חריגה בנפח עוצרת את הכתיבה.

    מחזיר RunReport. report.ok=False מחייב יציאה בקוד שגיאה.
    """
    report = RunReport("בראבו → AppSheet")
    app_id = os.getenv("APPSHEET_APP_ID")
    app_key = os.getenv("APPSHEET_APP_KEY")

    bravo_rows = [s for s in scraped_data if s.get("ארגון") == "בראבו"]
    report.scraped = len(bravo_rows)
    print(f"📥 נסרקו {report.scraped} מועדים של בראבו.")

    # ── כלל 4: הגנת נפח, לפני כל קריאה או כתיבה ──
    guard = VolumeGuard("bravo", min_ratio=0.7, min_rows=1)
    allowed, volume_message = guard.check(report.scraped)
    print(f"🛡️ {volume_message}")
    if not allowed:
        report.error(f"הכתיבה נעצרה בהגנת נפח: {volume_message}")
        return report

    records = get_appsheet_data(SOURCE_TABLE)
    if not records:
        report.error(f"לא התקבלו רשומות מטבלת {SOURCE_TABLE} — לא נכתב דבר.")
        return report
    print(f"📚 התקבלו {len(records)} רשומות מ-{SOURCE_TABLE}.")

    israel_tz = pytz.timezone("Asia/Jerusalem")
    now_israel = datetime.now(israel_tz).strftime("%Y-%m-%d %H:%M:00")

    batch_updates = []

    for seance in bravo_rows:
        name = str(seance.get("הפקה", "")).strip()
        date_text = str(seance.get("תאריך", "")).strip()
        label = f"{name} / {date_text}"

        try:
            scraped_date = datetime.strptime(date_text, "%d/%m/%Y").date()
        except Exception:
            report.skip(label, f"תאריך שאינו ניתן לפענוח: '{date_text}'")
            continue

        # ── כלל 1: נתון חסר נפסל, לא הופך לאפס ──
        sold = safe_int(seance.get("נמכרו"))
        if sold is MISSING:
            report.skip(label, f"ערך 'נמכרו' חסר או לא תקין: {seance.get('נמכרו')!r}")
            continue

        # ── כלל 3: התאמה מדויקת, ריבוי התאמות נפסל ──
        def matches(row, _name=name, _date=scraped_date, _org=seance.get("ארגון", "")):
            if _parse_appsheet_date(row.get("תאריך")) != _date:
                return False
            row_org = str(row.get("ארגון") or "").strip()
            if row_org and row_org not in str(_org).strip():
                return False
            return titles_match(_name, row.get("הפקה"), SHOW_ALIASES)

        match, status = find_single_match(records, matches)

        if status == "ambiguous":
            report.ambiguity(label, "יותר משורה אחת ב-AppSheet תואמת שם, תאריך וארגון")
            continue
        if status == "none":
            same_date = [
                str(r.get("הפקה", "")).strip()
                for r in records
                if _parse_appsheet_date(r.get("תאריך")) == scraped_date
            ]
            hint = f"שורות באותו תאריך: {same_date[:5]}" if same_date else "אין שורות בתאריך הזה"
            report.miss(label, hint)
            continue

        key_value = match.get(KEY_COLUMN)
        if key_value in (None, ""):
            report.skip(label, f"לשורה התואמת אין ערך בעמודת המפתח '{KEY_COLUMN}'")
            continue

        batch_updates.append({
            KEY_COLUMN: key_value,
            "נמכרו": sold,
            "עודכן לאחרונה": now_israel,
        })
        report.matched += 1
        print(f"✅ התאמה: {label} → {KEY_COLUMN}={key_value}, נמכרו={sold}")

    if not batch_updates:
        print("ℹ️ אין שורות לעדכון.")
        if report.scraped and not report.matched:
            report.error("נסרקו מועדים אך אף אחד לא הותאם — ייתכן שינוי במבנה המקור.")
        return report

    if DRY_RUN:
        print(f"🧪 DRY RUN — {len(batch_updates)} שורות היו נשלחות ל-{TARGET_TABLE}. לא נשלח דבר.")
        report.confirmed = 0
        return report

    # ── כלל 2: הצלחה לפי גוף התגובה ──
    url = f"https://api.appsheet.com/api/v1/apps/{app_id}/tables/{TARGET_TABLE}/Action"
    body = {
        "Action": "Edit",
        "Properties": {"Locale": "en-US", "Timezone": "Israel Standard Time"},
        "Rows": batch_updates,
    }

    print(f"📤 שולח {len(batch_updates)} שורות ל-{TARGET_TABLE} (מפתח: {KEY_COLUMN})...")
    try:
        response = requests.post(
            url, headers={"ApplicationAccessKey": app_key}, json=body, timeout=120
        )
    except Exception as exc:
        report.error(f"בקשת הכתיבה נכשלה: {exc}")
        return report

    ok, confirmed, detail = verify_appsheet_response(response, len(batch_updates))
    report.confirmed = confirmed

    if ok:
        print(f"🎉 אושרו {confirmed} שורות ב-{TARGET_TABLE}.")
        guard.record_success(report.scraped)
    else:
        report.error(f"הכתיבה לא אושרה: {detail}")
        print(f"❌ הכתיבה לא אושרה: {detail}")

    return report

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

            # ✅ עדכון AppSheet
            report = update_appsheet_with_bravo_data(unique_data)
            print(report.summary())
            if not report.ok:
                print("❌ הריצה נכשלה. ראה את הדוח למעלה.")
                sys.exit(1)
        else:
            # סריקה ריקה אינה הוכחה שאין מופעים. נכשל בקול, ולא כותבים דבר.
            print("❌ לא נמצאו מופעים — הסריקה חזרה ריקה. לא נכתב דבר.")
            sys.exit(1)

    except Exception as e:
        print("❌ ERROR encountered:")
        traceback.print_exc()
        sys.exit(1)
