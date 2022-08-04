import copy
from datetime import datetime, timedelta
from dateutil import parser
import threading
import psutil
import numpy as np
from bokeh.document import document
from bokeh.models.sources import ColumnDataSource
from functools import partial

import yaml
from yaml.loader import SafeLoader
import sys
import paho.mqtt.client

from hoymiles import __main__ as my_hm
import hoymiles



def update(x, y, source, rollover_limit):
    source.stream(dict(x=[x], y=[y]), rollover=rollover_limit)


def full_update(x: list, y: np.ndarray, source: ColumnDataSource):
    source.data = copy.deepcopy(dict(x=x, y=y))


class MySources(object):
    now: ColumnDataSource
    today: ColumnDataSource
    yesterday: ColumnDataSource
    some_day: ColumnDataSource

    def __init__(self, source_now: ColumnDataSource, source_today: ColumnDataSource, source_yesterday: ColumnDataSource,
                 source_some_day: ColumnDataSource):
        self.now = source_now
        self.today = source_today
        self.yesterday = source_yesterday
        self.some_day = source_some_day

    def sync_current_data(self, data_root: "MyData"):
        self.now.stream(dict(x=data_root.x_data_now, y=data_root.y_data_now),
                        rollover=data_root.rollover_limit)
        full_update(data_root.x_data_today, data_root.y_data_today, self.today)
        full_update(data_root.x_data_yesterday, data_root.y_data_yesterday, self.yesterday)


def load_day(filename):
    x_temp = []
    y_temp = []
    try:
        file_handler = open(filename, "r")
        for line in file_handler.readlines():
            temp = line.split("\t")
            x_temp.append(parser.parse(temp[0]))
            y_temp.append(float(temp[1]))
        file_handler.close()
    except FileNotFoundError:
        pass

    return x_temp, np.array(y_temp)


class MyData(object):
    sources: list[MySources]
    documents: list[document]

    def __init__(self, rollover_limit=20):
        self.rollover_limit = rollover_limit
        temp_time = datetime.now()
        self.x_data_now = [temp_time for _ in range(self.rollover_limit)]
        self.y_data_now = np.zeros(self.rollover_limit)
        self.x_data_today = []
        self.y_data_today = np.array([])
        self.x_data_yesterday = []
        self.y_data_yesterday = np.array([])
        self.documents = []
        self.sources = []
        self.documents_lock = threading.Lock()

        self.output_file_base = "test"
        self.output_file_date = datetime.now().date()
        self.output_file_extension = ".txt"
        self.output_file_name = ""
        self.output_file = None
        self.loop_interval = 1

    def update_output_file(self):
        if not (self.output_file is None):
            self.output_file.close()

        # maybe use isoformat instead of str
        self.output_file_name = self.output_file_base + str(self.output_file_date) + self.output_file_extension
        self.x_data_today, self.y_data_today = load_day(self.output_file_name)
        yesterday_name = self.output_file_base \
                         + str(self.output_file_date - timedelta(days=1)) \
                         + self.output_file_extension
        self.x_data_yesterday, self.y_data_yesterday = load_day(yesterday_name)
        for i in range(len(self.documents)):
            self.documents[i].add_next_tick_callback(partial(full_update, x=self.x_data_today, y=self.y_data_today,
                                                             source=self.sources[i].today))
            self.documents[i].add_next_tick_callback(partial(full_update, x=self.x_data_yesterday,
                                                             y=self.y_data_yesterday,
                                                             source=self.sources[i].yesterday))
        self.output_file = open(self.output_file_name, "a")

    def initialize_ahoy(self):
        # Load ahoy.yml config file
        config_file = "ahoy.yml"
        log_transactions = True
        verbose=True
        try:
            if isinstance(config_file, str):
                with open(config_file, 'r') as fh_yaml:
                    cfg = yaml.load(fh_yaml, Loader=SafeLoader)
            else:
                with open('ahoy.yml', 'r') as fh_yaml:
                    cfg = yaml.load(fh_yaml, Loader=SafeLoader)
        except FileNotFoundError:
            print("Could not load config file. Try --help")
            sys.exit(2)
        except yaml.YAMLError as e_yaml:
            print('Failed to load config frile {config_file}: {e_yaml}')
            sys.exit(1)

        my_hm.ahoy_config = dict(cfg.get('ahoy', {}))

        for radio_config in my_hm.ahoy_config.get('nrf', [{}]):
            my_hm.hmradio = hoymiles.HoymilesNRF(**radio_config)

        my_hm.mqtt_client = None

        my_hm.command_queue = {}
        my_hm.mqtt_command_topic_subs = []

        if log_transactions:
            hoymiles.HOYMILES_TRANSACTION_LOGGING = True
        if verbose:
            hoymiles.HOYMILES_DEBUG_LOGGING = True

        mqtt_config = my_hm.ahoy_config.get('mqtt', [])
        if not mqtt_config.get('disabled', False):
            my_hm.mqtt_client = paho.mqtt.client.Client()
            my_hm.mqtt_client.username_pw_set(mqtt_config.get('user', None), mqtt_config.get('password', None))
            my_hm.mqtt_client.connect(mqtt_config.get('host', '127.0.0.1'), mqtt_config.get('port', 1883))
            my_hm.mqtt_client.loop_start()
            my_hm.mqtt_client.on_message = my_hm.mqtt_on_command

        my_hm.influx_client = None
        influx_config = my_hm.ahoy_config.get('influxdb', {})
        if influx_config and not influx_config.get('disabled', False):
            from hoymiles.outputs import InfluxOutputPlugin
            my_hm.influx_client = InfluxOutputPlugin(
                influx_config.get('url'),
                influx_config.get('token'),
                org=influx_config.get('org', ''),
                bucket=influx_config.get('bucket', None),
                measurement=influx_config.get('measurement', 'hoymiles'))

        g_inverters = [g_inverter.get('serial') for g_inverter in ahoy_config.get('inverters', [])]
        for g_inverter in my_hm.ahoy_config.get('inverters', []):
            g_inverter_ser = g_inverter.get('serial')
            my_hm.command_queue[str(g_inverter_ser)] = []

            #
            # Enables and subscribe inverter to mqtt /command-Topic
            #
            if my_hm.mqtt_client and g_inverter.get('mqtt', {}).get('send_raw_enabled', False):
                topic_item = (
                    str(g_inverter_ser),
                    g_inverter.get('mqtt', {}).get('topic', f'hoymiles/{g_inverter_ser}') + '/command'
                )
                my_hm.mqtt_client.subscribe(topic_item[1])
                my_hm.mqtt_command_topic_subs.append(topic_item)
        self.loop_interval = my_hm.ahoy_config.get('interval', 1)

    def blocking_task(self):
        self.update_output_file()
        self.initialize_ahoy()
        while True:
            if not threading.main_thread().is_alive():
                self.output_file.close()
                print("Exiting server child thread")
                break
            my_hm.main_loop()
            print('', end='', flush=True)

            # do some blocking computation
            x = datetime.now()
            y = psutil.cpu_percent(interval=self.loop_interval)

            if x.date() != self.output_file_date:
                self.output_file_date = x.date()
                self.update_output_file()

            self.documents_lock.acquire()
            for i in range(len(self.documents)):
                self.documents[i].add_next_tick_callback(partial(update, x=x, y=y,
                                                                 source=self.sources[i].now,
                                                                 rollover_limit=self.rollover_limit))
                self.documents[i].add_next_tick_callback(partial(update, x=x, y=y,
                                                                 source=self.sources[i].today,
                                                                 rollover_limit=None))
            self.documents_lock.release()

            self.x_data_now.pop(0)
            self.x_data_now.append(x)
            self.y_data_now = np.append(np.delete(self.y_data_now, 0), y)

            self.x_data_today.append(x)
            self.y_data_today = np.append(self.y_data_today, y)

            print(f"{x}\t{y}", file=self.output_file)
            self.output_file.flush()

    def add_doc(self, doc: document, sources: MySources):
        self.documents_lock.acquire()
        self.documents.append(doc)
        self.sources.append(sources)
        sources.sync_current_data(self)
        self.documents_lock.release()
        doc.on_session_destroyed(lambda x: self.del_doc(doc))

    def del_doc(self, doc: document):
        self.documents_lock.acquire()
        index = self.documents.index(doc)
        self.documents.pop(index)
        self.sources.pop(index)
        self.documents_lock.release()


the_data = MyData()
