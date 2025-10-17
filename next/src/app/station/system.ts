

export interface SystemState {
    rollersMoving: [boolean, boolean, boolean]
    mds: [boolean, boolean, boolean, boolean, boolean, boolean, boolean, boolean, boolean],
    emergency: boolean
}
export const initialSystemState: SystemState = {
    rollersMoving: [false, false, false],
    mds: [false, false, false, false, false, false, false, false, false],
    emergency: false
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