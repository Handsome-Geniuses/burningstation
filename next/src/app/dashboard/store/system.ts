
type MotorState = 0 | 1 | 2 | 3
export const MotorStateName: Record<MotorState, string> = {
    0: "coast",
    1: "forward",
    2: "backward",
    3: "brake",
}

export interface MeterInfo {
    ip: string
    status: string
    hostname: string
    meter_type: string
    firmwares: Record<string, string>
    module_info: Record<string, unknown>
    system_versions: Record<string, string>
}

export interface MeterState extends MeterInfo {
    alive: boolean
}

export interface SystemState {
    // motors for rollers
    motors: [MotorState, MotorState, MotorState]

    // flags for meter detection sensors
    mds: [boolean, boolean, boolean, boolean, boolean, boolean, boolean, boolean, boolean],

    // flag for physical emergency button
    emergency: boolean,

    // flag for ?handsome 
    handsome: boolean,

    // flag for ?playground
    playground: boolean,

    // flag for sse connection
    connected: boolean

    // known connected meters
    meters: Record<string, MeterState>

    // current tab
    currentTab: string | undefined
    
    // running
    running: boolean

    // tower r,g,b,buzzer
    tower: [boolean, boolean, boolean, boolean]

    // lamp1, lamp2
    lamp: [number,number,number,number]

    mode:  'auto' | 'manual'
}
export const initialSystemState: SystemState = {
    motors: [0, 0, 0],
    mds: [false, false, false, false, false, false, false, false, false],
    emergency: false,
    handsome: false,
    playground: false,
    connected: false,
    meters: {},
    currentTab: undefined,
    running: false,
    tower: [false, false, false, false],
    lamp: [0, 0, 0, 0],
    mode: 'auto'
}

export type Action =
    | { type: 'set'; key: keyof SystemState; value: SystemState[keyof SystemState] }
    | { type: 'meter'; ip: string; info?: MeterInfo; alive: boolean }
    | { type: 'meters:clear' }

export function reducer(state: SystemState, action: Action): SystemState {
    switch (action.type) {
        case 'set':
            return { ...state, [action.key]: action.value }
        case 'meter': {
            if (!action.alive) {
                const nextMeters = { ...state.meters }
                delete nextMeters[action.ip]
                return { ...state, meters: nextMeters }
            }

            if (!action.info) return state
            return {
                ...state,
                meters: {
                    ...state.meters,
                    [action.ip]: { ...action.info, alive: true },
                },
            }
        }
        case 'meters:clear':
            return { ...state, meters: {} }
        default:
            return state
    }
}
