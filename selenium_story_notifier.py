import os
import time
import random
import json
import logging
import threading
from typing import Optional
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.firefox_profile import FirefoxProfile
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.firefox import GeckoDriverManager
from email.message import EmailMessage
import smtplib
from datetime import datetime, timedelta

# --- load environment ---
load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.office365.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
TO_EMAIL = os.getenv("TO_EMAIL", SMTP_USER)

INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME")
FIREFOX_PROFILE_PATH = os.getenv("FIREFOX_PROFILE_PATH")

POLL_INTERVAL_BASE = int(os.getenv("POLL_INTERVAL_BASE", "300"))
POLL_INTERVAL_RANDOM_RANGE = int(os.getenv("POLL_INTERVAL_RANDOM_RANGE", "120"))
RUN_START_HOUR = int(os.getenv("RUN_START_HOUR", "8"))
RUN_END_HOUR = int(os.getenv("RUN_END_HOUR", "22"))
STORED_FILE = os.getenv("STORED_FILE", "seen_viewers.json")

SPECIAL_USERS_STR = os.getenv("SPECIAL_USERS", "")
SPECIAL_USERS = {user.strip().lower() for user in SPECIAL_USERS_STR.split(',') if user.strip()}

# logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("insta-selenium")

# --- helper: smtp email ---
def send_email(subject: str, body: str, is_html=False):
    msg = EmailMessage()
    msg["From"] = SMTP_USER
    msg["To"] = TO_EMAIL
    msg["Subject"] = subject
    if is_html:
        msg.add_alternative(body, subtype='html')
    else:
        msg.set_content(body)
    try:
        if SMTP_USER is None or SMTP_PASS is None:
            raise ValueError("SMTP_USER y SMTP_PASS deben estar configurados en su archivo .env")
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        logger.info("Correo enviado: %s", subject)
    except Exception as e:
        logger.error("Error al enviar el correo: %s", e)

def send_hourly_report_email(new_viewers: list, total_viewers_count: int, new_special_users: list, last_check_time: str):

    special_alert_html = ""
    if "branvxvt" in new_special_users:
        special_alert_html = """
            <h3 style="color: red; text-align: center;">🚨 HA VUELTO 🚨</h3>
            <p style="font-size: 1.2em; font-weight: bold; text-align: center;">
                Se ha detectado la presencia de la mismísima <span style="font-style: italic;">Brenda</span>.
                Aquello que esperabas ha sucedido, y ella ha decidido "honrar" tu historia con su vista.
                ¿Qué proseguirá ahora? Solo el tiempo lo dirá.
            </p>
        """
    elif new_special_users:
        special_alert_html = "<h3 style='color: red; text-align: center;'>🚨 ¡ALERTA! 🚨</h3>"
        for user in new_special_users:
            special_alert_html += f"<p style='color: red; font-weight: bold; text-align: center;'>El usuario especial {user} vió tu historia.</p>"
    elif not new_special_users and not new_viewers:
        special_alert_html = """
            <hr style="border-color: #eee;">
            <p style="font-size: 1em; font-style: italic; color: #888; text-align: center;">
                ...Y aunque la esperanza nunca muere, en esta hora la brújula no ha señalado el Norte. Brenda no ha hecho acto de presencia.
            </p>
            <hr style="border-color: #eee;">
        """

    new_viewers_html = ""
    if new_viewers:
        new_viewers_html = "<h3>Nuevos espectadores encontrados en esta hora:</h3><ul>"
        for viewer in new_viewers:
            new_viewers_html += f"<li>{viewer}</li>"
        new_viewers_html += "</ul>"
        if not new_special_users:
            new_viewers_html += """
                <hr style="border-color: #eee;">
                <p style="font-size: 1em; font-style: italic; color: #888; text-align: center;">
                    ...Y aunque la esperanza nunca muere, en esta hora la brújula no ha señalado el Norte. Brenda no ha hecho acto de presencia.
                </p>
                <hr style="border-color: #eee;">
            """

    body_html = f"""
    <div style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px; color: #333;">
        <div style="max-width: 600px; margin: auto; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1);">
            <h2 style="text-align: center; color: #555;">📦 Reporte Horario de Alma</h2>
            <p style="font-size: 0.9em; color: #777; text-align: center;">Última verificación: <strong>{last_check_time}</strong></p>
            <hr style="border-color: #eee;">
            <div style="text-align: center;">
                <p style="font-size: 1.2em; margin: 0;">Total de espectadores de la historia:</p>
                <p style="font-size: 2em; font-weight: bold; color: #007BFF; margin: 5px 0 20px;">{total_viewers_count}</p>
            </div>

            {special_alert_html}

            {new_viewers_html}

            <p style="font-size: 0.8em; color: #aaa; text-align: center; margin-top: 30px;">
                Este correo fue generado automáticamente por Alma, tu vigilante de Instagram.
            </p>
        </div>
    </div>
    """
    send_email("📦 Reporte Horario de Alma - Instagram", body_html, is_html=True)

# --- storage ---
def load_seen():
    if os.path.exists(STORED_FILE):
        try:
            with open(STORED_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_seen(data):
    with open(STORED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# --- Selenium setup ---
def make_driver():
    if not FIREFOX_PROFILE_PATH:
        raise ValueError("FIREFOX_PROFILE_PATH debe estar configurado en su archivo .env")

    try:
        profile = FirefoxProfile(FIREFOX_PROFILE_PATH)
    except Exception as e:
        raise ValueError(f"No se pudo cargar el perfil de Firefox en {FIREFOX_PROFILE_PATH}: {e}") from e

    options = Options()
    options.profile = profile
    options.add_argument("--headless")

    service = FirefoxService(GeckoDriverManager().install())
    driver = webdriver.Firefox(service=service, options=options)

    logger.info("✅ Se ha creado exitosamente la instancia de Firefox en modo headless con el perfil existente.")
    return driver

# --- scraping logic ---
def open_my_profile(driver):
    wait = WebDriverWait(driver, 10)
    if INSTAGRAM_USERNAME:
        url = f"https://www.instagram.com/{INSTAGRAM_USERNAME}/"
    else:
        url = "https://www.instagram.com/"
    driver.get(url)
    logger.info("Abierto %s", url)
    try:
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except TimeoutException:
        logger.warning("Tiempo de espera agotado al cargar la página.")

def get_story_info(driver):
    try:
        timestamp_element = driver.find_element(By.CSS_SELECTOR, 'time.x197sbye')
        relative_time = timestamp_element.text
        iso_time = timestamp_element.get_attribute("datetime")
        return relative_time, iso_time
    except Exception:
        return "N/A", None

def open_latest_story(driver):
    wait = WebDriverWait(driver, 15)
    try:
        story_ring_xpath = "//div[@role='button' and .//canvas]"
        story_ring = wait.until(EC.element_to_be_clickable((By.XPATH, story_ring_xpath)))

        logger.info("Haciendo clic en el círculo de la historia del perfil para abrir la última historia.")
        story_ring.click()
        time.sleep(random.uniform(1.0, 2.5))
        return True
    except TimeoutException:
        logger.warning("No se pudo encontrar el círculo de la historia. No hay una historia nueva o la UI ha cambiado.")
        return False
    except Exception as e:
        logger.error("Error al abrir la historia: %s", e)
        return False

def fetch_viewers_from_open_story(driver):
    wait = WebDriverWait(driver, 10)

    try:
        viewers_button_xpath = "//div[@role='button' and .//span[contains(text(), 'Vista por') or contains(text(), 'Viewed by')]]"
        viewers_button = wait.until(EC.element_to_be_clickable((By.XPATH, viewers_button_xpath)))
        viewers_button.click()
        time.sleep(2)

        viewers_dialog = wait.until(
            EC.presence_of_element_located((By.XPATH, "//h2[contains(text(), 'Personas que vieron la historia') or contains(text(), 'Story viewers')]/ancestor::div[starts-with(@class, 'xs83m0k')]"))
        )
        scrollable_container = viewers_dialog.find_element(By.XPATH, ".//div[contains(@style, 'overflow: hidden auto;')]")

        all_usernames = set()
        last_user_count = 0

        while True:
            driver.execute_script("arguments[0].scrollTop += 100;", scrollable_container)
            time.sleep(1)

            current_anchors = scrollable_container.find_elements(By.XPATH, ".//a[starts-with(@href, '/')]")
            for a in current_anchors:
                href = a.get_attribute("href")
                if href and '/' in href:
                    username = href.split("instagram.com/")[-1].split('?')[0].strip('/')
                    if username:
                        all_usernames.add(username)

            new_user_count = len(all_usernames)
            if new_user_count == last_user_count:
                break

            last_user_count = new_user_count

        logger.info("Se han recopilado %d nombres de usuario del panel de espectadores.", len(all_usernames))
        return sorted(list(all_usernames))

    except TimeoutException:
        logger.warning("No se pudo encontrar el botón de espectadores o el diálogo. La UI pudo haber cambiado.")
        return []
    except Exception as e:
        logger.exception("Error al obtener los espectadores: %s", e)
        return []

# --- main loop ---
def main(stop_flag: Optional[threading.Event] = None, update_gui_callback=None):
    if not SMTP_USER or not SMTP_PASS:
        raise ValueError("SMTP_USER y SMTP_PASS deben estar configurados en su archivo .env")

    seen = load_seen()
    special_user_seen_status = {user: user in seen.get('all_viewers', []) for user in SPECIAL_USERS}
    story_id = None # Initialize story_id

    driver = None
    try:
        driver = make_driver()
    except WebDriverException as e:
        logger.error("Error al iniciar el controlador de Firefox: %s", e)
        return
    except ValueError as e:
        logger.error("Error de configuración: %s", e)
        return

    last_report_time = datetime.now()
    new_viewers_this_hour = set()
    new_special_users_this_hour = set()

    try:
        open_my_profile(driver)

        while True:
            current_time = datetime.now()
            current_hour = current_time.hour
            is_in_range = False

            if RUN_START_HOUR <= RUN_END_HOUR:
                if RUN_START_HOUR <= current_hour < RUN_END_HOUR:
                    is_in_range = True
            else:
                if current_hour >= RUN_START_HOUR or current_hour < RUN_END_HOUR:
                    is_in_range = True

            if not is_in_range:
                logger.info("Fuera del horario de ejecución (%d:00 - %d:00). Durmiendo hasta la próxima hora de inicio.", RUN_START_HOUR, RUN_END_HOUR)

                if current_hour < RUN_START_HOUR:
                    time_to_wait = (RUN_START_HOUR - current_hour) * 3600
                else:
                    time_to_wait = ((24 - current_hour) + RUN_START_HOUR) * 3600

                time.sleep(time_to_wait)
                continue

            if stop_flag and stop_flag.is_set():
                logger.info("Bandera de detención detectada. Saliendo del bucle principal.")
                break

            if (current_time - last_report_time) >= timedelta(hours=1):
                logger.info("Enviando reporte horario...")
                total_viewers_for_report = len(seen.get(story_id, [])) if story_id else 0
                send_hourly_report_email(
                    list(new_viewers_this_hour),
                    total_viewers_for_report,
                    list(new_special_users_this_hour),
                    current_time.strftime("%Y-%m-%d %H:%M:%S")
                )
                last_report_time = current_time
                new_viewers_this_hour = set()
                new_special_users_this_hour = set()

            logger.info("Comprobando nuevos espectadores de historias...")
            driver.get(f"https://www.instagram.com/{INSTAGRAM_USERNAME}/")
            time.sleep(5)

            ok = open_latest_story(driver)
            if not ok:
                logger.warning("No se pudo abrir la historia en este momento. Se reintentará más tarde.")
                story_id = None
                if update_gui_callback:
                    update_gui_callback(
                        last_check_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        total_viewers="N/A",
                        story_age="N/A"
                    )

                time.sleep(POLL_INTERVAL_BASE + random.uniform(0, POLL_INTERVAL_RANDOM_RANGE))
                continue

            relative_time, story_id = get_story_info(driver)
            if not story_id:
                logger.warning("No se pudo obtener un ID único para la historia. Pasando a la siguiente revisión.")
                if update_gui_callback:
                    update_gui_callback(
                        last_check_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        total_viewers="N/A",
                        story_age="N/A"
                    )

                continue

            viewers = fetch_viewers_from_open_story(driver)

            if update_gui_callback:
                update_gui_callback(
                    last_check_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    total_viewers=len(viewers),
                    story_age=relative_time
                )

            if story_id not in seen:
                seen[story_id] = []
                logger.info("Nueva historia detectada con ID: %s", story_id)

            prev = set(seen.get(story_id, []))
            new = set(viewers) - prev

            lowercase_viewers = {v.lower() for v in viewers}

            for user in SPECIAL_USERS:
                if user in special_user_seen_status and special_user_seen_status[user] and user not in lowercase_viewers:
                    logger.warning(f"El usuario especial {user} ya no está en la lista de espectadores.")
                    subject = f"🚨 ADVERTENCIA: {user} podría haberte bloqueado."
                    body = f"Parece que **{user}** ya no está en la lista de espectadores de tu historia. Es posible que te haya bloqueado o restringido."
                    send_email(subject, body, is_html=True)
                    special_user_seen_status[user] = False
                elif user not in special_user_seen_status or (user in lowercase_viewers and not special_user_seen_status[user]):
                    special_user_seen_status[user] = True
                    new_special_users_this_hour.add(user)

            if new:
                logger.info("Se han detectado nuevos espectadores: %s", new)
                new_special_users_in_check = {user for user in SPECIAL_USERS if user in {v.lower() for v in new}}

                subject = "Nuevos Espectadores de Historias"
                if new_special_users_in_check:
                    if "branvxvt" in new_special_users_in_check:
                        subject = f"🚨 HA VUELTO: ¡Brenda acaba de ver tu historia!"
                    else:
                        subject = f"🚨 ALERTA DE USUARIO: ¡{', '.join(new_special_users_in_check)} acaba de ver tu historia!"

                relative_hours = None
                try:
                    relative_hours_str = relative_time.split(" ")[0]
                    if relative_hours_str.isdigit():
                        relative_hours = int(relative_hours_str)
                except Exception:
                    pass

                # Nuevo bloque para generar el mensaje especial de Brenda
                special_message_html = ""
                if "branvxvt" in new_special_users_in_check:
                    special_message_html = f"""
                        <h3 style="color: #6a1b9a; text-align: center;">🌌 El Universo ha Conspirado 🌌</h3>
                        <p style="font-size: 1.2em; font-weight: bold; text-align: center; color: #4a148c;">
                            ¡Una aparición digna de las estrellas! <span style="font-style: italic; color: #8e24aa;">Brenda</span> ha hecho acto de presencia.
                            Un simple vistazo, pero, ¿qué significa para ti? ¿Qué significa en realidad?.
                        </p>
                        <hr style="border-color: #e1bee7;">
                    """

                other_special_users_html = ""
                if len(new_special_users_in_check) > 1 or ("branvxvt" not in new_special_users_in_check and new_special_users_in_check):
                    other_special_users_html = """
                        <div style="text-align: center;">
                            """
                    for user in new_special_users_in_check:
                        if user != "branvxvt":
                            other_special_users_html += f"""<p style='color: red; font-weight: bold; font-size: 1.5em;'>🚨 ¡{user} acaba de ver tu historia! 🚨</p>"""
                    other_special_users_html += "</div>"
                    if "branvxvt" not in new_special_users_in_check:
                        other_special_users_html = f"<hr style='border-color: #333;'>" + other_special_users_html + f"<hr style='border-color: #333;'>"

                # --- El resto del body_html (sin cambios sustanciales) ---
                body_html = f"""
                <div style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px; color: #333;">
                    <div style="max-width: 600px; margin: auto; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1);">
                        <h2 style="text-align: center; color: #555;">🚀 ¡Nuevos Espectadores de Historias de Instagram!</h2>
                        <hr style="border-color: #eee;">

                        <p style="font-size: 0.9em; color: #777; text-align: center;">
                            Esta historia fue publicada hace {relative_time}.
                        </p>

                        {"<p style='color: orange; font-weight: bold; text-align: center;'>⚠️ ¡Esta historia está a punto de caducar!</p>" if relative_hours is not None and relative_hours >= 23 else ""}

                        {special_message_html}

                        {other_special_users_html}

                        <h3>Nuevos Espectadores:</h3>
                        <ul>
                            {''.join([f"<li>{viewer}</li>" for viewer in new])}
                        </ul>
                    </div>
                </div>
                """

                send_email(subject, body_html, is_html=True)

                seen[story_id] = sorted(list(set(viewers) | prev))
                save_seen(seen)

                new_viewers_this_hour.update(new - new_special_users_in_check)

            else:
                logger.info("No se encontraron nuevos espectadores en esta revisión. Total de espectadores: %d", len(viewers))

            try:
                driver.switch_to.active_element.send_keys("\uE00C")
            except WebDriverException:
                pass

            sleep_for = POLL_INTERVAL_BASE + random.uniform(0, POLL_INTERVAL_RANDOM_RANGE)
            logger.info("Durmiendo por %.1f segundos.", sleep_for)
            time.sleep(sleep_for)

    except KeyboardInterrupt:
        logger.info("Interrumpido por el usuario.")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        save_seen(seen)
        logger.info("Saliendo.")

if __name__ == "__main__":
    main()