"""
    Author: Pantelis Gkatziaris
    Version : 0.1
    Description: Parsing router page every 30 seconds until 4:30 pm.
    The program stores phonecalls into multiple csv files, then merges
    them to one single csv file drop all the duplicates and
    then insert every single row in the database. The csv file is created only
    when there are new numbers in the page's log.
"""

import os
import datetime
import time
from call_parser import _router_parser
from file_manager import merge_files

while True:
    if not os.path.isdir('logs') or not os.path.isdir('cache'):
        os.mkdir('logs')
        os.mkdir('cache')

    if os.listdir('logs'):
        _router_parser(os.listdir('logs')[-1])
    else:
        _router_parser()
    
    if datetime.datetime.now().strftime('%H:%M:%S') >= '16:30:00':
        merge_files('logs')
        exit()
    time.sleep(30)