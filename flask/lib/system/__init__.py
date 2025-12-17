# import lib.system.tasks as tasks
import lib.system.register_listeners as register_listeners
from lib.system.states import states
# import lib.system.override as override
# import lib.system.station as station
# import lib.system.sim as sim
# import lib.system.program as program
from lib.gpio import emergency, rm, mdm, tm, lm


states['emergency'] = emergency.state
states['motors'] = rm.get_value_list()
states['mds'] = mdm.get_value_list()
states['tower'] = tm.get_value_list()
states['lamp'] = lm.get_value_list()



