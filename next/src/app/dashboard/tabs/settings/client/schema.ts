import type { SchemaNode, SettingsObject, SettingsValue } from "../_components/types"

type FieldOptions = {
    title?: string
    description?: string
}

type IntegerOptions = FieldOptions & {
    ge?: number
    le?: number
}

type SettingField<T extends SettingsValue> = {
    kind: "field"
    default: T
    schema: SchemaNode
}

type SettingSection<T extends SettingsShape> = {
    kind: "section"
    title?: string
    description?: string
    fields: T
}

type SettingNode = SettingField<SettingsValue> | SettingSection<SettingsShape>

interface SettingsShape {
    [key: string]: SettingNode
}

type InferSetting<T extends SettingNode> =
    T extends SettingField<infer TValue>
    ? TValue
    : T extends SettingSection<infer TShape>
    ? InferSettings<TShape>
    : never

type InferSettings<T extends SettingsShape> = {
    [K in keyof T]: InferSetting<T[K]>
}

const settingEntries = <T extends SettingsShape>(shape: T) =>
    Object.entries(shape) as [keyof T & string, T[keyof T]][]

const titleFromKey = (key: string) =>
    key
        .replace(/_/g, " ")
        .replace(/\b\w/g, (char) => char.toUpperCase())

const Bool = (defaultValue: boolean, options: FieldOptions = {}): SettingField<boolean> => ({
    kind: "field",
    default: defaultValue,
    schema: {
        type: "boolean",
        title: options.title,
        description: options.description,
        default: defaultValue,
    },
})

const Integer = (defaultValue: number, options: IntegerOptions = {}): SettingField<number> => ({
    kind: "field",
    default: defaultValue,
    schema: {
        type: "integer",
        title: options.title,
        description: options.description,
        minimum: options.ge,
        maximum: options.le,
        default: defaultValue,
    },
})

function Factory(defaultValue: boolean, options?: FieldOptions): SettingField<boolean>
function Factory(defaultValue: number, options?: IntegerOptions): SettingField<number>
function Factory(
    defaultValue: boolean | number,
    options: FieldOptions | IntegerOptions = {}
) {
    if (typeof defaultValue === "boolean") {
        return Bool(defaultValue, options)
    }

    return Integer(defaultValue, options)
}

const Section = <T extends SettingsShape>(
    fields: T,
    options: FieldOptions = {}
): SettingSection<T> => ({
    kind: "section",
    title: options.title,
    description: options.description,
    fields,
})

const buildDefaults = <T extends SettingsShape>(shape: T): InferSettings<T> => {
    return Object.fromEntries(
        settingEntries(shape).map(([key, node]) => [
            key,
            node.kind === "field" ? node.default : buildDefaults(node.fields),
        ])
    ) as InferSettings<T>
}

const buildSchema = <T extends SettingsShape>(
    shape: T,
    options: FieldOptions = {}
): SchemaNode => ({
    type: "object",
    title: options.title,
    description: options.description,
    properties: Object.fromEntries(
        settingEntries(shape).map(([key, node]) => {
            if (node.kind === "field") {
                return [
                    key,
                    {
                        ...node.schema,
                        title: node.schema.title ?? titleFromKey(key),
                    },
                ]
            }

            return [
                key,
                buildSchema(node.fields, {
                    title: node.title ?? titleFromKey(key),
                    description: node.description,
                }),
            ]
        })
    ),
})

// ========================================================================================
// Actual settings schema
// ========================================================================================
const example_options = Section(
    {
        this_is_boolean: Factory(true, { description: "This is a boolean" }),
        this_is_number: Factory(50, { ge: 0, le: 100, description: "This is a number between0-100" })
    },
    { description: "Example options section" }
)

const visual_options = Section(
    {
        dolly_visible: Factory(true, { description: "Show sliding dolly on controls page" }),
        dolly_flash: Factory(true, { description: "Flash dolly when meters in position" }),
        bay_seprator: Factory(true, { description: "Show/hide visual bay lines" }),
        auto_bay_verbose: Factory(true, { description: "Show/hide bay related notifications" })
    },
    { description: "Controls more visual related options" }
)

const clientSettingsDefinition = {
    visual_options,
    // example_options
} satisfies SettingsShape



// ========================================================================================
// settings schema done
// ========================================================================================
export type ClientSettings = InferSettings<typeof clientSettingsDefinition>
export const CLIENT_SETTINGS_DEFAULTS = buildDefaults(clientSettingsDefinition)
export const CLIENT_SETTINGS_SCHEMA = buildSchema(clientSettingsDefinition, {
    title: "Cockpit Settings",
    description: "Browser-only settings stored on this cockpit device.",
})
export const clientSettingsDefaultsObject = CLIENT_SETTINGS_DEFAULTS as unknown as SettingsObject
export const ClientSetting = {
    Bool,
    Factory,
    Integer,
    Section,
}
