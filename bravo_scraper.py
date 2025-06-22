from dotenv import load_dotenv
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import TimeoutException
import time
from tabulate import tabulate
from collections import defaultdict
# Load .env file
load_dotenv("creds/.env")

# Read credentials
USER1_EMAIL = os.getenv("USER1_EMAIL")
USER1_PASSWORD = os.getenv("USER1_PASSWORD")
USER2_EMAIL = os.getenv("USER2_EMAIL")
USER2_PASSWORD = os.getenv("USER2_PASSWORD")

def create_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    return webdriver.Chrome(options=options)

def login_and_navigate(driver, username, password):
    print(f"🔐 Logging in as {username}")
    driver.get("https://kb.israelinfo.co.il/#login")

    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, "login")))
    driver.find_element(By.NAME, "login").send_keys(username)
    driver.find_element(By.NAME, "password").send_keys(password)
    driver.find_element(By.CSS_SELECTOR, "button.btn.btn-primary").click()

    # Wait for redirect after login
    WebDriverWait(driver, 10).until(lambda d: "kupatbarzel.co.il" in d.current_url)

    redirected_url = driver.current_url
    print(f"🌐 Redirected to: {redirected_url}")

    # Append path to shows page
    if "index.cgi" in redirected_url:
        base_url = redirected_url.split("index.cgi")[0]
    else:
        base_url = redirected_url

    target_url = f"{base_url}index.cgi#!/kassy/shows"
    print(f"🚀 Navigating to Bravo Shows page: {target_url}")
    driver.get(target_url)

    try:
        WebDriverWait(driver, 10).until(
            EC.frame_to_be_available_and_switch_to_it((By.ID, "frmKassa"))
        )
    except TimeoutException:
        screenshot_path = f"login_failed_{username.replace('@', '_at_')}.png"
        driver.save_screenshot(screenshot_path)
        print(f"❌ Timeout for user {username}. Screenshot saved to {screenshot_path}")
        raise

    return extract_main_table_data(driver)


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
            org = row.find_element(By.CSS_SELECTOR, 'td[data-title="מפיק"]').text.strip()
            hall = row.find_element(By.CSS_SELECTOR, 'td[data-title="אולם"]').text.strip()
            date = row.find_element(By.CSS_SELECTOR, 'td[data-title="תאריך"]').text.strip()
            time_ = row.find_element(By.CSS_SELECTOR, 'td[data-title="שעה"]').text.strip()
            sold = row.find_element(By.CSS_SELECTOR, 'td[data-title="נמכר"]').text.strip()
            available = row.find_element(By.CSS_SELECTOR, 'td[data-title="נשאר למכירה"]').text.strip()

            seances.append({
                "שם ההופעה": show_name,
                "עיר": city,
                "מפיק": org,
                "אולם": hall,
                "תאריך": date,
                "שעה": time_,
                "נמכר": sold,
                "נשאר למכירה": available,
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
        key = (s["שם ההופעה"], s["תאריך"])
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


if __name__ == "__main__":
    combined_data = []

    combined_data += run_for_user(USER1_EMAIL, USER1_PASSWORD)
    combined_data += run_for_user(USER2_EMAIL, USER2_PASSWORD)

    print("\n📊 כל המופעים משני המשתמשים:\n")

    if combined_data:
        # ✅ Remove duplicates (same name + date), keep first
        unique_data = []
        seen = set()
        duplicate_keys = []

        for s in combined_data:
            key = (s["שם ההופעה"], s["תאריך"])
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
    else:
        print("❌ לא נמצאו מופעים.")
