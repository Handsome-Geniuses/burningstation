
type MotorState = 0 | 1 | 2 | 3
type BayGuess = [
    string | null,
    string | null,
    string | null,
    string | null,
    string | null,
    string | null,
    string | null,
    string | null,
    string | null,
    string | null,
    string | null,
    string | null,
    string | null,
    string | null,
    string | null,
]

export const MotorStateName: Record<MotorState, string> = {
    0: "coast",
    1: "forward",
    2: "backward",
    3: "brake",
}

export interface MeterInfo {
    ip: string
    status: string
    current_action?: string
    progress?: {
        current: number
        total: number
    }
    hostname: string
    meter_type: string
    firmwares: Record<string, string>
    module_info: Record<string, unknown>
    system_versions: Record<string, string>
}

export interface MeterState extends MeterInfo {
    alive: boolean
    progress?: {
        current: number
        total: number
    }
}

export interface SystemState {
    // motors for rollers
    motors: [MotorState, MotorState, MotorState]

    // flags for meter detection sensors
    mds: [boolean, boolean, boolean, boolean, boolean, boolean, boolean, boolean, boolean],

    // best guess for virtual position sensors:
    // 0-1 voids before bay0, 2-4 bay0, 5 void, 6-8 bay1, 9 void, 10-12 bay2, 13-14 voids after bay2
    bayGuess: BayGuess

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
    lamp: [number, number, number, number]

    mode: 'auto' | 'manual'
}
export const initialSystemState: SystemState = {
    motors: [0, 0, 0],
    mds: [false, false, false, false, false, false, false, false, false],
    bayGuess: [null, null, null, null, null, null, null, null, null, null, null, null, null, null, null],
    emergency: false,
    handsome: false,
    playground: false,
    connected: false,
    meters: {},
    currentTab: undefined,
    running: false,
    tower: [false, false, false, false],
    lamp: [0, 0, 0, 0],
    mode: 'manual'
}

export type Action =
    | { type: 'set'; key: keyof SystemState; value: SystemState[keyof SystemState] }
    | { type: 'meter'; ip: string; info?: MeterInfo; alive: boolean }
    | { type: 'meter:status'; ip: string; status: string; msg?: string; current_action?: string }
    | { type: 'meter:progress'; ip: string; current: number; total: number }
    | { type: 'meters:clear' }

export const BAY_GUESS_BAY_STARTS = [2, 6, 10] as const

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
                    [action.ip]: {
                        ...action.info,
                        current_action: action.info.current_action ?? "",
                        progress: action.info.progress ?? { current: 0, total: 0 },
                        alive: true,
                    },
                },
            }
        }
        case 'meters:clear':
            return { ...state, meters: {} }

        case 'meter:status': {
            const meter = state.meters[action.ip]
            if (!meter) return state

            return {
                ...state,
                meters: {
                    ...state.meters,
                    [action.ip]: {
                        ...meter,
                        status: action.status,
                        current_action: action.current_action ?? (action.status === "ready" ? "" : meter.current_action),
                        progress: action.status === "ready" ? { current: 0, total: 0 } : meter.progress,
                    },
                },
            }
        }

        case 'meter:progress': {
            const meter = state.meters[action.ip]
            if (!meter) return state

            return {
                ...state,
                meters: {
                    ...state.meters,
                    [action.ip]: {
                        ...meter,
                        progress: {
                            current: action.current,
                            total: action.total,
                        },
                    },
                },
            }
        }
        default:
            return state
    }
}
