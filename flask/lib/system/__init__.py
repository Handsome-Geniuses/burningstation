# import lib.system.tasks as tasks
import lib.system.register_listeners as register_listeners
from lib.system.states import states
from lib.gpio import emergency, rm, mdm, tm, lm


# setting up states
states['emergency'] = emergency.state
states['motors'] = rm.get_value_list()
states['mds'] = mdm.get_value_list()
states['tower'] = tm.get_value_list()
states['lamp'] = lm.get_value_list()
states['mode'] = 'manual'


# initialize some values. motors of. tower off. lamps off
lm.lamp(0,0,100)        # changing the dc here doesn't update screen. its not registered listening
lm.lamp(1,0,100)
rm.set_value(0)
tm.set_value_list([0,0,0,0])
