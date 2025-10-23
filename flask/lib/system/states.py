from lib.gpio import emergency, rm, mdm

""" not necessarily current. needs to be updated """
states = {
    'running': False
}

def update():
    states['emergency'] = emergency.state
    states['motors'] = rm.get_value_list()
    states['mds'] = mdm.get_state()
update()

__all__ = ['states', 'update']