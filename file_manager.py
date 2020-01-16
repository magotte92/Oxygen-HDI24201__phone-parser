import shutil
import os
import datetime
import pandas as pd
from connections import connectDB


def delete_files():
    print('[+] Deleting Trace...')
    shutil.rmtree('logs')
    shutil.rmtree('cache')


def write_to_db(file):
    print('[-] Trying to connect to Database...')
    conn = connectDB()
    if conn:
        print('[+] Success! Connection Established')
    else:
        print('[+] Connection Failed... Retrying...')
        write_to_db(file)

    for i in file.iterrows():
        query = f"INSERT INTO Phonecalls (Source, Destination, StartTime, Durations) VALUES ('{i[1]['Source']}', '{i[1]['Destination']}', '{i[1]['Start Time']}', '{i[1]['Duration']}')"
        with conn.cursor() as cur:
            try:
                cur.execute(query)
            except Exception as err:
                print(err)
    print(f'[+] Success! Written {len(file) - 1} new rows')


def merge_files(folder):
    print('[+] Merging files...')
    all = os.listdir(folder)
    combo = pd.concat([pd.read_csv(f'{folder}/{file}', sep=';', dtype=str) for file in all])
    combo = combo.drop_duplicates(subset=None, keep="first").dropna().reset_index().drop(columns='index')
    name = datetime.datetime.now().strftime('%d-%m-%Y')
    if not os.path.isdir(f'queries/{name}'):
        os.mkdir(f'queries/{name}')
        combo.to_csv(f"queries/{name}/query.csv", index=False, sep=';')
    write_to_db(combo)
    delete_files()