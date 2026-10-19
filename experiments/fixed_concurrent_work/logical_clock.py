import threading

def for_thread(owner,logical,real):
    return lambda:logical() if threading.get_ident()==owner else real()
