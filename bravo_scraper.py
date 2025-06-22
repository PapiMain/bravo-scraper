from dotenv import load_dotenv
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

load_dotenv("creds/.env")

USER1_EMAIL = os.getenv("USER1_EMAIL")
USER1_PASSWORD = os.getenv("USER1_PASSWORD")
USER2_EMAIL = os.getenv("USER2_EMAIL")
USER2_PASSWORD = os.getenv("USER2_PASSWORD")

def create_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    driver = webdriver.Chrome(options=options)
    return driver
