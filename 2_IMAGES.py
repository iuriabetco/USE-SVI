# ==========================================================
# 2_IMAGES.py — Image acquisition + metadata logging (portable)
# ==========================================================
# Improvements vs. previous version:
# - Works both as a script and in interactive environments (fallback if __file__ is undefined)
# - Clear error if the input CSV is missing (suggests running 1_URL.py first)
# - Optional CLI flags: --headless / --no-headless (default: headless)
# - Keeps repo-relative paths (outputs/, images/)
# - Saves the CSV after each URL (crash-safe)
# ==========================================================

# ==========================================================
# 2_IMAGES.py — Image acquisition + metadata logging (portable)
# ==========================================================
# Regras nesta versão:
# - Só guarda a imagem se existir data
# - Se não existir data, não guarda a imagem
# - Se não existir data, não regista nada no CSV para essa linha
# - Mantém compatibilidade com script e ambientes interativos
# ==========================================================

import re
import time
import argparse
from pathlib import Path

import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth


# --------------------------
# Path helpers (portable)
# --------------------------
def get_base_dir() -> Path:
    """
    Folder where this script is located.
    If __file__ is not defined (e.g., interactive console),
    falls back to the current working directory.
    """
    try:
        return Path(__file__).resolve().parent
    except NameError:
        return Path.cwd()


# ==========================================================
# Opens a Google Street View URL, extracts the image capture date,
# and only then saves the screenshot if a date exists
# ==========================================================
def capture_streetview(driver, url: str, output_file: Path):
    try:
        driver.get(url)

        # Accept cookies if button appears
        try:
            accept_button = driver.find_element(By.CSS_SELECTOR, "div.VtwTSb button")
            accept_button.click()
            time.sleep(1)
        except Exception:
            pass

        # Wait for Street View canvas
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "canvas"))
        )

        time.sleep(3)

        # -----------------------------
        # Extract image date (best effort)
        # -----------------------------
        date_text = None
        try:
            body_text = driver.find_element(By.TAG_NAME, "body").text
            patterns = [
                r"\b\d{2}/\d{4}\b",
                r"\b\d{1,2}/\d{4}\b",
                r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b",
                r"\b\d{4}\b",
            ]
            for p in patterns:
                m = re.search(p, body_text, flags=re.IGNORECASE)
                if m:
                    date_text = m.group(0)
                    break
        except Exception:
            pass

        # If there is no date, do not save the image
        if not date_text:
            print("No date detected — image not saved.")
            return None

        # -----------------------------
        # Hide everything except panorama canvas
        # -----------------------------
        driver.execute_script(
            """
            const canvases = Array.from(document.querySelectorAll('canvas'));
            if (canvases.length === 0) return;

            const area = (el) => {
                const r = el.getBoundingClientRect();
                return Math.max(0, r.width) * Math.max(0, r.height);
            };

            canvases.sort((a,b) => area(b) - area(a));
            const panoCanvas = canvases[0];

            const keep = new Set();
            let node = panoCanvas;
            while (node) {
                keep.add(node);
                node = node.parentElement;
            }

            const all = Array.from(document.body.querySelectorAll('*'));
            all.forEach(el => {
                if (!keep.has(el)) {
                    el.style.visibility = 'hidden';
                    el.style.pointerEvents = 'none';
                } else {
                    el.style.visibility = 'visible';
                }
            });

            document.documentElement.style.visibility = 'visible';
            document.body.style.visibility = 'visible';

            const itamenu = document.getElementById('itamenu');
            if (itamenu) {
                if (!itamenu.contains(panoCanvas) && !keep.has(itamenu)) {
                    itamenu.style.visibility = 'hidden';
                    itamenu.style.display = 'none';
                } else {
                    itamenu.style.background = 'transparent';
                    itamenu.style.boxShadow = 'none';
                    itamenu.style.border = 'none';
                    itamenu.style.filter = 'none';

                    Array.from(itamenu.querySelectorAll('*')).forEach(child => {
                        if (!keep.has(child) && child !== panoCanvas && !child.contains(panoCanvas)) {
                            child.style.visibility = 'hidden';
                            child.style.display = 'none';
                        }
                    });
                }
            }
            """
        )

        driver.save_screenshot(str(output_file))
        print(f"Image saved: {output_file}")

        return date_text

    except Exception as e:
        print(f"Error capturing image: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Download Google Street View images from a CSV and append status/date metadata."
    )

    parser.add_argument(
        "--headless",
        dest="headless",
        action="store_true",
        help="Run Chrome in headless mode (default).",
    )
    parser.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="Run Chrome with a visible window (useful for debugging).",
    )
    parser.set_defaults(headless=True)

    args = parser.parse_args()

    base_dir = get_base_dir()

    # Portable paths (repo-based)
    csv_file = base_dir / "outputs" / "streetview_urls.csv"
    output_folder = base_dir / "images"
    output_csv = base_dir / "outputs" / "streetview_urls_with_status_data.csv"

    # Check inputs
    if not csv_file.exists():
        print(f"ERROR: Input CSV not found:\n  {csv_file}")
        print("Tip: Run `python 1_URL.py` first to generate the URLs CSV.")
        return

    output_folder.mkdir(parents=True, exist_ok=True)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    # Load CSV
    df = pd.read_csv(csv_file)

    # Ensure Image_Name is string
    if "Image_Name" in df.columns:
        df["Image_Name"] = df["Image_Name"].apply(
            lambda x: str(int(x)) if isinstance(x, float) else str(x)
        )

    if "Image_URL" not in df.columns or "Image_Name" not in df.columns:
        print("ERROR: CSV is missing required columns: Image_URL and/or Image_Name.")
        return

    # Add columns if not present (resume-friendly)
    if "Image_Download_Status" not in df.columns:
        df["Image_Download_Status"] = "Not downloaded"
    if "Image_Date" not in df.columns:
        df["Image_Date"] = "Unavailable"

    # Selenium setup
    options = webdriver.ChromeOptions()
    if args.headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=en-US")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--use-gl=swiftshader")
    options.add_argument("--enable-unsafe-swiftshader")
    options.add_argument("--log-level=3")
    options.add_argument("--disable-logging")
    options.add_argument("--disable-features=MediaRouter")

    # Optional: consistent user-agent helps in some environments
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    # Stealth configuration
    stealth(
        driver,
        languages=["en-US", "en"],
        vendor="Google Inc.",
        platform="Win32",
        webgl_vendor="Intel Inc.",
        renderer="Intel Iris OpenGL Engine",
    )

    # Loop over URLs
    for index, row in df.iterrows():
        image_url = str(row["Image_URL"])
        image_name = str(row["Image_Name"])

        if "&pitch=" not in image_url:
            image_url += "&pitch=0"

        output_file = output_folder / f"{image_name}.png"

        try:
            date_text = capture_streetview(driver, image_url, output_file)

            # Only register in the CSV if a date was found
            if date_text:
                df.at[index, "Image_Download_Status"] = "Downloaded"
                df.at[index, "Image_Date"] = date_text

                # Save CSV continuously only when there is something to register
                try:
                    df.to_csv(output_csv, index=False)
                    print(f"CSV updated: {output_csv}")
                except Exception as e:
                    print(f"Error saving the CSV: {e}")
            else:
                print(f"Skipping {image_name}: no date found, nothing saved to CSV.")
                continue

        except Exception as e:
            print(f"Error capturing image for {image_url}: {e}")
            # Do not register failure in the CSV if you want no record when there is no valid output
            continue

    driver.quit()
    print("Process completed.")


if __name__ == "__main__":
    main()