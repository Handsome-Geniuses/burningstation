
type MotorState = 0 | 1 | 2 | 3
export const MotorStateName: Record<MotorState, string> = {
    0: "coast",
    1: "forward",
    2: "backward",
    3: "brake",
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

    // flag for sse connection
    connected: boolean

    // current tab
    currentTab: string | undefined
    
    // running
    running: boolean

    // tower r,g,b,buzzer
    tower: [boolean, boolean, boolean, boolean]

    // lamp1, lamp2
    lamp: [number,number,number,number]
}
export const initialSystemState: SystemState = {
    motors: [0, 0, 0],
    mds: [false, false, false, false, false, false, false, false, false],
    emergency: false,
    handsome: false,
    connected: false,
    currentTab: undefined,
    running: false,
    tower: [false, false, false, false],
    lamp: [0, 0, 0, 0],
}

export type Action = { type: 'set'; key: keyof SystemState; value: SystemState[keyof SystemState] }

export function reducer(state: SystemState, action: Action): SystemState {
    switch (action.type) {
        case 'set':
            return { ...state, [action.key]: action.value }
        default:
            return state
    }
}