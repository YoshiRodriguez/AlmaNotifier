import os
import time
import random
import json
import logging
import threading
import pyodbc
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
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException
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

DB_SERVER = os.getenv("DB_SERVER", "DESKTOP-T432ACE\\GTESTER")
DB_NAME = os.getenv("DB_NAME", "dbFLDSMDFR")
ENABLE_DB_LOGGING = os.getenv("ENABLE_DB_LOGGING", "true").lower() in ('true', '1', 't', 'y', 'yes')

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

def send_hourly_report_email(new_viewers: list, total_viewers_count: int, special_users_this_hour: list, last_check_time: str, story_id: str, relative_time: str):

    special_alert_html = ""
    brenda_message_html = ""

    if "branvxvt" in special_users_this_hour:
        special_alert_html = """
            <h3 style="color: red; text-align: center;">🚨 HA VUELTO 🚨</h3>
            <p style="font-size: 1.2em; font-weight: bold; text-align: center;">
                Se ha detectado la presencia de la mismísima <span style="font-style: italic;">Brenda</span>.
                Aquello que esperabas ha sucedido, y ella ha decidido "honrar" tu historia con su vista.
                ¿Qué proseguirá ahora? Solo el tiempo lo dirá.
            </p>
        """
    elif special_users_this_hour:
        special_alert_html = "<h3 style='color: red; text-align: center;'>🚨 ¡ALERTA! 🚨</h3>"
        for user in special_users_this_hour:
            special_alert_html += f"<p style='color: red; font-weight: bold; text-align: center;'>El usuario especial {user} vió tu historia.</p>"
    else:
        brenda_message_html = """
            <hr style="border-color: #eee;">
            <p style="font-size: 1em; font-style: italic; color: #888; text-align: center;">
                ...Y aunque la esperanza nunca muere, en esta hora la brújula no ha señalado el Norte. Brenda no ha hecho acto de presencia.
            </p>
            <hr style="border-color: #eee;">
        """

    new_viewers_html = ""
    body_html = f"""
    <div style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px; color: #333;">
        <div style="max-width: 600px; margin: auto; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1);">
            <h2 style="text-align: center; color: #555;">📦 Reporte Horario de Alma</h2>
            <p style="font-size: 0.9em; color: #777; text-align: center;">Última verificación: <strong>{last_check_time}</strong></p>
            <hr style="border-color: #eee;">

            <div style="text-align: center; margin: 10px 0;">
                <p style="font-size: 1em; color: #333;">
                    Historia ID: <strong>{story_id}</strong><br>
                    Publicada hace: <strong>{relative_time}</strong>
                </p>
            </div>
            <hr style="border-color: #eee;">

            <div style="text-align: center;">
                <p style="font-size: 1.2em; margin: 0;">Total de espectadores de la historia:</p>
                <p style="font-size: 2em; font-weight: bold; color: #007BFF; margin: 5px 0 20px;">{total_viewers_count}</p>
            </div>

            {special_alert_html}
            {brenda_message_html}
            {new_viewers_html}

            <p style="font-size: 0.8em; color: #aaa; text-align: center; margin-top: 30px;">
                Este correo fue generado automáticamente por Alma, tu vigilante de Instagram.
            </p>
        </div>
    </div>
    """
    if new_viewers:
        new_viewers_html = "<h3>Nuevos espectadores encontrados en esta hora:</h3><ul>"
        for viewer in new_viewers:
            new_viewers_html += f"<li>{viewer}</li>"
        new_viewers_html += "</ul>"
        # Insert the new_viewers_html into body_html
        body_html = f"""
        <div style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px; color: #333;">
            <div style="max-width: 600px; margin: auto; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1);">
                <h2 style="text-align: center; color: #555;">📦 Reporte Horario de Alma</h2>
                <p style="font-size: 0.9em; color: #777; text-align: center;">Última verificación: <strong>{last_check_time}</strong></p>
                <hr style="border-color: #eee;">

                <div style="text-align: center; margin: 10px 0;">
                    <p style="font-size: 1em; color: #333;">
                        Historia ID: <strong>{story_id}</strong><br>
                        Publicada hace: <strong>{relative_time}</strong>
                    </p>
                </div>
                <hr style="border-color: #eee;">

                <div style="text-align: center;">
                    <p style="font-size: 1.2em; margin: 0;">Total de espectadores de la historia:</p>
                    <p style="font-size: 2em; font-weight: bold; color: #007BFF; margin: 5px 0 20px;">{total_viewers_count}</p>
                </div>

                {special_alert_html}
                {brenda_message_html}
                {new_viewers_html}

                <p style="font-size: 0.8em; color: #aaa; text-align: center; margin-top: 30px;">
                    Este correo fue generado automáticamente por Alma, tu vigilante de Instagram.
                </p>
            </div>
        </div>
        """

    send_email("Bitácora de Alma 📦: Tu Informe Estelar de la Hora", body_html, is_html=True)

# --- helper: sql server database ---
def save_users_and_views(new_viewers: list, story_id: str, total_views: int):
    """
    Guarda los nuevos usuarios y vistas en las tablas 'StoryUsers' y 'StoryViews'.
    Actualiza el conteo de vistas y la última vez que se vio la historia para cada usuario.
    """
    if not ENABLE_DB_LOGGING or not DB_SERVER or not DB_NAME:
        logger.warning("La configuración de la base de datos no está completa. No se guardará en SQL Server.")
        return

    cnxn = None
    try:
        cnxn = pyodbc.connect(
            f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={DB_SERVER};DATABASE={DB_NAME};Trusted_Connection=yes;'
        )
        cursor = cnxn.cursor()

        for viewer in new_viewers:
            # 1. Comprueba si el usuario ya existe en la tabla 'StoryUsers'
            cursor.execute("SELECT id FROM StoryUsers WHERE username = ?", viewer)
            user_row = cursor.fetchone()

            user_id = None
            if user_row:
                user_id = user_row[0]
                logger.info(f"El usuario {viewer} ya existe con el ID {user_id}. Actualizando su conteo de vistas.")

                # 2a. Si el usuario existe, actualiza el conteo de vistas y la última fecha de visualización
                cursor.execute(
                    "UPDATE StoryUsers SET total_views_count = total_views_count + 1, last_viewed_at = ? WHERE id = ?",
                    datetime.now(), user_id
                )
            else:
                # 2b. Si el usuario no existe, insértalo en 'StoryUsers' con un conteo inicial de 1
                is_special = 1 if viewer.lower() in SPECIAL_USERS else 0
                cursor.execute(
                    "INSERT INTO StoryUsers (username, is_special, created_at, total_views_count, last_viewed_at) VALUES (?, ?, ?, ?, ?)",
                    viewer, is_special, datetime.now(), 1, datetime.now()
                )
                cursor.execute("SELECT @@IDENTITY AS id")
                user_row = cursor.fetchone()
                user_id = user_row[0] if user_row is not None else None
                logger.info(f"Nuevo usuario {viewer} insertado con el ID {user_id}.")

            # 3. Inserta la vista en la tabla 'StoryViews'
            if user_id:
                cursor.execute(
                    "INSERT INTO StoryViews (user_id, story_id, viewed_at, total_views) VALUES (?, ?, ?, ?)",
                    user_id, story_id, datetime.now(), total_views
                )
                logger.info(f"La vista de {viewer} para la historia {story_id} ha sido guardada. Vistas totales en ese momento: {total_views}")

        cnxn.commit()

    except pyodbc.Error as e:
        sqlstate = e.args[0]
        logger.error(f"Error al conectar o interactuar con la base de datos SQL Server. SQLSTATE: {sqlstate}")
        logger.error(f"Mensaje de error: {e}")
    except Exception as e:
        logger.error(f"Error inesperado al intentar conectar a la base de datos: {e}")
    finally:
        if cnxn:
            cnxn.close()

def sleep_with_keepalive(driver, duration_seconds: float, interval_seconds: int = 60):
    """
    Duerme durante 'duration_seconds' en intervalos, enviando un comando
    keep-alive para evitar que la sesión del driver caduque.
    """
    logger.info(f"Durmiendo por {duration_seconds:.1f} segundos (con keep-alive)...")

    end_time = time.time() + duration_seconds
    while time.time() < end_time:
        sleep_chunk = min(interval_seconds, end_time - time.time())
        if sleep_chunk <= 0:
            break

        time.sleep(sleep_chunk)

        try:
            # Comando inofensivo para mantener la sesión viva
            _ = driver.title
            logger.info("Keep-alive enviado al driver.")
        except Exception as e:
            logger.warning(f"No se pudo enviar el keep-alive, la conexión puede estar perdida: {e}")
            # Si la conexión ya está rota, no hay nada que hacer, salimos del bucle.
            break

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
    # options.add_argument("--headless")

    service = FirefoxService(GeckoDriverManager().install())
    driver = webdriver.Firefox(service=service, options=options)

    logger.info("✅ Se ha creado exitosamente la instancia de Firefox en modo headless con el perfil existente.")
    return driver

def safe_get(driver, url, retries=5):
    """
    Intenta cargar una URL con reintentos para manejar errores de red.
    """
    for i in range(retries):
        try:
            driver.get(url)
            return True
        except WebDriverException as e:
            logger.warning(f"Intento {i+1} de {retries} fallido. Error: {e.msg}")
            # Retroceso exponencial: espera 2^i segundos
            sleep_time = 2 ** i
            logger.info(f"Esperando {sleep_time} segundos antes de reintentar...")
            time.sleep(sleep_time)
    logger.error("No se pudo cargar la página después de varios intentos. Saliendo.")
    return False

# --- scraping logic ---
def open_my_profile(driver):
    wait = WebDriverWait(driver, 10)
    if INSTAGRAM_USERNAME:
        url = f"https://www.instagram.com/{INSTAGRAM_USERNAME}/"
    else:
        url = "https://www.instagram.com/"
    return safe_get(driver, url)

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
        # Abrir panel de espectadores
        viewers_button_xpath = "//div[@role='button' and .//span[contains(text(), 'Vista por') or contains(text(), 'Viewed by')]]"
        viewers_button = wait.until(EC.element_to_be_clickable((By.XPATH, viewers_button_xpath)))
        viewers_button.click()
        time.sleep(2)

        # Localizar diálogo principal
        viewers_dialog = wait.until(
            EC.presence_of_element_located((By.XPATH, "//div[@role='dialog']"))
        )

        # 🔹 Encontrar contenedor con scroll (dinámico)
        containers = viewers_dialog.find_elements(By.XPATH, ".//div")
        viewers_container = None
        for c in containers:
            try:
                is_scrollable = driver.execute_script(
                    "return arguments[0].scrollHeight > arguments[0].clientHeight;", c
                )
                if is_scrollable:
                    viewers_container = c
                    break
            except:
                continue

        if not viewers_container:
            raise Exception("❌ No se encontró contenedor scrollable para los espectadores")

        all_usernames = set()
        last_user_count = -1

        # 🔹 Scroll lento incremental (como tenías)
        while len(all_usernames) > last_user_count:
            last_user_count = len(all_usernames)

            # Hacer scroll de 100 px
            driver.execute_script("arguments[0].scrollTop += 100;", viewers_container)
            time.sleep(1)

            # Extraer usuarios visibles
            viewer_links = viewers_container.find_elements(By.XPATH, ".//a[starts-with(@href, '/')]")
            for link in viewer_links:
                href = link.get_attribute("href")
                if href:
                    username = href.strip("/").split("/")[-1]
                    if username:
                        all_usernames.add(username)

        logger.info("✅ Se han recopilado %d usernames del panel de espectadores.", len(all_usernames))
        return sorted(list(all_usernames))

    except TimeoutException:
        logger.warning("⚠️ No se pudo encontrar el botón de espectadores o el diálogo. La UI pudo haber cambiado.")
        return []
    except Exception as e:
        logger.exception("Error al obtener los espectadores: %s", e)
        return []


def go_to_next_story(driver):
    """
    Intenta avanzar a la siguiente historia usando la tecla Flecha Derecha.
    Retorna True si logra pasar a otra historia, False si no hay más.
    """
    try:
        # Enviar flecha derecha al elemento activo (historia abierta)
        driver.switch_to.active_element.send_keys(Keys.ARROW_RIGHT)
        time.sleep(2)

        # Comprobar si aparece un nuevo timestamp (indicador de nueva historia)
        timestamp_element = driver.find_elements(By.CSS_SELECTOR, 'time.x197sbye')
        if not timestamp_element:
            return False  # ya no hay más historias

        return True
    except NoSuchElementException:
        return False
    except Exception as e:
        logger.warning(f"No se pudo avanzar a la siguiente historia: {e}")
        return False


# --- main loop ---
def main(stop_flag: Optional[threading.Event] = None, update_gui_callback=None):
    if not SMTP_USER or not SMTP_PASS:
        raise ValueError("SMTP_USER y SMTP_PASS deben estar configurados en su archivo .env")

    seen = load_seen()
    special_user_seen_status = {user: user in seen.get('all_viewers', []) for user in SPECIAL_USERS}
    story_id = None
    current_story_viewers = []
    relative_time = "N/A"

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
        if not open_my_profile(driver):
            return

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
                total_viewers_for_report = len(current_story_viewers)
                special_users_in_story = {v for v in current_story_viewers if v.lower() in SPECIAL_USERS}

                send_hourly_report_email(
                    list(new_viewers_this_hour),
                    total_viewers_for_report,
                    list(special_users_in_story),
                    current_time.strftime("%Y-%m-%d %H:%M:%S"),
                    story_id if story_id is not None else "N/A",
                    relative_time
                )

                last_report_time = current_time
                new_viewers_this_hour = set()
                new_special_users_this_hour = set()

            logger.info("Comprobando nuevos espectadores de historias...")

            if not safe_get(driver, f"https://www.instagram.com/{INSTAGRAM_USERNAME}/"):
                continue

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

            # 🔹 recorrer TODAS las historias
            has_more_stories = True
            all_viewers_this_cycle = set()
            while has_more_stories:
                relative_time, story_id = get_story_info(driver)
                if not story_id:
                    logger.warning("No se pudo obtener un ID único para la historia. Pasando a la siguiente.")
                    has_more_stories = go_to_next_story(driver)
                    continue

                viewers = fetch_viewers_from_open_story(driver)
                all_viewers_this_cycle.update(viewers) # <--- AÑADE ESTA LÍNEA
                current_story_viewers = viewers
                total_views = len(viewers)

                if update_gui_callback:
                    update_gui_callback(
                        last_check_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        total_viewers=total_views,
                        story_age=relative_time
                    )

                if story_id not in seen:
                    seen[story_id] = []
                    logger.info("Nueva historia detectada con ID: %s", story_id)

                prev = set(seen.get(story_id, []))
                new = set(viewers) - prev

                lowercase_viewers = {v.lower() for v in viewers}

                # for user in SPECIAL_USERS:
                #     if user in special_user_seen_status and special_user_seen_status[user] and user not in lowercase_viewers:
                #         logger.warning(f"El usuario especial {user} ya no está en la lista de espectadores.")
                #         subject = f"🚨 ADVERTENCIA: {user} podría haberte bloqueado."
                #         body = f"Parece que **{user}** ya no está en la lista de espectadores de tu historia. Es posible que te haya bloqueado o restringido."
                #         send_email(subject, body, is_html=True)
                #         special_user_seen_status[user] = False
                #     elif user not in special_user_seen_status or (user in lowercase_viewers and not special_user_seen_status[user]):
                #         special_user_seen_status[user] = True
                #         new_special_users_this_hour.add(user)

                if new:
                    logger.info("Se han detectado nuevos espectadores: %s", new)
                    new_special_users_in_check = {user for user in SPECIAL_USERS if user in {v.lower() for v in new}}

                    subject = "Nuevos Espectadores de Historias"
                    relative_hours = None
                    try:
                        relative_hours_str = relative_time.split(" ")[0]
                        if relative_hours_str.isdigit():
                            relative_hours = int(relative_hours_str)
                    except Exception:
                        pass

                    special_message_html = ""
                    if "branvxvt" in new_special_users_in_check:
                        subject = "🚨 HA VUELTO: ¡Brenda acaba de ver tu historia!"
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
                        if "branvxvt" in new_special_users_in_check:
                            subject = f"🚨 ALERTA DE USUARIOS ESPECIALES: ¡Brenda y otros han visto tu historia!"
                        else:
                            # Un asunto más elegante si solo son otros usuarios
                            user_list = ', '.join(new_special_users_in_check)
                            subject = f"Visita Notable: {user_list} ha visto tu historia"

                    # Construimos un cuerpo de mensaje más estilizado
                    other_special_users_html = "<hr style='border-color: #ddd;'>"
                    for user in new_special_users_in_check:
                        if user != "branvxvt": # Nos aseguramos de no duplicar el mensaje de Brenda
                            other_special_users_html += f"""
                            <div style="margin-top: 15px; padding: 10px; border-left: 3px solid #FFC107;">
                                <h4 style="margin: 0; color: #555;">✨ Presencia Notable Detectada</h4>
                                <p style="margin: 5px 0 0; font-size: 1.1em;">
                                    El rastro de <strong>{user}</strong> ha cruzado la órbita de tu historia más reciente.
                                </p>
                            </div>
                            """
                    other_special_users_html += "<hr style='border-color: #ddd; margin-top: 15px;'>"

                    body_html = f"""
                    <div style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px; color: #333;">
                        <div style="max-width: 600px; margin: auto; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1);">
                            <h2 style="text-align: center; color: #555;">🚀 ¡Nuevos Espectadores de Historias de Instagram!</h2>
                            <hr style="border-color: #eee;">

                            <p style="font-size: 0.9em; color: #777; text-align: center;">
                                Esta historia fue publicada hace {relative_time}.
                            </p>

                            <p style="font-size: 1em; text-align: center; color: #555;">
                                Historia ID: <strong>{story_id}</strong>
                            </p>
                            <hr style="border-color: #eee;">

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

                    if ENABLE_DB_LOGGING:
                        save_users_and_views(list(new), story_id, total_views)

                    new_viewers_this_hour.update(new - new_special_users_in_check)

                else:
                    logger.info("No se encontraron nuevos espectadores en esta revisión. Total de espectadores: %d", total_views)

                # Intentar pasar a la siguiente historia
                has_more_stories = go_to_next_story(driver)

            # --- NUEVA LÓGICA DE VERIFICACIÓN DE BLOQUEO ---
            # Se ejecuta después de haber revisado TODAS las historias
            lowercase_all_viewers = {v.lower() for v in all_viewers_this_cycle}
            for user in SPECIAL_USERS:
                is_currently_viewing = user in lowercase_all_viewers
                was_previously_viewing = special_user_seen_status.get(user, False)

                if was_previously_viewing and not is_currently_viewing:
                    # Estaba viendo, pero ahora no aparece en NINGUNA historia
                    # Reemplaza el bloque de envío de correo en tu nueva lógica de bloqueo
                    subject = f"🚨 Anomalía Detectada: Se ha perdido el rastro de {user}"
                    body = f"""
                    <div style="font-family: Arial, sans-serif; text-align: center; background-color: #f4f4f4; padding: 20px; color: #333;">
                        <div style="max-width: 600px; margin: auto; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1);">
                            <h2 style="color: #d32f2f;">🌌 Silencio en el Cosmos 🌌</h2>
                            <hr style="border-color: #eee;">
                            <p style="font-size: 1.1em; color: #555;">
                                En mi última vigilia, he barrido el firmamento de tus historias activas y no he podido encontrar la señal de <strong>{user}</strong>.
                            </p>
                            <p style="font-size: 1em; font-style: italic; color: #777;">
                                Su luz, que antes estaba presente, se ha desvanecido del espectro visible.
                            </p>
                            <p style="font-size: 1em; color: #555;">
                                Esto podría ser una simple nube pasajera, o podría significar que su telescopio ya no apunta en tu dirección. Permanezco en alerta.
                            </p>
                        </div>
                    </div>
                    """
                    send_email(subject, body, is_html=True)
                    special_user_seen_status[user] = False
                elif is_currently_viewing:
                    # Si está viendo, nos aseguramos de que su estado sea True
                    if not was_previously_viewing:
                         new_special_users_this_hour.add(user) # Contabiliza para reporte horario si es un "regreso"
                    special_user_seen_status[user] = True
            # --- FIN DE LA NUEVA LÓGICA ---

            sleep_for = POLL_INTERVAL_BASE + random.uniform(0, POLL_INTERVAL_RANDOM_RANGE)
            # logger.info("Durmiendo por %.1f segundos.", sleep_for)
            sleep_with_keepalive(driver, sleep_for)

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
