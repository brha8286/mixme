import logging
import os

from dotenv import load_dotenv
from nicegui import ui

from mixer.client import MixerClient
from ui.app import setup_page
from ui.connect import setup_connect_page

load_dotenv()
logging.basicConfig(level=logging.INFO)

client = MixerClient()

setup_connect_page(client)
setup_page(client)

ui.run(title='MR18', dark=True, port=int(os.environ.get('PORT', '8018')), reload=False)
