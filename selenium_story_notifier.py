"""
Un script para monitorear los espectadores de historias de Instagram
usando Selenium para la automatización del navegador. El script inicia sesión,
navega a las historias y notifica por correo electrónico cuando nuevos
espectadores de una lista específica ven la historia.
"""

import os
import time
import random
import json
import logging
import threading
from typing import Optional
from email.message import EmailMessage
import smtplib
from datetime import datetime

# Third party imports
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

# Cargar variables de entorno
load_dotenv()

# Configuración del logger
LOG_FILE_PATH = "logs/selenium_story_notifier.log"
os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE_PATH, mode="w"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Configuración de variables
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD")
TARGET_USERS = os.getenv("TARGET_USERS", "").split(",")
SPECIAL_TARGET_USERS = os.getenv("SPECIAL_TARGET_USERS", "").split(",")
FIREFOX_PROFILE_PATH = os.getenv("FIREFOX_PROFILE_PATH")
TO_EMAIL = os.getenv("TO_EMAIL")
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = os.getenv("SMTP_PORT")
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SEEN_FILE = "seen_users.json"


def load_seen():
    """Carga los usuarios vistos desde un archivo JSON."""
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except (IOError, json.JSONDecodeError) as e:
            logger.error("Error al cargar el archivo de usuarios vistos: %s", e)
    return set()


def save_seen(seen_users: set):
    """Guarda los usuarios vistos en un archivo JSON."""
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen_users), f, ensure_ascii=False, indent=4)


def send_email(subject: str, body: str, is_html=False):
    """Envía un correo electrónico a la dirección TO_EMAIL configurada.

    Args:
        subject (str): El asunto del correo.
        body (str): El cuerpo del mensaje.
        is_html (bool, optional): Indica si el cuerpo es HTML. Por defecto es False.
    """
    if TO_EMAIL is None:
        logger.warning("No se puede enviar el correo porque TO_EMAIL no está configurado.")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = TO_EMAIL
    if is_html:
        msg.add_alternative(body, subtype="html")
    else:
        msg.set_content(body)

    try:
        if SMTP_USER is None or SMTP_PASS is None or SMTP_HOST is None or SMTP_PORT is None:
            raise ValueError("SMTP_USER, SMTP_PASS, SMTP_HOST y SMTP_PORT deben estar configurados en su archivo .env")

        with smtplib.SMTP(SMTP_HOST, int(SMTP_PORT)) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        logger.info("Correo enviado: %s", subject)
    except (smtplib.SMTPException, OSError, ValueError) as e:
        logger.error("Error al enviar el correo: %s", e)


def make_driver():
    """Crea y configura el controlador de Selenium para Firefox.

    Returns:
        webdriver.Firefox: La instancia del controlador de Firefox.

    Raises:
        ValueError: Si el perfil de Firefox no se puede cargar.
        WebDriverException: Si hay un error al iniciar el controlador.
    """
    options = Options()
    options.add_argument("-headless")

    if not FIREFOX_PROFILE_PATH or not os.path.exists(FIREFOX_PROFILE_PATH):
        raise ValueError(
            f"El perfil de Firefox no se encontró en la ruta: {FIREFOX_PROFILE_PATH}. "
            "Por favor, verifique la ruta y que el perfil existe."
        )

    try:
        profile = FirefoxProfile(FIREFOX_PROFILE_PATH)
    except OSError as e:
        raise ValueError(
            f"No se pudo cargar el perfil de Firefox en {FIREFOX_PROFILE_PATH}: {e}"
        ) from e

    options.profile = profile

    service = FirefoxService(GeckoDriverManager().install())
    driver = webdriver.Firefox(service=service, options=options)
    logger.info(
        "✅ Se ha creado exitosamente la instancia de Firefox en modo headless "
        "con el perfil existente."
    )
    return driver


def login(driver):
    """Inicia sesión en Instagram si es necesario.

    Args:
        driver (webdriver.Firefox): La instancia del controlador de Firefox.
    """
    driver.get("https://www.instagram.com/")

    try:
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "input[name='username']")
            )
        )

        driver.find_element(By.CSS_SELECTOR, "input[name='username']").send_keys(
            INSTAGRAM_USERNAME
        )
        driver.find_element(By.CSS_SELECTOR, "input[name='password']").send_keys(
            INSTAGRAM_PASSWORD
        )
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

        time.sleep(5)

        # Manejar el posible diálogo de "Guardar información de inicio de sesión"
        try:
            WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//div[text()='Ahora no']")
                )
            ).click()
        except TimeoutException:
            pass  # El diálogo no apareció, no hay problema

        logger.info("✅ Inicio de sesión exitoso en Instagram.")

    except WebDriverException as e:
        logger.error("Error durante el inicio de sesión: %s", e)


def open_latest_story(driver):
    """Abre la última historia disponible en la página principal.

    Args:
        driver (webdriver.Firefox): La instancia del controlador de Firefox.

    Returns:
        bool: True si se abrió una historia, False en caso contrario.
    """
    logger.info("Buscando si hay historias nuevas para ver...")

    story_button_xpath = (
        "//div[contains(@aria-label, 'Stories') and "
        "not(contains(@aria-label, 'History'))]"
    )

    try:
        story_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, story_button_xpath))
        )
        story_button.click()

        logger.info("✅ Se ha abierto la última historia disponible.")
        time.sleep(3)
        return True
    except TimeoutException:
        logger.warning(
            "No se pudo encontrar el círculo de la historia. No hay una historia "
            "nueva o la UI ha cambiado."
        )
        return False
    except WebDriverException as e:
        logger.error("Error al abrir la historia: %s", e)
        return False


def fetch_viewers_from_open_story(driver):
    """Extrae los nombres de usuario de los espectadores de la historia abierta.

    Args:
        driver (webdriver.Firefox): La instancia del controlador de Firefox.

    Returns:
        list: Una lista ordenada de los nombres de usuario de los espectadores.
    """
    logger.info("Extrayendo los espectadores de la historia...")
    viewers_button_xpath = (
        "//div[@role='button' and .//span[contains(text(), 'Vista por') or "
        "contains(text(), 'Viewed by')]]"
    )

    try:
        viewers_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, viewers_button_xpath))
        )
        viewers_button.click()

        time.sleep(3)

        # Esperar a que el diálogo de espectadores aparezca
        dialog_xpath = "//div[@role='dialog' and @aria-modal='true']"
        dialog = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, dialog_xpath))
        )

        all_usernames = set()
        last_height = driver.execute_script("return arguments[0].scrollHeight", dialog)

        while True:
            # Obtener todos los nombres de usuario
            username_elements = dialog.find_elements(
                By.XPATH, ".//div[@class='_aacl _aaco _aacv _aacy _aad6 _aade']"
            )

            for element in username_elements:
                all_usernames.add(element.text)

            # Scroll down
            driver.execute_script(
                "arguments[0].scrollTop = arguments[0].scrollHeight", dialog
            )
            time.sleep(2)

            new_height = driver.execute_script("return arguments[0].scrollHeight", dialog)
            if new_height == last_height:
                break
            last_height = new_height

        return sorted(list(all_usernames))
    except TimeoutException:
        logger.warning(
            "No se pudo encontrar el botón de espectadores o el diálogo. "
            "La UI pudo haber cambiado."
        )
        return []
    except WebDriverException as e:
        logger.exception("Error al obtener los espectadores: %s", e)
        return []


def get_story_publish_time(driver):
    """Obtiene la hora de publicación de la historia.

    Args:
        driver (webdriver.Firefox): La instancia del controlador de Firefox.

    Returns:
        datetime.datetime: La hora de publicación de la historia.
    """
    try:
        time_element = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.TAG_NAME, "time"))
        )
        iso_time = time_element.get_attribute("datetime")
        if iso_time:
            return datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
        else:
            logger.warning("El atributo 'datetime' no está presente en el elemento <time>.")
            return datetime.now()
    except WebDriverException:
        logger.warning("No se pudo obtener la hora de publicación de la historia.")
        return datetime.now()


def get_relative_time_info(story_time):
    """Calcula el tiempo relativo desde la publicación de la historia.

    Args:
        story_time (datetime.datetime): La hora de publicación de la historia.

    Returns:
        tuple: Una tupla con la cadena de tiempo relativo y las horas transcurridas.
    """
    now = datetime.now(story_time.tzinfo)
    delta = now - story_time
    total_seconds = delta.total_seconds()
    relative_hours = total_seconds // 3600

    if total_seconds < 60:
        return f"{int(total_seconds)} segundos", relative_hours
    if total_seconds < 3600:
        minutes = int(total_seconds // 60)
        return f"{minutes} minutos", relative_hours
    if relative_hours < 24:
        return f"{int(relative_hours)} horas", relative_hours

    days = int(relative_hours // 24)
    return f"{days} días", relative_hours


def check_for_new_viewers(driver, seen_users: set):
    """Comprueba si hay nuevos espectadores y envía notificaciones.

    Args:
        driver (webdriver.Firefox): La instancia del controlador de Firefox.
        seen_users (set): Un conjunto de usuarios que ya han sido vistos.
    """
    time.sleep(random.randint(5, 15))

    if not open_latest_story(driver):
        return

    story_time = get_story_publish_time(driver)
    relative_time, relative_hours = get_relative_time_info(story_time)

    all_viewers = fetch_viewers_from_open_story(driver)

    current_viewers_set = set(all_viewers)

    if not current_viewers_set:
        logger.info("No hay espectadores de la historia todavía. Esperando...")
        return

    new_viewers = current_viewers_set - seen_users

    if not new_viewers:
        logger.info("No se han detectado nuevos espectadores. Siguiente verificación en 5 minutos.")
        return

    logger.info("Se han detectado nuevos espectadores: %s", new_viewers)

    new_special_users = list(
        set(TARGET_USERS).intersection(new_viewers)
    )
    new_special_users_in_check = list(
        set(SPECIAL_TARGET_USERS).intersection(new_viewers)
    )

    if not new_special_users and not new_special_users_in_check:
        logger.info("Ninguno de los nuevos espectadores está en la lista objetivo.")
        seen_users.update(new_viewers)
        return

    # Preparar el correo electrónico
    new = new_special_users + new_special_users_in_check

    subject = "Nuevos Espectadores de Historias"
    if new_special_users_in_check:
        if "branvxvt" in new_special_users_in_check:
            subject = "🚨 HA VUELTO: ¡Brenda acaba de ver tu historia!"
        else:
            subject = (
                f"🚨 ALERTA DE USUARIO: ¡{', '.join(new_special_users_in_check)} "
                "acaba de ver tu historia!"
            )

    special_message_html = ""
    if "branvxvt" in new_special_users_in_check:
        special_message_html = """
            <h3 style="color: #6a1b9a; text-align: center;">🌌 El Universo ha Conspirado 🌌</h3>
            <p style="font-size: 1.2em; font-weight: bold; text-align: center; color: #4a148c;">
                ¡Una aparición digna de las estrellas! <span style="font-style: italic; color: #8e24aa;">Brenda</span> ha hecho acto de presencia.
                Un simple vistazo, pero, ¿qué significa para ti? ¿Qué significa en realidad?.
            </p>
            <hr style="border-color: #e1bee7;">
        """

    other_special_users_html = """
        <div style="text-align: center;">
            """
    for user in new_special_users_in_check:
        if user != "branvxvt":
            other_special_users_html += f"""
                <p style='color: red; font-weight: bold; font-size: 1.5em;'>🚨 ¡{user} acaba de ver tu historia! 🚨</p>
            """
    other_special_users_html += "</div>"
    if "branvxvt" not in new_special_users_in_check:
        other_special_users_html = (
            "<hr style='border-color: #333;'>"
            + other_special_users_html
            + "<hr style='border-color: #333;'>"
        )

    body_html = f"""
        <div style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px; color: #333;">
            <div style="max-width: 600px; margin: auto; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1);">
                <h2 style="text-align: center; color: #555;">🚀 ¡Nuevos Espectadores de Historias de Instagram!</h2>
                <hr style="border-color: #eee;">

                <p style="font-size: 0.9em; color: #777; text-align: center;">
                    Esta historia fue publicada hace {relative_time}.
                </p>

                {"<p style='color: orange; font-weight: bold; text-align: center;'>⚠️ ¡Esta historia está a punto de caducar!</p>"
                 if relative_hours is not None and relative_hours >= 23 else ""
                }

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

    seen_users.update(new_viewers)
    logger.info("Se han agregado %s nuevos usuarios al conjunto de vistos.", len(new_viewers))


def main(stop_flag: Optional[threading.Event] = None):
    """Función principal para ejecutar el scraper de historias de Instagram.

    Args:
        stop_flag (threading.Event, optional): Un evento para detener el bucle
            principal. Defaults to None.
    """
    seen = load_seen()
    driver = None

    try:
        driver = make_driver()
        login(driver)

        while not stop_flag or not stop_flag.is_set():
            check_for_new_viewers(driver, seen)

            wait_time = random.randint(300, 600)

            logger.info("Esperando %s segundos para la próxima verificación...", wait_time)

            if stop_flag:
                stop_flag.wait(wait_time)
            else:
                time.sleep(wait_time)

    except json.JSONDecodeError as e:
        logger.exception("Ha ocurrido un error inesperado de decodificación JSON: %s", e)
    except (WebDriverException, ValueError) as e:
        logger.error("Error al iniciar el controlador de Firefox: %s", e)
        return
    except KeyboardInterrupt:
        logger.warning("Programa interrumpido por el usuario.")
    except (OSError, smtplib.SMTPException) as e:
        logger.exception("Ha ocurrido un error inesperado: %s", e)
    finally:
        if driver:
            try:
                driver.quit()
            except WebDriverException:
                pass
        save_seen(seen)
        logger.info("Saliendo.")

if __name__ == "__main__":
    main()
