export type OperatorKeypadIcon =
    | "accept"
    | "back"
    | "cancel"
    | "down"
    | "globe"
    | "help"
    | "up"

export type OperatorKeypadKey = {
    button: string
    label: string
    icon?: OperatorKeypadIcon
    colSpan?: number
    tone?: "default" | "confirm" | "danger" | "utility"
    title?: string
}

export const FUNCTION_KEYPAD_KEYS: OperatorKeypadKey[] = [
    { button: "MAX", label: "", icon: "globe", tone: "utility" },
    { button: "UP", label: "", icon: "up", tone: "utility" },
    { button: "DOWN", label: "", icon: "down", tone: "utility" },
    { button: "CANCEL", label: "", icon: "cancel", tone: "utility" },
    { button: "ACCEPT", label: "", icon: "accept", tone: "utility" },
    { button: "HELP", label: "", icon: "help", tone: "utility"  },
]

export const MAIN_KEYPAD_ROWS: OperatorKeypadKey[][] = [
    [
        { button: "1", label: "1" },
        { button: "2", label: "2" },
        { button: "3", label: "3" },
        { button: "4", label: "4" },
        { button: "5", label: "5" },
        { button: "ASTERISK", label: "*" },
    ],
    [
        { button: "6", label: "6" },
        { button: "7", label: "7" },
        { button: "8", label: "8" },
        { button: "9", label: "9" },
        { button: "0", label: "0" },
        { button: "POUND", label: "#" },
    ],
    ["A", "B", "C", "D", "E", "F"].map((button) => ({ button, label: button })),
    ["G", "H", "I", "J", "K", "L"].map((button) => ({ button, label: button })),
    ["M", "N", "O", "P", "Q", "R"].map((button) => ({ button, label: button })),
    ["S", "T", "U", "V", "W", "X"].map((button) => ({ button, label: button })),
    [
        { button: "BACK", label: "", icon: "back", tone: "utility", colSpan: 2 },
        { button: "Y", label: "Y" },
        { button: "Z", label: "Z" },
        { button: "ENTER", label: "OK", icon: "accept", tone: "utility", colSpan: 2 },
    ],
]

export const OPERATOR_KEYPAD_LAYOUT_BUTTONS = new Set(
    [...FUNCTION_KEYPAD_KEYS, ...MAIN_KEYPAD_ROWS.flat()].map((key) => key.button)
)
