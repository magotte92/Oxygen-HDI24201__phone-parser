import os
import datetime

import pandas as pd
from bs4 import BeautifulSoup

from connections import connectRouter


def _router_parser(file=None):
    page = connectRouter()
    soup = BeautifulSoup(page, 'html.parser')
    last_call = soup.findAll('table', {'class', 'main_table'})[1].text
    new_log = datetime.datetime.now().strftime('%d-%m-%y %H_%M_%S') + '.csv'

    with open(f'cache/{new_log}', 'w+') as f:
        for counter, i in enumerate(last_call.split('\n')):
            if i:
                f.write(i + ';')
            else:
                if counter == 0:
                    pass
                if counter % 2 == 0:
                    f.write('\n')

    if file:
        to_check = pd.read_csv(f'logs/{file}', sep=';', dtype=str)
        db = pd.read_csv(f'cache/{new_log}', sep=';', dtype=str)
        db = db.drop(columns=db.columns[-1])
        if to_check.equals(db):
            pass
        else:
            print(f'Created new log with name {new_log}')
            db.to_csv(f'logs/{new_log}', sep=';', index=False)
    else:
        db = pd.read_csv(f'cache/{new_log}', sep=';', dtype=str)
        db = db.drop(columns=db.columns[-1])
        db.to_csv(f'logs/{new_log}', sep=';', index=False)

    os.remove(f'cache/{new_log}')