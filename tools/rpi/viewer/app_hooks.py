from threading import Thread
from . import data_generation


def on_server_loaded(server_context):
    print("hello")
    thread = Thread(target=data_generation.the_data.blocking_task)
    thread.setDaemon(True)
    thread.start()


def on_server_unloaded(server_context):
    print("by")
    pass


def on_session_created(session_context):
    print("meep")
    pass


def on_session_destroyed(session_context):
    print("moop")
