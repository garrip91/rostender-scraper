import argparse
import csv
import sqlite3
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from fastapi import FastAPI
import uvicorn
import logging
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

def setup_driver():
    """Настройка Selenium WebDriver."""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    return driver

def init_db():
    """Инициализация SQLite базы данных."""
    conn = sqlite3.connect('tenders.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tenders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number TEXT,
            link TEXT,
            customer TEXT,
            goods TEXT,
            end_date TEXT
        )
    ''')
    conn.commit()
    return conn, cursor

def parse_tenders(max_tenders=100):
    """Парсинг тендеров с сайта rostender.info с обработкой пагинации."""
    driver = setup_driver()
    tenders = []
    try:
        driver.get("https://rostender.info/extsearch/")
        logger.info("Page loaded: https://rostender.info/extsearch/")
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "tenders-search-form"))
        )
        search_button = driver.find_element(By.CSS_SELECTOR, "#start-search-button")
        search_button.click()
        time.sleep(2)
        max_pages = 5
        current_page = 1
        while len(tenders) < max_tenders and current_page <= max_pages:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CLASS_NAME, "tender-row"))
            )
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            tender_elements = driver.find_elements(By.CLASS_NAME, "tender-row")
            for element in tender_elements:
                if len(tenders) >= max_tenders:
                    break
                try:
                    number_elem = element.find_element(By.CLASS_NAME, "tender__number")
                    number = number_elem.text.replace("Тендер №", "").strip()
                    link_elem = element.find_element(By.CSS_SELECTOR, ".tender-info__link")
                    link = link_elem.get_attribute("href")
                    goods = link_elem.text.strip()
                    end_date_elem = element.find_element(By.CLASS_NAME, "tender__date-end")
                    end_date = end_date_elem.find_element(By.CLASS_NAME, "black").text
                    tender = {
                        "number": number,
                        "link": link,
                        "customer": "N/A",
                        "goods": goods,
                        "end_date": end_date
                    }
                    tenders.append(tender)
                    logger.info(f"Parsed tender: {number}")
                except Exception as e:
                    logger.error(f"Error parsing tender element: {e}")
                    continue
            if len(tenders) >= max_tenders:
                break
            try:
                next_page = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".pagination .last a"))
                )
                driver.execute_script("arguments[0].click();", next_page)
                current_page += 1
                time.sleep(3)
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "tender-row"))
                )
            except Exception as e:
                logger.error(f"Error navigating to next page {current_page}: {e}")
                break
    except Exception as e:
        logger.error(f"Error loading or parsing page: {e}")
    finally:
        driver.quit()
    return tenders

def save_to_csv(tenders, filename):
    """Сохранение данных в CSV."""
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["number", "link", "customer", "goods", "end_date"])
        writer.writeheader()
        writer.writerows(tenders)
    logger.info(f"Saved {len(tenders)} tenders to {filename}")

def save_to_db(tenders):
    """Сохранение данных в SQLite."""
    conn, cursor = init_db()
    for tender in tenders:
        cursor.execute('''
            INSERT INTO tenders (number, link, customer, goods, end_date)
            VALUES (?, ?, ?, ?, ?)
        ''', (tender["number"], tender["link"], tender["customer"], tender["goods"], tender["end_date"]))
    conn.commit()
    conn.close()
    logger.info(f"Saved {len(tenders)} tenders to SQLite")

@app.get("/tenders")
async def get_tenders():
    """FastAPI эндпоинт для получения тендеров."""
    conn, cursor = init_db()
    cursor.execute("SELECT * FROM tenders")
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "number": row[1],
            "link": row[2],
            "customer": row[3],
            "goods": row[4],
            "end_date": row[5]
        } for row in rows
    ]

def main():
    parser = argparse.ArgumentParser(description="Tender parser")
    parser.add_argument("--max", type=int, default=100, help="Maximum number of tenders to parse")
    parser.add_argument("--output", type=str, default="tenders.csv", help="Output CSV file")
    args = parser.parse_args()
    tenders = parse_tenders(args.max)
    if tenders:
        save_to_csv(tenders, args.output)
        save_to_db(tenders)
    else:
        logger.warning("No tenders parsed")

if __name__ == "__main__":
    main()
    uvicorn.run(app, host="0.0.0.0", port=8000)
