import os
import requests
import pyodbc
from dotenv import load_dotenv


def connectDB():
    load_dotenv()

    try:
        conn = pyodbc.connect(f'Driver={os.getenv("SQL_SERVER")};'
                              f'Server={os.getenv("SQL_NAME")};'
                              f'Database={os.getenv("SQL_DB")};'
                              f'UID={os.getenv("SQL_USER")};'
                              f'PWD={os.getenv("SQL_PWD")};'
                              f'Trusted_Connection={os.getenv("SQL_TRUST")};')

        return conn

    except pyodbc.InterfaceError:
        print('Couldn\'t connect to DB')


def connectRouter():
    load_dotenv()
    try:
        page = os.getenv('PAGE_SRC')
        username = os.getenv('USERNAME').lower()
        password = os.getenv('USER_PWD')

        r = requests.get(page, auth=(username, password))

        return r.text

    except Exception as err:
        print(err)